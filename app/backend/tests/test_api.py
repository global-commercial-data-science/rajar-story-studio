"""API tests with the fact engine stubbed (no Snowflake, no LLM)."""

import pytest
from fastapi.testclient import TestClient

from app.backend import main
from app.backend.tests.test_agents import small_factset


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "get_facts", lambda release: small_factset())
    return TestClient(main.app)


ANGLE = {"id": "lbc_record", "headline": "LBC sets a record 3.7 million weekly listeners", "brand": "lbc",
         "fact_keys": ["lbc_reach", "lbc_reach_yoy"], "why": "", "strength": 5, "selected": True}


def test_facts_shape(client):
    body = client.get("/api/facts").json()
    assert body["release_label"] == "Q2 2026"
    assert {"key", "display", "status"} <= set(body["facts"][0])


def test_draft_fallback_reports_tokens(client):
    body = client.post("/api/draft", json={"format": "press_release", "angles": [ANGLE], "use_llm": False}).json()
    assert body["used_llm"] is False
    assert "lbc_reach" in body["tokens_used"]
    assert body["unverified_numbers"] == []


def test_draft_needs_an_angle(client):
    assert client.post("/api/draft", json={"angles": [{**ANGLE, "selected": False}], "use_llm": False}).status_code == 400


def test_export_docx(client):
    r = client.post("/api/export/docx", json={"title": "LBC {{lbc_reach}}", "markdown": "- **LBC** up {{lbc_reach_yoy}}"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert r.content[:2] == b"PK"


@pytest.fixture
def agents_stubbed(monkeypatch, tmp_path):
    from app.backend import cache
    from app.backend.agents import ChatOutput, DraftOutput
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    calls = {"angles": 0, "draft": 0}

    async def fake_angles(state, model=None, on_done=None):
        calls["angles"] += 1
        return [{"key": "lbc", "name": "LBC", "angles": [ANGLE | {"family": "lbc"}], "also_moved": ["Capital −4.7% YoY"],
                 "tool_log": [], "extra_facts": [], "model_used": "gpt-6-sol"}]

    async def fake_draft(state, model=None):
        calls["draft"] += 1
        return DraftOutput(title="LBC record", subtitle_lines=[], markdown="LBC reaches {{lbc_reach}}.")

    async def fake_chat(state, question, history, model=None):
        assert history == [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
        return ChatOutput(answer=f"LBC reaches {{{{lbc_reach}}}} ({question})", suggestions=["What about LBC News?"])

    monkeypatch.setattr(main, "run_family_angles", fake_angles)
    monkeypatch.setattr(main, "run_draft", fake_draft)
    monkeypatch.setattr(main, "run_chat", fake_chat)
    return calls


def test_angles_are_cached_until_refresh(client, agents_stubbed):
    first = client.post("/api/angles", json={}).json()
    second = client.post("/api/angles", json={}).json()
    assert (first["cached"], second["cached"]) == (False, True)
    assert second["angles"] == first["angles"]
    assert first["groups"][0]["key"] == "lbc" and first["model"] == "gpt-6-sol"
    assert agents_stubbed["angles"] == 1
    assert client.post("/api/angles", json={"refresh": True}).json()["cached"] is False
    assert agents_stubbed["angles"] == 2


def test_drafts_are_cached_per_selection(client, agents_stubbed):
    body = {"format": "press_release", "angles": [ANGLE]}
    assert client.post("/api/draft", json=body).json()["cached"] is False
    assert client.post("/api/draft", json=body).json()["cached"] is True
    assert client.post("/api/draft", json={**body, "tone": "Celebratory"}).json()["cached"] is False
    assert agents_stubbed["draft"] == 2


def test_chat_passes_history_and_returns_facts(client, agents_stubbed):
    r = client.post("/api/chat", json={"question": "How is LBC doing?", "history": [
        {"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]}).json()
    assert "{{lbc_reach}}" in r["answer"]
    assert r["facts_used"][0]["key"] == "lbc_reach"
    assert r["suggestions"] == ["What about LBC News?"]


def test_angle_job_reports_progress(client, agents_stubbed):
    start = client.post("/api/angles/start", json={}).json()
    assert start["status"] in {"running", "done"}
    if start["job_id"]:
        import time
        for _ in range(50):
            job = client.get(f"/api/jobs/{start['job_id']}").json()
            if job["status"] != "running":
                break
            time.sleep(0.05)
        assert job["status"] == "done" and job["result"]["groups"][0]["key"] == "lbc"
    again = client.post("/api/angles/start", json={}).json()
    assert again["job_id"] is None and again["result"]["cached"] is True


def test_passcode_guard(monkeypatch, client):
    import base64
    monkeypatch.setattr(main, "_PASSCODE", "radio")
    assert client.get("/api/facts").status_code == 401
    assert client.get("/api/health").status_code == 200
    ok = "Basic " + base64.b64encode(b"anyone:radio").decode()
    assert client.get("/api/facts", headers={"Authorization": ok}).status_code == 200

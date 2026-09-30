"""Agent graph tests. TestModel/FunctionModel runs offline; the live section uses real facts but no LLM."""

import asyncio

import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel

from app.backend.agents import FORMATS, State, run_angles, run_draft
from app.backend.facts import Fact, FactSet
from app.backend.tokens import find_unverified_numbers, render, token_keys


def small_factset():
    def f(key, display, value, brand=None, direction=None, status="verified"):
        return Fact(key=key, label=key, value=value, display=display, unit="", brand=brand,
                    direction=direction, status=status)
    return FactSet(release=202602, release_label="Q2 2026", qoq_release=202601, qoq_label="Q1 2026",
                   yoy_release=202502, yoy_label="Q2 2025", history_quarters=20, facts=[
                       f("heart_reach", "12.8 million", 12826, "heart"),
                       f("heart_vs_bbc_r2", "459,000", 459, "heart", "ahead"),
                       f("lbc_reach", "3.7 million", 3688, "lbc"),
                       f("lbc_reach_yoy", "9.2%", 9.2, "lbc", "up"),
                   ])


def test_angle_graph_runs_offline_and_drops_unknown_keys():
    model = TestModel(call_tools=[], custom_output_args={
        "angles": [
            {"id": "lbc_record", "headline": "LBC record", "brand": "lbc", "fact_keys": ["lbc_reach", "not_a_fact"],
             "why": "Record.", "strength": 5, "selected": True},
            {"id": "ghost", "headline": "Ghost", "brand": None, "fact_keys": ["nope"], "why": "x", "strength": 1, "selected": False},
        ],
        "also_moved": ["Capital -4.7% YoY"], "analyst_insights": "- none",
    })
    out = asyncio.run(run_angles(State(facts=small_factset()), model=model))
    assert [a.id for a in out.angles] == ["lbc_record"]
    assert out.angles[0].fact_keys == ["lbc_reach"]


def test_writer_retries_until_numbers_are_tokens():
    calls = {"n": 0}

    def fake_llm(messages, info):
        calls["n"] += 1
        body = "LBC reaches 3.7 million listeners." if calls["n"] == 1 else "LBC reaches {{lbc_reach}}, up {{lbc_reach_yoy}}."
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,
                                                 {"title": "LBC record", "subtitle_lines": [], "markdown": body})])

    state = State(facts=small_factset(), angles=[{"headline": "LBC record", "fact_keys": ["lbc_reach"], "why": ""}])
    out = asyncio.run(run_draft(state, model=FunctionModel(fake_llm)))
    assert calls["n"] == 2
    assert render(out.markdown, state.all_facts()) == "LBC reaches 3.7 million, up 9.2%."


def test_every_format_has_a_prompt():
    assert set(FORMATS) == {"press_release", "exec_email", "internal_memo", "social_cards", "next_quarter"}


@pytest.mark.live
def test_rule_based_drafts_use_only_tokens():
    from app.backend.facts import build_facts
    from app.backend.templates import rule_angles, rule_draft

    facts = build_facts(202602)
    angles = rule_angles(facts)
    assert angles.angles[0].id in {"heart_top", "lbc_record"}
    assert any(a.id == "lbc_record" for a in angles.angles)
    assert "Capital −4.7% YoY" in angles.also_moved
    selected = [a.model_dump() for a in angles.angles if a.selected]
    known = facts.by_key()
    for fmt in FORMATS:
        d = rule_draft(facts, selected, fmt)
        text = "\n".join([d.title, *d.subtitle_lines, d.markdown])
        assert find_unverified_numbers(text) == [], (fmt, find_unverified_numbers(text))
        assert all(k in known for k in token_keys(text)), fmt


def test_writer_rejects_confirm_markers():
    calls = {"n": 0}

    def fake_llm(messages, info):
        calls["n"] += 1
        body = "LBC reaches {{lbc_reach}} [CONFIRM]." if calls["n"] == 1 else "LBC reaches {{lbc_reach}}."
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"title": "LBC", "subtitle_lines": [], "markdown": body})])

    state = State(facts=small_factset(), angles=[{"headline": "LBC", "fact_keys": ["lbc_reach"], "why": ""}])
    out = asyncio.run(run_draft(state, model=FunctionModel(fake_llm)))
    assert calls["n"] == 2 and "[CONFIRM]" not in out.markdown


def test_writer_gets_editor_notes_in_its_request_and_their_tokens_in_the_fact_list():
    seen = {}

    def fake_llm(messages, info):
        request = messages[0]
        seen["system"] = "\n".join(p.content for p in request.parts if p.part_kind == "system-prompt")
        seen["user"] = "\n".join(p.content for p in request.parts if p.part_kind == "user-prompt")
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,
                                                 {"title": "LBC", "subtitle_lines": [], "markdown": "LBC reaches {{lbc_reach}}."})])

    notes = "Mention that Heart reaches {{heart_reach}} and its audience skews female."
    state = State(facts=small_factset(), angles=[{"headline": "LBC", "fact_keys": ["lbc_reach"], "why": ""}],
                  editor_notes=notes)
    asyncio.run(run_draft(state, model=FunctionModel(fake_llm)))
    assert notes in seen["user"]
    assert "heart_reach = 12.8 million" in seen["system"]


def test_angle_headline_prefixes_are_stripped():
    model = TestModel(call_tools=[], custom_output_args={
        "angles": [{"id": "a", "headline": "Selected: LBC record", "brand": "lbc", "fact_keys": ["lbc_reach"],
                    "why": "", "strength": 5, "selected": True}], "also_moved": [], "analyst_insights": ""})
    out = asyncio.run(run_angles(State(facts=small_factset()), model=model))
    assert out.angles[0].headline == "LBC record"

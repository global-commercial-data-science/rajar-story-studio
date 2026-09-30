"""RAJAR Pulse API.

Run:  uvicorn app.backend.main:app --reload --port 8000   (from the project root, aiEnv)
"""

import asyncio
import base64
import logging
import os
import re
import secrets
import time
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import cache, config, presets
from .agents import (ANGLE_PROMPT_VERSION, FORMATS, WRITER_PROMPT_VERSION, State, run_chat, run_draft,
                     run_family_angles)
from .export import to_docx
from .facts import Fact, FactSet, build_facts
from .templates import rule_angles, rule_draft
from .tokens import find_unverified_numbers, render, token_keys

log = logging.getLogger("rajar_pulse")
app = FastAPI(title="RAJAR Pulse")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])

# Optional passcode for sharing on a network: set APP_PASSCODE and browsers will ask for it (any username).
_PASSCODE = os.getenv("APP_PASSCODE")


@app.middleware("http")
async def passcode_guard(request, call_next):
    if _PASSCODE and request.url.path != "/api/health":
        header = request.headers.get("authorization", "")
        ok = False
        if header.startswith("Basic "):
            try:
                _, _, given = base64.b64decode(header[6:]).decode().partition(":")
                ok = secrets.compare_digest(given, _PASSCODE)
            except Exception:
                ok = False
        if not ok:
            return Response("Passcode required", status_code=401, headers={"WWW-Authenticate": 'Basic realm="RAJAR Pulse"'})
    return await call_next(request)


Format = Literal["press_release", "exec_email", "internal_memo", "social_cards", "next_quarter"]


# ---------------------------------------------------------------- shared helpers

_facts_cache: dict[int, FactSet] = {}


def get_facts(release: int) -> FactSet:
    if release not in _facts_cache:
        _facts_cache[release] = build_facts(release)
    return _facts_cache[release]


@lru_cache
def knowledge_graph() -> str:
    """Compact table/column/rule summary of the AdWanted model for the Angle agent's prompt."""
    path = config.ROOT / "semantic" / "offline" / "rajar_analytics_semantic_layer.yaml"
    model = yaml.safe_load(path.read_text())
    lines = []
    for t in model["tables"]:
        cols = ", ".join(c["name"] + (f"={c['values']}" if c.get("values") and len(c["values"]) <= 8 else "")
                         for c in t["columns"] if c["role"] != "technical")
        lines.append(f"{t['physical']} ({t['grain']}): {cols}")
    lines.append("Semantic view HACKATHON_TEAM_GINGER_DB.ANALYTICS.ADWANTED_LISTENING_SV metrics: "
                 "brand_listening.brand_weekly_reach_000s, brand_listening.brand_total_hours_000s, "
                 "brand_listening.brand_unweighted_sample, listening.weekly_reach_000s, listening.total_hours_000s; "
                 "dimensions e.g. brand_listening.platform, brands.brand_name, brands.owner, respondents.age_band, "
                 "respondents.gender, respondents.social_segment, time_slots.daypart")
    lines += [f"Rule: {r['text']}" for r in model["rules"][:6]]
    return "\n".join(lines)


def state_for(facts: FactSet, extra_facts: list[Fact], **kw) -> State:
    return State(facts=facts, knowledge_graph=knowledge_graph(),
                 extra_facts={f.key: f for f in extra_facts}, **kw)


# ---------------------------------------------------------------- routes

class AnglesRequest(BaseModel):
    release: int = config.LATEST_RELEASE
    query: str = ""
    use_llm: bool = True
    refresh: bool = False          # ignore the cache and re-run the agent


class AngleIn(BaseModel):
    id: str
    headline: str
    brand: Optional[str] = None
    fact_keys: list[str]
    why: str = ""
    strength: int = 3
    selected: bool = True
    family: Optional[str] = None


class DraftRequest(BaseModel):
    release: int = config.LATEST_RELEASE
    format: Format = "press_release"
    angles: list[AngleIn]
    extra_facts: list[Fact] = []
    tone: str = "Global house style"
    editor_notes: str = ""
    use_llm: bool = True
    refresh: bool = False


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    release: int = config.LATEST_RELEASE
    question: str
    history: list[ChatTurn] = []
    angles: list[AngleIn] = []
    extra_facts: list[Fact] = []
    draft_title: str = ""
    draft_markdown: str = ""


class ExportRequest(BaseModel):
    release: int = config.LATEST_RELEASE
    title: str
    subtitle_lines: list[str] = []
    markdown: str
    extra_facts: list[Fact] = []


@app.get("/api/health")
def health():
    return {"ok": True, "model": config.LLM_LABEL, "provider": config.LLM_PROVIDER, "release": config.LATEST_RELEASE}


@app.get("/api/facts")
def facts(release: int = config.LATEST_RELEASE):
    try:
        return get_facts(release)
    except Exception as e:
        raise HTTPException(502, f"Could not load RAJAR figures from Snowflake: {e}")


@app.post("/api/angles")
async def angles(req: AnglesRequest):
    """Angles grouped by brand family (one agent run per family, in parallel), cached per release and focus."""
    return await compute_angles(req)


# ---------------------------------------------------------------- background jobs (progress for long agent runs)

_jobs: dict[str, dict] = {}


@app.post("/api/angles/start")
async def angles_start(req: AnglesRequest):
    """Start an angle run and return a job id to poll; cache hits come back immediately."""
    fs = get_facts(req.release)
    if req.use_llm and not req.refresh and (hit := cache.get(_angles_key(req, fs))):
        return {"job_id": None, "status": "done", "result": {**hit["value"], "cached": True, "cached_at": hit["cached_at"]}}
    job_id = uuid.uuid4().hex[:12]
    total = len(config.FAMILIES) + 1
    job = {"status": "running", "started": time.time(), "result": None, "error": None,
           "progress": {"done": 0, "total": total, "completed": [], "stage": "Reading published RAJAR figures"}}
    _jobs[job_id] = job

    def on_done(name):
        p = job["progress"]
        p["done"] += 1
        p["completed"].append(name)
        p["stage"] = f"Analysed {name}" if p["done"] < total else "Ranking and grouping the angles"

    async def run():
        try:
            job["progress"]["stage"] = f"Analysing {total} brand families in parallel"
            job["result"] = await compute_angles(req, on_done=on_done)
            job["status"] = "done"
        except Exception as e:
            log.exception("Angle job failed")
            job["status"], job["error"] = "error", f"{type(e).__name__}: {e}"

    asyncio.create_task(run())
    return {"job_id": job_id, "status": "running", "progress": job["progress"]}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown job (the server may have restarted). Start again.")
    return {"status": job["status"], "progress": job["progress"], "elapsed": round(time.time() - job["started"]),
            "result": job["result"], "error": job["error"]}


def _angles_key(req, fs):
    return cache.make_key("angles", release=req.release, facts=cache.facts_fingerprint(fs), query=req.query.strip().lower(),
                          prompt=ANGLE_PROMPT_VERSION)


async def compute_angles(req: AnglesRequest, on_done=None):
    fs = get_facts(req.release)
    key = _angles_key(req, fs)
    if req.use_llm and not req.refresh and (hit := cache.get(key)):
        return {**hit["value"], "cached": True, "cached_at": hit["cached_at"]}
    error = None
    if req.use_llm:
        try:
            groups = await run_family_angles(state_for(fs, [], user_query=req.query), on_done=on_done)
            failed = [g["name"] for g in groups if g.get("error")]
            if len(failed) < len(groups):
                value = _angles_payload(groups, used_llm=True,
                                        error=f"No angles for {', '.join(failed)} (agent error)." if failed else None)
                record = cache.put(key, value) if not failed else {"cached_at": None}
                return {**value, "cached": False, "cached_at": record["cached_at"]}
            error = "The angle agent failed for every brand, so these are rule-based angles."
        except Exception as e:
            log.exception("Angle agent failed")
            error = f"The angle agent failed, so these are rule-based angles: {type(e).__name__}: {e}"
    out = rule_angles(fs)
    groups = {}
    for a in out.angles:
        fam = config.BRAND_FAMILY.get(a.brand, a.brand) if a.brand else "market"
        g = groups.setdefault(fam, {"key": fam, "name": next((n for k, n, _ in config.FAMILIES if k == fam), "Global & market"),
                                    "angles": [], "also_moved": [], "tool_log": [], "extra_facts": [], "model_used": None})
        g["angles"].append(a.model_dump() | {"family": fam, "id": f"{fam}__{a.id}"})
    order = [k for k, _, _ in config.FAMILIES] + ["market"]
    grouped = sorted(groups.values(), key=lambda g: order.index(g["key"]) if g["key"] in order else 99)
    if grouped:
        grouped[-1]["also_moved"] = out.also_moved
    return {**_angles_payload(grouped, used_llm=False, error=error), "cached": False, "cached_at": None}


def _angles_payload(groups, used_llm, error):
    models = sorted({g["model_used"] for g in groups if g.get("model_used")})
    return {
        "groups": [{k: g.get(k) for k in ("key", "name", "angles", "also_moved", "error")} for g in groups],
        "angles": [a for g in groups for a in g["angles"]],
        "also_moved": [m for g in groups for m in g["also_moved"]],
        "extra_facts": [f.model_dump() if hasattr(f, "model_dump") else f for g in groups for f in g.get("extra_facts", [])],
        "tool_log": [t for g in groups for t in g.get("tool_log", [])],
        "used_llm": used_llm, "model": (", ".join(models) + (" via Cortex" if config.LLM_PROVIDER == "cortex" else "")) if models else (config.LLM_LABEL if used_llm else None),
        "analyst_insights": "", "error": error,
    }


def _draft_response(req, out, state, used_llm, error):
    text = "\n".join([out.title, *out.subtitle_lines, out.markdown])
    known = state.all_facts()
    used = [k for k in token_keys(text) if k in known]
    return {"format": req.format, **out.model_dump(), "tokens_used": used,
            "facts_used": [known[k].model_dump() for k in used],
            "unknown_tokens": [k for k in token_keys(text) if k not in known],
            "unverified_numbers": find_unverified_numbers(text), "used_llm": used_llm, "error": error}


@app.post("/api/draft")
async def draft(req: DraftRequest):
    fs = get_facts(req.release)
    selected = [a.model_dump() for a in req.angles if a.selected]
    if not selected:
        raise HTTPException(400, "Select at least one angle.")
    key = cache.make_key("draft", release=req.release, facts=cache.facts_fingerprint(fs), format=req.format,
                         angles=[(a["id"], a["headline"], a["fact_keys"]) for a in selected],
                         extra=sorted((f.key, f.display) for f in req.extra_facts), tone=req.tone, notes=req.editor_notes.strip(),
                         prompt=WRITER_PROMPT_VERSION)
    if req.use_llm and not req.refresh and (hit := cache.get(key)):
        return {**hit["value"], "cached": True, "cached_at": hit["cached_at"]}
    state = state_for(fs, req.extra_facts, angles=selected, draft_format=req.format, tone=req.tone,
                      editor_notes=req.editor_notes)
    if req.use_llm:
        try:
            value = _draft_response(req, await run_draft(state), state, True, None) | {"model": state.model_used}
            record = cache.put(key, value)
            return {**value, "cached": False, "cached_at": record["cached_at"]}
        except Exception as e:
            log.exception("Writer agent failed")
            error = f"The writer agent failed, so this is a template draft: {type(e).__name__}: {e}"
    else:
        error = None
    return {**_draft_response(req, rule_draft(fs, selected, req.format), state, False, error), "cached": False, "cached_at": None}


@app.post("/api/chat")
async def chat(req: ChatRequest):
    fs = get_facts(req.release)
    context = ""
    if req.angles:
        context += "Selected angles:\n" + "\n".join(f"- {a.headline}" for a in req.angles if a.selected)
    if req.draft_markdown:
        context += f"\n\nDraft headline: {req.draft_title}\nDraft body:\n{req.draft_markdown[:4000]}"
    state = state_for(fs, req.extra_facts, draft_context=context)
    try:
        out = await run_chat(state, req.question, [t.model_dump() for t in req.history])
    except Exception as e:
        log.exception("Chat agent failed")
        raise HTTPException(502, f"Pulse couldn't answer: {type(e).__name__}: {e}")
    known = state.all_facts()
    used = [k for k in token_keys(out.answer) if k in known]
    return {**out.model_dump(), "facts_used": [known[k].model_dump() for k in used], "tool_log": state.tool_log,
            "model": state.model_used}


class PresetRequest(BaseModel):
    release: int = config.LATEST_RELEASE
    kind: Literal["brand", "audience", "area", "period", "compare"]
    value: str
    audience: str = "adults"
    area: str = "uk"


@app.get("/api/menu")
def menu(release: int = config.LATEST_RELEASE):
    return presets.menu(get_facts(release))


@app.post("/api/preset")
def preset(req: PresetRequest):
    fs = get_facts(req.release)
    if req.kind == "brand":
        out = presets.brand_scorecard(fs, req.value)
    elif req.kind == "period":
        out = presets.period_table(fs)
    elif req.kind == "compare":
        out = presets.compare_table(fs, req.value)
    else:
        audience = req.value if req.kind == "audience" else req.audience
        area = req.value if req.kind == "area" else req.area
        if audience not in presets.AUDIENCES or area not in presets.AREAS:
            raise HTTPException(400, "Unknown audience or area.")
        key = cache.make_key("preset", audience=audience, area=area, release=req.release)
        if hit := cache.get(key):
            return hit["value"]
        out = cache.put(key, presets.audience_query(audience, area))["value"]
    return out


@app.post("/api/export/docx")
def export_docx(req: ExportRequest):
    fs = get_facts(req.release)
    known = fs.by_key()
    known.update({f.key: f for f in req.extra_facts})
    data = to_docx(render(req.title, known), [render(s, known) for s in req.subtitle_lines],
                   render(req.markdown, known))
    name = re.sub(r"[^A-Za-z0-9]+", "_", req.title)[:60].strip("_") or "draft"
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": f'attachment; filename="{name}.docx"'})


# Serve the built frontend (npm run build) from the same server for demos
_dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")

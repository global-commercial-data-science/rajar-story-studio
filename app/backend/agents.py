"""Story Studio agents, ported from reference_project/Commercial-Insight-Agent/rajar_lite.py.

Same shape as the reference: a State dataclass shared through pydantic-graph, an Analyst
node (here the Angle agent) and a Compiler node (here the Writer agent), each a pydantic-ai
Agent with a dynamic system prompt, tools and a structured output type.

Differences from the reference:
- Data comes from Snowflake (published RAJAR + the AdWanted semantic view), not CSV files.
- Numbers are fact tokens. The Writer may only cite {{fact_key}}; an output validator
  rejects unknown tokens and bare numbers so the model retries.
- Figures the Angle agent pulls from AdWanted become 'confirm' facts, never 'verified'.
"""

import json
import os
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Annotated, Optional

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext, Tool
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_graph import BaseNode, End, Graph, GraphRunContext

from . import config, db
from .facts import Fact, FactSet
from .tokens import find_unverified_numbers, token_keys

if os.getenv("LOGFIRE_TOKEN"):
    import logfire
    logfire.configure(token=os.getenv("LOGFIRE_TOKEN"), scrubbing=False)
    logfire.instrument_pydantic_ai()


def default_model():
    if config.LLM_PROVIDER == "cortex":
        return _cortex_model()
    # gpt-6 models only allow function tools on the Responses API
    return OpenAIResponsesModel(config.OPENAI_MODEL, provider=OpenAIProvider(api_key=os.getenv("OPENAI_API_KEY")))


def _cortex_model():
    """Snowflake Cortex's OpenAI-compatible chat API, authenticated as the current Snowflake session."""
    from openai import AsyncOpenAI

    if config.IN_SPCS:
        with open("/snowflake/session/token") as f:
            token = f.read()
        base = f"https://{os.environ['SNOWFLAKE_HOST']}"
        headers = {"Authorization": f"Bearer {token}", "X-Snowflake-Authorization-Token-Type": "OAUTH"}
    else:
        conn = db.connection()
        base = "https://" + conn.host.replace("_", "-")     # TLS certificates don't cover underscores
        headers = {"Authorization": f'Snowflake Token="{conn.rest.token}"'}
    client = AsyncOpenAI(base_url=f"{base}/api/v2/cortex/v1", api_key="unused", default_headers=headers)
    return OpenAIChatModel(config.CORTEX_MODEL, provider=OpenAIProvider(openai_client=client))


# Bump when a prompt changes so cached results made with the old prompt are not reused
ANGLE_PROMPT_VERSION = 4
WRITER_PROMPT_VERSION = 6

FORMATS = {
    "press_release": (
        "Press release for journalists, in Global's house style: confident, factual, UK English, no hype words. "
        "Structure: a headline (title); three short standfirst lines (subtitle_lines); an opening paragraph on the "
        "group and the market; one bullet per selected angle starting with the **brand name in bold**; then exactly "
        "these two quote placeholders on their own lines: '[Quote: Group CEO, on group performance]' and "
        "'[Quote: Chief Content Officer, on content wins]'; finish with the line "
        "'Figures sourced from RAJAR / Ipsos / RSMB, {release}, Adults 15+.'"
    ),
    "exec_email": (
        "Email from the Insight team to Global's executive committee on RAJAR day. title is the subject line. "
        "Open with a two-sentence summary, then 'Wins' and 'Watch-outs' bullet lists (use declines from also-moved "
        "facts for watch-outs), then one line on what comms will say publicly. Under 220 words. Sign off '[Insight team]'."
    ),
    "internal_memo": (
        "Internal memo to all Global staff celebrating the results. title is the memo subject. Warm but factual, "
        "credit the teams behind each brand, 150-250 words, bullets allowed. No watch-outs."
    ),
    "social_cards": (
        "Four to six social stat cards for LinkedIn and X. Each card is a '### ' heading with one headline figure "
        "token, then one caption line under 120 characters, then a hashtag line. title is 'Social stat cards'."
    ),
    "next_quarter": (
        "Recommendations for next quarter's RAJAR insight work. title is 'Next quarter: insight plan'. Sections: "
        "'What to watch' (brands and metrics at risk or on a streak, citing tokens), 'Analysis to prepare' "
        "(custom AdWanted cuts worth running before RAJAR day, e.g. platform, demographic, daypart), "
        "'Data gaps' (definitions to confirm, e.g. group total definitions), 'Story bank' (angles to pre-write)."
    ),
}


# ================================================================ State

@dataclass
class State:
    facts: FactSet
    user_query: str = ""
    current_date: str = field(default_factory=lambda: date.today().isoformat())
    knowledge_graph: str = ""
    extra_facts: dict = field(default_factory=dict)       # key -> Fact (AdWanted, status confirm)
    angles: list = field(default_factory=list)            # selected Angle dicts for the writer
    draft_format: str = "press_release"
    tone: str = "Global house style"
    editor_notes: str = ""
    tool_log: list = field(default_factory=list)
    additional_instructions: str = "None"
    draft_context: str = ""                               # current draft/angles, for the chat agent
    focus_family: Optional[str] = None                    # angle run for one brand family ('market' = group & market)
    model_used: Optional[str] = None                      # model name reported by the API response

    def all_facts(self):
        facts = self.facts.by_key()
        facts.update(self.extra_facts)
        return facts


# ================================================================ Output models

class Angle(BaseModel):
    id: str = Field(description="Short snake_case id, e.g. 'lbc_record'")
    headline: str = Field(description="One-line angle as an editor would label it (no 'Selected:' or other prefix), under 90 characters, numbers as digits "
                                      "exactly as the fact displays them (e.g. '3.7 million', '9.2%', '459,000')")
    brand: Optional[str] = Field(default=None, description="Brand key, or null for group/market angles")
    fact_keys: list[str] = Field(description="Fact keys that prove the angle")
    why: str = Field(description="Why it matters for the story, one sentence")
    strength: int = Field(ge=1, le=5, description="News value, 5 = lead story")
    selected: bool = Field(description="True if it belongs in the default press release")
    family: Optional[str] = Field(default=None, description="Leave empty; filled in by the app")


class AnglesOutput(BaseModel):
    agent_name: str = "Angle agent"
    angles: list[Angle] = Field(description="6-10 angles ranked by news value")
    also_moved: list[str] = Field(description="Up to 5 notable declines not used as angles, each a short label under 30 characters in the form '<Brand> −4.7% YoY' (use the − sign)")
    analyst_insights: str = Field(description="Bullet points of what the drill-downs found")


class DraftOutput(BaseModel):
    title: str = Field(description="Headline / subject line; may use tokens")
    subtitle_lines: list[str] = Field(default_factory=list, description="Standfirst lines; may use tokens")
    markdown: str = Field(description="Body in Markdown; every number as a {{fact_key}} token")


class ChatOutput(BaseModel):
    answer: str = Field(description="Answer in Markdown. Cite published figures as {{fact_key}} tokens; "
                                    "figures from your own queries may be written out, and say they are AdWanted custom cuts.")
    sources: list[str] = Field(default_factory=list, description="Short notes on where figures came from")
    suggestions: list[str] = Field(default_factory=list, description="2-3 short follow-up questions")


# ================================================================ Tools

def _log(ctx, tool, detail):
    ctx.deps.tool_log.append({"tool": tool, "detail": detail[:300]})


def get_brand_facts(ctx: RunContext[State], brand: Annotated[str, "Brand family key (heart, capital, smooth, classic_fm, lbc, radio_x, gold), 'group' for Global totals, or 'market'"]) -> str:
    """Return every fact token for one brand family (headline brand plus spin-offs), the group or the market."""
    _log(ctx, "get_brand_facts", brand)
    facts = ctx.deps.all_facts().values()
    if brand == "group":
        chosen = [f for f in facts if f.key.startswith("global_")]
    elif brand == "market":
        chosen = [f for f in facts if f.key.startswith(("all_radio", "commercial", "bbc_share", "bbc_reach"))]
    else:
        chosen = [f for f in facts if f.family == brand or f.brand == brand or f.key.startswith(brand + "_")]
    return json.dumps([f.model_dump(include={"key", "display", "direction", "status", "note"}) for f in chosen])


def run_sql(ctx: RunContext[State], sql: Annotated[str, "One read-only Snowflake SELECT"],
            purpose: Annotated[str, "Why you are running it"]) -> str:
    """Run a read-only SELECT on HACKATHON_TEAM_GINGER_DB (RAJAR published tables or ANALYTICS AdWanted tables). Max 50 rows."""
    _log(ctx, "run_sql", f"{purpose}: {sql}")
    try:
        return json.dumps(db.read_only_query(sql, max_rows=50), default=str)
    except Exception as e:
        return f"Query failed: {e}. Check column names in the semantic model and try again."


def semantic_view_query(ctx: RunContext[State],
                        metrics: Annotated[list[str], "e.g. ['brand_listening.brand_weekly_reach_000s']"],
                        dimensions: Annotated[list[str], "e.g. ['brand_listening.platform']"],
                        where: Annotated[str, "Filter using semantic names, e.g. \"brands.brand_name = 'LBC (UK)'\""]) -> str:
    """Query the AdWanted respondent-level semantic view (2026 Q2 only) for drill-downs: platform, daypart, demographics, cross-listening."""
    _log(ctx, "semantic_view_query", f"{metrics} by {dimensions} where {where}")
    sql = (f"SELECT * FROM SEMANTIC_VIEW({config.ANALYTICS}.ADWANTED_LISTENING_SV "
           f"METRICS {', '.join(metrics)}"
           + (f" DIMENSIONS {', '.join(dimensions)}" if dimensions else "")
           + (f" WHERE {where}" if where else "") + ")")
    try:
        return json.dumps(db.query(sql + " LIMIT 50"), default=str)
    except Exception as e:
        return f"Semantic view query failed: {e}"


def search_filters(ctx: RunContext[State], phrase: Annotated[str, "A short attribute phrase, e.g. 'young listeners'"]) -> str:
    """Find the table/column/value for a phrase using the Cortex-embedded SCHEMA_VECTORS store (top 3 candidates)."""
    _log(ctx, "search_filters", phrase)
    rows = db.query(f"SELECT CONTEXT, FILTER_SQL, SIMILARITY FROM TABLE({config.ANALYTICS}.SEARCH_SCHEMA_VECTORS(%s, '', 3, 'single_value'))", (phrase,))
    return json.dumps(rows, default=str)


def audience_profile(ctx: RunContext[State],
                     audience: Annotated[str, "One of: adults, 15_24, 25_34, 35_54, 55_plus, men, women, abc1, c2de, parents"],
                     area: Annotated[str, "One of: uk, london, north_west, midlands, yorkshire, north_east, scotland, wales, south, east"] = "uk") -> str:
    """Weekly reach, % of the audience reached, and index vs all adults (100 = average) for every Global brand family,
    within an audience and/or area. Use for over-/under-index, audience skew, demographic and regional questions."""
    from . import presets
    _log(ctx, "audience_profile", f"{audience} / {area}")
    if audience not in presets.AUDIENCES or area not in presets.AREAS:
        return f"Unknown audience or area. Audiences: {list(presets.AUDIENCES)}; areas: {list(presets.AREAS)}."
    return presets.audience_query(audience, area)["markdown"]


def brand_scorecard(ctx: RunContext[State],
                    family: Annotated[str, "Brand family key: heart, capital, smooth, classic_fm, lbc, radio_x, gold"]) -> str:
    """Published RAJAR scorecard for a brand family: headline brand, network and spin-offs with reach, changes and share."""
    from . import presets
    _log(ctx, "brand_scorecard", family)
    if not any(f["key"] == family for f in ctx.deps.facts.families):
        return "Unknown brand family. Use heart, capital, smooth, classic_fm, lbc, radio_x or gold."
    return presets.brand_scorecard(ctx.deps.facts, family)["markdown"]


def add_supporting_fact(ctx: RunContext[State],
                        key: Annotated[str, "snake_case key, prefixed 'adw_'"],
                        label: Annotated[str, "What the figure is"],
                        value: Annotated[float, "The number exactly as returned by your query"],
                        display: Annotated[str, "How it reads in copy, e.g. '41%' or '1.1 million'"],
                        source_query: Annotated[str, "The query that produced it"]) -> str:
    """Register a figure from an AdWanted drill-down so the writer can cite it. It is marked 'to confirm', never verified."""
    if not key.startswith("adw_"):
        key = "adw_" + key
    ctx.deps.extra_facts[key] = Fact(key=key, label=label, value=value, display=display, unit="", status="confirm",
                                     note="AdWanted respondent-level custom cut; will not match published RAJAR exactly",
                                     source=source_query[:500])
    return f"Registered {{{{{key}}}}} = {display} (status: confirm)"


# ================================================================ Agents

MARKET_PREFIXES = ("global_", "all_radio", "commercial", "bbc_share", "bbc_reach")
HEAD_BRANDS = {k for k, _, _ in config.GLOBAL_BRANDS}


def _facts_digest(state: State, families=None, keys=()):
    """Fact lines for the prompt. families=None -> heads + group/market only; a set -> those families in full."""
    lines = []
    for f in state.all_facts().values():
        if families is None:
            keep = f.family is None or f.brand in HEAD_BRANDS
        else:
            keep = f.family in families or f.key.startswith(MARKET_PREFIXES) or f.key in keys or f.key.startswith("adw_")
        if keep:
            lines.append(f"{f.key} = {f.display}" + (f" ({f.direction})" if f.direction else "")
                         + (" [CONFIRM]" if f.status == "confirm" else ""))
    return "\n".join(lines)


def _family_name(key):
    return next((n for k, n, _ in config.FAMILIES if k == key), "Global & market")


def _brand_context():
    return "\n".join(f"- {k} ({n}): {config.BRAND_BLURBS[k]}" for k, n, _ in config.GLOBAL_BRANDS)


angle_agent = Agent(
    output_type=AnglesOutput,
    deps_type=State,
    tools=[Tool(get_brand_facts, takes_ctx=True), Tool(run_sql, takes_ctx=True), Tool(semantic_view_query, takes_ctx=True),
           Tool(search_filters, takes_ctx=True), Tool(add_supporting_fact, takes_ctx=True)],
    instrument=True,
)


@angle_agent.system_prompt
def angle_agent_prompt(ctx: RunContext[State]) -> str:
    s = ctx.deps
    return f"""
    **Role:** Expert RAJAR analyst in Global's Insight team, preparing the RAJAR-day story.
    **Agent Name:** Angle agent

    **Objective:** {_angle_objective(s)}

    **Instructions:**
    - Start from the fact tokens below. Records, year-on-year gains, head-to-head wins and market share moves make angles.
    - Return 2-4 angles for this scope, ranked by news value; mark the 1-2 strongest positive ones as selected.
      Include spin-off stations (e.g. Heart 80s, Capital Dance) when their figures make a story.
    - Every angle must list the fact keys that prove it. Only use keys that exist.
    - A claim like "biggest radio brand" must hold against the head-to-head facts; check heart_vs_hits_portfolio before
      claiming Heart beats every commercial brand, and phrase it against the BBC if not.
    - Put notable declines in also_moved as short labels like "Capital −4.7% YoY" (max 5, biggest first), never in selected angles.
    - Facts marked [CONFIRM] use a disputed definition; you may use them but say so in 'why'.
    - At most 1 drill-down (semantic_view_query or run_sql) for supporting colour such as platform or age mix; register a
      useful figure with add_supporting_fact. AdWanted is 2026 Q2 respondent data. Skip it if the facts are enough.
    - Reach is in 000s. Use search_filters to find exact column values when unsure.

    **Additional Instructions:** {s.additional_instructions}

    **Context:**
    - Today: {s.current_date}
    - Editor request: {s.user_query or 'Draft the RAJAR-day press story for Global brands'}
    - Brands:
{_brand_context()}
    - Semantic model (AdWanted):
{s.knowledge_graph}

    **Fact tokens:**
{_facts_digest(s, families=_angle_families(s))}
    """


def _angle_families(s):
    return set() if s.focus_family in (None, "market") else {s.focus_family}


def _angle_objective(s):
    period = f"the {s.facts.release_label} RAJAR release (compared with {s.facts.qoq_label} and {s.facts.yoy_label})"
    if s.focus_family in (None, "market"):
        return (f"Find the group and market angles for Global in {period}: Global's total reach and share, all radio, "
                "commercial vs BBC share. Brand-specific stories are handled separately.")
    return (f"Find the strongest, defensible story angles for the {_family_name(s.focus_family)} brand family in {period}: "
            "the headline brand, its network and its spin-off stations.")


writer_agent = Agent(output_type=DraftOutput, deps_type=State, instrument=True)


@writer_agent.system_prompt
def writer_agent_prompt(ctx: RunContext[State]) -> str:
    s = ctx.deps
    spec = FORMATS[s.draft_format].format(release=s.facts.release_label)
    angles = "\n".join(f"- {a['headline']} (facts: {', '.join(a['fact_keys'])}) — {a.get('why', '')}" for a in s.angles)
    return f"""
    # Role and Objective
    You are Global's senior comms writer. Write the {s.draft_format.replace('_', ' ')} for the {s.facts.release_label}
    RAJAR results from the selected angles and the editor notes in the request.

    # Format
    {spec}

    # Tone
    {s.tone}

    # Number rules (strict)
    - Never type a number. Every figure must be a token like {{{{heart_reach}}}}, chosen from the fact list.
    - Tokens render as text, e.g. {{{{heart_reach}}}} -> "12.8 million", {{{{lbc_reach_yoy}}}} -> "9.2%" (unsigned: write
      'up' or 'down' yourself from the direction), {{{{commercial_share_qoq_pp}}}} -> "0.8 points".
    - Record tokens (keys ending _peak or _low) render as a whole phrase such as "the highest in 20 quarters" or
      "the lowest since Q1 2022". Use them as a complete clause: "LBC reaches {{{{lbc_reach}}}}, {{{{lbc_reach_peak}}}}" or
      "reach is {{{{lbc_reach_peak}}}}". Never write "its highest ... {{{{..._peak}}}}" or "in {{{{..._peak}}}}".
    - Head-to-head tokens (keys with _vs_) render as the gap only, e.g. "459,000"; write "459,000 ahead of" yourself.
    - Write "weekly listeners" or "people a week" for reach. Share changes are points, not percent.
    - Dates such as "Q2 2026" and "Adults 15+" may be typed.
    - Facts marked [CONFIRM] may be used but only if an angle needs them. Never write "[CONFIRM]" or any other
      bracketed marker in the copy; the app flags those figures to the editor itself.

    # Editor notes (they come with the request; they take priority)
    - Every point in the editor notes must show up in the copy, even if it goes beyond the selected angles. Notes
      often hold narrative pasted from Ask Pulse: work each point in, and reuse every {{{{token}}}} the notes contain.
    - Figures written out as plain numbers in the notes are unverified custom cuts. Never copy those numbers; keep the
      point and say it in words (e.g. "LBC's audience skews older", "most of its listening is on DAB").

    # Selected angles
{angles}

    # Fact tokens
{_facts_digest(s, families={a.get("family") for a in s.angles if a.get("family")} | {s.facts.by_key()[k].family for a in s.angles for k in a["fact_keys"] if k in s.facts.by_key() and s.facts.by_key()[k].family}, keys={k for a in s.angles for k in a["fact_keys"]} | set(token_keys(s.editor_notes)))}
    """


def writer_request(state: State) -> str:
    """The writer's user message: the task, plus the editor notes as instructions it must apply."""
    task = f"Write the {state.draft_format.replace('_', ' ')}."
    if not state.editor_notes.strip():
        return task
    return (f"{task}\n\nApply these editor notes. Every point must show up in the copy "
            f"(figures as {{{{tokens}}}} or in words, never as typed numbers):\n\n{state.editor_notes.strip()}")


@writer_agent.output_validator
def check_numbers(ctx: RunContext[State], output: DraftOutput) -> DraftOutput:
    text = "\n".join([output.title, *output.subtitle_lines, output.markdown])
    known = ctx.deps.all_facts()
    unknown = [k for k in token_keys(text) if k not in known]
    stray = find_unverified_numbers(text)
    if "[CONFIRM]" in text.upper():
        raise ModelRetry('Remove every "[CONFIRM]" marker from the copy; do not write bracketed markers.')
    if unknown or stray:
        raise ModelRetry(
            (f"Unknown tokens: {unknown}. Use only keys from the fact list. " if unknown else "")
            + (f"Bare numbers found: {stray}. Replace each with the matching {{{{token}}}} or remove it." if stray else "")
        )
    return output


chat_agent = Agent(
    output_type=ChatOutput,
    deps_type=State,
    tools=[Tool(get_brand_facts, takes_ctx=True), Tool(audience_profile, takes_ctx=True), Tool(brand_scorecard, takes_ctx=True),
           Tool(semantic_view_query, takes_ctx=True), Tool(run_sql, takes_ctx=True), Tool(search_filters, takes_ctx=True)],
    instrument=True,
)


@chat_agent.system_prompt
def chat_agent_prompt(ctx: RunContext[State]) -> str:
    s = ctx.deps
    return f"""
    **Role:** Pulse, the RAJAR analyst built into Global's Story Studio. Answer the editor's questions about
    Global's brands, competitors and the {s.facts.release_label} RAJAR release, in plain UK English.

    **Instructions:**
    - Be brief: lead with the answer in one or two sentences, then bullets if needed. No preamble.
    - For published figures (reach, hours, share, changes, records, head-to-heads), cite the fact tokens below as
      {{{{fact_key}}}} so they stay verified. Check a brand's full list with get_brand_facts when unsure.
    - For questions the tokens can't answer (platform, age, gender, daypart, region, cross-listening), query the AdWanted
      semantic view or run SQL, write the numbers out, and say they are AdWanted custom cuts (2026 Q2 only).
    - For trends over time use RAJAR WEEKLY_REACH (columns REPORT_NUMBER, RELEASE_NUMBER, WEEKLY_REACH_000S, TOTAL_HOURS,
      MARKET_SHARE, SURVEY_PERIOD; reach in 000s). Brand report numbers:
      {", ".join(f"{n}={r}" for _, n, r in config.GLOBAL_BRANDS)}.
    - Pick the right tool first, and keep it to 1-2 calls:
      * over-/under-index, skew, "which brands do best with <audience>", regional questions -> audience_profile
        (it already computes reach, % of audience and index for every Global brand family). Do not write SQL for these.
      * how a brand family and its spin-offs performed -> brand_scorecard.
      * published figures -> the fact tokens / get_brand_facts.
      * anything else about AdWanted audiences -> semantic_view_query.
    - Never add or combine reach across brands or stations: people listen to several, so totals must come from a
      table row (e.g. "All Global brands" in audience_profile). If no row gives the total, say so.
    - If you must write SQL, never use reserved words (sample, order, group, table, date, level) as column aliases.
    - The semantic view answers most other audience questions in one call, e.g.
      semantic_view_query(metrics=['brand_listening.brand_weekly_reach_000s', 'brand_listening.brand_unweighted_sample'],
      dimensions=['respondents.age_band'], where="brands.brand_name = 'LBC (UK)'"). Other useful dimensions:
      brand_listening.platform, brand_listening.day_band, time_slots.daypart, respondents.gender,
      respondents.social_segment, respondents.ilr_region. Brand names: 'Heart London', 'Capital London', 'LBC (UK)',
      'Classic FM', 'Smooth Radio London', 'BBC Radio 2' (search DIM_BRAND with ILIKE if unsure).
    - Short Markdown tables are fine for breakdowns.
    - Never invent figures. If data is missing, say so.
    - If asked to change the draft, suggest wording; the editor applies it.

    **Context:**
    - Today: {s.current_date}
    - Brands:
{_brand_context()}
    - Current Story Studio draft and angles:
{s.draft_context or '(none yet)'}
    - Semantic model (AdWanted):
{s.knowledge_graph}

    **Fact tokens:**
{_facts_digest(s)}
    """


def _history_messages(history):
    from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
    messages = []
    for turn in history[-8:]:
        if turn["role"] == "user":
            messages.append(ModelRequest(parts=[UserPromptPart(content=turn["content"])]))
        else:
            messages.append(ModelResponse(parts=[TextPart(content=turn["content"])]))
    return messages


async def run_chat(state: State, question: str, history: list, model=None) -> ChatOutput:
    from pydantic_ai.exceptions import UsageLimitExceeded
    from pydantic_ai.usage import UsageLimits
    try:
        result = await chat_agent.run(question, deps=state, message_history=_history_messages(history),
                                      model=model or default_model(), usage_limits=UsageLimits(request_limit=8))
    except UsageLimitExceeded:
        return ChatOutput(
            answer=("I couldn't answer that within the step limit. Try a narrower question (one brand, one audience or one "
                    "region), or use the Audience, Area and Brands filters above for instant breakdowns."),
            suggestions=["Which Global brands over-index with 25-34?", "How did Heart's stations perform?"])
    state.model_used = result.response.model_name or config.LLM_MODEL
    return result.output


# ================================================================ Graph (as in rajar_lite.py)

@dataclass
class AngleNode(BaseNode[State, None, AnglesOutput]):
    """Find and rank the story angles."""
    model: object = None

    async def run(self, ctx: GraphRunContext[State]) -> End[AnglesOutput]:
        ctx.state.additional_instructions = "Keep drill-downs to the top angles; stop after three."
        result = await angle_agent.run(ctx.state.user_query or "Find the angles.", deps=ctx.state, model=self.model or default_model())
        ctx.state.model_used = result.response.model_name or config.LLM_MODEL
        out = result.output
        known = ctx.state.all_facts()
        for angle in out.angles:
            angle.fact_keys = [k for k in angle.fact_keys if k in known]
            angle.headline = re.sub(r"^\s*(selected|not selected|angle \d+)\s*[:\-–]\s*", "", angle.headline, flags=re.I).strip()
        out.angles = [a for a in out.angles if a.fact_keys]
        return End(out)


@dataclass
class WriterNode(BaseNode[State, None, DraftOutput]):
    """Compile the selected angles into the requested format."""
    model: object = None

    async def run(self, ctx: GraphRunContext[State]) -> End[DraftOutput]:
        result = await writer_agent.run(writer_request(ctx.state), deps=ctx.state, model=self.model or default_model())
        ctx.state.model_used = result.response.model_name or config.LLM_MODEL
        return End(result.output)


angle_graph = Graph(nodes=[AngleNode])
writer_graph = Graph(nodes=[WriterNode])


async def run_angles(state: State, model=None) -> AnglesOutput:
    result = await angle_graph.run(AngleNode(model=model), state=state)
    return result.output


async def run_family_angles(base: State, model=None, on_done=None) -> list[dict]:
    """One angle run per brand family plus one for group & market, in parallel. Returns groups.
    on_done(name) is called as each family finishes, for progress reporting."""
    import asyncio
    import copy

    scopes = [k for k, _, _ in config.FAMILIES] + ["market"]

    async def one(scope):
        st = copy.copy(base)
        st.focus_family, st.tool_log, st.extra_facts = scope, [], dict(base.extra_facts)
        out = await run_angles(st, model=model)
        for a in out.angles:
            a.id = f"{scope}__{a.id}" if not a.id.startswith(scope + "__") else a.id
        return {"key": scope, "name": _family_name(scope), "angles": [a.model_dump() | {"family": scope} for a in out.angles],
                "also_moved": out.also_moved, "insights": out.analyst_insights, "tool_log": st.tool_log,
                "extra_facts": list(st.extra_facts.values()), "model_used": st.model_used}

    async def tracked(scope):
        try:
            return await one(scope)
        finally:
            if on_done:
                on_done(_family_name(scope))

    results = await asyncio.gather(*(tracked(sc) for sc in scopes), return_exceptions=True)
    groups = []
    for scope, r in zip(scopes, results):
        if isinstance(r, Exception):
            groups.append({"key": scope, "name": _family_name(scope), "angles": [], "also_moved": [], "insights": "",
                           "tool_log": [], "extra_facts": [], "model_used": None, "error": f"{type(r).__name__}: {r}"})
        else:
            groups.append(r)
    return groups


async def run_draft(state: State, model=None) -> DraftOutput:
    result = await writer_graph.run(WriterNode(model=model), state=state)
    return result.output

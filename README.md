# Team Ginger: RAJAR listening model

## RAJAR Pulse app (Story Studio)

Drafts RAJAR-day press material for Global's brands. It reads the published figures, has an agent find and rank story angles (with AdWanted drill-downs), then writes a press release, exec email, internal memo, social stat cards or a next-quarter insight plan. Every figure is a locked fact token that the Fact check panel verifies.

```bash
./app/start.sh                 # builds the frontend once, serves http://localhost:8000
REBUILD=1 ./app/start.sh       # rebuild the frontend first
```

**Sharing with colleagues on the same wifi:**

```bash
./app/serve_lan.sh             # http://<your-ip>:8000
./app/serve_lan.sh --https     # https://<your-ip>:8443, for networks that block plain HTTP
APP_PASSCODE=mycode ./app/serve_lan.sh   # choose the passcode (otherwise one is generated)
```

The script prints the address and passcode. The browser asks for a username (anything) and the passcode. With `--https` the certificate is self-signed, so colleagues click past the warning once. The first time, macOS asks whether Python may accept incoming connections: choose Allow. If colleagues still can't connect, the network is probably isolating devices from each other (common on guest and corporate wifi), and IT would need to allow it.

**Deploying to Snowflake (Snowpark Container Services):**

```bash
pip install snowflake-cli                      # once, for the registry login (or set SNOW_BIN)
python app/spcs/deploy.py                      # build linux/amd64 image, push, create/upgrade the service
python app/spcs/deploy.py --status             # status and URL
python app/spcs/deploy.py --eai PULSE_OPENAI_EAI   # after organisers run app/spcs/organiser_setup.sql
```

The service `HACKATHON_TEAM_GINGER_DB.ANALYTICS.RAJAR_PULSE` runs on `HACKATHON_CPU_POOL` with a public endpoint. People sign in with their Snowflake login, and anyone with role `HACKATHON_PARTICIPANT` can open it. Inside the container the app signs in to Snowflake with the service's own token. The OpenAI key from `.env` is stored as the Snowflake secret `ANALYTICS.OPENAI_API_KEY` and passed to the container as the environment variable `OPENAI_API_KEY`; it is never baked into the image. Inside Snowflake the agents use **Cortex** (`openai-gpt-5.4`, through Cortex's OpenAI-compatible API), because containers can't reach api.openai.com without an external access integration. `gpt-6-sol` isn't offered in Cortex in this account (`gpt-5.5` is blocked for the account; `gpt-5.4` is the newest OpenAI model available). To use `gpt-6-sol` in the container instead, an organiser runs `app/spcs/organiser_setup.sql` (needs ACCOUNTADMIN), then you set `LLM_PROVIDER: openai` in `app/spcs/service.yaml` and run `deploy.py --eai PULSE_OPENAI_EAI`.

**LLM provider switch:** `LLM_PROVIDER=openai` (the default on a laptop: `gpt-6-sol` via api.openai.com) or `LLM_PROVIDER=cortex` (the default in Snowflake: `CORTEX_MODEL`, default `openai-gpt-5.4`). For example, `LLM_PROVIDER=cortex ./app/start.sh` runs the local app on Cortex too.

For frontend development, run the API with `uvicorn app.backend.main:app --reload --port 8000` and the frontend with `cd app/frontend && npm run dev` (http://localhost:5173, which proxies `/api` to the API).

- **Cache:** agent results are saved in `app/.cache/`. The angle agent runs once per release (and per question); after that the angles load instantly, and **Refresh angles** in the app forces a new run. Drafts are saved per format, angle selection, tone and notes. Old results are ignored automatically when the RAJAR figures, the model or a prompt version (`ANGLE_PROMPT_VERSION` / `WRITER_PROMPT_VERSION` in `agents.py`) change. Delete `app/.cache/` to clear everything.
- **Filter chips:** Release switches the RAJAR release. "vs" sets which comparison the writer leads with. Brands filters the angle groups and shows a scorecard. Audience and Area run an instant AdWanted query (reach, % of the audience, and an index against all adults). Every chip also lists prepared questions for Ask Pulse.
- **Angles:** one angle-agent run per brand family (Heart, Capital, Smooth, Classic FM, LBC, Radio X, Gold) plus Global & market, in parallel, with live progress. Families come from RAJAR `REPORT_HIERARCHY`.
- **Ask Pulse:** a chat tab next to Fact check (or type in the top search bar). The chat agent answers from the published fact tokens and runs AdWanted queries for audience breakdowns, labelled as custom cuts.
- **Model:** `OPENAI_MODEL` in `.env` (default `gpt-6-sol`), with `OPENAI_API_KEY`. If the model call fails, the app falls back to rule-based angles and template drafts.
- **Agents:** `app/backend/agents.py`, ported from `reference_project/Commercial-Insight-Agent/rajar_lite.py`: the Angle agent, then the Writer agent.
- **Facts:** `app/backend/facts.py` builds 153 facts per release from `WEEKLY_REACH` and `WEEKLY_REACH_COMPARABLES`.
- **Tests:** `pytest app/backend/tests`. Add `-m "not live"` to skip the Snowflake tests.
- **Design and plan:** `docs/superpowers/specs/` and `docs/superpowers/plans/`.


A star schema and AI-ready semantic layer over the RAJAR AdWanted respondent data (2026 Q2), linked to published RAJAR reports and owners. It lives in `HACKATHON_TEAM_GINGER_DB.ANALYTICS`.

## What's in Snowflake

| Object | Grain | Rows |
|---|---|---|
| `FACT_LISTENING` | one diary claim, adults 15+ | 2,327,515 |
| `FACT_BRAND_LISTENING` | claim × brand it counts towards | 5,285,404 |
| `DIM_RESPONDENT` | respondent (demographics, weight, app use) | 33,839 |
| `DIM_STATION` | station code (station × platform) | 2,395 |
| `DIM_BRAND` | AdWanted brand / sales group, with owner and matched RAJAR report | 1,192 |
| `DIM_TIME_SLOT` | diary slot with daypart and RAJAR time band | 84 |
| `BRIDGE_BRAND_STATION` | brand ↔ station code | 6,777 |
| `ADWANTED_LISTENING_SV` | semantic view over all of the above, for Cortex Analyst and agents | |
| `SCHEMA_VECTORS` | vector store: one sentence per categorical value combination, with embedding and filters | 93,717 |
| `SEARCH_SCHEMA_VECTORS(q, table, k, entry_type)` | table function: semantic search over `SCHEMA_VECTORS` | |

Every table and column has a Snowflake comment.

## Rules baked into the model

- `weight_persons = "Weight" / 10`
- `quarter_hours = (2 if half-hour slot else 1) / claimcount`, where `claimcount` is the number of stations claimed in the same slot
- `weighted_hours = weight_persons * quarter_hours / 4`
- Weekly reach is the weighted count of distinct respondents. The semantic view computes it exactly with `(SUM(DISTINCT reach_key) - SUM(DISTINCT reach_base)) / 10000`, which works under any filter.

## Validation

`python scripts/validate_model.py` checks the semantic view against published RAJAR 2026 Q2 figures:
- All Radio: 51,119k reach and 1,040,047k hours
- BBC Radio 2: 12,367k reach and 138,039k hours
- Radio 2 women 25–34: 602k
- Radio 2 ABC1 men: 3,287k
- All 53 quarterly-published brands match their published reach exactly

It also checks row counts and that no rows are orphaned. All checks pass.

## Scripts (run in the `aiEnv` conda env)

| Command | What it does |
|---|---|
| `python scripts/run_sql.py sql/analytics/01_build_model.sql` | Rebuild all tables (about 15 s on X-Small) |
| `python scripts/deploy_semantic_view.py` | Validate and deploy the semantic view, apply comments |
| `python scripts/validate_model.py` | Run the checks above |
| `python scripts/ask_analyst.py "question"` | Ask Cortex Analyst and run its SQL |
| `python scripts/run_sql.py sql/analytics/02_build_schema_vectors.sql` | Rebuild the vector store (about 30 s) |
| `python scripts/vector_search.py "young" "women" "on DAB"` | Top-3 filter candidates per phrase |
| `python test_snowflake_connection.py` | Check the key-pair connection |

All scripts use the `rajar_hackathon` connection in `~/.snowflake/connections.toml` (key-pair auth).

## Other files

- `semantic/adwanted_listening.yaml`: the semantic model (source of truth for the view)
- `docs/agent_context.md`: routing and rules to load into the custom agent
- `sql/adwanted_rajar_lineage.sql`: the original lineage exploration queries
- Lineage write-up: https://claude.ai/artifact/PmCDMBFvCBTsjKSdrAZbfQ

## Known gaps

- `where_listened_code` (1, 2, 3, 5) has no labels in the share.
- Day names Monday–Sunday are inferred from diary codes 1–7. Saturday and Sunday reach are within 2% of the published figures.
- 380 of 1,192 AdWanted brands have no matching RAJAR report. They still work for respondent-level analysis, but they have no owner or published figures.
- Media-habit codes such as `working_status_code`, `mosaic_type_code` and `acorn_group_code` are loaded raw because the share has no codebook for them.

# RAJAR data: context for the AI agent

Load this file into the agent's system prompt. It tells the agent which Snowflake source answers which kind of question and the rules that keep numbers correct.

## Two semantic views, one job each

| Question type | Use | Why |
|---|---|---|
| Custom cuts for 2026 Q2: platform, daypart, time slot, day of week, custom age ranges, gender × social grade, region, app users, cross-listening between brands | `HACKATHON_TEAM_GINGER_DB.ANALYTICS.ADWANTED_LISTENING_SV` | Respondent-level diary data. Calculates audiences on demand. |
| Published RAJAR figures, trends across quarters, quarter-on-quarter and year-on-year change, market share in a report's own area, competitor sets | `SRC_RAJAR_SHARE.RAJAR.REACH_DEMOGRAPHICS_V2` | The official pre-aggregated E-Demogs numbers across many releases. |

If a question needs both (for example "how did Heart London's reach change since last year, and which platforms drive it now?"), answer the trend from `REACH_DEMOGRAPHICS_V2` and the platform split from `ADWANTED_LISTENING_SV`, then join them with `brands.rajar_report_number` = `REPORT_NUMBER`.

## Calling it

- **Cortex Analyst:** `scripts/ask_analyst.py` → `ask(question)` returns the generated SQL, the result rows and Analyst's interpretation text. Pass `semantic_view` = the view name.
- **Direct SQL:** `SELECT * FROM SEMANTIC_VIEW(HACKATHON_TEAM_GINGER_DB.ANALYTICS.ADWANTED_LISTENING_SV METRICS brand_listening.brand_weekly_reach_000s DIMENSIONS brands.brand_name WHERE brands.owner LIKE 'GLOBAL%')`
- **Model description:** `semantic/adwanted_listening.yaml` (same content as the deployed view), or `DESCRIBE SEMANTIC VIEW ...` at runtime.

## Turning phrases into filters (vector store)

`ANALYTICS.SCHEMA_VECTORS` holds 93,717 embedded sentences built from every table's categorical values (model `snowflake-arctic-embed-m-v1.5`). Each row has `TABLE_NAME`, `CONTEXT`, `VECTOR`, `FILTERS` (`{"TABLE.COLUMN": value}`) and `FILTER_SQL`.

| ENTRY_TYPE | Rows | Use |
|---|---|---|
| `single_value` | 687 | One column = one value. Use these to build filters. |
| `combination` | 31,351 | Every distinct combination per table (respondent demographics, station, brand, brand × platform × day, bridge). Use as "closest segment" examples. |
| `profile` | 61,679 | Respondent demographic combination × station listened to (`FACT_LISTENING`). |

How to use it:
1. Split the question into attribute phrases ("young", "working class", "in London", "on DAB").
2. Call `match_phrases(phrases)` in `scripts/vector_search.py`, or run `SELECT * FROM TABLE(SEARCH_SCHEMA_VECTORS('<phrase>', '', 3, 'single_value'))`.
3. Pick one candidate per phrase yourself. The right value is the top match for 21 of 25 test phrases and in the top 3 for all 25. The embedding model confuses opposites ("working class" ranks ABC1 just above C2DE), so read the `CONTEXT`, don't just take the first row.
4. Build the WHERE clause with `to_where(filters)`. Filter keys are `TABLE.COLUMN`, so reference tables by name, or rewrite them to your aliases.

Don't embed the whole question: it blurs the attributes together and pulls in look-alike station names.

## Rules the agent must follow

1. Reach is always a distinct-respondent metric (`weekly_reach_000s`, `brand_weekly_reach_000s`). Never add reach across rows, platforms or dayparts.
2. `brand_listening` repeats each claim once per brand. Filter to named brands or group by brand. For all-radio questions use `listening`.
3. "Global" means `owner LIKE 'GLOBAL%'`; "Bauer" means `owner LIKE 'BAUER%'`.
4. Report `unweighted_sample` with every figure and call out samples under 100 as low base.
5. Units: reach in thousands of people aged 15+; hours in thousands of weekly hours. Universe is about 59.0 million adults.
6. Published figures in `brands` are comparable only when `published_survey_period = 'Q'`. H and Y periods use 6 or 12 months of fieldwork and will differ.
7. Day names are inferred from diary codes 1–7 (Monday–Sunday). `where_listened_code` has no labels; report the code.

## Checked answers (use as few-shot examples)

| Question | Answer |
|---|---|
| Weekly reach of BBC Radio 2 | 12,367k, 138,039k hours (matches published) |
| All radio weekly reach | 51,119k, 1,040,047k hours (matches published) |
| BBC Radio 2 among women 25–34 | 602k, sample 466 |
| Top Global brand among 15–34s | Capital XTRA (UK), 886k, sample 405 |
| Heart London listeners who also listen to Capital London | 23.8% (441k of 1,851k) |

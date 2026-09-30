"""Check the ANALYTICS model and semantic view against published RAJAR 2026 Q2 figures.

Every check queries through the semantic view (SEMANTIC_VIEW(...)) so it tests the
metric definitions an AI agent will use, not just the tables.

Usage:  python scripts/validate_model.py      (exit code 1 if any check fails)
"""

import sys

import snowflake.connector

CONNECTION = "rajar_hackathon"
SV = "HACKATHON_TEAM_GINGER_DB.ANALYTICS.ADWANTED_LISTENING_SV"
RAJAR = "HACKATHON_TEAM_GINGER_DB.RAJAR"
ANALYTICS = "HACKATHON_TEAM_GINGER_DB.ANALYTICS"


def brand_sv(where):
    return f"""
        SELECT ROUND(brand_weekly_reach_000s), ROUND(brand_total_hours_000s)
        FROM SEMANTIC_VIEW({SV}
            METRICS brand_listening.brand_weekly_reach_000s, brand_listening.brand_total_hours_000s
            WHERE {where})"""


def published(report, demographic=None):
    if demographic:
        return f"""SELECT WEEKLY_REACH_000S, TOTAL_HOURS FROM {RAJAR}.WEEKLY_REACH_BY_DEMOGRAPHIC
                   WHERE RELEASE_NUMBER = 202602 AND REPORT_NUMBER = {report} AND DEMOGRAPHIC = '{demographic}'"""
    return f"""SELECT WEEKLY_REACH_000S, TOTAL_HOURS FROM {RAJAR}.WEEKLY_REACH
               WHERE RELEASE_NUMBER = 202602 AND REPORT_NUMBER = {report}"""


# (label, model query, expected query, compare hours too?)
CHECKS = [
    ("All Radio reach + hours (listening)",
     f"""SELECT ROUND(weekly_reach_000s), ROUND(total_hours_000s)
         FROM SEMANTIC_VIEW({SV} METRICS listening.weekly_reach_000s, listening.total_hours_000s)""",
     published(1690), True),
    ("BBC Radio 2 reach + hours (brand_listening)",
     brand_sv("brands.brand_name = 'BBC Radio 2'"), published(1901), True),
    ("BBC Radio 2 women 25-34 reach",
     brand_sv("brands.brand_name = 'BBC Radio 2' AND respondents.gender = 'Women' AND respondents.age BETWEEN 25 AND 34"),
     published(1901, "Women 25-34"), False),
    ("BBC Radio 2 ABC1 men reach",
     brand_sv("brands.brand_name = 'BBC Radio 2' AND respondents.social_segment = 'ABC1' AND respondents.gender = 'Men'"),
     published(1901, "ABC1 Men"), False),
]

INTEGRITY = [
    ("Every quarterly-published matched brand (survey period Q) reproduces published reach exactly",
     f"""WITH m AS (
             SELECT brand_id, ROUND(brand_weekly_reach_000s) AS model_reach
             FROM SEMANTIC_VIEW({SV} METRICS brand_listening.brand_weekly_reach_000s DIMENSIONS brands.brand_id))
         SELECT COUNT(*) FROM {ANALYTICS}.DIM_BRAND b JOIN m USING (brand_id)
         WHERE b.published_survey_period = 'Q' AND m.model_reach <> b.published_weekly_reach_000s""",
     "SELECT 0"),
    ("FACT_LISTENING rows = diary rows for adults 15+",
     f"SELECT COUNT(*) FROM {ANALYTICS}.FACT_LISTENING",
     f"""SELECT COUNT(*) FROM {RAJAR}.ADWANTED_DIARY_2026_Q2 d
         JOIN {RAJAR}.ADWANTED_PERSON_2026_Q2 p ON p."MTPersonNo" = d."MTPersonNo" WHERE p."age" >= 15"""),
    ("FACT_BRAND_LISTENING rows = ADWANTED_DIARY_IMPACTS rows",
     f"SELECT COUNT(*) FROM {ANALYTICS}.FACT_BRAND_LISTENING",
     f"SELECT COUNT(*) FROM {RAJAR}.ADWANTED_DIARY_IMPACTS"),
    ("Every fact station code is in DIM_STATION",
     f"""SELECT COUNT(*) FROM {ANALYTICS}.FACT_LISTENING f
         LEFT JOIN {ANALYTICS}.DIM_STATION s USING (station_code) WHERE s.station_code IS NULL""",
     "SELECT 0"),
    ("Every fact respondent is in DIM_RESPONDENT",
     f"""SELECT COUNT(*) FROM {ANALYTICS}.FACT_LISTENING f
         LEFT JOIN {ANALYTICS}.DIM_RESPONDENT r USING (respondent_id) WHERE r.respondent_id IS NULL""",
     "SELECT 0"),
]


def one(cur, sql):
    cur.execute(sql)
    return cur.fetchone()


def main():
    failures = 0
    conn = snowflake.connector.connect(connection_name=CONNECTION)
    with conn:
        cur = conn.cursor()
        print("Published-figure checks (through the semantic view)")
        for label, model_sql, expected_sql, with_hours in CHECKS:
            got, want = one(cur, model_sql), one(cur, expected_sql)
            if got is None or want is None:
                failures += 1
                print(f"  FAIL  {label}: no row returned (model={got}, expected={want})")
                continue
            ok = float(got[0]) == float(want[0]) and (not with_hours or float(got[1]) == float(want[1]))
            failures += not ok
            detail = f"reach {got[0]:,.0f} vs {want[0]:,.0f}"
            if with_hours:
                detail += f", hours {got[1]:,.0f} vs {want[1]:,.0f}"
            print(f"  {'PASS' if ok else 'FAIL'}  {label}: {detail}")

        print("\nIntegrity checks")
        for label, model_sql, expected_sql in INTEGRITY:
            got, want = one(cur, model_sql)[0], one(cur, expected_sql)[0]
            ok = got == want
            failures += not ok
            print(f"  {'PASS' if ok else 'FAIL'}  {label}: {got:,} vs {want:,}")

    print(f"\n{'All checks passed' if not failures else f'{failures} check(s) failed'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()

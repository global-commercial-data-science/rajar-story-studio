"""Semantic search over ANALYTICS.SCHEMA_VECTORS, for turning question phrases into SQL filters.

Recommended flow for the agent:
  1. The LLM splits the question into attribute phrases:
       "young upmarket women in London on DAB" -> ["young", "upmarket", "women", "in London", "on DAB"]
  2. match_phrases(phrases) returns the top-3 single-value filter candidates per phrase.
  3. The LLM picks one candidate per phrase (the right value is in the top 3 for 25/25 test
     phrases, top 1 for 21/25), then to_where(chosen_filters) builds the WHERE fragment.

Searching whole questions blurs attributes together, so prefer phrases. search() is also
exposed for raw access to combination and profile entries.

Usage:  python scripts/vector_search.py "young" "upmarket" "women" "in London" "on DAB"
"""

import json
import sys

import snowflake.connector

CONNECTION = "rajar_hackathon"
SEARCH_FN = "HACKATHON_TEAM_GINGER_DB.ANALYTICS.SEARCH_SCHEMA_VECTORS"


def search(question, table="", k=10, entry_type="", conn=None):
    """Nearest SCHEMA_VECTORS entries. entry_type: '', 'single_value', 'combination' or 'profile'."""
    conn = conn or snowflake.connector.connect(connection_name=CONNECTION)
    cur = conn.cursor(snowflake.connector.DictCursor)
    cur.execute(
        f"SELECT * FROM TABLE({SEARCH_FN}(%s, %s, %s, %s))",
        (question, table or "", k, entry_type or ""),
    )
    rows = cur.fetchall()
    for r in rows:
        if isinstance(r["FILTERS"], str):
            r["FILTERS"] = json.loads(r["FILTERS"])
    return rows


def match_phrases(phrases, k=3, table="", conn=None):
    """Return {phrase: [{"filter": {TABLE.COLUMN: value}, "context": str, "similarity": float}, ...]}."""
    conn = conn or snowflake.connector.connect(connection_name=CONNECTION)
    return {
        phrase: [
            {"filter": h["FILTERS"], "context": h["CONTEXT"], "similarity": round(h["SIMILARITY"], 3)}
            for h in search(phrase, table=table, k=k, entry_type="single_value", conn=conn)
        ]
        for phrase in phrases
    }


def to_where(filters):
    """{TABLE.COLUMN: value} -> "TABLE.COLUMN = 'value' AND ..." (same rules as FILTERS_TO_SQL)."""
    def literal(v):
        if v is None:
            return "IS NULL"
        if isinstance(v, bool):
            return f"= {'TRUE' if v else 'FALSE'}"
        if isinstance(v, (int, float)):
            return f"= {v}"
        return "= '" + str(v).replace("'", "''") + "'"
    return " AND ".join(f"{c} {literal(v)}" for c, v in sorted(filters.items()))


if __name__ == "__main__":
    phrases = sys.argv[1:] or ["young", "upmarket", "women", "in London", "on DAB"]
    print(json.dumps(match_phrases(phrases), indent=2, default=str))

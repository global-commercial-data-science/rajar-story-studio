"""Ask Cortex Analyst a question against the ADWANTED_LISTENING_SV semantic view.

Reuses the key-pair session from the rajar_hackathon connection, sends the question to
the Cortex Analyst REST API, then runs the SQL it returns. A ready-made tool for the agent.

Usage:  python scripts/ask_analyst.py "What is the weekly reach of Heart London by platform?"
"""

import json
import sys

import requests
import snowflake.connector

CONNECTION = "rajar_hackathon"
SEMANTIC_VIEW = "HACKATHON_TEAM_GINGER_DB.ANALYTICS.ADWANTED_LISTENING_SV"


def ask(question, conn=None):
    """Return {"text": ..., "sql": ..., "columns": [...], "rows": [...]} for a question."""
    conn = conn or snowflake.connector.connect(connection_name=CONNECTION)
    # TLS certificates don't cover underscores in account hostnames; use the hyphenated form
    host = "https://" + conn.host.removeprefix("https://").replace("_", "-")
    resp = requests.post(
        f"{host}/api/v2/cortex/analyst/message",
        headers={
            "Authorization": f'Snowflake Token="{conn.rest.token}"',
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json={
            "messages": [{"role": "user", "content": [{"type": "text", "text": question}]}],
            "semantic_view": SEMANTIC_VIEW,
        },
        timeout=120,
    )
    resp.raise_for_status()
    content = resp.json()["message"]["content"]

    answer = {"text": "", "sql": None, "columns": [], "rows": [], "suggestions": []}
    for block in content:
        if block["type"] == "text":
            answer["text"] += block["text"]
        elif block["type"] == "sql":
            answer["sql"] = block["statement"]
        elif block["type"] == "suggestions":
            answer["suggestions"] = block["suggestions"]

    if answer["sql"]:
        cur = conn.cursor()
        cur.execute(answer["sql"])
        answer["columns"] = [d[0] for d in cur.description]
        answer["rows"] = cur.fetchall()
    return answer


if __name__ == "__main__":
    result = ask(" ".join(sys.argv[1:]) or "What is the weekly reach of BBC Radio 2?")
    print(result["text"], "\n")
    if result["sql"]:
        print(result["sql"], "\n")
        print(" | ".join(result["columns"]))
        for row in result["rows"][:25]:
            print(" | ".join(str(v) for v in row))
    elif result["suggestions"]:
        print("Suggestions:\n" + json.dumps(result["suggestions"], indent=2))

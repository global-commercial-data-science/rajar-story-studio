"""Deploy semantic/adwanted_listening.yaml as a Snowflake semantic view.

1. Validates the YAML with SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML (verify only).
2. Replaces the semantic view HACKATHON_TEAM_GINGER_DB.ANALYTICS.ADWANTED_LISTENING_SV.
3. Copies every table and column description onto the physical tables as COMMENTs,
   so plain-SQL tools and agents see the same documentation.

Usage:  python scripts/deploy_semantic_view.py [--verify-only]
"""

import re
import sys
from pathlib import Path

import snowflake.connector
import yaml

CONNECTION = "rajar_hackathon"
TARGET_SCHEMA = "HACKATHON_TEAM_GINGER_DB.ANALYTICS"
YAML_PATH = Path(__file__).resolve().parent.parent / "semantic" / "adwanted_listening.yaml"
BARE_COLUMN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def sql_str(text):
    return "'" + " ".join(str(text).split()).replace("\\", "\\\\").replace("'", "''") + "'"


def column_comments(model):
    """Yield (table, column, description) for fields whose expr is a plain column."""
    for table in model["tables"]:
        base = table["base_table"]
        fqn = f'{base["database"]}.{base["schema"]}.{base["table"]}'
        yield fqn, None, table["description"]
        seen = set()
        for kind in ("dimensions", "time_dimensions", "facts"):
            for field in table.get(kind, []):
                expr = field["expr"].strip()
                if BARE_COLUMN.match(expr) and expr.lower() not in seen and field.get("description"):
                    seen.add(expr.lower())
                    yield fqn, expr, field["description"]


def main(verify_only):
    raw = YAML_PATH.read_text()
    model = yaml.safe_load(raw)
    view = f'{TARGET_SCHEMA}.{model["name"]}'

    conn = snowflake.connector.connect(connection_name=CONNECTION)
    with conn:
        cur = conn.cursor()
        cur.execute(f"CALL SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML('{TARGET_SCHEMA}', %s, TRUE)", (raw,))
        print("verify:", cur.fetchone()[0])
        if verify_only:
            return

        cur.execute(f"DROP SEMANTIC VIEW IF EXISTS {view}")
        cur.execute(f"CALL SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML('{TARGET_SCHEMA}', %s)", (raw,))
        print("create:", cur.fetchone()[0])

        n = 0
        for fqn, column, text in column_comments(model):
            if column is None:
                cur.execute(f"COMMENT ON TABLE {fqn} IS {sql_str(text)}")
            else:
                cur.execute(f"COMMENT ON COLUMN {fqn}.{column} IS {sql_str(text)}")
            n += 1
        print(f"comments: {n} table/column comments applied")


if __name__ == "__main__":
    main("--verify-only" in sys.argv)

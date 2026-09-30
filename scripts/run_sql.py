"""Run a .sql file against the rajar_hackathon connection, statement by statement.

Usage:  python scripts/run_sql.py sql/analytics/01_build_model.sql
"""

import io
import sys
import time

import snowflake.connector

CONNECTION = "rajar_hackathon"


def main(path):
    sql = open(path).read()
    conn = snowflake.connector.connect(connection_name=CONNECTION)
    start = time.time()
    with conn:
        for cur in conn.execute_stream(io.StringIO(sql)):
            first = cur.query.strip().splitlines()[0][:90] if cur.query else ""
            rows = cur.fetchmany(20) if cur.description else []
            if cur.description and cur.description[0][0].lower() != "status":
                print(f"\n-- {first}")
                print(" | ".join(d[0] for d in cur.description))
                for r in rows:
                    print(" | ".join("" if v is None else str(v) for v in r))
            else:
                msg = rows[0][0] if rows else "ok"
                print(f"[{time.time() - start:6.1f}s] {msg}")
    print(f"\nDone in {time.time() - start:.1f}s")


if __name__ == "__main__":
    main(sys.argv[1])

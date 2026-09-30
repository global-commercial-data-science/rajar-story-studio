"""Smoke-test the connection to the rajar_hackathon Snowflake account.

Uses key-pair (JWT) auth so no password or MFA prompt is needed.
The public key must already be registered on the user with
ALTER USER ... SET RSA_PUBLIC_KEY = '...'.

Run:  conda run -n aiEnv python test_snowflake_connection.py
"""

import os
import sys
from pathlib import Path

import snowflake.connector
from snowflake.connector.errors import DatabaseError

ACCOUNT = os.getenv("SNOWFLAKE_ACCOUNT", "global-rajar_hackathon")
USER = os.getenv("SNOWFLAKE_USER", "vipul.kumar@global.com")
PRIVATE_KEY_FILE = Path(
    os.getenv("SNOWFLAKE_PRIVATE_KEY_FILE", "~/.snowflake/keys/rajar_hackathon_key.p8")
).expanduser()


def connect():
    if not PRIVATE_KEY_FILE.exists():
        sys.exit(f"Private key not found at {PRIVATE_KEY_FILE}")
    return snowflake.connector.connect(
        account=ACCOUNT,
        user=USER,
        authenticator="SNOWFLAKE_JWT",
        private_key_file=str(PRIVATE_KEY_FILE),
        login_timeout=30,
    )


def show(cur, title, sql, columns=None, limit=50):
    print(f"\n== {title} ==")
    rows = cur.execute(sql).fetchall()
    names = [d[0].lower() for d in cur.description]
    idx = [names.index(c) for c in columns] if columns else range(len(names))
    for row in rows[:limit]:
        print("  " + " | ".join(str(row[i]) for i in idx))
    if len(rows) > limit:
        print(f"  ... {len(rows) - limit} more")
    return rows


def main():
    print(f"Connecting to {ACCOUNT} as {USER} ...")
    try:
        conn = connect()
    except DatabaseError as e:
        print(f"\nConnection FAILED: {e}")
        if "JWT token is invalid" in str(e):
            print("-> Public key not registered on this user (or wrong user). "
                  "Run the ALTER USER ... SET RSA_PUBLIC_KEY statement in Snowsight.")
        sys.exit(1)

    print("Connected OK")
    with conn:
        cur = conn.cursor()
        show(cur, "Session",
             "SELECT CURRENT_ORGANIZATION_NAME(), CURRENT_ACCOUNT_NAME(), CURRENT_USER(), "
             "CURRENT_ROLE(), CURRENT_WAREHOUSE(), CURRENT_REGION(), CURRENT_VERSION()")
        show(cur, "Available roles", "SELECT CURRENT_AVAILABLE_ROLES()")
        show(cur, "Warehouses", "SHOW WAREHOUSES", ["name", "state", "size"])
        dbs = show(cur, "Databases", "SHOW DATABASES", ["name", "owner", "comment"])

        # List tables/views in every non-system database so we can see the dataset.
        db_names = [r[1] for r in dbs if r[1] not in ("SNOWFLAKE", "SNOWFLAKE_SAMPLE_DATA")]
        for db in db_names:
            try:
                show(cur, f"Tables & views in {db}",
                     f'SELECT table_schema, table_name, table_type, row_count '
                     f'FROM "{db}".INFORMATION_SCHEMA.TABLES '
                     f"WHERE table_schema <> 'INFORMATION_SCHEMA' "
                     f'ORDER BY 1, 2')
            except DatabaseError as e:
                print(f"  (could not list: {e.msg})")


if __name__ == "__main__":
    main()

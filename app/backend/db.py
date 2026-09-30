"""Snowflake access: one shared key-pair connection and a read-only query helper."""

import os
import re
import threading

import snowflake.connector

from . import config

_conn = None
_lock = threading.Lock()

_WRITE_WORDS = re.compile(
    r"\b(insert|update|delete|merge|create|alter|drop|truncate|grant|revoke|call|put|copy|use)\b", re.I
)


SPCS_TOKEN = "/snowflake/session/token"   # present only inside Snowpark Container Services


def _connect():
    if os.path.exists(SPCS_TOKEN):
        # Inside Snowflake: sign in as the service with the token Snowflake rotates for us
        with open(SPCS_TOKEN) as f:
            token = f.read()
        return snowflake.connector.connect(
            host=os.environ["SNOWFLAKE_HOST"], account=os.environ["SNOWFLAKE_ACCOUNT"],
            authenticator="oauth", token=token,
            warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"), database=os.getenv("SNOWFLAKE_DATABASE"),
            schema=os.getenv("SNOWFLAKE_SCHEMA"), client_session_keep_alive=True,
        )
    return snowflake.connector.connect(connection_name=config.SNOWFLAKE_CONNECTION)


def connection(fresh=False):
    global _conn
    with _lock:
        if fresh or _conn is None or _conn.is_closed():
            _conn = _connect()
        return _conn


def query(sql, params=None, _retry=True):
    """Run a query and return rows as a list of dicts with lower-case keys (reconnects once on an expired session)."""
    cur = connection().cursor(snowflake.connector.DictCursor)
    try:
        cur.execute(sql, params)
        return [{k.lower(): v for k, v in row.items()} for row in cur.fetchall()]
    except snowflake.connector.errors.DatabaseError as e:
        if _retry and getattr(e, "errno", None) in (390114, 390111, 390195, 250001):
            connection(fresh=True)
            return query(sql, params, _retry=False)
        raise
    finally:
        cur.close()


def read_only_query(sql, max_rows=200):
    """Run agent-written SQL: a single SELECT/WITH statement, capped rows."""
    stripped = sql.strip().rstrip(";").strip()
    if ";" in stripped:
        raise ValueError("Only one statement is allowed.")
    if not re.match(r"^(select|with)\b", stripped, re.I):
        raise ValueError("Only SELECT or WITH queries are allowed.")
    if _WRITE_WORDS.search(re.sub(r"'[^']*'", "''", stripped)):
        raise ValueError("Write or session statements are not allowed.")
    return query(f"SELECT * FROM ({stripped}) LIMIT {int(max_rows)}")

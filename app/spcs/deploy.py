"""Build, push and (re)deploy RAJAR Pulse to Snowpark Container Services.

    python app/spcs/deploy.py                   # deploy (app works; OpenAI calls blocked until an EAI exists)
    python app/spcs/deploy.py --eai PULSE_OPENAI_EAI   # after organisers run organiser_setup.sql
    python app/spcs/deploy.py --status          # show status and URL only

Uses the rajar_hackathon key-pair connection. Needs Docker running (Rancher Desktop) and the
Snowflake CLI for the registry login (pip install snowflake-cli, or set SNOW_BIN to its path).
The OpenAI key is read from .env and stored as a Snowflake secret; it is never printed or baked into the image.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import snowflake.connector
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "HACKATHON_TEAM_GINGER_DB.ANALYTICS"
REPO = f"{SCHEMA}.PULSE_REPO"
SERVICE = f"{SCHEMA}.RAJAR_PULSE"
POOL = "HACKATHON_CPU_POOL"
SECRET = f"{SCHEMA}.OPENAI_API_KEY"
NETWORK_RULE = f"{SCHEMA}.OPENAI_EGRESS"
SHARE_WITH_ROLE = "HACKATHON_PARTICIPANT"


def sql(cur, statement, quiet=False):
    if not quiet:
        print(f"  sql> {statement.splitlines()[0][:110]}")
    cur.execute(statement)
    return cur.fetchall()


def run(cmd, **kw):
    print(f"  $ {' '.join(cmd)}")
    subprocess.run(cmd, check=True, **kw)


def setup_objects(cur):
    print("1. Snowflake objects")
    sql(cur, f"CREATE IMAGE REPOSITORY IF NOT EXISTS {REPO}")
    sql(cur, f"CREATE NETWORK RULE IF NOT EXISTS {NETWORK_RULE} MODE = EGRESS TYPE = HOST_PORT VALUE_LIST = ('api.openai.com:443')")
    key = dotenv_values(ROOT / ".env").get("OPENAI_API_KEY")
    if not key:
        sys.exit("OPENAI_API_KEY is missing from .env")
    escaped = key.replace("\\", "\\\\").replace("'", "\\'")
    print(f"  sql> CREATE OR REPLACE SECRET {SECRET} TYPE = GENERIC_STRING SECRET_STRING = '***'")
    cur.execute(f"CREATE OR REPLACE SECRET {SECRET} TYPE = GENERIC_STRING SECRET_STRING = '{escaped}'")
    rows = sql(cur, f"SHOW IMAGE REPOSITORIES LIKE 'PULSE_REPO' IN SCHEMA {SCHEMA}", quiet=True)
    return rows[0][4]  # repository_url


def docker_login(repo_url):
    """Log Docker in to the Snowflake registry with the Snowflake CLI (pip install snowflake-cli)."""
    print("2. Docker login to the Snowflake registry")
    snow = os.getenv("SNOW_BIN", shutil.which("snow") or "snow")
    r = subprocess.run([snow, "spcs", "image-registry", "login", "-c", "rajar_hackathon", "--role", "HACKATHON_TEAM_GINGER"],
                       capture_output=True, text=True)
    if r.returncode != 0 or "Login Succeeded" not in r.stdout:
        sys.exit(f"Registry login failed. Install the Snowflake CLI (pip install snowflake-cli) or set SNOW_BIN.\n{r.stdout}{r.stderr}")
    print(f"  logged in to {repo_url.split('/')[0]}")


def build_and_push(repo_url):
    tag = time.strftime("%Y%m%d-%H%M%S")
    image = f"{repo_url}/rajar-pulse:{tag}"
    print("3. Build (linux/amd64) and push")
    run(["docker", "build", "--platform", "linux/amd64", "-t", image, str(ROOT)])
    run(["docker", "push", image])
    return image


def deploy_service(cur, repo_url, image, eai):
    print("4. Service")
    image_path = "/" + image.split("/", 1)[1]           # spec uses /db/schema/repo/image:tag
    spec = (ROOT / "app/spcs/service.yaml").read_text().replace("{{IMAGE}}", image_path)
    exists = sql(cur, f"SHOW SERVICES LIKE 'RAJAR_PULSE' IN SCHEMA {SCHEMA}", quiet=True)
    eai_clause = f"EXTERNAL_ACCESS_INTEGRATIONS = ({eai})" if eai else ""
    if exists:
        sql(cur, f"ALTER SERVICE {SERVICE} FROM SPECIFICATION $${spec}$$")
        if eai:
            sql(cur, f"ALTER SERVICE {SERVICE} SET {eai_clause}")
    else:
        sql(cur, f"""CREATE SERVICE {SERVICE} IN COMPUTE POOL {POOL}
                     FROM SPECIFICATION $${spec}$$
                     MIN_INSTANCES = 1 MAX_INSTANCES = 1 {eai_clause}
                     COMMENT = 'RAJAR Pulse Story Studio (Team Ginger)'""")
    try:
        sql(cur, f"GRANT SERVICE ROLE {SERVICE}!ALL_ENDPOINTS_USAGE TO ROLE {SHARE_WITH_ROLE}")
    except snowflake.connector.errors.ProgrammingError as e:
        print(f"  (could not share the endpoint with {SHARE_WITH_ROLE}: {e.msg})")


def status(cur, wait=True):
    print("5. Status")
    deadline = time.time() + (600 if wait else 0)
    while True:
        st = json.loads(sql(cur, f"SELECT SYSTEM$GET_SERVICE_STATUS('{SERVICE}')", quiet=True)[0][0])
        state = st[0]["status"] if st else "UNKNOWN"
        print(f"  service status: {state} {st[0].get('message', '') if st else ''}")
        if state == "READY" or time.time() > deadline:
            break
        time.sleep(15)
    for _ in range(40 if wait else 1):
        rows = sql(cur, f"SHOW ENDPOINTS IN SERVICE {SERVICE}", quiet=True)
        url = next((r[5] for r in rows if r[0] == "app"), "")
        if url and "provisioning" not in url.lower():
            print(f"\n  RAJAR Pulse is live at: https://{url}\n  Sign in with a Snowflake user that has role {SHARE_WITH_ROLE} or HACKATHON_TEAM_GINGER.")
            return
        if not wait:
            break
        time.sleep(15)
    print("  Endpoint still provisioning; run `python app/spcs/deploy.py --status` in a minute.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eai", help="External access integration name (after organiser_setup.sql)")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()
    conn = snowflake.connector.connect(connection_name="rajar_hackathon")
    cur = conn.cursor()
    sql(cur, "USE ROLE HACKATHON_TEAM_GINGER", quiet=True)
    if args.status:
        return status(cur, wait=False)
    repo_url = setup_objects(cur)
    docker_login(repo_url)
    image = build_and_push(repo_url)
    deploy_service(cur, repo_url, image, args.eai)
    status(cur)


if __name__ == "__main__":
    main()

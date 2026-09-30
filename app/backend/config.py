"""Settings and the registry of RAJAR reports the app writes about."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

SNOWFLAKE_CONNECTION = os.getenv("SNOWFLAKE_CONNECTION", "rajar_hackathon")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-6-sol")

# LLM provider: "openai" calls api.openai.com with OPENAI_API_KEY; "cortex" calls the same OpenAI-compatible
# API inside Snowflake (no external access needed). Inside Snowpark Container Services the default is Cortex,
# because containers cannot reach the internet without an external access integration.
IN_SPCS = os.path.exists("/snowflake/session/token")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "cortex" if IN_SPCS else "openai").lower()
CORTEX_MODEL = os.getenv("CORTEX_MODEL", "openai-gpt-5.4")    # gpt-6-sol is not offered in Cortex in this account
LLM_MODEL = CORTEX_MODEL if LLM_PROVIDER == "cortex" else OPENAI_MODEL
LLM_LABEL = f"{LLM_MODEL} via Cortex" if LLM_PROVIDER == "cortex" else LLM_MODEL
RAJAR = "HACKATHON_TEAM_GINGER_DB.RAJAR"
ANALYTICS = "HACKATHON_TEAM_GINGER_DB.ANALYTICS"
LATEST_RELEASE = 202602

# Global brands: (key, display name, published report number)
GLOBAL_BRANDS = [
    ("heart", "Heart", 4520),
    ("capital", "Capital", 4388),
    ("smooth", "Smooth", 4441),
    ("classic_fm", "Classic FM", 6491),
    ("lbc", "LBC", 4090),
    ("lbc_news", "LBC News", 4821),
    ("radio_x", "Radio X", 6317),
    ("capital_xtra", "Capital XTRA", 4792),
    ("gold", "Gold", 4126),
]

# Major brand families shown as angle groups: key -> (name, head report numbers).
# Members (spin-offs, networks) are discovered from RAJAR REPORT_HIERARCHY descendants.
FAMILIES = [
    ("heart", "Heart", [4520]),
    ("capital", "Capital", [4388, 4792]),
    ("smooth", "Smooth", [4441]),
    ("classic_fm", "Classic FM", [6491]),
    ("lbc", "LBC", [4090]),
    ("radio_x", "Radio X", [6317]),
    ("gold", "Gold", [4126]),
]
BRAND_FAMILY = {"capital_xtra": "capital", "lbc_news": "lbc"}   # head brand key -> family key
FAMILY_MEMBER_MIN_REACH = 150      # 000s; smaller spin-offs are skipped
FAMILY_MEMBER_LIMIT = 8

BRAND_BLURBS = {
    "heart": "The UK's largest commercial radio brand: feel-good music plus digital spin-offs like Heart 80s and Heart Dance.",
    "capital": "The UK's leading hit music network, with digital companions Capital Dance and Capital XTRA.",
    "smooth": "Adult-contemporary network of relaxing, familiar music.",
    "classic_fm": "The UK's national commercial classical music station.",
    "lbc": "Leading Britain's Conversation: talk and news with high-profile phone-in shows.",
    "lbc_news": "LBC's rolling news service.",
    "radio_x": "National station for alternative music and indie rock.",
    "capital_xtra": "Capital's hip-hop, R&B and dance station.",
    "gold": "Classic hits, mainly from the 1950s, 60s and 70s.",
}

# Group totals: two published definitions, so both need confirming before use
GROUP_REPORTS = [
    ("global_brands", "Global radio brands (brands total)", 4433),
    ("global_total", "Global radio (all stations total)", 4100),
]

ALL_RADIO_REPORT = 1690

# Rivals used for head-to-head facts: key -> (display name, report number)
RIVALS = {
    "bbc_r2": ("BBC Radio 2", 1901),
    "bbc_r1": ("BBC Radio 1", 1900),
    "bbc_r3": ("BBC Radio 3", 1902),
    "bbc_r4": ("BBC Radio 4 (inc 4 Extra)", 4345),
    "magic": ("Magic Network (inc Jazz FM)", 6139),
    "absolute": ("Absolute Radio Network (inc Planet Rock)", 4401),
    "kiss": ("Kiss Network (inc heat & Kerrang!)", 4411),
    "greatest_hits": ("Greatest Hits Network (inc partners)", 4858),
    "hits_radio": ("Hits Radio Network (inc partners)", 4854),
    "hits_portfolio": ("Hits Radio Portfolio (inc partners)", 4850),
    "talksport": ("talkSPORT", 1005),
}

# Head-to-head pairings turned into "ahead/behind by" facts
HEAD_TO_HEAD = [
    ("heart", "bbc_r2"),
    ("heart", "hits_portfolio"),
    ("capital", "bbc_r1"),
    ("capital", "kiss"),
    ("smooth", "magic"),
    ("classic_fm", "bbc_r3"),
    ("lbc", "talksport"),
    ("radio_x", "absolute"),
    ("gold", "greatest_hits"),
]

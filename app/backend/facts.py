"""Fact engine: published RAJAR figures for Global's brands, turned into locked fact tokens.

No LLM here. Every figure a draft can quote is produced by these queries, with its
survey period, comparison release and a verification status.
"""

import re
from typing import Literal, Optional

from pydantic import BaseModel

from . import config, db


class Fact(BaseModel):
    key: str
    label: str
    value: float
    display: str
    unit: str
    brand: Optional[str] = None
    status: Literal["verified", "confirm"] = "verified"
    note: str = ""
    source: str = ""
    direction: Optional[str] = None  # up / down / flat, ahead / behind
    family: Optional[str] = None     # brand family key (heart, capital, ...) for grouping


class FactSet(BaseModel):
    release: int
    release_label: str
    qoq_release: Optional[int]
    qoq_label: Optional[str]
    yoy_release: Optional[int]
    yoy_label: Optional[str]
    history_quarters: int
    facts: list[Fact]
    families: list[dict] = []        # [{key, name, heads: [report], members: [{report, name, key}]}]

    def by_key(self):
        return {f.key: f for f in self.facts}


# ---------------------------------------------------------------- formatting

def format_reach(thousands):
    """Reach in 000s -> '12.8 million' or '459,000'."""
    thousands = abs(float(thousands))
    if thousands >= 1000:
        return f"{thousands / 1000:.1f} million"
    return f"{thousands:,.0f},000"


def format_hours(thousands):
    thousands = float(thousands)
    if thousands >= 1_000_000:
        return f"{thousands / 1_000_000:.2f} billion hours"
    if thousands >= 1000:
        return f"{thousands / 1000:.1f} million hours"
    return f"{thousands:,.0f},000 hours"


def format_share(pct):
    return f"{float(pct):.1f}%"


def format_change(current, previous):
    """Percent change -> (signed value, unsigned display, direction)."""
    pct = (float(current) / float(previous) - 1) * 100
    direction = "up" if pct > 0.05 else "down" if pct < -0.05 else "flat"
    return pct, f"{abs(pct):.1f}%", direction


def format_points(current, previous):
    diff = float(current) - float(previous)
    direction = "up" if diff > 0.05 else "down" if diff < -0.05 else "flat"
    points = abs(diff)
    return diff, f"{points:.1f} {'point' if round(points, 1) == 1 else 'points'}", direction


def quarter_label(release_label):
    """'2026 Q2' -> 'Q2 2026'."""
    year, quarter = release_label.split()
    return f"{quarter} {year}"


# ---------------------------------------------------------------- data access

def load_families(release):
    """Brand families from REPORT_HIERARCHY: national spin-offs and networks under each head report."""
    heads = sorted({r for _, _, reports in config.FAMILIES for r in reports})
    rows = db.query(
        f"""WITH kids AS (
                SELECT h.REPORT_NUMBER AS head, c.value::NUMBER AS child
                FROM {config.RAJAR}.REPORT_HIERARCHY h, LATERAL FLATTEN(input => h.DESCENDANT_REPORTS) c
                WHERE h.REPORT_NUMBER IN ({",".join(map(str, heads))}))
            SELECT k.head, k.child, ch.REPORT_NAME, w.WEEKLY_REACH_000S
            FROM kids k
            JOIN {config.RAJAR}.REPORT_HIERARCHY ch ON ch.REPORT_NUMBER = k.child
            JOIN {config.RAJAR}.WEEKLY_REACH w ON w.REPORT_NUMBER = k.child AND w.RELEASE_NUMBER = %s
            WHERE (ch.IS_NATIONAL OR ch.REPORT_AS_NETWORK OR ch.REPORT_NAME ILIKE '%%(UK)%%')
              AND w.WEEKLY_REACH_000S >= %s
            ORDER BY w.WEEKLY_REACH_000S DESC""",
        (release, config.FAMILY_MEMBER_MIN_REACH),
    )
    head_reports = {r for _, _, r in config.GLOBAL_BRANDS}
    used = {k for k, _, _ in config.GLOBAL_BRANDS} | {k for k, _, _ in config.GROUP_REPORTS} | set(config.RIVALS) | {"all_radio"}
    families = []
    for key, name, fam_heads in config.FAMILIES:
        members, seen = [], set()
        for r in rows:
            child = r["child"]
            if r["head"] not in fam_heads or child in head_reports or child in seen:
                continue
            seen.add(child)
            slug = re.sub(r"[^a-z0-9]+", "_", r["report_name"].lower()).strip("_")
            if slug in used:
                slug = f"{slug}_r{child}"
            used.add(slug)
            members.append({"report": child, "name": r["report_name"], "key": slug})
            if len(members) >= config.FAMILY_MEMBER_LIMIT:
                break
        families.append({"key": key, "name": name, "heads": fam_heads, "members": members})
    return families


def _load(release, extra_reports=()):
    report_numbers = sorted(
        set(extra_reports)
        | {r for _, _, r in config.GLOBAL_BRANDS}
        | {r for _, _, r in config.GROUP_REPORTS}
        | {r for _, r in config.RIVALS.values()}
        | {config.ALL_RADIO_REPORT}
    )
    rows = db.query(
        f"""SELECT REPORT_NUMBER, RELEASE_NUMBER, SURVEY_PERIOD, WEEKLY_REACH_000S, TOTAL_HOURS,
                   AVG_HOURS_PER_LISTENER, MARKET_SHARE
            FROM {config.RAJAR}.WEEKLY_REACH
            WHERE REPORT_NUMBER IN ({",".join(map(str, report_numbers))}) AND RELEASE_NUMBER <= %s""",
        (release,),
    )
    shares = db.query(
        f"""SELECT RELEASE_NUMBER, COMPARABLE_NAME, MARKET_SHARE, WEEKLY_REACH_000S
            FROM {config.RAJAR}.WEEKLY_REACH_COMPARABLES
            WHERE REPORT_NUMBER = %s AND COMPARABLE_NAME IN ('Any Commercial', 'Any BBC') AND RELEASE_NUMBER <= %s""",
        (config.ALL_RADIO_REPORT, release),
    )
    labels = {r["release_number"]: quarter_label(r["release_label"])
              for r in db.query(f"SELECT RELEASE_NUMBER, RELEASE_LABEL FROM {config.RAJAR}.RAJAR_RELEASES")}
    series = {}
    for r in rows:
        series.setdefault(r["report_number"], {})[r["release_number"]] = r
    share_series = {}
    for r in shares:
        share_series.setdefault(r["comparable_name"], {})[r["release_number"]] = r
    return series, share_series, labels


# ---------------------------------------------------------------- fact builders

class _Builder:
    def __init__(self, release, series, share_series, labels):
        self.release = release
        self.series = series
        self.share_series = share_series
        self.labels = labels
        releases = sorted({rel for s in series.values() for rel in s})
        self.releases = releases
        earlier = [r for r in releases if r < release]
        self.qoq = earlier[-1] if earlier else None
        self.yoy = release - 100 if (release - 100) in releases else None
        self.facts = []

    def add(self, key, label, value, display, unit, **kw):
        self.facts.append(Fact(key=key, label=label, value=round(float(value), 4), display=display, unit=unit, **kw))

    def source(self, report, release=None):
        return f"RAJAR WEEKLY_REACH · report {report} · release {release or self.release}"

    def period_note(self, row, other=None):
        period = {"Q": "3-month", "H": "6-month", "Y": "12-month"}.get(row["survey_period"], row["survey_period"])
        note = f"{period} survey period ({row['survey_period']})"
        if other is not None:
            note += f" · vs {self.labels.get(other, other)}"
        return note

    def peak_fact(self, key, name, report, brand, status):
        s = self.series[report]
        history = [rel for rel in self.releases if rel in s and rel <= self.release]
        current = s[self.release]["weekly_reach_000s"]
        earlier = [rel for rel in history if rel < self.release]
        higher = [rel for rel in earlier if s[rel]["weekly_reach_000s"] >= current]
        lower = [rel for rel in earlier if s[rel]["weekly_reach_000s"] <= current]
        if not higher and len(history) >= 4:
            self.add(f"{key}_reach_peak", f"{name} reach record", current, f"the highest in {len(history)} quarters",
                     "record", brand=brand, status=status, direction="up", source=self.source(report),
                     note=f"Highest weekly reach across {len(history)} releases ({self.labels[history[0]]} to {self.labels[self.release]})")
        elif higher and history.index(higher[-1]) <= len(history) - 5:
            since = higher[-1]
            self.add(f"{key}_reach_peak", f"{name} reach high", current, f"the highest since {self.labels[since]}",
                     "record", brand=brand, status=status, direction="up", source=self.source(report),
                     note=f"Highest weekly reach since {self.labels[since]}")
        if not lower and len(history) >= 4:
            self.add(f"{key}_reach_low", f"{name} reach low", current, f"the lowest in {len(history)} quarters",
                     "record", brand=brand, status=status, direction="down", source=self.source(report))
        elif lower and history.index(lower[-1]) <= len(history) - 5:
            self.add(f"{key}_reach_low", f"{name} reach low", current, f"the lowest since {self.labels[lower[-1]]}",
                     "record", brand=brand, status=status, direction="down", source=self.source(report))

    def report_facts(self, key, name, report, brand=None, status="verified", note_prefix="", family=None, lite=False):
        start = len(self.facts)
        self._report_facts(key, name, report, brand, status, note_prefix, lite)
        for f in self.facts[start:]:
            f.family = family

    def _report_facts(self, key, name, report, brand, status, note_prefix, lite):
        s = self.series.get(report, {})
        row = s.get(self.release)
        if not row:
            return
        extra = f"{note_prefix} · " if note_prefix else ""
        src = self.source(report)
        self.add(f"{key}_reach", f"{name} weekly reach", row["weekly_reach_000s"], format_reach(row["weekly_reach_000s"]),
                 "000s", brand=brand, status=status, source=src, note=extra + self.period_note(row))
        if not lite:
            self.add(f"{key}_hours", f"{name} total weekly hours", row["total_hours"], format_hours(row["total_hours"]),
                     "000s hours", brand=brand, status=status, source=src, note=extra + self.period_note(row))
        self.add(f"{key}_share", f"{name} share of listening", row["market_share"], format_share(row["market_share"]),
                 "%", brand=brand, status=status, source=src, note=extra + "Share of all radio listening in its survey area")
        if row["avg_hours_per_listener"] is not None and not lite:
            self.add(f"{key}_avg_hours", f"{name} hours per listener", row["avg_hours_per_listener"],
                     f"{float(row['avg_hours_per_listener']):.1f} hours", "hours", brand=brand, status=status, source=src)
        for tag, other in (("qoq", self.qoq), ("yoy", self.yoy)):
            prev = s.get(other) if other else None
            if not prev:
                continue
            same_period = prev["survey_period"] == row["survey_period"]
            st = status if same_period else "confirm"
            period_note = self.period_note(row, other) + ("" if same_period else " · survey periods differ")
            val, disp, direction = format_change(row["weekly_reach_000s"], prev["weekly_reach_000s"])
            self.add(f"{key}_reach_{tag}", f"{name} reach change vs {self.labels[other]}", val, disp, "%",
                     brand=brand, status=st, direction=direction, source=src,
                     note=f"{extra}{format_reach(prev['weekly_reach_000s'])} in {self.labels[other]} · {period_note}")
            if not lite:
                val, disp, direction = format_change(row["total_hours"], prev["total_hours"])
                self.add(f"{key}_hours_{tag}", f"{name} hours change vs {self.labels[other]}", val, disp, "%",
                         brand=brand, status=st, direction=direction, source=src, note=extra + period_note)
            val, disp, direction = format_points(row["market_share"], prev["market_share"])
            self.add(f"{key}_share_{tag}_pp", f"{name} share change vs {self.labels[other]}", val, disp, "points",
                     brand=brand, status=st, direction=direction, source=src,
                     note=f"{extra}Written as points, not % · {format_share(prev['market_share'])} in {self.labels[other]}")
        self.peak_fact(key, name, report, brand, status)

    def market_facts(self):
        for name, key in (("Any Commercial", "commercial"), ("Any BBC", "bbc")):
            s = self.share_series.get(name, {})
            row = s.get(self.release)
            if not row:
                continue
            label = "Commercial radio" if key == "commercial" else "BBC radio"
            src = f"RAJAR WEEKLY_REACH_COMPARABLES · All Radio (report {config.ALL_RADIO_REPORT}) · {name}"
            self.add(f"{key}_share", f"{label} share of listening", row["market_share"], format_share(row["market_share"]),
                     "%", source=src, note="Share of all UK radio listening hours")
            self.add(f"{key}_reach", f"{label} weekly reach", row["weekly_reach_000s"], format_reach(row["weekly_reach_000s"]),
                     "000s", source=src)
            for tag, other in (("qoq", self.qoq), ("yoy", self.yoy)):
                prev = s.get(other) if other else None
                if prev:
                    val, disp, direction = format_points(row["market_share"], prev["market_share"])
                    self.add(f"{key}_share_{tag}_pp", f"{label} share change vs {self.labels[other]}", val, disp, "points",
                             direction=direction, source=src,
                             note=f"Written as points, not % · {format_share(prev['market_share'])} in {self.labels[other]}")
        c = self.share_series.get("Any Commercial", {}).get(self.release)
        b = self.share_series.get("Any BBC", {}).get(self.release)
        if c and b:
            val, disp, direction = format_points(c["market_share"], b["market_share"])
            self.add("commercial_lead_pp", "Commercial share lead over the BBC", val, disp, "points",
                     direction="ahead" if val > 0 else "behind", source="Any Commercial minus Any BBC share")

    def head_to_head(self):
        by_key = {k: (n, r) for k, n, r in config.GLOBAL_BRANDS}
        for brand_key, rival_key in config.HEAD_TO_HEAD:
            name, report = by_key[brand_key]
            rival_name, rival_report = config.RIVALS[rival_key]
            a = self.series.get(report, {}).get(self.release)
            b = self.series.get(rival_report, {}).get(self.release)
            if not (a and b):
                continue
            diff = a["weekly_reach_000s"] - b["weekly_reach_000s"]
            periods = f"{a['survey_period']} vs {b['survey_period']} survey periods"
            self.add(f"{brand_key}_vs_{rival_key}", f"{name} reach vs {rival_name}", abs(diff), format_reach(abs(diff)),
                     "000s", brand=brand_key, family=config.BRAND_FAMILY.get(brand_key, brand_key),
                     direction="ahead" if diff > 0 else "behind",
                     source=f"{self.source(report)} and report {rival_report}",
                     note=f"{name} {format_reach(a['weekly_reach_000s'])} vs {rival_name} {format_reach(b['weekly_reach_000s'])} · {periods}")

    def rival_facts(self):
        for key, (name, report) in config.RIVALS.items():
            row = self.series.get(report, {}).get(self.release)
            if row:
                self.add(f"{key}_reach", f"{name} weekly reach", row["weekly_reach_000s"], format_reach(row["weekly_reach_000s"]),
                         "000s", source=self.source(report), note=self.period_note(row))


def build_facts(release=config.LATEST_RELEASE):
    families = load_families(release)
    member_reports = [m["report"] for f in families for m in f["members"]]
    series, share_series, labels = _load(release, member_reports)
    b = _Builder(release, series, share_series, labels)
    for key, name, report in config.GLOBAL_BRANDS:
        b.report_facts(key, name, report, brand=key, family=config.BRAND_FAMILY.get(key, key))
    for fam in families:
        for m in fam["members"]:
            b.report_facts(m["key"], m["name"], m["report"], brand=m["key"], family=fam["key"], lite=True)
    for key, name, report in config.GROUP_REPORTS:
        other = "Total Global Radio (UK), all stations" if key == "global_brands" else "Total Global Radio Brands (UK)"
        b.report_facts(key, name, report, status="confirm",
                       note_prefix=f"Confirm definition: group total with a second published definition ({other})")
    b.report_facts("all_radio", "All radio", config.ALL_RADIO_REPORT)
    b.market_facts()
    b.head_to_head()
    b.rival_facts()
    return FactSet(
        release=release, release_label=labels.get(release, str(release)),
        qoq_release=b.qoq, qoq_label=labels.get(b.qoq), yoy_release=b.yoy, yoy_label=labels.get(b.yoy),
        history_quarters=len([r for r in b.releases if r <= release]), facts=b.facts, families=families,
    )

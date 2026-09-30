"""Filter chips: menu options, prepared questions and prepared (instant, no-LLM) queries.

Audience and area queries run on the AdWanted respondent data. Brand families are mapped to
their stations through RAJAR REPORT_STATIONS, so figures are AdWanted custom cuts (2026 Q2).
"""

from . import config, db
from .facts import format_reach

AUDIENCES = {
    "adults": ("Adults 15+", "TRUE"),
    "15_24": ("15-24", "r.age BETWEEN 15 AND 24"),
    "25_34": ("25-34", "r.age BETWEEN 25 AND 34"),
    "35_54": ("35-54", "r.age BETWEEN 35 AND 54"),
    "55_plus": ("55+", "r.age >= 55"),
    "men": ("Men", "r.gender = 'Men'"),
    "women": ("Women", "r.gender = 'Women'"),
    "abc1": ("ABC1", "r.social_segment = 'ABC1'"),
    "c2de": ("C2DE", "r.social_segment = 'C2DE'"),
    "parents": ("Parents (kids 0-14)", "r.has_children_0_14"),
}

AREAS = {
    "uk": ("UK", "TRUE"),
    "london": ("London", "r.ilr_region = 'London'"),
    "north_west": ("North West", "r.ilr_region = 'North West'"),
    "midlands": ("Midlands", "r.ilr_region = 'Midlands'"),
    "yorkshire": ("Yorkshire", "r.ilr_region = 'Yorkshire'"),
    "north_east": ("North East", "r.ilr_region = 'North East'"),
    "scotland": ("Scotland", "r.ilr_region IN ('Central Scotland', 'North Scotland')"),
    "wales": ("Wales", "r.ilr_region = 'Wales'"),
    "south": ("South", "r.ilr_region IN ('South', 'South West', 'West')"),
    "east": ("East of England", "r.ilr_region = 'East of England'"),
}

COMPARE = {
    "both": ("Q1 2026 · Q2 2025", ""),
    "qoq": ("Quarter on quarter", "Focus on changes versus the previous quarter."),
    "yoy": ("Year on year", "Focus on changes versus the same quarter last year."),
}


def menu(factset):
    """Everything the chips need: options and prepared questions."""
    releases = db.query(
        f"""SELECT RELEASE_NUMBER, RELEASE_LABEL FROM {config.RAJAR}.RAJAR_RELEASES
            WHERE NO_OF_REPORTS > 0 AND RELEASE_NUMBER <= %s ORDER BY RELEASE_NUMBER DESC LIMIT 6""",
        (config.LATEST_RELEASE,),
    )
    fams = [{"key": f["key"], "name": f["name"]} for f in factset.families]
    return {
        "releases": [{"value": r["release_number"], "label": " ".join(reversed(r["release_label"].split()))} for r in releases],
        "compare": [{"value": k, "label": v[0]} for k, v in COMPARE.items()],
        "brands": [{"value": "all", "label": "Global portfolio"}] + [{"value": f["key"], "label": f["name"]} for f in fams],
        "audiences": [{"value": k, "label": v[0]} for k, v in AUDIENCES.items()],
        "areas": [{"value": k, "label": v[0]} for k, v in AREAS.items()],
        "questions": {
            "release": [
                f"What are the three biggest stories for Global in {factset.release_label}?",
                f"Which Global brands hit a record high in {factset.release_label}?",
                "Which Global brands lost the most reach year on year, and why might that be?",
            ],
            "compare": [
                "Which Global brands grew reach quarter on quarter?",
                "Which Global brands grew reach year on year?",
                "How has commercial radio's share of listening moved over the last year?",
            ],
            "period": [
                "Why are Global's brands reported on 6-month survey periods?",
                "How do RAJAR's 3, 6 and 12-month survey periods differ?",
                "Which Global stations are reported quarterly?",
            ],
            "brand": [
                "How did {brand} perform versus last quarter and last year?",
                "Which {brand} stations grew fastest?",
                "How does {brand}'s audience split by age and gender?",
                "Who are {brand}'s main competitors and how do they compare?",
            ],
            "audience": [
                "Which Global brands over-index with {audience}?",
                "How do {audience} listen to Global brands: which platforms?",
                "Which Global brand has grown most with {audience}?",
            ],
            "area": [
                "Which Global brands lead in {area}?",
                "How does Global's reach in {area} compare with the BBC?",
                "Which platforms do listeners in {area} use for Global brands?",
            ],
        },
    }


def _family_heads():
    return {k: (n, reports[0]) for k, n, reports in config.FAMILIES}


# Benchmarks shown under the Global brands: market totals, BBC and the biggest Bauer portfolio
BENCHMARKS = {
    "all_global": ("All Global brands", 4433),
    "all_radio": ("All radio", 1690),
    "all_commercial": ("All commercial radio", 1670),
    "all_bbc": ("All BBC radio", 1660),
    "bbc_r2": ("BBC Radio 2", 1901),
    "bbc_r1": ("BBC Radio 1", 1900),
    "hits_portfolio": ("Hits Radio Portfolio (Bauer)", 4850),
}


def audience_query(audience_key="adults", area_key="uk"):
    """Weekly reach of each Global brand family within an audience and area (AdWanted custom cut)."""
    aud_label, aud_sql = AUDIENCES[audience_key]
    area_label, area_sql = AREAS[area_key]
    heads = _family_heads()
    everything = {**heads, **BENCHMARKS}
    reports = ",".join(str(r) for _, r in everything.values())
    where = f"({aud_sql}) AND ({area_sql})"
    rows = db.query(f"""
        WITH fam AS (
            SELECT r.REPORT_NUMBER, f.value::NUMBER AS station_code
            FROM {config.RAJAR}.REPORT_STATIONS r, LATERAL FLATTEN(input => r.STATION_CODES) f
            WHERE r.REPORT_NUMBER IN ({reports})),
        pop AS (
            SELECT SUM(IFF({where}, r.weight_persons, 0)) AS pop_seg, SUM(r.weight_persons) AS pop_all
            FROM {config.ANALYTICS}.DIM_RESPONDENT r WHERE r.is_adult_15_plus),
        hits AS (
            SELECT DISTINCT fam.REPORT_NUMBER, l.respondent_id, r.weight_persons, ({where}) AS in_seg
            FROM fam
            JOIN {config.ANALYTICS}.FACT_LISTENING l ON l.station_code = fam.station_code
            JOIN {config.ANALYTICS}.DIM_RESPONDENT r ON r.respondent_id = l.respondent_id)
        SELECT h.REPORT_NUMBER,
               SUM(IFF(h.in_seg, h.weight_persons, 0)) / 1000 AS reach_seg,
               SUM(h.weight_persons) / 1000 AS reach_all,
               COUNT_IF(h.in_seg) AS n_sample,
               ANY_VALUE(p.pop_seg) / 1000 AS pop_seg, ANY_VALUE(p.pop_all) / 1000 AS pop_all
        FROM hits h CROSS JOIN pop p
        GROUP BY h.REPORT_NUMBER
        ORDER BY reach_seg DESC""")
    by_report = {n: k for k, (_, n) in everything.items()}
    header = ["| {label} | Weekly reach | % of audience | Index vs all adults | Sample |", "|---|---:|---:|---:|---:|"]

    def row(r):
        name = everything[by_report[r["report_number"]]][0]
        seg_pct = 100 * float(r["reach_seg"]) / float(r["pop_seg"]) if r["pop_seg"] else 0
        all_pct = 100 * float(r["reach_all"]) / float(r["pop_all"]) if r["pop_all"] else 0
        index = 100 * seg_pct / all_pct if all_pct else 0
        low = " (low base)" if r["n_sample"] < 100 else ""
        return f"| {name} | {format_reach(r['reach_seg'])} | {seg_pct:.0f}% | {index:.0f} | {r['n_sample']:,}{low} |"

    global_rows = [r for r in rows if by_report[r["report_number"]] in heads]
    bench_rows = [r for r in rows if by_report[r["report_number"]] in BENCHMARKS]
    lines = [header[0].format(label="Global brand"), header[1]] + [row(r) for r in global_rows]
    lines += ["", header[0].format(label="Benchmark"), header[1]] + [row(r) for r in bench_rows]
    scope = aud_label if area_key == "uk" else f"{aud_label} in {area_label}"
    pop = format_reach(rows[0]["pop_seg"]) if rows else "n/a"
    title = f"Global brands among {scope}"
    note = (f"AdWanted custom cut, {config.LATEST_RELEASE // 100} Q{config.LATEST_RELEASE % 100}: weekly reach of each brand's "
            f"stations among {scope} (population {pop}). Index 100 = same reach rate as all adults 15+. "
            "Will not match published RAJAR exactly.")
    return {"title": title, "markdown": f"**{title}**\n\n" + "\n".join(lines) + f"\n\n{note}"}


def brand_scorecard(factset, family_key):
    """Published RAJAR scorecard for a brand family: headline brand, network and spin-offs."""
    facts = factset.by_key()
    fam = next(f for f in factset.families if f["key"] == family_key)
    heads = [(k, n) for k, n, r in config.GLOBAL_BRANDS if config.BRAND_FAMILY.get(k, k) == family_key]
    rows = heads + [(m["key"], m["name"]) for m in fam["members"]]

    def change(key):
        f = facts.get(key)
        if not f:
            return "–"
        sign = "+" if f.direction == "up" else "−" if f.direction == "down" else ""
        return f"{sign}{f.display}"

    lines = [f"| Station | Reach | vs {factset.qoq_label} | vs {factset.yoy_label} | Share | Note |",
             "|---|---:|---:|---:|---:|---|"]
    for key, name in rows:
        if f"{key}_reach" not in facts:
            continue
        peak = facts.get(f"{key}_reach_peak") or facts.get(f"{key}_reach_low")
        lines.append(f"| {name} | {{{{{key}_reach}}}} | {change(key + '_reach_qoq')} | {change(key + '_reach_yoy')} | "
                     f"{{{{{key}_share}}}} | {peak.display if peak else ''} |")
    title = f"{fam['name']} scorecard, RAJAR {factset.release_label}"
    return {"title": title, "markdown": f"**{title}**\n\n" + "\n".join(lines) +
            "\n\nPublished RAJAR figures. Brand totals use 6-month survey periods; spin-offs are quarterly."}


def period_table(factset):
    facts = factset.by_key()
    lines = ["| Report | Survey period | Reach |", "|---|---|---:|"]
    for k, n, _ in config.GLOBAL_BRANDS:
        f = facts.get(f"{k}_reach")
        if f:
            lines.append(f"| {n} | {f.note.split(' survey period')[0]} | {{{{{k}_reach}}}} |")
    return {"title": "Survey periods", "markdown": "**Survey periods behind Global's headline figures**\n\n" + "\n".join(lines)
            + "\n\nRAJAR reports smaller brands on longer fieldwork (6 or 12 months) to get a robust sample. "
              "Compare like with like: a 6-month figure against the previous 6-month figure."}


def compare_table(factset, mode):
    facts = factset.by_key()
    tag = "qoq" if mode == "qoq" else "yoy"
    label = factset.qoq_label if tag == "qoq" else factset.yoy_label
    rows = []
    for k, n, _ in config.GLOBAL_BRANDS:
        f = facts.get(f"{k}_reach_{tag}")
        if f:
            rows.append((f.value, n, k, f))
    rows.sort(reverse=True)
    lines = [f"| Brand | Reach | Change vs {label} |", "|---|---:|---:|"]
    for _, n, k, f in rows:
        sign = "+" if f.direction == "up" else "−" if f.direction == "down" else ""
        lines.append(f"| {n} | {{{{{k}_reach}}}} | {sign}{f.display} |")
    return {"title": f"Reach change vs {label}", "markdown": f"**Global brands: reach change vs {label}**\n\n" + "\n".join(lines)}

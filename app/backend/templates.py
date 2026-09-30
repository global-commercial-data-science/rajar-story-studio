"""Rule-based angles and drafts, used when the LLM is unavailable (and as a sanity baseline)."""

from . import config
from .agents import Angle, AnglesOutput, DraftOutput

NAMES = {k: n for k, n, _ in config.GLOBAL_BRANDS}


def rule_angles(facts) -> AnglesOutput:
    f = facts.by_key()
    angles = []

    def add(id_, headline, keys, why, strength, selected, brand=None):
        keys = [k for k in keys if k in f]
        if keys:
            angles.append(Angle(id=id_, headline=headline, brand=brand, fact_keys=keys, why=why,
                                strength=strength, selected=selected))

    if f.get("heart_vs_bbc_r2") and f["heart_vs_bbc_r2"].direction == "ahead":
        add("heart_top", f"Heart is the UK's biggest radio brand, {f['heart_vs_bbc_r2'].display} ahead of BBC Radio 2",
            ["heart_reach", "heart_vs_bbc_r2", "bbc_r2_reach"], "Global's headline claim every quarter.", 5, True, "heart")
    for key, name, _ in config.GLOBAL_BRANDS:
        peak = f.get(f"{key}_reach_peak")
        if peak and "highest in" in peak.display:
            add(f"{key}_record", f"{name} sets a record {f[f'{key}_reach'].display} weekly listeners",
                [f"{key}_reach", f"{key}_reach_peak", f"{key}_reach_yoy"], f"{name} reach is {peak.display}.",
                5 if key == "lbc" else 4, True, key)
    for key, name, _ in config.GLOBAL_BRANDS:
        yoy = f.get(f"{key}_reach_yoy")
        if yoy and yoy.direction == "up" and yoy.value >= 3 and not any(a.id == f"{key}_record" for a in angles):
            add(f"{key}_growth", f"{name} grows reach {yoy.display} year on year to {f[f'{key}_reach'].display}",
                [f"{key}_reach", f"{key}_reach_yoy", f"{key}_share_yoy_pp"], "Year-on-year growth on the same survey period.",
                3, True, key)
    if f.get("commercial_share") and f.get("bbc_share"):
        qoq = f.get("commercial_share_qoq_pp")
        add("commercial_share", f"Commercial share {f['commercial_share'].display} vs BBC {f['bbc_share'].display}",
            ["commercial_share", "bbc_share", "commercial_share_qoq_pp", "commercial_lead_pp"],
            "Commercial radio's lead over the BBC" + (f" moved {qoq.direction} on the quarter." if qoq else "."), 4, True)
    if f.get("all_radio_reach_peak") and "highest in" in f["all_radio_reach_peak"].display:
        add("all_radio_record", f"Radio reaches a record {f['all_radio_reach'].display} adults a week",
            ["all_radio_reach", "all_radio_reach_peak"], "Market context for the release.", 3, False)
    for brand_key, rival_key in config.HEAD_TO_HEAD:
        h = f.get(f"{brand_key}_vs_{rival_key}")
        if h and h.direction == "ahead" and brand_key != "heart":
            add(f"{brand_key}_vs_{rival_key}", f"{NAMES[brand_key]} {h.display} ahead of {config.RIVALS[rival_key][0]}",
                [f"{brand_key}_reach", f"{brand_key}_vs_{rival_key}"], h.note, 2, False, brand_key)
    if f.get("global_brands_reach"):
        add("group_reach", f"Global's brands reach {f['global_brands_reach'].display} listeners a week",
            ["global_brands_reach", "global_brands_share"], "Group total; confirm which definition comms uses.", 3, True)

    declines = sorted(
        (x for x in facts.facts if x.key.endswith("_reach_yoy") and x.brand in NAMES and x.direction == "down"),
        key=lambda x: x.value,
    )
    also = [f"{NAMES[x.brand]} −{x.display} YoY" for x in declines if x.value <= -1]
    angles.sort(key=lambda a: -a.strength)
    return AnglesOutput(angles=angles, also_moved=also, analyst_insights="Rule-based angles (LLM not used).")


def tokenize(text, keys, facts_by_key):
    """Swap the displayed values of an angle's facts back to {{tokens}} (longest first)."""
    pairs = sorted(((facts_by_key[k].display, k) for k in keys if k in facts_by_key), key=lambda p: -len(p[0]))
    for display, key in pairs:
        text = text.replace(display, "{{" + key + "}}")
    return text


def rule_draft(facts, angles, fmt) -> DraftOutput:
    f = facts.by_key()
    tok = lambda a: tokenize(a["headline"], a["fact_keys"], f)
    label = facts.release_label
    bullets = []
    for a in angles:
        brand = NAMES.get(a["brand"]) if a.get("brand") else None
        keys = a["fact_keys"]
        if brand and f"{a['brand']}_reach" in keys:
            line = f"**{brand}** reaches {{{{{a['brand']}_reach}}}} people a week"
            yoy = f.get(f"{a['brand']}_reach_yoy")
            if f"{a['brand']}_reach_yoy" in keys and yoy:
                line += f", {yoy.direction} {{{{{a['brand']}_reach_yoy}}}} on last year"
            if f"{a['brand']}_reach_peak" in keys:
                line += f", {{{{{a['brand']}_reach_peak}}}}"
            if a["id"] == "heart_top":
                line += ", {{heart_vs_bbc_r2}} more than BBC Radio 2"
            for k in keys:
                if "_vs_" in k and k != "heart_vs_bbc_r2":
                    rival = config.RIVALS[k.split("_vs_", 1)[1]][0]
                    line += f", {{{{{k}}}}} {f[k].direction} of {rival}"
            bullets.append(line + ".")
        elif a["id"] == "commercial_share":
            bullets.append("**Commercial radio** takes {{commercial_share}} of listening, against {{bbc_share}} for the BBC.")
        elif a["id"] == "group_reach":
            continue
        else:
            bullets.append(tok(a) + ".")
    body = "\n".join(f"- {b}" if not b.startswith("- ") else b for b in bullets)
    intro = ("Global's radio brands reached {{global_brands_reach}} listeners every week in " + label +
             ", with a {{global_brands_share}} share of all radio listening, according to RAJAR. Across the UK, radio reached "
             "{{all_radio_reach}} adults each week.")
    if fmt == "press_release":
        md = (f"{intro}\n\n{body}\n\n[Quote: Group CEO, on group performance]\n\n[Quote: Chief Content Officer, on content wins]\n\n"
              f"Figures sourced from RAJAR / Ipsos / RSMB, {label}, Adults 15+.")
        title = tok(angles[0]) if angles else f"Global's {label} RAJAR results"
        return DraftOutput(title=title, subtitle_lines=[tok(a) for a in angles[:3]], markdown=md)
    if fmt == "exec_email":
        return DraftOutput(title=f"RAJAR {label}: headlines for Global", markdown=f"Summary of today's RAJAR release.\n\n**Wins**\n\n{body}\n\n[Insight team]")
    if fmt == "internal_memo":
        return DraftOutput(title=f"Our {label} RAJAR results", markdown=f"Thank you, everyone. {intro}\n\n{body}")
    if fmt == "social_cards":
        cards = "\n\n".join(f"### {tok(a)}\n[Caption to write]\n#RAJAR #GlobalRadio" for a in angles[:5])
        return DraftOutput(title="Social stat cards", markdown=cards)
    return DraftOutput(title="Next quarter: insight plan",
                       markdown=f"## What to watch\n\n{body}\n\n## Data gaps\n\n- Confirm which group total definition comms uses.")

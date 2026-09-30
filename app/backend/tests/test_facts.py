"""Fact engine checks against published RAJAR 2026 Q2 figures (needs the Snowflake connection)."""

import pytest

from app.backend.facts import build_facts, format_change, format_reach

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def facts():
    return build_facts(202602).by_key()


def test_format_reach():
    assert format_reach(12826) == "12.8 million"
    assert format_reach(459) == "459,000"
    assert format_reach(1198) == "1.2 million"


def test_format_change():
    assert format_change(3688, 3377) == (pytest.approx(9.2, abs=0.05), "9.2%", "up")
    assert format_change(95, 100)[2] == "down"


def test_brand_reach_matches_published(facts):
    assert facts["heart_reach"].value == 12826 and facts["heart_reach"].display == "12.8 million"
    assert facts["lbc_reach"].value == 3688 and facts["lbc_reach"].display == "3.7 million"
    assert facts["classic_fm_reach"].value == 4514
    assert facts["lbc_news_reach"].display == "1.2 million"


def test_year_on_year_uses_same_period(facts):
    yoy = facts["lbc_reach_yoy"]
    assert yoy.display == "9.2%" and yoy.direction == "up"
    assert "Q2 2025" in yoy.note


def test_record_detection(facts):
    assert facts["lbc_reach_peak"].display == "the highest in 20 quarters"


def test_market_shares(facts):
    assert facts["commercial_share"].display == "55.1%"
    assert facts["bbc_share"].display == "42.6%"
    assert facts["all_radio_reach"].display == "51.1 million"


def test_group_totals_need_confirmation(facts):
    assert facts["global_brands_reach"].display == "29.0 million"
    assert facts["global_brands_share"].display == "27.5%"
    assert facts["global_brands_reach"].status == "confirm"
    assert facts["global_total_reach"].value == 27587


def test_head_to_head(facts):
    h2h = facts["heart_vs_bbc_r2"]
    assert h2h.value == 459 and h2h.display == "459,000" and h2h.direction == "ahead"

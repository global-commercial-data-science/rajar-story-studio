from app.backend.facts import Fact
from app.backend.tokens import find_unverified_numbers, render, token_keys


def fact(key, display, value=0.0):
    return Fact(key=key, label=key, value=value, display=display, unit="", brand=None,
                status="verified", note="", source="")


FACTS = {"heart_reach": fact("heart_reach", "12.8 million", 12826), "lbc_reach_yoy": fact("lbc_reach_yoy", "9.2%", 9.2)}


def test_render_replaces_known_tokens():
    assert render("Heart reaches {{heart_reach}} people.", FACTS) == "Heart reaches 12.8 million people."


def test_render_tolerates_spaces_inside_braces():
    assert render("up {{ lbc_reach_yoy }}", FACTS) == "up 9.2%"


def test_render_marks_unknown_tokens():
    assert render("{{made_up}}", FACTS) == "[[unknown:made_up]]"


def test_token_keys_lists_keys_in_order():
    assert token_keys("{{a}} and {{ b }} then {{a}}") == ["a", "b"]


def test_plain_numbers_outside_tokens_are_flagged():
    assert find_unverified_numbers("Heart reaches 12.8 million, up 3%.") == ["12.8 million", "3%"]


def test_tokens_dates_and_list_numbers_are_allowed():
    text = "1. In Q2 2026 Heart reaches {{heart_reach}}.\n2. Adults 15+ across the UK in 2026."
    assert find_unverified_numbers(text) == []

"""Fact tokens in drafts: {{fact_key}} placeholders that render to locked, verified values."""

import re

TOKEN = re.compile(r"\{\{\s*([a-z0-9_]+)\s*\}\}")

# A number with optional decimals/commas and an optional unit word or symbol after it
_NUMBER = re.compile(
    r"(?<![\w.])\d[\d,]*(?:\.\d+)?(?:\s?(?:%|pp|points?|million|m|billion|bn|k|thousand|hours))?(?![\w])",
    re.I,
)
_ALLOWED = [
    re.compile(r"^(19|20)\d{2}$"),          # years
    re.compile(r"^[1-9]\.?$"),              # small list / step numbers
]
_ALLOWED_CONTEXT = re.compile(r"(Q[1-4]\s(19|20)\d{2}|(19|20)\d{2}\sQ[1-4]|15\+|0-14|24/7|\d{1,2}(am|pm)|Q[1-4])", re.I)


def token_keys(markdown):
    """Token keys in order of first appearance."""
    seen = []
    for key in TOKEN.findall(markdown):
        if key not in seen:
            seen.append(key)
    return seen


def render(markdown, facts):
    """Replace {{key}} with the fact's display value; unknown keys stay visible as [[unknown:key]]."""
    def sub(match):
        fact = facts.get(match.group(1))
        return fact.display if fact else f"[[unknown:{match.group(1)}]]"
    return TOKEN.sub(sub, markdown)


def find_unverified_numbers(markdown):
    """Numbers written as plain text instead of tokens (dates, 'Adults 15+' and list numbers are allowed)."""
    text = TOKEN.sub(" ", markdown)
    text = _ALLOWED_CONTEXT.sub(" ", text)
    text = re.sub(r"^\s*\d+[.)]\s", " ", text, flags=re.M)  # numbered list markers
    found = []
    for match in _NUMBER.finditer(text):
        value = match.group(0).strip()
        if not any(p.match(value) for p in _ALLOWED):
            found.append(value)
    return found

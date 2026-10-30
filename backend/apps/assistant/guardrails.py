"""Checks that run outside the model, so they hold for any provider."""

import re
from decimal import Decimal, InvalidOperation

from apps.crm.models import HandoffTask

R = HandoffTask.Reason

# Pre-filter: questions the assistant must not answer itself. Each rule is
# (reason, label, pattern). Fair-housing rules come first so a steering question
# phrased as a complaint is still classified as fair-housing sensitive.
SCOPE_RULES: list[tuple[str, str, re.Pattern]] = [
    (
        R.FAIR_HOUSING,
        "who lives here",
        re.compile(
            r"\b(what|which) (kind|kinds|type|types|sort) of (people|neighbou?rs|tenants|residents|"
            r"families|crowd)\b|\bwho (lives|live|is living) (here|there|in the building)\b"
            r"|\b(demographic|demographics|diverse|diversity)\b"
        ),
    ),
    (
        R.FAIR_HOUSING,
        "protected class",
        re.compile(
            r"\b(race|racial|ethnic|ethnicity|nationality|national origin|religion|religious|"
            r"church|churches|mosque|synagogue|temple|christians?|muslims?|jewish|jews|hindus?|"
            r"hispanics?|latinos?|latinas?|asians?|immigrants?|foreigners?|"
            r"african[- ]americans?|caucasians?)\b"
        ),
    ),
    (
        R.FAIR_HOUSING,
        "familial status / age / sex",
        re.compile(
            r"\b(good|great|right|best|suitable|ideal|safe|appropriate|ok|okay)\b[^.?!]{0,30}\b"
            r"(for|with) (an? |my )?(older |elderly |young |single |senior |retired )*"
            r"(families|family|kids|children|seniors|elderly|retirees|people|folks|adults|"
            r"professionals|singles|woman|women|man|men|mom|mother|dad|father|couple)\b"
            r"|\b(adults?[- ]only|no kids|no children|child[- ]free|without (kids|children)|"
            r"lots of kids|many kids|mostly (families|students|seniors|young|older|retirees))\b"
            r"|\b(gay|lesbian|lgbtq?\+?|transgender|straight) (friendly|neighbou?rs|tenants|"
            r"residents|community)\b"
        ),
    ),
    (
        R.FAIR_HOUSING,
        "neighborhood safety / schools",
        re.compile(
            r"\b(safe|unsafe|dangerous|sketchy|crime|criminal|bad|rough|good|nice) "
            r"(neighbou?rhood|area|part of town|block)\b|\bcrime\b|\bis it safe\b"
            r"|\b(neighbou?rhood|area)\b[^.?!]{0,20}\b(safe|unsafe|dangerous|sketchy|rough)\b"
            r"|\b(schools?|school district|school ratings?)\b"
        ),
    ),
    (
        R.FAIR_HOUSING,
        "accommodation request",
        re.compile(
            r"\b(wheelchair|disabled|disability|handicap\w*|reasonable accommodation|"
            r"accessible unit|mobility (issues|impairment))\b"
        ),
    ),
    (
        R.REQUESTED_HUMAN,
        "asked for a person",
        re.compile(
            r"\b(speak|talk|chat) (to|with) (a |an |the |someone|somebody|real )*(human|person|"
            r"agent|manager|someone|somebody|leasing (agent|office|team))\b|\breal person\b"
            r"|\b(call|phone) me\b|\bhuman please\b"
        ),
    ),
    (
        R.OUT_OF_SCOPE,
        "legal",
        re.compile(
            r"\b(lawyer|attorney|lawsuit|sue|suing|legal(ly)?|evict\w*|court|small claims|"
            r"tenant rights|landlord[- ]tenant law|withh?old\w* (my )?"
            r"(deposit|rent)|discriminat\w*)\b"
        ),
    ),
    (
        R.OUT_OF_SCOPE,
        "complaint / maintenance",
        re.compile(
            r"\b(complain\w*|leak\w*|mold|mould|broken|repair\w*|maintenance (request|issue)|"
            r"not working|stopped working|noisy|roach\w*|bed ?bugs?|rodents?|mice|rats?|"
            r"infest\w*|rude|unacceptable|terrible|worst|disgusting|refund)\b"
        ),
    ),
    (
        R.OUT_OF_SCOPE,
        "negotiation",
        re.compile(
            r"\b(lower|reduce|drop|knock|bring down|negotiat\w*|waive\w*|match|beat|haggle)\b"
            r"[^.?!]{0,40}\b(rent|price|fee|fees|deposit|offer|deal|quote|it)\b"
            r"|\b(give|offer|cut) me (a|any|some) (discount|deal|break)\b|\bwiggle room\b"
            r"|\bbest (price|deal|rate) you can\b"
        ),
    ),
    (
        R.OUT_OF_SCOPE,
        "other residents' information",
        re.compile(
            r"\b(name|names|phone|number|email|contact)\b[^.?!]{0,25}\b(of )?(the )?(current )?"
            r"(tenant|tenants|resident|residents|neighbou?r|neighbou?rs|person|people) "
            r"(in|at|living|who)\b"
            r"|\bwho (lives|live|lived|rents|rented|is living|was living) in "
            r"(unit|apartment|apt|#)"
        ),
    ),
    (
        R.OUT_OF_SCOPE,
        "prompt injection",
        re.compile(
            r"\bignore (all |any |your |the |previous |prior |above )*(instructions|rules|"
            r"prompt|guidelines)\b|\b(system prompt|developer mode|jailbreak|you are now|"
            r"act as (an? )?(admin|manager|landlord|owner)|pretend (you|to be))\b"
            r"|\bnew instructions?\b"
        ),
    ),
]


def classify_scope(question: str) -> tuple[str, str] | None:
    text = question.lower()
    for reason, label, pattern in SCOPE_RULES:
        if pattern.search(text):
            return reason, label
    return None


# Post-checks on the model's answer.

MONEY = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{2}))?")
UNIT_REF = re.compile(r"\b(?:unit|apt\.?|apartment|#)\s*#?\s*([A-Za-z]?\d{2,4}[A-Za-z]?)\b", re.I)
STEERING = re.compile(
    r"\b(great|perfect|ideal|good) (for|with) (families|kids|children|seniors|singles|young)"
    r"|\b(quiet|safe) (neighbou?rhood|area)\b|\bmostly (families|young|older|students)\b",
    re.I,
)


def money_amounts(text: str) -> set[Decimal]:
    amounts = set()
    for whole, cents in MONEY.findall(text):
        try:
            amounts.add(Decimal(whole.replace(",", "") + (f".{cents}" if cents else "")))
        except InvalidOperation:
            continue
    return amounts


def ungrounded_prices(answer: str, sources: list[str]) -> set[Decimal]:
    """Dollar amounts in the answer that no source supports.

    Simple arithmetic on sourced amounts is allowed (2-13x for per-person or per-month
    totals, and sums of two amounts such as rent plus a fee); anything else is ungrounded.
    """
    base = set().union(*(money_amounts(s) for s in sources)) if sources else set()
    grounded = set(base)
    grounded |= {a * k for a in base for k in range(2, 14)}
    grounded |= {a + b for a in base for b in base}
    return money_amounts(answer) - grounded


def ungrounded_units(answer: str, unit_numbers: set[str]) -> set[str]:
    mentioned = {m.upper() for m in UNIT_REF.findall(answer)}
    return mentioned - {u.upper() for u in unit_numbers}


def steers(answer: str) -> bool:
    return bool(STEERING.search(answer))

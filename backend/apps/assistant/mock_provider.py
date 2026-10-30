"""Deterministic rule-based stand-in for the LLM.

It reads the same transcript the real model gets (context block, question, tool
results) and returns the same kinds of turns (tool calls, then text), so the tool
loop, guardrails and eval scoring are exercised in CI without an API key. Its
quality is that of a keyword router; it is a smoke-test baseline, not a model.
"""

import json
import re
from datetime import date, timedelta

from .embeddings import tokens
from .providers import LLMTurn, ToolCall

TOPIC_PATTERNS = [
    ("PETS", r"\b(pets?|dogs?|cats?|puppy|kitten|animals?|breed|terrier|lab|retriever)\b"),
    ("PARKING", r"\b(park|parking|garage|cars?|vehicles?|ev|charg\w*|spots?|motorcycle)\b"),
    (
        "APPLICATION",
        r"\b(apply|application process|credit|income|background|guarantors?|"
        r"qualify|requirements?|screening|cosigner|co-signer)\b",
    ),
    (
        "LEASE_TERMS",
        r"\b(lease (term|terms|length|options)|month lease|short[- ]term|"
        r"\d+[- ]month|month[- ]to[- ]month|how long)\b",
    ),
    (
        "FEES",
        r"\b(fees?|admin|charges?|utilities|utility|trash|internet|wifi|water|electric\w*|"
        r"deposit|move[- ]in costs?|upfront)\b",
    ),
    (
        "AMENITIES",
        r"\b(pool|gym|fitness|amenit\w*|laundry|washer|dryer|rooftop|package\w*|"
        r"bikes?|storage|lounge)\b",
    ),
    ("GENERAL", r"\b(office hours|hours|open on|located|address)\b"),
]
BOOKING = re.compile(
    r"\b(tour|tours|visit|viewing|showing|come (by|see|look)|see (it|the "
    r"(unit|apartment|place))|book|schedule)\b"
)
UNITS = re.compile(
    r"\b(rent|rents|price|prices|pricing|cost|costs|how much|available|"
    r"availability|vacan\w*|openings?|move[- ]?in date|studios?|bed(room)?s?|"
    r"\dbr|\d ?bd|units?|apartments?|specials?)\b|\$"
)
WORD_NUM = {"studio": 0, "one": 1, "two": 2, "three": 3, "1": 1, "2": 2, "3": 3, "0": 0}
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def parse_context(text: str) -> dict:
    ctx = {}
    for key in ("today", "property_id", "prospect_id"):
        m = re.search(rf"^{key}: (\S+)", text, re.M)
        ctx[key] = m.group(1) if m else None
    q = re.search(r"<question>\s*(.*?)\s*</question>", text, re.S)
    ctx["question"] = q.group(1) if q else text
    ctx["excerpts"] = re.findall(r"^- \[(\w+)\] (.+)$", text, re.M)
    return ctx


def parse_beds(q: str) -> int | None:
    if "studio" in q:
        return 0
    m = re.search(r"\b(one|two|three|\d)[- ]?(bed(room)?s?|br|bd)\b", q)
    return WORD_NUM.get(m.group(1)) if m else None


def parse_max_rent(q: str) -> float | None:
    m = re.search(
        r"\b(under|below|less than|max(imum)?|budget( is| of)?|up to|no more than)"
        r"\s*\$?\s?(\d[\d,]*)",
        q,
    )
    return float(m.group(4).replace(",", "")) if m else None


def parse_date(q: str, today: date) -> date | None:
    if "tomorrow" in q:
        return today + timedelta(days=1)
    if re.search(r"\btoday\b", q):
        return today
    m = re.search(r"\b(" + "|".join(MONTHS) + r")[a-z]*\.?\s+(\d{1,2})(st|nd|rd|th)?\b", q)
    if m:
        month = MONTHS.index(m.group(1)) + 1
        year = today.year + (1 if month < today.month else 0)
        return date(year, month, int(m.group(2)))
    m = re.search(r"\b(\d{1,2})/(\d{1,2})\b", q)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        return date(today.year + (1 if month < today.month else 0), month, day)
    for i, name in enumerate(WEEKDAYS):
        if re.search(rf"\b{name}\b", q):
            ahead = (i - today.weekday()) % 7
            if "next " + name in q and ahead == 0:
                ahead = 7
            return today + timedelta(days=ahead)
    return None


def parse_move_by(q: str, today: date) -> date | None:
    if re.search(r"\b(right away|asap|immediately|this week)\b", q):
        return today + timedelta(days=7)
    if "next month" in q:
        nxt = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
        return nxt
    m = re.search(
        r"\b(by|in|for|on|before|starting)\s+(the )?(" + "|".join(MONTHS) + r")[a-z]*"
        r"(\s+(\d{1,2}))?",
        q,
    )
    if m:
        month = MONTHS.index(m.group(3)) + 1
        year = today.year + (1 if month < today.month else 0)
        return date(year, month, int(m.group(5)) if m.group(5) else 28)
    return None


def parse_time(q: str) -> str | None:
    if re.search(r"\bnoon\b", q):
        return "12:00"
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)", q)
    if not m:
        return None
    hour, minute = int(m.group(1)) % 12, int(m.group(2) or 0)
    if m.group(3).startswith("p"):
        hour += 12
    return f"{hour:02d}:{minute:02d}"


def unit_number(q: str) -> str | None:
    m = re.search(r"\b(?:unit|apt|apartment|#)\s*#?\s*(\d{2,4}[a-z]?)\b", q)
    return m.group(1) if m else None


def best_sentences(text: str, question: str, n: int = 2) -> str:
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    qtok = set(tokens(question))
    ranked = sorted(sentences, key=lambda s: -len(qtok & set(tokens(s))))
    keep = [s for s in sentences if s in ranked[:n]]
    return " ".join(keep)


class MockProvider:
    name = "mock"

    def run(self, system: str, messages: list[dict], tools: list[dict]) -> LLMTurn:
        first = messages[0]["content"]
        ctx = parse_context(first if isinstance(first, str) else first[0]["text"])
        q = ctx["question"].lower()
        today = date.fromisoformat(ctx["today"])
        results = self._tool_results(messages)
        tool_names = {t["name"] for t in tools}
        step = len([m for m in messages if m["role"] == "assistant"])

        def call(name, args):
            return self._turn_call(f"mock_{step}_{name}", name, args)

        topics = [t for t, pat in TOPIC_PATTERNS if re.search(pat, q)]
        wants_booking = bool(BOOKING.search(q))
        wants_units = bool(UNITS.search(q)) or unit_number(q) is not None

        if wants_booking:
            return self._booking(q, ctx, today, results, tool_names, call)

        if wants_units and "search_units" not in results:
            return call(
                "search_units",
                {
                    "property_id": None,
                    "beds": parse_beds(q),
                    "min_beds": None,
                    "max_rent": parse_max_rent(q),
                    "available_by": (d.isoformat() if (d := parse_move_by(q, today)) else None),
                },
            )
        topic = next((t for t in topics if t != "FEES" or "pet" not in q), None)
        if topic and "get_policy" not in results:
            return call("get_policy", {"topic": topic})

        parts = []
        if "search_units" in results:
            parts.append(self._describe_units(results["search_units"], q))
        if "get_policy" in results and "error" not in results["get_policy"]:
            parts.append(best_sentences(results["get_policy"]["text"], q))
        if not parts:
            excerpt = self._matching_excerpt(ctx["excerpts"], q)
            if excerpt:
                parts.append(best_sentences(excerpt, q))
        if not parts:
            return call(
                "handoff_to_human",
                {"reason": "unsure", "summary": "No source covers this question."},
            )
        return self._turn_text(" ".join(p for p in parts if p))

    # --- booking flow ---

    def _booking(self, q, ctx, today, results, tool_names, call):
        if "book_tour" in results:
            r = results["book_tour"]
            if r.get("booked"):
                return self._turn_text(
                    f"You're booked! Your tour of unit {r['unit_number']} at {r['property']} is "
                    f"{r['start_local']}. We'll send a reminder the day before."
                )
            return self._turn_text("That time was just taken. Could you pick another time?")
        if "search_units" not in results:
            return call(
                "search_units",
                {
                    "property_id": None,
                    "beds": parse_beds(q),
                    "min_beds": None,
                    "max_rent": None,
                    "available_by": None,
                },
            )
        units = results["search_units"].get("units", [])
        wanted = unit_number(q)
        unit = (
            next((u for u in units if u["unit_number"].lower() == wanted), None)
            if wanted
            else (units[0] if units else None)
        )
        if unit is None:
            if wanted:
                return self._turn_text(
                    f"Unit {wanted} isn't open for tours right now. "
                    + self._describe_units(results["search_units"], q)
                )
            return self._turn_text("I don't see a matching unit available to tour right now.")
        day = parse_date(q, today)
        if day is None:
            return self._turn_text(
                f"Happy to set up a tour of unit {unit['unit_number']}! What day and time work "
                "for you?"
            )
        if "check_tour_slots" not in results:
            return call("check_tour_slots", {"unit_id": unit["unit_id"], "date": day.isoformat()})
        slots = results["check_tour_slots"].get("slots", [])
        when = parse_time(q)
        if not slots:
            return self._turn_text(
                f"There are no open tour times for unit {unit['unit_number']} on "
                f"{day:%A, %B %-d}. Would another day work?"
            )
        if when in slots and "book_tour" in tool_names and ctx["prospect_id"] not in (None, "None"):
            return call(
                "book_tour",
                {
                    "prospect_id": int(ctx["prospect_id"]),
                    "unit_id": unit["unit_id"],
                    "slot": f"{day.isoformat()}T{when}",
                },
            )
        listed = ", ".join(self._fmt_time(s) for s in slots[:4])
        lead = (
            f"{self._fmt_time(when)} isn't open on {day:%A}."
            if when and when not in slots
            else f"Here are open times for unit {unit['unit_number']} on {day:%A, %B %-d}:"
        )
        return self._turn_text(f"{lead} Available: {listed}. Which works best?")

    # --- helpers ---

    @staticmethod
    def _fmt_time(hhmm: str) -> str:
        h, m = map(int, hhmm.split(":"))
        return f"{(h - 1) % 12 + 1}:{m:02d} {'AM' if h < 12 else 'PM'}"

    @staticmethod
    def _describe_units(result: dict, q: str) -> str:
        units = result.get("units", [])
        wanted = unit_number(q)
        if wanted:
            match = [u for u in units if u["unit_number"].lower() == wanted]
            if not match:
                return f"Unit {wanted} isn't currently available."
            units = match
        if not units:
            return "I don't see any units matching that right now."
        lines = [
            f"Unit {u['unit_number']} ({'studio' if u['beds'] == 0 else str(u['beds']) + ' bed'}"
            f"/{u['baths']} bath) is {u['rent']}, available {u['available_from']}"
            for u in units[:3]
        ]
        return "; ".join(lines) + "."

    @staticmethod
    def _matching_excerpt(excerpts, q):
        qtok = set(tokens(q))
        for _topic, text in excerpts:
            if len(qtok & set(tokens(text))) >= 2:
                return text
        return None

    @staticmethod
    def _tool_results(messages: list[dict]) -> dict[str, dict]:
        names = {}
        out = {}
        for m in messages:
            for block in m["content"] if isinstance(m["content"], list) else []:
                b = block if isinstance(block, dict) else block.model_dump()
                if b.get("type") == "tool_use":
                    names[b["id"]] = b["name"]
                elif b.get("type") == "tool_result":
                    out[names[b["tool_use_id"]]] = json.loads(b["content"])
        return out

    @staticmethod
    def _turn_call(call_id: str, name: str, args: dict) -> LLMTurn:
        block = {"type": "tool_use", "id": call_id, "name": name, "input": args}
        return LLMTurn(
            text="",
            tool_calls=[ToolCall(call_id, name, args)],
            content=[block],
            stop_reason="tool_use",
            model="mock",
        )

    @staticmethod
    def _turn_text(text: str) -> LLMTurn:
        return LLMTurn(
            text=text,
            tool_calls=[],
            content=[{"type": "text", "text": text}],
            stop_reason="end_turn",
            model="mock",
        )

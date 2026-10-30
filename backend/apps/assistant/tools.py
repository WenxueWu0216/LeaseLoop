"""Assistant tools. All reads are scoped to the conversation's org; live prices and
availability come from these tools, never from embedded text."""

import json
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Q

from apps.crm.models import Conversation, Prospect, Tour
from apps.properties.models import Property, PropertyPolicy, Unit

TOUR_MINUTES = 30
OPEN_HOUR, CLOSE_HOUR = 9, 17  # tours start 9:00 through 16:30 local
MIN_LEAD = timedelta(hours=1)
CLOSED_WEEKDAYS = {6}  # Sunday


def _nullable(t: str) -> dict:
    return {"type": [t, "null"]}


TOOL_DEFS = [
    {
        "name": "search_units",
        "description": (
            "Live unit inventory with current rent and move-in dates. Use for any question "
            "about price, availability or unit options. Pass null for filters you don't need."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "property_id": _nullable("integer"),
                "beds": {**_nullable("integer"), "description": "Exact bedrooms; 0 = studio"},
                "min_beds": _nullable("integer"),
                "max_rent": _nullable("number"),
                "available_by": {**_nullable("string"), "description": "YYYY-MM-DD"},
            },
            "required": ["property_id", "beds", "min_beds", "max_rent", "available_by"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_policy",
        "description": "Full text of a property policy when the excerpts provided are not enough.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "enum": [t.value for t in PropertyPolicy.Topic]},
            },
            "required": ["topic"],
            "additionalProperties": False,
        },
    },
    {
        "name": "check_tour_slots",
        "description": "Open 30-minute tour start times for a unit on a date, in local time.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "unit_id": {"type": "integer"},
                "date": {"type": "string", "description": "YYYY-MM-DD"},
            },
            "required": ["unit_id", "date"],
            "additionalProperties": False,
        },
    },
    {
        "name": "book_tour",
        "description": (
            "Book a tour for the renter in this conversation. The slot must be one returned "
            "by check_tour_slots; it is re-validated before booking."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "prospect_id": {"type": "integer"},
                "unit_id": {"type": "integer"},
                "slot": {"type": "string", "description": "Local start, YYYY-MM-DDTHH:MM"},
            },
            "required": ["prospect_id", "unit_id", "slot"],
            "additionalProperties": False,
        },
    },
    {
        "name": "handoff_to_human",
        "description": (
            "Pass the conversation to a leasing agent instead of answering: when the renter "
            "asks for a person, complains, asks legal questions, negotiates, requests an "
            "accommodation, asks fair-housing-sensitive questions, or the sources don't "
            "contain the answer."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "enum": ["needs_human", "out_of_scope", "fair_housing", "unsure"],
                },
                "summary": {"type": "string"},
            },
            "required": ["reason", "summary"],
            "additionalProperties": False,
        },
    },
]


class ToolError(Exception):
    pass


@dataclass
class AssistantContext:
    prop: Property
    now: datetime
    mode: str = "chat"  # chat: may book; draft: agent-facing suggestion, no side effects
    prospect: Prospect | None = None
    conversation: Conversation | None = None

    @property
    def organization_id(self) -> int:
        return self.prop.organization_id

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.prop.timezone)


@dataclass
class ToolCallRecord:
    name: str
    input: dict
    ok: bool
    output: str


@dataclass
class ToolExecutor:
    ctx: AssistantContext
    calls: list[ToolCallRecord] = field(default_factory=list)
    booked_tour_id: int | None = None

    def definitions(self) -> list[dict]:
        if self.ctx.mode == "chat":
            return TOOL_DEFS
        return [t for t in TOOL_DEFS if t["name"] != "book_tour"]

    def run(self, name: str, args: dict) -> tuple[str, bool]:
        handler = getattr(self, f"_{name}", None)
        if handler is None or (name == "book_tour" and self.ctx.mode != "chat"):
            output, ok = json.dumps({"error": f"unknown tool {name}"}), False
        else:
            try:
                output, ok = json.dumps(handler(**args), default=str), True
            except ToolError as exc:
                output, ok = json.dumps({"error": str(exc)}), False
            except (TypeError, ValueError) as exc:
                output, ok = json.dumps({"error": f"bad arguments: {exc}"}), False
        self.calls.append(ToolCallRecord(name=name, input=args, ok=ok, output=output))
        return output, ok

    # --- helpers ---

    def _property(self, property_id: int | None) -> Property:
        if property_id in (None, self.ctx.prop.pk):
            return self.ctx.prop
        prop = Property.objects.filter(
            pk=property_id, organization_id=self.ctx.organization_id
        ).first()
        if prop is None:
            raise ToolError("property not found")
        return prop

    def _unit(self, unit_id: int) -> Unit:
        unit = (
            Unit.objects.select_related("property")
            .filter(pk=unit_id, organization_id=self.ctx.organization_id)
            .first()
        )
        if unit is None:
            raise ToolError("unit not found")
        return unit

    @staticmethod
    def _parse_date(value: str) -> date:
        try:
            return date.fromisoformat(value)
        except ValueError:
            raise ToolError("date must be YYYY-MM-DD") from None

    def _open_slots(self, unit: Unit, day: date) -> list[datetime]:
        tz = ZoneInfo(unit.property.timezone)
        if day.weekday() in CLOSED_WEEKDAYS or unit.status == Unit.Status.OFFLINE:
            return []
        first = datetime.combine(day, time(OPEN_HOUR), tzinfo=tz)
        candidates = [
            first + timedelta(minutes=TOUR_MINUTES * i)
            for i in range((CLOSE_HOUR - OPEN_HOUR) * 60 // TOUR_MINUTES)
        ]
        taken = set(
            Tour.objects.filter(
                unit=unit,
                status=Tour.Status.SCHEDULED,
                start__lt=candidates[-1] + timedelta(minutes=TOUR_MINUTES),
                end__gt=candidates[0],
            ).values_list("start", flat=True)
        )
        earliest = self.ctx.now + MIN_LEAD
        return [c for c in candidates if c >= earliest and c not in taken]

    # --- tools ---

    def _search_units(self, property_id, beds, min_beds, max_rent, available_by):
        prop = self._property(property_id)
        qs = Unit.objects.filter(
            property=prop, status__in=[Unit.Status.AVAILABLE, Unit.Status.NOTICE]
        )
        if beds is not None:
            qs = qs.filter(beds=beds)
        if min_beds is not None:
            qs = qs.filter(beds__gte=min_beds)
        if max_rent is not None:
            qs = qs.filter(rent__lte=max_rent)
        if available_by:
            qs = qs.filter(
                Q(available_from__lte=self._parse_date(available_by))
                | Q(available_from__isnull=True)
            )
        units = [
            {
                "unit_id": u.pk,
                "unit_number": u.number,
                "beds": u.beds,
                "baths": str(u.baths),
                "sqft": u.sqft,
                "rent": f"${u.rent:,.0f}/month",
                "available_from": (u.available_from or self.ctx.now.date()).isoformat(),
            }
            for u in qs.order_by("rent", "number")[:6]
        ]
        return {
            "property": prop.name,
            "units": units,
            "count": len(units),
            "as_of": self.ctx.now.date().isoformat(),
        }

    def _get_policy(self, topic):
        policies = PropertyPolicy.objects.filter(
            organization_id=self.ctx.organization_id, topic=topic
        ).filter(Q(property=self.ctx.prop) | Q(property__isnull=True))
        # Property-specific policy overrides the org-wide one for the same topic.
        chosen = sorted(policies, key=lambda p: p.property_id is None)[:1]
        if not chosen:
            raise ToolError(f"no {topic} policy on file")
        return {"topic": topic, "title": chosen[0].title, "text": chosen[0].body}

    def _check_tour_slots(self, unit_id, date):
        unit = self._unit(unit_id)
        day = self._parse_date(date)
        slots = self._open_slots(unit, day)
        return {
            "unit_id": unit.pk,
            "unit_number": unit.number,
            "date": day.isoformat(),
            "timezone": unit.property.timezone,
            "slots": [s.strftime("%H:%M") for s in slots],
        }

    def _book_tour(self, prospect_id, unit_id, slot):
        prospect = self.ctx.prospect
        if prospect is None or prospect_id != prospect.pk:
            raise ToolError("prospect_id does not match this conversation")
        unit = self._unit(unit_id)
        tz = ZoneInfo(unit.property.timezone)
        try:
            start = datetime.fromisoformat(slot).replace(tzinfo=tz)
        except ValueError:
            raise ToolError("slot must be YYYY-MM-DDTHH:MM") from None
        with transaction.atomic():
            # Lock the unit so two conversations can't book the same slot concurrently.
            Unit.objects.select_for_update().get(pk=unit.pk)
            if start not in self._open_slots(unit, start.date()):
                raise ToolError("slot is not available; call check_tour_slots for open times")
            tour = Tour.objects.create(
                organization_id=self.ctx.organization_id,
                prospect=prospect,
                unit=unit,
                agent=prospect.assigned_agent,
                start=start,
                end=start + timedelta(minutes=TOUR_MINUTES),
                booked_by=Tour.BookedBy.ASSISTANT,
            )
            if prospect.status in (Prospect.Status.NEW, Prospect.Status.CONTACTED):
                prospect.status = Prospect.Status.TOUR_SCHEDULED
                prospect.save(update_fields=["status", "updated_at"])
        self.booked_tour_id = tour.pk
        return {
            "booked": True,
            "tour_id": tour.pk,
            "unit_number": unit.number,
            "start_local": start.strftime("%A, %B %-d at %-I:%M %p"),
            "property": unit.property.name,
        }

    def _handoff_to_human(self, reason, summary):
        return {"handed_off": True}

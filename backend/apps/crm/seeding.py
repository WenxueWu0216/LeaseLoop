"""Deterministic synthetic data for benchmarks and load tests.

Everything here is fake: names come from Faker, emails use example.com and
phone numbers use the fictional 555 exchange. Rows are written with
``bulk_create`` in batches so 100K prospects seed in minutes, not hours.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.hashers import make_password
from django.db import connection, transaction
from django.utils import timezone
from faker import Faker

from apps.accounts.models import Membership, Organization, User
from apps.properties.models import Property, Unit

from .models import Application, Channel, Conversation, Prospect, Tour

PERF_PASSWORD = "perf-pass-1234"  # synthetic account, local benchmarks only

PROSPECT_STATUS_WEIGHTS = {
    Prospect.Status.NEW: 30,
    Prospect.Status.CONTACTED: 25,
    Prospect.Status.TOUR_SCHEDULED: 12,
    Prospect.Status.TOURED: 12,
    Prospect.Status.APPLIED: 7,
    Prospect.Status.APPROVED: 3,
    Prospect.Status.LEASED: 3,
    Prospect.Status.LOST: 8,
}


@dataclass
class SeedContext:
    org: Organization
    manager: User
    agents: list[User]
    properties: list[Property]
    units: list[Unit]
    rng: random.Random
    fake: Faker
    counts: dict[str, int] = field(default_factory=dict)


def make_context(
    *,
    slug: str = "perf-org",
    agents: int = 10,
    properties: int = 20,
    units_per_property: int = 20,
    seed: int = 42,
) -> SeedContext:
    """Create (or reuse) an org with a manager, agents, properties and units."""
    rng = random.Random(seed)
    fake = Faker("en_US")
    fake.seed_instance(seed)

    org, _ = Organization.objects.get_or_create(slug=slug, defaults={"name": f"Perf {slug}"})
    pw = make_password(PERF_PASSWORD)  # hash once, reuse: hashing is the slow part

    def member(email: str, role: str) -> User:
        user, _ = User.objects.get_or_create(
            email=email,
            defaults={
                "password": pw,
                "first_name": fake.first_name(),
                "last_name": fake.last_name(),
            },
        )
        Membership.objects.get_or_create(user=user, organization=org, defaults={"role": role})
        return user

    manager = member(f"manager@{slug}.example.com", Membership.Role.PROPERTY_MANAGER)
    agent_users = [
        member(f"agent{i}@{slug}.example.com", Membership.Role.LEASING_AGENT) for i in range(agents)
    ]

    props = list(Property.objects.filter(organization=org).order_by("id"))
    if not props:
        props = Property.objects.bulk_create(
            Property(
                organization=org,
                name=f"{fake.last_name()} {rng.choice(['Lofts', 'Flats', 'Commons', 'Place'])}",
                address=fake.street_address(),
                city=fake.city(),
                state=fake.state_abbr(),
                zip_code=fake.zipcode(),
            )
            for _ in range(properties)
        )
        Unit.objects.bulk_create(
            Unit(
                organization=org,
                property=p,
                number=f"{100 + n}",
                floor=1 + n // 10,
                beds=rng.randint(0, 3),
                baths=Decimal(rng.choice(["1.0", "1.5", "2.0"])),
                sqft=rng.randint(450, 1400),
                rent=Decimal(rng.randint(1100, 3200)),
                available_from=timezone.now().date() + timedelta(days=rng.randint(0, 90)),
            )
            for p in props
            for n in range(units_per_property)
        )
    units = list(Unit.objects.filter(organization=org).order_by("id"))
    return SeedContext(org, manager, agent_users, props, units, rng, fake)


def _prospect(ctx: SeedContext, i: int) -> Prospect:
    rng, fake = ctx.rng, ctx.fake
    first, last = fake.first_name(), fake.last_name()
    return Prospect(
        organization=ctx.org,
        first_name=first,
        last_name=last,
        email=f"{first}.{last}.{i}@example.com".lower(),
        phone=f"+1555{rng.randint(0, 9999999):07d}",
        source=rng.choice(Prospect.Source.values),
        status=rng.choices(
            list(PROSPECT_STATUS_WEIGHTS), weights=list(PROSPECT_STATUS_WEIGHTS.values())
        )[0],
        # ~15% unassigned so agent-visibility rules have something to filter.
        assigned_agent=rng.choice(ctx.agents) if rng.random() > 0.15 else None,
        interested_property=rng.choice(ctx.properties) if rng.random() > 0.1 else None,
        desired_move_in=timezone.now().date() + timedelta(days=rng.randint(7, 120)),
        beds_min=rng.randint(0, 3),
        budget_max=Decimal(rng.randint(12, 35) * 100),
        has_pets=rng.random() < 0.3,
    )


def _children(ctx: SeedContext, p: Prospect, now) -> tuple[list, list, list]:
    rng = ctx.rng
    tours, apps = [], []
    for _ in range(rng.randint(1, 3)):
        start = now + timedelta(days=rng.randint(-60, 30), hours=rng.randint(9, 17))
        if start > now:
            status = Tour.Status.SCHEDULED
        else:
            status = rng.choice([Tour.Status.COMPLETED, Tour.Status.NO_SHOW, Tour.Status.CANCELED])
        tours.append(
            Tour(
                organization=ctx.org,
                prospect=p,
                unit=rng.choice(ctx.units),
                agent=p.assigned_agent,
                start=start,
                end=start + timedelta(minutes=30),
                status=status,
            )
        )
    for _ in range(rng.choice([0, 0, 1, 1, 2])):
        apps.append(
            Application(
                organization=ctx.org,
                prospect=p,
                unit=rng.choice(ctx.units),
                status=rng.choice(Application.Status.values),
                monthly_income=Decimal(rng.randint(30, 150) * 100),
            )
        )
    convo = Conversation(
        organization=ctx.org,
        prospect=p,
        channel=rng.choice(Channel.values),
        last_message_at=now - timedelta(minutes=rng.randint(1, 60 * 24 * 90)),
        is_unread=rng.random() < 0.2,
    )
    return tours, apps, [convo]


def seed_prospects(ctx: SeedContext, count: int, batch_size: int = 5000, log=None) -> dict:
    """Bulk-insert ``count`` prospects plus tours, applications and conversations."""
    now = timezone.now()
    totals = {"prospects": 0, "tours": 0, "applications": 0, "conversations": 0}
    start_index = Prospect.objects.filter(organization=ctx.org).count()
    done = 0
    while done < count:
        n = min(batch_size, count - done)
        with transaction.atomic():
            prospects = Prospect.objects.bulk_create(
                [_prospect(ctx, start_index + done + k) for k in range(n)]
            )
            tours, apps, convos = [], [], []
            for p in prospects:
                t, a, c = _children(ctx, p, now)
                tours += t
                apps += a
                convos += c
            Tour.objects.bulk_create(tours, batch_size=batch_size)
            Application.objects.bulk_create(apps, batch_size=batch_size)
            Conversation.objects.bulk_create(convos, batch_size=batch_size)
            # auto_now_add stamps every row with "now"; spread created_at over
            # ~2 years (deterministic in the id) so ordering/filters are realistic.
            with connection.cursor() as cur:
                cur.execute(
                    "UPDATE crm_prospect SET created_at = %s::timestamptz"
                    " - ((id * 7919) %% 63072000) * interval '1 second'"
                    " WHERE id BETWEEN %s AND %s",
                    [now, prospects[0].pk, prospects[-1].pk],
                )
        done += n
        totals["prospects"] += n
        totals["tours"] += len(tours)
        totals["applications"] += len(apps)
        totals["conversations"] += len(convos)
        if log:
            log(f"  {done}/{count} prospects")
    return totals

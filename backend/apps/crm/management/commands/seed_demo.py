import random
import time
from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from faker import Faker
from rest_framework.authtoken.models import Token

from apps.accounts.models import Membership, Organization, User
from apps.crm.models import Application, Channel, Conversation, Lease, Message, Prospect, Tour
from apps.properties.models import Property, PropertyPolicy, Unit

DEMO_PASSWORD = "demo1234!"
BATCH = 5000

STATUS_WEIGHTS = {
    Prospect.Status.NEW: 22,
    Prospect.Status.CONTACTED: 25,
    Prospect.Status.TOUR_SCHEDULED: 8,
    Prospect.Status.TOURED: 12,
    Prospect.Status.APPLIED: 6,
    Prospect.Status.APPROVED: 3,
    Prospect.Status.LEASED: 6,
    Prospect.Status.LOST: 18,
}
SOURCE_WEIGHTS = {
    Prospect.Source.WEBSITE: 25,
    Prospect.Source.ZILLOW: 22,
    Prospect.Source.APARTMENTS_COM: 18,
    Prospect.Source.EMAIL: 12,
    Prospect.Source.SMS: 10,
    Prospect.Source.CHAT: 6,
    Prospect.Source.WALK_IN: 4,
    Prospect.Source.REFERRAL: 3,
}
INBOUND = [
    "Hi, is the {beds} bedroom still available for {month}?",
    "Do you allow dogs? I have a small terrier.",
    "What's the rent for a {beds} bed and is parking included?",
    "Could I schedule a tour this weekend?",
    "Are utilities included in the rent?",
    "What are the application fees?",
]
OUTBOUND = [
    "Thanks for reaching out! Yes, it's available. Want to book a tour?",
    "We're pet friendly for dogs under 50 lbs. Happy to share details.",
    "I've sent you our current pricing. Let me know a good time to talk.",
]
POLICIES = [
    (
        PropertyPolicy.Topic.PETS,
        "Pet policy",
        "Cats and dogs under 50 lbs are welcome, two pets max. $300 refundable pet deposit and "
        "$35/month pet rent per pet. Breed restrictions apply. Service and support animals are "
        "not pets and have no fees.",
    ),
    (
        PropertyPolicy.Topic.PARKING,
        "Parking",
        "Each apartment includes one surface spot. Covered garage spots are $85/month, subject to "
        "availability. EV chargers are available in the garage.",
    ),
    (
        PropertyPolicy.Topic.FEES,
        "Fees",
        "Application fee is $50 per adult applicant. Administrative fee is $200 at lease signing. "
        "Trash and pest control are $25/month.",
    ),
    (
        PropertyPolicy.Topic.LEASE_TERMS,
        "Lease terms",
        "Lease terms from 6 to 15 months. Terms under 12 months carry a short-term premium.",
    ),
    (
        PropertyPolicy.Topic.APPLICATION,
        "Application & screening",
        "Applicants need gross monthly income of at least 2.5x rent, a credit check and a "
        "background check. Guarantors are accepted.",
    ),
    (
        PropertyPolicy.Topic.AMENITIES,
        "Amenities",
        "Pool, 24-hour fitness center, package lockers, rooftop lounge and bike storage.",
    ),
]


@contextmanager
def manual_timestamps(*models):
    """Let bulk_create keep our backdated created_at instead of auto_now_add's now()."""
    fields = [m._meta.get_field("created_at") for m in models]
    for f in fields:
        f.auto_now_add = False
    try:
        yield
    finally:
        for f in fields:
            f.auto_now_add = True


def weighted(rng, weights):
    return rng.choices(list(weights), weights=list(weights.values()))[0]


class Command(BaseCommand):
    help = "Generate realistic demo data (several orgs) for development and load testing."

    def add_arguments(self, parser):
        parser.add_argument("--prospects", type=int, default=2000)
        parser.add_argument("--orgs", type=int, default=4)
        parser.add_argument("--properties-per-org", type=int, default=5)
        parser.add_argument("--units-per-property", type=int, default=120)
        parser.add_argument("--agents-per-org", type=int, default=8)
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument("--reset", action="store_true", help="Delete existing demo orgs first")

    def handle(self, *args, **opts):
        started = time.perf_counter()
        rng = random.Random(opts["seed"])
        fake = Faker()
        Faker.seed(opts["seed"])
        existing = Organization.objects.filter(slug__startswith="demo-")
        if existing.exists():
            if not opts["reset"]:
                raise CommandError("Demo data exists; pass --reset to replace it.")
            self.stdout.write("Deleting existing demo data...")
            # Leases/applications PROTECT units and prospects, so remove them first.
            Lease.objects.filter(organization__in=existing).delete()
            Application.objects.filter(organization__in=existing).delete()
            existing.delete()
            User.objects.filter(email__endswith=".demo").delete()

        # Pools keep Faker out of the 100K-row hot loop.
        # Hash once: PBKDF2 per user would dominate seeding time.
        self.password_hash = make_password(DEMO_PASSWORD)
        first_names = [fake.first_name() for _ in range(1500)]
        last_names = [fake.last_name() for _ in range(1500)]
        now = timezone.now()
        n_orgs = opts["orgs"]
        per_org = [opts["prospects"] // n_orgs] * n_orgs
        per_org[0] += opts["prospects"] - sum(per_org)

        for i in range(n_orgs):
            with transaction.atomic():
                self._seed_org(i + 1, per_org[i], opts, rng, fake, first_names, last_names, now)
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {opts['prospects']} prospects in {time.perf_counter() - started:.1f}s. "
                f"Log in as manager@org1.demo / {DEMO_PASSWORD}"
            )
        )

    def _seed_org(self, n, prospect_count, opts, rng, fake, first_names, last_names, now):
        org = Organization.objects.create(name=f"{fake.last_name()} Living {n}", slug=f"demo-{n}")
        manager = User.objects.create(
            email=f"manager@org{n}.demo",
            password=self.password_hash,
            first_name=fake.first_name(),
            last_name=fake.last_name(),
        )
        Membership.objects.create(
            user=manager, organization=org, role=Membership.Role.PROPERTY_MANAGER
        )
        Token.objects.get_or_create(user=manager)
        agents = []
        for a in range(opts["agents_per_org"]):
            agent = User.objects.create(
                email=f"agent{a + 1}@org{n}.demo",
                password=self.password_hash,
                first_name=fake.first_name(),
                last_name=fake.last_name(),
            )
            Membership.objects.create(user=agent, organization=org)
            Token.objects.get_or_create(user=agent)
            agents.append(agent)

        properties = Property.objects.bulk_create(
            [
                Property(
                    organization=org,
                    name=f"{fake.street_name()} {kind}",
                    address=fake.street_address(),
                    city=fake.city(),
                    state=fake.state_abbr(),
                    zip_code=fake.zipcode(),
                    # Deterministic routing keys used by the sample webhooks and ILS feed.
                    inbound_email=f"leasing-{n}-{i}@inbound.leaseloop.dev",
                    sms_number=f"+1555{n:03d}{i:04d}",
                    ils_listing_id=f"LL-{n}-{i}",
                )
                for i, kind in enumerate(
                    rng.sample(
                        ["Lofts", "Commons", "Residences", "Flats", "Place", "Terrace", "Gardens"],
                        opts["properties_per_org"],
                    ),
                    start=1,
                )
            ]
        )
        PropertyPolicy.objects.bulk_create(
            [
                PropertyPolicy(organization=org, topic=t, title=title, body=body)
                for t, title, body in POLICIES
            ]
        )

        units = []
        for prop in properties:
            base = rng.randint(1300, 2200)
            for u in range(opts["units_per_property"]):
                beds = rng.choices([0, 1, 2, 3], weights=[10, 45, 35, 10])[0]
                status = rng.choices(
                    ["AVAILABLE", "NOTICE", "OCCUPIED", "OFFLINE"], weights=[12, 6, 80, 2]
                )[0]
                units.append(
                    Unit(
                        organization=org,
                        property=prop,
                        number=f"{u // 20 + 1}{u % 20 + 1:02d}",
                        floor=u // 20 + 1,
                        beds=beds,
                        baths=Decimal("1.0") if beds < 2 else Decimal("2.0"),
                        sqft=450 + beds * 350 + rng.randint(0, 120),
                        rent=Decimal(base + beds * 450 + rng.randint(-60, 60)),
                        deposit=Decimal(500),
                        available_from=(now + timedelta(days=rng.randint(0, 75))).date()
                        if status in ("AVAILABLE", "NOTICE")
                        else None,
                        status=status,
                    )
                )
        units = Unit.objects.bulk_create(units, batch_size=BATCH)

        prospects = []
        for _ in range(prospect_count):
            first, last = rng.choice(first_names), rng.choice(last_names)
            status = weighted(rng, STATUS_WEIGHTS)
            created = now - timedelta(seconds=rng.randint(0, 365 * 86400))
            prospects.append(
                Prospect(
                    organization=org,
                    first_name=first,
                    last_name=last,
                    email=f"{first}.{last}{rng.randint(1, 9999)}@example.com".lower(),
                    phone=f"+1{rng.randint(2012000000, 9899999999)}",
                    source=weighted(rng, SOURCE_WEIGHTS),
                    status=status,
                    assigned_agent=rng.choice(agents) if rng.random() < 0.8 else None,
                    interested_property=rng.choice(properties) if rng.random() < 0.85 else None,
                    desired_move_in=(created + timedelta(days=rng.randint(14, 90))).date(),
                    beds_min=rng.choice([0, 1, 1, 2, 2, 3]),
                    budget_max=Decimal(rng.randrange(1400, 4200, 50)),
                    has_pets=rng.random() < 0.35,
                    last_contacted_at=created + timedelta(hours=rng.randint(1, 72))
                    if status != Prospect.Status.NEW
                    else None,
                    created_at=created,
                )
            )
        with manual_timestamps(Prospect):
            prospects = Prospect.objects.bulk_create(prospects, batch_size=BATCH)

        self._seed_activity(org, prospects, units, agents, rng, now)
        self.stdout.write(f"  org {n}: {len(prospects)} prospects, {len(units)} units")

    def _seed_activity(self, org, prospects, units, agents, rng, now):
        conversations, messages, tours, applications = [], [], [], []
        units_by_property = {}
        for u in units:
            units_by_property.setdefault(u.property_id, []).append(u)
        for p in prospects:
            channel = {Prospect.Source.SMS: Channel.SMS, Prospect.Source.CHAT: Channel.CHAT}.get(
                p.source, Channel.EMAIL
            )
            conversations.append(
                Conversation(
                    organization=org,
                    prospect=p,
                    channel=channel,
                    is_unread=rng.random() < 0.2,
                    last_message_at=p.last_contacted_at or p.created_at,
                )
            )
        conversations = Conversation.objects.bulk_create(conversations, batch_size=BATCH)

        for p, conv in zip(prospects, conversations, strict=True):
            t = p.created_at
            for k in range(rng.randint(1, 4)):
                inbound = k % 2 == 0
                body = rng.choice(INBOUND if inbound else OUTBOUND).format(
                    beds=p.beds_min or 1, month="next month"
                )
                messages.append(
                    Message(
                        organization=org,
                        conversation=conv,
                        direction="IN" if inbound else "OUT",
                        channel=conv.channel,
                        body=body,
                        sent_at=t,
                        sender=None if inbound else p.assigned_agent,
                    )
                )
                t += timedelta(hours=rng.randint(1, 30))

            early = (Prospect.Status.NEW, Prospect.Status.CONTACTED, Prospect.Status.LOST)
            if p.status in early and rng.random() > 0.08:
                continue
            pool = units_by_property.get(p.interested_property_id) or units
            unit = rng.choice(pool)
            if p.status == Prospect.Status.TOUR_SCHEDULED or rng.random() < 0.1:
                start = now + timedelta(days=rng.randint(0, 14), hours=rng.randint(9, 17))
                status = Tour.Status.SCHEDULED
            else:
                start = p.created_at + timedelta(days=rng.randint(1, 10), hours=rng.randint(9, 17))
                status = rng.choices(
                    [Tour.Status.COMPLETED, Tour.Status.NO_SHOW, Tour.Status.CANCELED],
                    weights=[80, 10, 10],
                )[0]
            start = start.replace(minute=rng.choice([0, 30]), second=0, microsecond=0)
            tours.append(
                Tour(
                    organization=org,
                    prospect=p,
                    unit=unit,
                    agent=p.assigned_agent or rng.choice(agents),
                    start=start,
                    end=start + timedelta(minutes=30),
                    status=status,
                )
            )
            if p.status in (
                Prospect.Status.APPLIED,
                Prospect.Status.APPROVED,
                Prospect.Status.LEASED,
            ):
                applications.append(
                    Application(
                        organization=org,
                        prospect=p,
                        unit=unit,
                        status={Prospect.Status.APPLIED: Application.Status.SUBMITTED}.get(
                            p.status, Application.Status.APPROVED
                        ),
                        monthly_income=Decimal(rng.randrange(4000, 15000, 100)),
                        submitted_at=p.created_at + timedelta(days=12),
                    )
                )

        Message.objects.bulk_create(messages, batch_size=BATCH)
        Tour.objects.bulk_create(tours, batch_size=BATCH)
        applications = Application.objects.bulk_create(applications, batch_size=BATCH)
        leases = []
        for app in applications:
            if app.prospect.status != Prospect.Status.LEASED:
                continue
            start = (app.submitted_at + timedelta(days=20)).date()
            leases.append(
                Lease(
                    organization=org,
                    application=app,
                    prospect=app.prospect,
                    unit=app.unit,
                    status=Lease.Status.ACTIVE,
                    start_date=start,
                    end_date=start + timedelta(days=365),
                    term_months=12,
                    monthly_rent=app.unit.rent,
                    signed_at=app.submitted_at + timedelta(days=15),
                )
            )
        Lease.objects.bulk_create(leases, batch_size=BATCH)

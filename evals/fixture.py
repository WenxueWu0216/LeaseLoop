# ruff: noqa: E501  (policy prose)
"""Deterministic data for the assistant eval: one org, two properties, known facts.

Every expected fact in inquiries.jsonl comes from here, and the eval clock is fixed
at EVAL_NOW so relative dates ("tomorrow", "Thursday") resolve the same way each run.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

EVAL_NOW = datetime(2026, 11, 2, 10, 0, tzinfo=ZoneInfo("America/New_York"))  # a Monday

POLICIES = {
    # (property key or None for org-wide, topic): (title, body)
    (None, "PRICING"): (
        "Pricing & specials",
        (
            "Rent is set per unit and can change daily, so ask for live pricing on a specific unit. "
            "Current special: one month free on 13-month leases for 2-bedroom homes that start by "
            "December 31. Rent is due on the 1st, and a $75 late fee applies after the 5th."
        ),
    ),
    (None, "FEES"): (
        "Fees",
        (
            "The application fee is $50 per adult applicant and is non-refundable. A $200 "
            "administrative fee is due at lease signing. The security deposit is $500 for approved "
            "applicants and up to one month's rent for conditional approvals. Trash and pest control "
            "are $25 per month. Water and sewer are billed back based on usage, typically $40 to $60 "
            "per month. Electricity is set up in your name with the local utility. High-speed "
            "internet is provided for $65 per month through our bulk plan."
        ),
    ),
    (None, "LEASE_TERMS"): (
        "Lease terms",
        (
            "We offer lease terms from 6 to 15 months. Leases shorter than 12 months add $150 per "
            "month to the rent. Month-to-month is available after your first lease term ends at $250 "
            "per month over the current rent. Early termination requires 60 days' notice and a fee "
            "equal to two months' rent."
        ),
    ),
    (None, "APPLICATION"): (
        "Application & screening",
        (
            "Applications are completed online and take about 15 minutes. Each adult 18 or older "
            "applies separately. We look for gross monthly income of at least 2.5 times the rent, a "
            "credit check and a background check. Guarantors are accepted and need income of 5 times "
            "the rent. Decisions usually come within two business days."
        ),
    ),
    (None, "GENERAL"): (
        "Office hours & tours",
        (
            "The leasing office is open Monday through Saturday from 9 AM to 6 PM and closed on "
            "Sundays. Tours run every 30 minutes from 9 AM to 5 PM, Monday through Saturday, and "
            "take about 30 minutes. Self-guided tours are not offered."
        ),
    ),
    ("maple", "PETS"): (
        "Pet policy",
        (
            "Cats and dogs are welcome, up to two pets per apartment. Dogs must be under 50 lbs. "
            "There is a $300 refundable pet deposit and $35 monthly pet rent per pet. Restricted "
            "breeds include pit bulls, rottweilers, dobermans and wolf hybrids. Service animals and "
            "emotional support animals are not pets: no pet deposit, pet rent or weight limit "
            "applies to them."
        ),
    ),
    ("birch", "PETS"): (
        "Pet policy",
        (
            "Birch Lofts is cat-friendly: up to two cats per apartment with a $250 pet deposit and "
            "$25 monthly pet rent per cat. Dogs are not allowed at Birch Lofts. Service animals and "
            "emotional support animals are not pets and are always welcome."
        ),
    ),
    ("maple", "PARKING"): (
        "Parking",
        (
            "Each apartment includes one uncovered surface spot at no charge. Reserved garage spaces "
            "are $85 per month, subject to availability. Additional surface spots are $40 per month. "
            "EV charging stations are in the garage and are free for garage renters. Guest parking "
            "is on Level 1 of the garage for up to 48 hours."
        ),
    ),
    ("birch", "PARKING"): (
        "Parking",
        (
            "Birch Lofts has street parking only; residential permits are $30 per year through the "
            "city. Secure bike storage is on the ground floor."
        ),
    ),
    ("maple", "AMENITIES"): (
        "Amenities",
        (
            "Maple Court amenities include a heated outdoor pool (open May through September), a "
            "24-hour fitness center, package lockers, a rooftop lounge with grills, and in-unit "
            "washers and dryers in every apartment."
        ),
    ),
    ("birch", "AMENITIES"): (
        "Amenities",
        (
            "Birch Lofts includes a coworking lounge, a shared laundry room on each floor, a rooftop "
            "deck and package lockers. Apartments do not have in-unit laundry."
        ),
    ),
}

UNITS = {
    # property: [(number, beds, baths, sqft, rent, status, available_from offset days)]
    "maple": [
        ("101", 0, "1.0", 480, 1450, "AVAILABLE", 0),
        ("102", 1, "1.0", 690, 1725, "AVAILABLE", 0),
        ("203", 1, "1.0", 720, 1795, "NOTICE", 29),  # Dec 1
        ("204", 2, "2.0", 1040, 2350, "AVAILABLE", 0),
        ("305", 2, "2.0", 1050, 2425, "OCCUPIED", None),
        ("306", 2, "1.0", 960, 2195, "NOTICE", 43),  # Dec 15
        ("401", 3, "2.0", 1310, 3100, "NOTICE", 48),  # Dec 20
    ],
    "birch": [
        ("110", 1, "1.0", 650, 1600, "AVAILABLE", 0),
        ("210", 2, "1.0", 900, 2150, "AVAILABLE", 13),  # Nov 15
        ("310", 1, "1.0", 660, 1650, "OCCUPIED", None),
    ],
}

# Existing tours that make some requested slots unavailable (local times).
BOOKED = [
    ("maple", "204", datetime(2026, 11, 5, 14, 0)),
    ("maple", "102", datetime(2026, 11, 7, 10, 0)),
]


def build():
    """Create the eval org and return {"maple": Property, "birch": Property, "agent": User}."""
    from apps.accounts.models import Membership, Organization, User
    from apps.assistant.retrieval import index_policy
    from apps.crm.models import Prospect, Tour
    from apps.properties.models import Property, PropertyPolicy, Unit

    org = Organization.objects.create(name="Maple Property Group", slug="eval-maple")
    agent = User.objects.create(email="agent@eval.test", first_name="Avery", last_name="Lee")
    Membership.objects.create(user=agent, organization=org)
    props = {
        "maple": Property.objects.create(
            organization=org,
            name="Maple Court",
            address="12 Maple Ave",
            city="Hoboken",
            state="NJ",
            zip_code="07030",
            timezone="America/New_York",
        ),
        "birch": Property.objects.create(
            organization=org,
            name="Birch Lofts",
            address="400 Birch St",
            city="Chicago",
            state="IL",
            zip_code="60607",
            timezone="America/Chicago",
        ),
    }
    today = EVAL_NOW.date()
    units = {}
    for key, rows in UNITS.items():
        for number, beds, baths, sqft, rent, status, offset in rows:
            units[(key, number)] = Unit.objects.create(
                organization=org,
                property=props[key],
                number=number,
                beds=beds,
                baths=Decimal(baths),
                sqft=sqft,
                rent=Decimal(rent),
                status=status,
                available_from=today + timedelta(days=offset) if offset is not None else None,
            )
    for (key, topic), (title, body) in POLICIES.items():
        policy = PropertyPolicy.objects.create(
            organization=org,
            property=props[key] if key else None,
            topic=topic,
            title=title,
            body=body,
        )
        index_policy(policy)
    other = Prospect.objects.create(organization=org, first_name="Existing", last_name="Renter")
    for key, number, local in BOOKED:
        start = local.replace(tzinfo=ZoneInfo(props[key].timezone))
        Tour.objects.create(
            organization=org,
            prospect=other,
            unit=units[(key, number)],
            start=start,
            end=start + timedelta(minutes=30),
        )
    return {**props, "agent": agent, "org": org}


assert EVAL_NOW.date() == date(2026, 11, 2)

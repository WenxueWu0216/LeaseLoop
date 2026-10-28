from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models

from apps.core.models import OrgOwnedModel


class Property(OrgOwnedModel):
    name = models.CharField(max_length=200)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=2)
    zip_code = models.CharField(max_length=10)
    timezone = models.CharField(max_length=64, default="America/New_York")
    phone = models.CharField(max_length=32, blank=True)
    email = models.EmailField(blank=True)

    class Meta:
        verbose_name_plural = "properties"
        indexes = [models.Index(fields=["organization", "name"], name="property_org_name")]

    def __str__(self) -> str:
        return self.name


class Unit(OrgOwnedModel):
    class Status(models.TextChoices):
        AVAILABLE = "AVAILABLE", "Available"
        NOTICE = "NOTICE", "On notice"
        OCCUPIED = "OCCUPIED", "Occupied"
        OFFLINE = "OFFLINE", "Offline"

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="units")
    number = models.CharField(max_length=20)
    floor = models.PositiveSmallIntegerField(default=1)
    beds = models.PositiveSmallIntegerField()
    baths = models.DecimalField(max_digits=3, decimal_places=1)
    sqft = models.PositiveIntegerField(null=True, blank=True)
    rent = models.DecimalField(
        max_digits=8, decimal_places=2, validators=[MinValueValidator(Decimal(0))]
    )
    deposit = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    available_from = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.AVAILABLE)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["property", "number"], name="uniq_unit_number"),
        ]
        indexes = [
            models.Index(
                fields=["organization", "status", "available_from"], name="unit_org_status_avail"
            ),
            models.Index(fields=["property", "beds", "rent"], name="unit_prop_beds_rent"),
        ]

    def __str__(self) -> str:
        return f"{self.property.name} #{self.number}"


class PropertyPolicy(OrgOwnedModel):
    """Free-text policy/FAQ documents. Source material for the leasing assistant.

    ``property`` null means the policy applies to every property in the org.
    Live prices and availability are intentionally NOT stored here; the
    assistant reads those from Unit via tool calls.
    """

    class Topic(models.TextChoices):
        PRICING = "PRICING", "Pricing & specials"
        PETS = "PETS", "Pet policy"
        PARKING = "PARKING", "Parking"
        FEES = "FEES", "Fees"
        LEASE_TERMS = "LEASE_TERMS", "Lease terms"
        AMENITIES = "AMENITIES", "Amenities"
        APPLICATION = "APPLICATION", "Application & screening"
        GENERAL = "GENERAL", "General"

    property = models.ForeignKey(
        Property, on_delete=models.CASCADE, related_name="policies", null=True, blank=True
    )
    topic = models.CharField(max_length=20, choices=Topic.choices)
    title = models.CharField(max_length=200)
    body = models.TextField()

    class Meta:
        verbose_name_plural = "property policies"
        indexes = [models.Index(fields=["organization", "topic"], name="policy_org_topic")]

    def __str__(self) -> str:
        return self.title

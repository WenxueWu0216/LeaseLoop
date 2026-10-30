from rest_framework import serializers

from apps.core.serializers import OrgScopedPrimaryKeyRelatedField

from .models import Property, PropertyPolicy, Unit


class PropertySerializer(serializers.ModelSerializer):
    class Meta:
        model = Property
        exclude = ["organization"]


class UnitSerializer(serializers.ModelSerializer):
    property = OrgScopedPrimaryKeyRelatedField(queryset=Property.objects.all())
    property_name = serializers.CharField(source="property.name", read_only=True)

    class Meta:
        model = Unit
        exclude = ["organization"]


class PropertyPolicySerializer(serializers.ModelSerializer):
    property = OrgScopedPrimaryKeyRelatedField(
        queryset=Property.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = PropertyPolicy
        exclude = ["organization"]

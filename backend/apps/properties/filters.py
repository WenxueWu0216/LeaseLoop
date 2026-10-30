import django_filters as df

from .models import PropertyPolicy, Unit


class UnitFilter(df.FilterSet):
    property = df.NumberFilter(field_name="property_id")
    status = df.MultipleChoiceFilter(choices=Unit.Status.choices)
    beds = df.NumberFilter()
    beds_min = df.NumberFilter(field_name="beds", lookup_expr="gte")
    rent_max = df.NumberFilter(field_name="rent", lookup_expr="lte")
    available_by = df.DateFilter(field_name="available_from", lookup_expr="lte")

    class Meta:
        model = Unit
        fields = ["status", "beds"]


class PolicyFilter(df.FilterSet):
    property = df.NumberFilter(field_name="property_id")

    class Meta:
        model = PropertyPolicy
        fields = ["topic"]

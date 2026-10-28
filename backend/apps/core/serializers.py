from rest_framework import serializers


class OrgScopedPrimaryKeyRelatedField(serializers.PrimaryKeyRelatedField):
    """FK field that only accepts objects from the request's organization.

    Prevents attaching, say, a Unit from another tenant to a Tour.
    """

    def get_queryset(self):
        qs = super().get_queryset()
        org = self.context.get("organization")
        if org is None:
            return qs.none()
        return qs.filter(organization=org)


class OrgMemberUserField(serializers.PrimaryKeyRelatedField):
    """User FK restricted to members of the request's organization."""

    def get_queryset(self):
        qs = super().get_queryset()
        org = self.context.get("organization")
        if org is None:
            return qs.none()
        return qs.filter(memberships__organization=org)

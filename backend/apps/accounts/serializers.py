from rest_framework import serializers

from .models import Membership, Organization, User


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ["id", "name", "slug"]


class UserSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name"]


class MembershipSerializer(serializers.ModelSerializer):
    user = UserSummarySerializer(read_only=True)
    email = serializers.EmailField(write_only=True)
    first_name = serializers.CharField(write_only=True, required=False, default="")
    last_name = serializers.CharField(write_only=True, required=False, default="")

    class Meta:
        model = Membership
        fields = ["id", "user", "role", "email", "first_name", "last_name", "created_at"]
        read_only_fields = ["created_at"]

    def create(self, validated_data):
        org = validated_data["organization"]
        user, _ = User.objects.get_or_create(
            email=validated_data.pop("email").lower(),
            defaults={
                "first_name": validated_data.pop("first_name", ""),
                "last_name": validated_data.pop("last_name", ""),
            },
        )
        if Membership.objects.filter(user=user, organization=org).exists():
            raise serializers.ValidationError({"email": "User is already a member."})
        return Membership.objects.create(user=user, organization=org, role=validated_data["role"])

    def update(self, instance, validated_data):
        instance.role = validated_data.get("role", instance.role)
        instance.save(update_fields=["role", "updated_at"])
        return instance


class MeSerializer(serializers.ModelSerializer):
    memberships = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name", "memberships"]

    def get_memberships(self, user):
        return [
            {"organization": OrganizationSerializer(m.organization).data, "role": m.role}
            for m in user.memberships.select_related("organization")
        ]

from django.contrib import admin

from .models import Property, PropertyPolicy, Unit


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "city", "state")
    list_filter = ("organization",)
    search_fields = ("name", "address")


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ("number", "property", "beds", "baths", "rent", "status", "available_from")
    list_filter = ("status", "beds", "organization")
    list_select_related = ("property",)


@admin.register(PropertyPolicy)
class PropertyPolicyAdmin(admin.ModelAdmin):
    list_display = ("title", "topic", "property", "organization")
    list_filter = ("topic", "organization")

from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.core.tenancy import resolve_membership


class IsOrgMember(BasePermission):
    def has_permission(self, request, view) -> bool:
        if not (request.user and request.user.is_authenticated):
            return False
        resolve_membership(request)
        return True


class IsManager(IsOrgMember):
    message = "Only property managers can perform this action."

    def has_permission(self, request, view) -> bool:
        return super().has_permission(request, view) and resolve_membership(request).is_manager


class IsManagerOrReadOnly(IsOrgMember):
    """Managers write, agents read.

    On detail routes the role check runs against the looked-up object, so a
    foreign-tenant id yields 404 (not found in the scoped queryset) rather
    than 403, regardless of role.
    """

    message = "Only property managers can modify this resource."

    def _allowed(self, request) -> bool:
        return request.method in SAFE_METHODS or resolve_membership(request).is_manager

    def has_permission(self, request, view) -> bool:
        if not super().has_permission(request, view):
            return False
        if view.kwargs.get(getattr(view, "lookup_url_kwarg", None) or view.lookup_field):
            return True
        return self._allowed(request)

    def has_object_permission(self, request, view, obj) -> bool:
        return self._allowed(request)

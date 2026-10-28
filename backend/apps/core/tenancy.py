from __future__ import annotations

from typing import TYPE_CHECKING

from rest_framework.exceptions import NotFound, PermissionDenied

if TYPE_CHECKING:
    from rest_framework.request import Request

    from apps.accounts.models import Membership

ORG_HEADER = "HTTP_X_ORGANIZATION"


def resolve_membership(request: Request) -> Membership:
    """Pick the caller's active membership.

    Users in several orgs select one with the ``X-Organization`` header (org id);
    users with a single membership get it implicitly.
    """
    cached = getattr(request, "_membership", None)
    if cached is not None:
        return cached

    user = request.user
    memberships = user.memberships.select_related("organization")
    org_id = request.META.get(ORG_HEADER)
    if org_id:
        try:
            membership = memberships.get(organization_id=int(org_id))
        except (ValueError, memberships.model.DoesNotExist):
            # Don't reveal whether the org exists.
            raise NotFound("Organization not found.") from None
    else:
        found = list(memberships[:2])
        if not found:
            raise PermissionDenied("You are not a member of any organization.")
        if len(found) > 1:
            raise PermissionDenied("Multiple organizations: send the X-Organization header.")
        membership = found[0]

    request._membership = membership
    return membership

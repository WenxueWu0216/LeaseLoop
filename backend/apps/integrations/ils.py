"""Mock ILS (Zillow / Apartments.com style) lead feed.

The real feeds are paginated HTTP APIs returning leads for your listings since a
cursor. This client reads the same shape from JSON fixtures so the sync logic
(cursoring, upserts, retries) is exercised without accounts.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings


class ILSUnavailable(Exception):
    """Feed timed out or returned 5xx: retry with backoff."""


@dataclass(frozen=True)
class ILSLead:
    external_id: str
    listing_id: str
    first_name: str
    last_name: str
    email: str
    phone: str
    message: str
    move_in: str | None
    created_at: str


class MockILSClient:
    page_size = 50
    # Test hook: number of upcoming fetches that should fail like a flaky upstream.
    fail_next = 0

    def __init__(self, source: str):
        self.source = source
        self.path = Path(settings.ILS_FEED_DIR) / f"ils_{source.lower()}.json"

    def fetch(self, listing_ids: set[str], cursor: str = "") -> tuple[list[ILSLead], str]:
        if MockILSClient.fail_next > 0:
            MockILSClient.fail_next -= 1
            raise ILSUnavailable(f"{self.source} feed returned 503")
        if not self.path.exists():
            return [], cursor
        rows = sorted(json.loads(self.path.read_text())["leads"], key=lambda r: r["created_at"])
        # Cursor is the last seen (created_at, id); the feed is append-only by created_at.
        fresh = [
            r
            for r in rows
            if f"{r['created_at']}|{r['id']}" > cursor and r["listing_id"] in listing_ids
        ][: self.page_size]
        if not fresh:
            return [], cursor
        next_cursor = f"{fresh[-1]['created_at']}|{fresh[-1]['id']}"
        leads = [
            ILSLead(
                external_id=r["id"],
                listing_id=r["listing_id"],
                first_name=r.get("first_name", ""),
                last_name=r.get("last_name", ""),
                email=r.get("email", "").lower(),
                phone=r.get("phone", ""),
                message=r.get("message", ""),
                move_in=r.get("move_in"),
                created_at=r["created_at"],
            )
            for r in fresh
        ]
        return leads, next_cursor

# Webhooks and background jobs

## Inbound email and SMS

| Provider | Endpoint | Authenticity check | Idempotency key |
|---|---|---|---|
| SendGrid Inbound Parse (multipart) | `POST /api/webhooks/sendgrid/inbound/?token=…` | Shared secret in the URL, compared in constant time. SendGrid does not sign Inbound Parse requests. | The email's `Message-ID` header, or a SHA-256 of from/to/subject/body if the header is missing |
| Twilio SMS (form-encoded) | `POST /api/webhooks/twilio/sms/` | `X-Twilio-Signature`: HMAC-SHA1 of the public URL plus the sorted form fields | `MessageSid` |

A webhook request goes through these steps:

1. **Verify.** A bad signature or token returns 403, and nothing is stored.
2. **Record.** Insert a row into `WebhookEvent`, which has a unique `(provider, event_id)` constraint.
3. **Enqueue.** If the insert succeeds, enqueue `process_inbound_event` with
   `transaction.on_commit`, so the worker cannot run before the row is visible.
4. **Answer.** Return 200 right away. A duplicate delivery hits the unique constraint and gets
   `{"status": "duplicate"}` without enqueuing anything.

The duplicate check relies on the database constraint, not on reading first and then writing.
So two concurrent deliveries of the same message cannot both get through.

The worker then processes the event:

- It locks the event row (`SELECT … FOR UPDATE`) and skips the event if it is already
  processed. This covers Celery delivering the same task twice.
- It routes the message by recipient: the property's `inbound_email` or `sms_number` decides
  the organization.
- It matches an existing prospect by email or phone *within that organization*, or creates
  one.
- It reuses the prospect's conversation for that channel, and stores the message with the
  provider's id. That id is unique, which is a second guard against duplicates.
- A message for an unknown recipient is marked `IGNORED` and still answered with 200, so the
  provider stops retrying it.

`scripts/post_webhooks.py` posts the sample payloads in
`backend/apps/integrations/sample_payloads/`, each one twice:

```
sendgrid 1 200 {'status': 'accepted', 'event': 1}
sendgrid 2 200 {'status': 'duplicate', 'event': 1}
twilio 1 200 {'status': 'accepted', 'event': 3}
twilio 2 200 {'status': 'duplicate', 'event': 3}
```

## Scheduled tasks (Celery beat)

| Task | Schedule | What it does |
|---|---|---|
| `send_tour_reminders` | every 5 min | Enqueues `send_tour_reminder(tour, "24h")` for tours starting in 1 to 24 hours, and `(tour, "1h")` for tours within the next hour, skipping tours whose reminder is already marked sent |
| `follow_up_stale_prospects` | hourly at :07 | NEW/CONTACTED prospects who are quiet for 3+ days, under 30 days old, and have fewer than 2 nudges. At most 500 per run |
| `sync_all_lead_sources` | every 15 min | Fans out `sync_lead_source(org, source)` for Zillow and Apartments.com |

**At most once, with retries.** Each worker task:

- locks its row,
- re-checks the condition (reminder not sent yet, prospect still stale),
- sends with a deterministic idempotency key (`tour:42:reminder:24h`,
  `prospect:7:followup:1`),
- records the outbound message under that key, which is unique,
- and marks the row, all in one transaction.

If the send fails, nothing is marked and the task retries. If the send succeeds but the commit
fails, the retry reuses the same key, and real providers drop duplicate keys. The trade-off is
that a row lock is held during one provider call.

**Retries.** `autoretry_for` covers transient errors only: provider timeouts, ILS 5xx
responses, and DB `OperationalError`. Retries use `retry_backoff=True` (1s, 2s, 4s, … capped
at 600s), `retry_jitter=True` and `max_retries=5`. After the last retry, the reminder stays
unmarked, so the next scan picks it up again.

**ILS sync.** The mock feed (`ils.py`, with fixtures in `sample_payloads/`) returns leads for
our listings after a `(created_at, id)` cursor. Leads are upserted on the unique
`(organization, source, external_id)` constraint. The cursor only moves forward in the same
transaction as the inserts.

## Run against a real worker (not eager)

These results come from running the stack locally on the 100K-prospect seed: gunicorn, one
Celery worker with 2 processes, and Redis.

- **ILS sync.** The first fan-out created 60 prospects, each with its inquiry message, across
  4 orgs × 2 sources. The second fan-out created 0, because the cursors had advanced.
- **Follow-ups.** One scan enqueued 500 prospects (the batch cap) and sent exactly 500 nudges.
- **Duplicate scans.** This happened by accident, and it shows the idempotency holding. A
  misconfigured test run had published 4 copies of the reminder scan to Redis. When the
  worker started, each copy found the same 715 due tours and enqueued a reminder for each:
  2,860 tasks processed by two concurrent worker processes. Exactly **715** reminders were
  sent and recorded, one per tour. The rest saw the tour already claimed and returned
  `False`. Tests now use a `memory://` broker (`config/settings_test.py`), so this cannot
  happen again.

## Tests

- `tests/test_webhooks.py`:
  - duplicate deliveries for both providers;
  - forged and tampered signatures;
  - a missing token configuration;
  - matching an existing prospect, but never across orgs;
  - unknown recipients;
  - the content-hash fallback;
  - re-processing an event that is already processed.
- `tests/test_tasks.py` (eager Celery):
  - scans that run twice, and duplicate task deliveries;
  - reminder time windows;
  - retry until delivered, keeping the same idempotency key;
  - giving up after `max_retries` without marking the reminder sent;
  - follow-up eligibility and the cap;
  - ILS cursoring, replaying the feed with no duplicates, and a flaky feed with retries.

"""Normalize provider payloads into one InboundMessage shape."""

import email
import hashlib
import json
from dataclasses import dataclass
from email.utils import getaddresses, parseaddr

from apps.crm.models import Channel


@dataclass(frozen=True)
class InboundMessage:
    channel: str
    sender_name: str
    sender_email: str
    sender_phone: str
    recipients: tuple[str, ...]
    subject: str
    body: str


def sendgrid_event_id(payload: dict) -> str:
    """The email's Message-ID header; a content hash if the sender omitted it."""
    headers = email.message_from_string(payload.get("headers", ""))
    message_id = (headers.get("Message-ID") or "").strip()
    if message_id:
        return message_id
    raw = "|".join(payload.get(k, "") for k in ("from", "to", "subject", "text"))
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


def parse_sendgrid(payload: dict) -> InboundMessage:
    name, address = parseaddr(payload.get("from", ""))
    try:
        recipients = json.loads(payload.get("envelope") or "{}").get("to") or []
    except json.JSONDecodeError:
        recipients = []
    if not recipients:
        recipients = [addr for _, addr in getaddresses([payload.get("to", "")])]
    return InboundMessage(
        channel=Channel.EMAIL,
        sender_name=name,
        sender_email=address.lower(),
        sender_phone="",
        recipients=tuple(r.lower() for r in recipients if r),
        subject=payload.get("subject", "")[:255],
        body=(payload.get("text") or payload.get("html") or "").strip(),
    )


def parse_twilio(payload: dict) -> InboundMessage:
    return InboundMessage(
        channel=Channel.SMS,
        sender_name="",
        sender_email="",
        sender_phone=payload.get("From", ""),
        recipients=(payload.get("To", ""),),
        subject="",
        body=payload.get("Body", "").strip(),
    )


PARSERS = {"sendgrid": parse_sendgrid, "twilio": parse_twilio}

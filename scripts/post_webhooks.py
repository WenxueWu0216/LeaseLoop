"""Post the sample SendGrid/Twilio payloads to a running server, twice each.

The second delivery of each payload simulates a provider retry; the API should
answer "duplicate" and create nothing new.

    python scripts/post_webhooks.py --base http://localhost:8000 \
        --sendgrid-token "$SENDGRID_INBOUND_TOKEN" --twilio-token "$TWILIO_AUTH_TOKEN"
"""

import argparse
import base64
import hashlib
import hmac
import json
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

SAMPLES = Path(__file__).resolve().parents[1] / "backend/apps/integrations/sample_payloads"


def load(name):
    data = json.loads((SAMPLES / name).read_text())
    data.pop("_comment", None)
    return data


def post(url, body, content_type, headers=None):
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": content_type, **(headers or {})}
    )
    with urllib.request.urlopen(req) as resp:
        return resp.status, json.load(resp)


def multipart(fields):
    boundary = uuid.uuid4().hex
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'
        for k, v in fields.items()
    ]
    body = "".join(parts) + f"--{boundary}--\r\n"
    return body.encode(), f"multipart/form-data; boundary={boundary}"


def twilio_signature(token, url, params):
    payload = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    return base64.b64encode(
        hmac.new(token.encode(), payload.encode(), hashlib.sha1).digest()
    ).decode()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--sendgrid-token", default="dev-sendgrid-token")
    ap.add_argument("--twilio-token", default="dev-twilio-token")
    args = ap.parse_args()

    sg_url = f"{args.base}/api/webhooks/sendgrid/inbound/?token={args.sendgrid_token}"
    body, ctype = multipart(load("sendgrid_inbound.json"))
    for attempt in (1, 2):
        print("sendgrid", attempt, *post(sg_url, body, ctype))

    tw_url = f"{args.base}/api/webhooks/twilio/sms/"
    params = load("twilio_sms.json")
    sig = twilio_signature(args.twilio_token, tw_url, params)
    form = urllib.parse.urlencode(params).encode()
    for attempt in (1, 2):
        print(
            "twilio",
            attempt,
            *post(
                tw_url,
                form,
                "application/x-www-form-urlencoded",
                {"X-Twilio-Signature": sig},
            ),
        )


if __name__ == "__main__":
    main()

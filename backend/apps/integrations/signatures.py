import base64
import hashlib
import hmac


def twilio_signature(auth_token: str, url: str, params: dict[str, str]) -> str:
    """Twilio's X-Twilio-Signature: base64(HMAC-SHA1(token, url + sorted key/value pairs))."""
    payload = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    digest = hmac.new(auth_token.encode(), payload.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def valid_twilio_signature(auth_token: str, url: str, params: dict[str, str], header: str) -> bool:
    if not auth_token or not header:
        return False
    return hmac.compare_digest(twilio_signature(auth_token, url, params), header)

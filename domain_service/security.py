"""Small HS256 JWT and password helpers shared by the CrediMarket APIs."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

JWT_ISSUER = "credimarket"
JWT_TTL_SECONDS = 8 * 60 * 60
PASSWORD_ITERATIONS = 310_000


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return _b64(salt), _b64(digest)


def verify_password(password: str, salt: str, expected: str) -> bool:
    _, actual = hash_password(password, _unb64(salt))
    return hmac.compare_digest(actual, expected)


def issue_token(subject: str, role: str, customer_id: str | None = None) -> str:
    secret = os.getenv("JWT_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError("JWT_SECRET must contain at least 32 characters")
    now = int(time.time())
    payload = {"iss": JWT_ISSUER, "sub": subject, "role": role,
               "customer_id": customer_id, "iat": now, "exp": now + JWT_TTL_SECONDS}
    head = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{head}.{body}"
    signature = hmac.new(secret.encode(), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_b64(signature)}"


def verify_token(token: str) -> dict:
    secret = os.getenv("JWT_SECRET", "")
    if len(secret) < 32:
        raise ValueError("JWT secret is not configured")
    head, body, supplied = token.split(".")
    signing_input = f"{head}.{body}"
    expected = _b64(hmac.new(secret.encode(), signing_input.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(supplied, expected):
        raise ValueError("Invalid signature")
    header = json.loads(_unb64(head))
    claims = json.loads(_unb64(body))
    if header != {"alg": "HS256", "typ": "JWT"} or claims.get("iss") != JWT_ISSUER:
        raise ValueError("Invalid token issuer or algorithm")
    if int(claims.get("exp", 0)) <= int(time.time()):
        raise ValueError("Token expired")
    if not claims.get("sub") or claims.get("role") not in {"ADMIN", "CUSTOMER"}:
        raise ValueError("Invalid claims")
    return claims

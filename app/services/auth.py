# Heimdall API — auth JWT (patrón Glasir)
import hashlib
import hmac
import jwt
from datetime import datetime, timedelta, timezone

from ..config import JWT_SECRET, JWT_EXPIRATION_DAYS


def hash_password(pw: str) -> str:
    salt = hmac.new(JWT_SECRET.encode(), pw.encode(), hashlib.sha256).digest()
    return hmac.new(salt, pw.encode(), hashlib.sha256).hexdigest()


def verify_password(pw: str, stored: str) -> bool:
    return hmac.compare_digest(hash_password(pw), stored)


def create_token(user_id: int, email: str) -> str:
    payload = {
        "sub": str(user_id),
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRATION_DAYS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def decode_token(token: str):
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None

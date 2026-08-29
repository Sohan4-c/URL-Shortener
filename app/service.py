import hashlib
import secrets
import string
from datetime import datetime, timedelta, timezone
from botocore.exceptions import ClientError
from .config import settings
from .db import DynamoDBRepository

ALPHABET = string.ascii_letters + string.digits

class URLService:
    def __init__(self, repo=None):
        self.repo = repo or DynamoDBRepository()

    def generate_code(self, url: str) -> str:
        seed = f"{url}:{datetime.now(timezone.utc).timestamp()}:{secrets.token_hex(16)}".encode()
        digest = hashlib.sha256(seed).digest()
        number = int.from_bytes(digest, "big")
        chars = []
        while number and len(chars) < settings.short_code_length:
            number, remainder = divmod(number, 62)
            chars.append(ALPHABET[remainder])
        while len(chars) < settings.short_code_length:
            chars.append(secrets.choice(ALPHABET))
        return "".join(chars)

    def _expiry(self, ttl_days):
        if ttl_days is None:
            ttl_days = settings.default_ttl_days
        expires = datetime.now(timezone.utc) + timedelta(days=ttl_days)
        return expires, int(expires.timestamp())

    def create(self, original_url: str, custom_code=None, ttl_days=None):
        expires_at, ttl = self._expiry(ttl_days)
        code = custom_code or self.generate_code(original_url)

        for _ in range(5 if custom_code is None else 1):
            item = {
                "shortCode": code,
                "originalUrl": str(original_url),
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "expiresAt": expires_at.isoformat(),
                "ttl": ttl,
                "clickCount": 0,
                "isActive": True,
            }
            try:
                self.repo.put(item)
                return item
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                    raise
                if custom_code:
                    raise ValueError("Short code already exists")
                code = self.generate_code(original_url)

        raise RuntimeError("Unable to generate a unique short code")

    def get_url(self, code):
        item = self.repo.get(code)
        if not item:
            return None
        if not item.get("isActive", True):
            return {"deleted": True, "item": item}
        expires = datetime.fromisoformat(item["expiresAt"])
        if expires <= datetime.now(timezone.utc):
            return {"expired": True, "item": item}
        return {"item": item}

    def redirect(self, code):
        result = self.get_url(code)
        if result is None:
            return None, 404
        if result.get("deleted"):
            return None, 410
        if result.get("expired"):
            return None, 410
        item = result["item"]
        self.repo.increment_clicks(code)
        return item["originalUrl"], 307

    def stats(self, code):
        result = self.get_url(code)
        if result is None:
            return None
        item = result["item"]
        return {
            "short_code": code,
            "original_url": item["originalUrl"],
            "click_count": int(item.get("clickCount", 0)),
            "created_at": datetime.fromisoformat(item["createdAt"]),
            "expires_at": datetime.fromisoformat(item["expiresAt"]) if item.get("expiresAt") else None,
            "is_active": bool(item.get("isActive", True)) and not result.get("expired", False),
        }

    def delete(self, code):
        result = self.get_url(code)
        if result is None:
            return None
        if result.get("deleted"):
            return result["item"]
        return self.repo.delete(code)

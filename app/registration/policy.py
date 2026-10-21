"""Verification cryptography and limits; no database or transport dependencies."""

import hashlib
import hmac


class VerificationPolicy:
    CODE_TTL_SECONDS = 600
    RESEND_SECONDS = 60
    MAX_ATTEMPTS = 5
    MAX_EMAILS_PER_HOUR = 5

    def __init__(self, secret: str):
        self._secret = bytes.fromhex(secret)
        if len(self._secret) != 32:
            raise ValueError("A 32-byte verification secret is required.")

    def digest(self, user_id: int, nonce: str, code: str) -> str:
        return hmac.new(
            self._secret, f"{user_id}:{nonce}:{code}".encode(), hashlib.sha256
        ).hexdigest()

    def matches(self, stored_hash: str, user_id: int, nonce: str, code: str) -> bool:
        return hmac.compare_digest(stored_hash, self.digest(user_id, nonce, code))

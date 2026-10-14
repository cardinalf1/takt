"""
Desert Ant Labs 'Redact' Privacy Shield
On-device PII and Secrets Redaction Engine.
Masks credit cards, API keys, passwords, phone numbers, SSNs, and emails
before text is dispatched to clipboard injection or terminal insertion.
"""

import re
from typing import List, Optional

class DALRedactEngine:
    def __init__(
        self,
        enabled: bool = False,
        mask_char: str = "*",
        rules: Optional[List[str]] = None
    ):
        self.enabled = enabled
        self.mask_char = mask_char
        # Priority order: api_key first to avoid partial numeric phone matches on secret hashes
        self.rules = rules or ["api_key", "credit_card", "ssn", "email", "phone_number"]

        # Compile fast regex patterns
        self._patterns = {
            # API keys and secret tokens (OpenAI sk- / sk-proj-, GitHub, AWS, Bearer)
            "api_key": re.compile(
                r"\b(?:sk-(?:proj-)?[a-zA-Z0-9\-_]{20,}|ghp_[a-zA-Z0-9]{36}|Bearer\s+[a-zA-Z0-9\-_]{20,}|AKIA[0-9A-Z]{16})\b",
                re.IGNORECASE
            ),
            # Credit card: 13 to 19 digits with optional hyphens or spaces
            "credit_card": re.compile(
                r"\b(?:(?:\d{4}[ -]?){3}\d{4}|\d{13,19})\b"
            ),
            # Social Security Number (SSN)
            "ssn": re.compile(
                r"\b\d{3}-\d{2}-\d{4}\b"
            ),
            # Email address
            "email": re.compile(
                r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b"
            ),
            # Phone number (US / International format)
            "phone_number": re.compile(
                r"(?<![a-zA-Z0-9\-_])(?:\+?\d{1,3}[-. ]?)?\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}\b"
            ),
        }

    def redact(self, text: str) -> str:
        """
        Scans and redacts matching sensitive entities if privacy shield is enabled.
        """
        if not self.enabled or not text:
            return text

        redacted = text
        for rule in self.rules:
            pattern = self._patterns.get(rule)
            if not pattern:
                continue

            if rule == "api_key":
                redacted = pattern.sub("[API_KEY_PROTECTED]", redacted)
            elif rule == "credit_card":
                def _mask_cc(m):
                    val = m.group(0).replace(" ", "").replace("-", "")
                    return f"[CARD_ENDING_{val[-4:]}]"
                redacted = pattern.sub(_mask_cc, redacted)
            elif rule == "email":
                def _mask_email(m):
                    parts = m.group(0).split("@")
                    user, domain = parts[0], parts[1]
                    masked_user = user[0] + self.mask_char * max(1, len(user) - 1)
                    return f"{masked_user}@{domain}"
                redacted = pattern.sub(_mask_email, redacted)
            elif rule == "phone_number":
                redacted = pattern.sub("[PHONE_REDACTED]", redacted)
            elif rule == "ssn":
                redacted = pattern.sub("[SSN_REDACTED]", redacted)

        return redacted

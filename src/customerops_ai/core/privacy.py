"""Best-effort minimization for conversational storage; not a comprehensive PII detector."""

import re


def redact_sensitive(text: str) -> str:
    patterns = (
        (r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[email_redacted]"),
        (r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [credential_redacted]"),
        (r"\bsk-[A-Za-z0-9_-]{12,}\b", "[credential_redacted]"),
        (
            r"(?i)\b(password|api[_ -]?key|secret|authorization)\s*[:=]\s*\S+",
            r"\1=[credential_redacted]",
        ),
        (r"(?<!\w)\+\d[\d ().-]{8,}\d(?!\w)", "[phone_redacted]"),
        (r"(?<![\w-])\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?![\w-])", "[phone_redacted]"),
        (r"(?<![\w-])(?:\d[ -]?){13,19}(?![\w-])", "[payment_number_redacted]"),
    )
    for pattern, replacement in patterns:
        text = re.sub(pattern, replacement, text)
    return text

"""ID + clock helpers (port of ids.ts)."""

import secrets
import time

# Crockford-ish base32 alphabet (no l/o/u to avoid ambiguity) — matches ids.ts.
_ALPHABET = "0123456789abcdefghijkmnpqrstvwxyz"


def new_id(prefix: str) -> str:
    """A prefixed, URL-safe random id, e.g. ``agent_3f8k…`` (10 chars of entropy)."""
    suffix = "".join(_ALPHABET[b % len(_ALPHABET)] for b in secrets.token_bytes(10))
    return f"{prefix}_{suffix}"


def now_seconds() -> int:
    """Current unix time in whole seconds (all timestamps in the schema are seconds)."""
    return int(time.time())

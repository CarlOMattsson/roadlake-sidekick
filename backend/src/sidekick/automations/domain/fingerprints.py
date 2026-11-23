"""Keyed hashes of what the server must recognise again but never keep: a source reference, an MCP
session. One configured secret yields a separate key for each purpose, so no hash of one kind can
stand for another."""

import hashlib
import hmac

MIN_KEY_BYTES = 16
SOURCE_PURPOSE = "source"
DEDUPE_PURPOSE = "dedupe"
SESSION_PURPOSE = "session"


def derive_key(secret: str, purpose: str) -> bytes:
    """The key for one purpose, derived from the instance's secret."""

    label = f"sidekick.automations.{purpose}".encode()
    return hmac.new(secret.encode("utf-8"), label, hashlib.sha256).digest()


def keyed_hash(key: bytes, *parts: str) -> str:
    """HMAC-SHA256 over the parts, which cannot run into one another."""

    if len(key) < MIN_KEY_BYTES:
        raise ValueError("the hash key is too short")
    material = "\x00".join(parts).encode("utf-8")
    return hmac.new(key, material, hashlib.sha256).hexdigest()

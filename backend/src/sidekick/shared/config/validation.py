"""Secret and placeholder checks shared by the settings groups."""

from pydantic import SecretStr

PLACEHOLDER_PREFIXES = ("development-", "replace-with-")


def is_unusable_secret(value: str) -> bool:
    """True for a blank, whitespace-only or placeholder value (also when wrapped in whitespace).

    Judged on the stripped text so that padding cannot turn an empty value or a shipped
    placeholder into something that looks configured. Callers must never put `value` in a message.
    """

    stripped = value.strip()
    return not stripped or stripped.startswith(PLACEHOLDER_PREFIXES)


def secret_is_blank(secret: SecretStr | None) -> bool:
    return secret is None or not secret.get_secret_value().strip()

"""Encrypt or decrypt a stream with Fernet: stdin to stdout, the key from the environment.

Usage: python -I snapshot_crypto.py encrypt|decrypt   (run inside the api image, which already has `cryptography`)

The one implementation of the wire format of the encrypted database snapshots of deploy/selfhost/update.sh: the line
`SIDEKICK-SNAPSHOT-1`, then one authenticated Fernet token. The key is read from SIDEKICK_BACKUP_ENCRYPTION_KEY, or from
the file SIDEKICK_BACKUP_ENCRYPTION_KEY_FILE names (a Docker secret), never from the command line, and never printed. Nothing is written to stdout unless the whole input was processed, so a
wrong key or a damaged file produces no output at all. Fernet is not a streaming format, so the data is held in memory; a ceiling of MAX_PLAINTEXT_BYTES (512 MiB of
plaintext) keeps that bounded. Longer input is refused with an explicit message before anything is encrypted or written.
update.sh (its snapshots) and tools/work.sh (the work package's backups) both run this file.
"""

import os
import sys

MAGIC = b"SIDEKICK-SNAPSHOT-1\n"
MAX_PLAINTEXT_BYTES = 512 * 1024 * 1024
KEY_FILE_LIMIT = 4096
# A Fernet token is the plaintext padded, plus about 73 bytes of header and MAC, base64-encoded (4/3 growth).
MAX_TOKEN_BYTES = (MAX_PLAINTEXT_BYTES + 16 + 73) * 4 // 3 + 4


def read_key() -> bytes:
    """The key from the file named by SIDEKICK_BACKUP_ENCRYPTION_KEY_FILE, else from the environment variable.

    Both set, or a file over 4 KiB or empty, is refused (the message names the problem, never the key).
    """
    path = os.environ.get("SIDEKICK_BACKUP_ENCRYPTION_KEY_FILE", "")
    plain = os.environ.get("SIDEKICK_BACKUP_ENCRYPTION_KEY", "")
    if not path:
        return plain.strip().encode()
    if plain.strip():
        raise ValueError("SIDEKICK_BACKUP_ENCRYPTION_KEY and SIDEKICK_BACKUP_ENCRYPTION_KEY_FILE are both set")
    with open(path, "rb") as handle:
        data = handle.read(KEY_FILE_LIMIT + 1)
    if len(data) > KEY_FILE_LIMIT:
        raise ValueError("the key file is over the size limit")
    if not data.strip():
        raise ValueError("the key file is empty")
    return data.strip()


class TooLarge(ValueError):
    """The input is over the in-memory ceiling."""


def read_bounded(limit: int) -> bytes:
    data = sys.stdin.buffer.read(limit + 1)
    if len(data) > limit:
        raise TooLarge
    return data


def main(mode: str) -> int:
    from cryptography.fernet import Fernet

    try:
        key = read_key()
        if mode not in ("encrypt", "decrypt"):
            raise ValueError("mode must be encrypt or decrypt")
        raw = read_bounded(MAX_PLAINTEXT_BYTES if mode == "encrypt" else len(MAGIC) + MAX_TOKEN_BYTES)
        if mode == "encrypt":
            if not raw:
                raise ValueError("empty input")
            out = MAGIC + Fernet(key).encrypt(raw)
        elif mode == "decrypt":
            if not raw.startswith(MAGIC):
                raise ValueError("not a Sidekick snapshot")
            out = Fernet(key).decrypt(raw[len(MAGIC) :])
        else:
            raise ValueError("mode must be encrypt or decrypt")
    except TooLarge:
        limit_mib = MAX_PLAINTEXT_BYTES // (1024 * 1024)
        sys.stderr.write(f"backup {mode} refused: input is over the {limit_mib} MiB ceiling\n")
        return 1
    except Exception as error:  # the message is the exception type only: it may not quote data or the key
        sys.stderr.write(f"backup {mode} failed: {type(error).__name__}\n")
        return 1
    sys.stdout.buffer.write(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else ""))

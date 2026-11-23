"""The media store as one owner uses it: file names come from the owner's HMAC key.

`MediaStore` holds bytes under a 64-hex owner key it is given. This module derives that key from
an owner's id (`owner_media_key`), so no caller handles a key and the volume never names an owner.
A file that is read back is hashed again, so a file that was changed on disk is never served as
the photo it is named after. Nothing here logs.
"""

import hashlib
from collections.abc import Iterable
from pathlib import Path
from uuid import UUID

from sidekick.journal.domain.photo import owner_media_key
from sidekick.journal.infrastructure.media_store import MediaNotFoundError, MediaStore


class OwnerPhotoFiles:
    """Put, read and remove the photo files of owners, by owner id."""

    def __init__(self, store: MediaStore, secret: str) -> None:
        self._store = store
        self._secret = secret

    @classmethod
    def at(cls, directory: Path, secret: str) -> "OwnerPhotoFiles":
        return cls(MediaStore(directory), secret)

    def key_of(self, owner_id: UUID) -> str:
        return owner_media_key(self._secret, owner_id)

    def put(self, owner_id: UUID, data: bytes) -> str:
        """Store the bytes and return their SHA-256 digest. Storing them again is harmless."""

        return self._store.put(self.key_of(owner_id), data)

    def read(self, owner_id: UUID, digest: str) -> bytes:
        """The bytes of a file; `MediaNotFoundError` when it is missing or no longer matches."""

        data = self._store.read(self.key_of(owner_id), digest)
        if hashlib.sha256(data).hexdigest() != digest:
            raise MediaNotFoundError("photo file does not match its name")
        return data

    def remove(self, owner_id: UUID, digests: Iterable[str]) -> int:
        """Delete these files; how many were there. The caller has checked no row names them."""

        key = self.key_of(owner_id)
        return sum(1 for digest in set(digests) if self._store.remove(key, digest))

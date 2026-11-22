"""The strict last gate for a journal photo: container markers only, no image is ever decoded.

The client downscales and re-encodes a photo before it is sent, which also drops its metadata. This
module is the server's backstop for a client that did not. It reads the markers of a JPEG or WebP
file, checks type, dimensions and sizes, and **refuses** (never repairs) a file that

- carries metadata: a JPEG segment other than a plain JFIF header, scan data and the tables a
  decoder needs (so Exif, XMP, ICC profiles, comments and every other application segment), or a
  WebP EXIF, XMP or ICC chunk, or a WebP whose header announces one;
- is over the limits, is cut short, or has a header that lies about its own size;
- has bytes after the end of the image (a file that is also something else), or is an animation or
  a coding the browsers do not produce (arithmetic, lossless or hierarchical JPEG).

This is a last barrier against structured metadata, not a guarantee against a hostile client: bytes
hidden in scan data or in the values of quantisation and Huffman tables cannot be closed without
decoding the image, and nothing here tries to.

The parser never decodes pixels, never calls a third-party image library, never reads outside the
buffer and loops a bounded number of times: a JPEG scan is crossed with one regular expression in a
single pass, and a header has at most `_MAX_JPEG_MARKERS` markers.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum

from sidekick.shared.errors import ValidationError

JPEG = "image/jpeg"
WEBP = "image/webp"


@dataclass(frozen=True, slots=True)
class PhotoLimits:
    """Largest long edge in pixels and largest file in bytes that the gate lets through."""

    max_edge: int
    max_bytes: int


# What the owner decided: a photo is optimised on the client to at most 2048 px and 4 MiB.
PHOTO_LIMITS = PhotoLimits(max_edge=2048, max_bytes=4 * 1024 * 1024)
# The small picture shown in lists.
THUMBNAIL_LIMITS = PhotoLimits(max_edge=320, max_bytes=128 * 1024)


class PhotoRefusal(StrEnum):
    """Why a photo was refused; a fixed word, never a value from the file."""

    UNRECOGNISED = "unrecognised_type"
    CARRIES_METADATA = "carries_metadata"
    TOO_MANY_BYTES = "too_many_bytes"
    TOO_MANY_PIXELS = "too_many_pixels"
    TRUNCATED = "truncated"
    MALFORMED = "malformed"
    UNSUPPORTED = "unsupported"


class PhotoRefusedError(ValidationError):
    """A photo the gate refused. The text is a fixed refusal word, nothing from the file."""

    code = "photo_refused"
    safe_title = "Photo refused"

    def __init__(self, refusal: PhotoRefusal) -> None:
        super().__init__(refusal.value)
        self.refusal = refusal


@dataclass(frozen=True, slots=True)
class PhotoInfo:
    media_type: str
    width: int
    height: int
    byte_size: int


_MAX_JPEG_MARKERS = 512
_MAX_WEBP_CHUNKS = 3
_MAX_TABLES_PER_SEGMENT = 4
# `FF xx` where xx is a marker that can follow scan data: not 00 (a stuffed byte), not FF (fill),
# not D0-D7 (restart markers, which belong to the scan).
_SCAN_MARKER = re.compile(rb"\xff[\x01-\xcf\xd8-\xfe]")

_SOF_BASELINE_OR_PROGRESSIVE = frozenset({0xC0, 0xC1, 0xC2})
_DHT, _DQT, _DRI = 0xC4, 0xDB, 0xDD
_APP0, _SOS, _EOI = 0xE0, 0xDA, 0xD9
_JFIF_LENGTH = 14

_WEBP_METADATA_CHUNKS = frozenset({b"ICCP", b"EXIF", b"XMP "})
_WEBP_ANIMATION_CHUNKS = frozenset({b"ANIM", b"ANMF"})
_VP8X_FLAGS_METADATA = 0x04 | 0x08 | 0x20  # XMP, EXIF, ICC profile
_VP8X_FLAG_ANIMATION = 0x02
_VP8X_FLAGS_RESERVED = 0xC1


def _refuse(refusal: PhotoRefusal) -> PhotoRefusedError:
    return PhotoRefusedError(refusal)


def _check_dimensions(width: int, height: int, limits: PhotoLimits) -> None:
    if width < 1 or height < 1:
        raise _refuse(PhotoRefusal.MALFORMED)
    if max(width, height) > limits.max_edge:
        raise _refuse(PhotoRefusal.TOO_MANY_PIXELS)


def inspect_photo(data: bytes, limits: PhotoLimits = PHOTO_LIMITS) -> PhotoInfo:
    """The type and size of a JPEG or WebP photo that carries no metadata, or a refusal.

    Raises `PhotoRefusedError`; no other error comes out of a malformed file.
    """

    if len(data) > limits.max_bytes:
        raise _refuse(PhotoRefusal.TOO_MANY_BYTES)
    if data[:3] == b"\xff\xd8\xff":
        width, height = _inspect_jpeg(data, limits)
        return PhotoInfo(JPEG, width, height, len(data))
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        width, height = _inspect_webp(data, limits)
        return PhotoInfo(WEBP, width, height, len(data))
    raise _refuse(PhotoRefusal.UNRECOGNISED)


# JPEG ---------------------------------------------------------------------------------------


def _marker_at(data: bytes, pos: int) -> tuple[int, int]:
    """The marker code at `pos` (after any fill bytes) and the offset just past it."""

    size = len(data)
    if pos >= size:
        raise _refuse(PhotoRefusal.TRUNCATED)
    if data[pos] != 0xFF:
        raise _refuse(PhotoRefusal.MALFORMED)
    while pos < size and data[pos] == 0xFF:
        pos += 1
    if pos >= size:
        raise _refuse(PhotoRefusal.TRUNCATED)
    return data[pos], pos + 1


def _segment(data: bytes, pos: int) -> tuple[bytes, int]:
    """The payload of the length-prefixed segment at `pos` and the offset just past it."""

    if pos + 2 > len(data):
        raise _refuse(PhotoRefusal.TRUNCATED)
    length = int.from_bytes(data[pos : pos + 2], "big")
    if length < 2:
        raise _refuse(PhotoRefusal.MALFORMED)
    end = pos + length
    if end > len(data):
        raise _refuse(PhotoRefusal.TRUNCATED)
    return data[pos + 2 : end], end


def _check_jfif_header(payload: bytes) -> None:
    """Only a plain JFIF header without a thumbnail is allowed; anything else is data to refuse."""

    if (
        len(payload) != _JFIF_LENGTH
        or payload[:5] != b"JFIF\x00"
        or payload[12] != 0
        or payload[13] != 0
    ):
        raise _refuse(PhotoRefusal.CARRIES_METADATA)


def _read_frame(payload: bytes, limits: PhotoLimits) -> tuple[int, int]:
    if len(payload) < 6 or payload[0] != 8:
        raise _refuse(PhotoRefusal.MALFORMED)
    components = payload[5]
    if components not in (1, 3):
        raise _refuse(PhotoRefusal.UNSUPPORTED)
    if len(payload) != 6 + 3 * components:
        raise _refuse(PhotoRefusal.MALFORMED)
    height = int.from_bytes(payload[1:3], "big")
    width = int.from_bytes(payload[3:5], "big")
    _check_dimensions(width, height, limits)
    return width, height


def _check_quantisation_tables(payload: bytes) -> None:
    """DQT holds whole tables and nothing else, so it cannot carry a free-form payload."""

    pos = 0
    for _ in range(_MAX_TABLES_PER_SEGMENT + 1):
        if pos >= len(payload):
            break
        precision, identifier = payload[pos] >> 4, payload[pos] & 0x0F
        if precision > 1 or identifier > 3:
            raise _refuse(PhotoRefusal.MALFORMED)
        pos += 1 + 64 * (precision + 1)
    else:
        raise _refuse(PhotoRefusal.MALFORMED)
    if pos != len(payload) or not payload:
        raise _refuse(PhotoRefusal.MALFORMED)


def _check_huffman_tables(payload: bytes) -> None:
    """DHT holds whole tables (16 counts and that many symbols) and nothing else."""

    pos = 0
    for _ in range(_MAX_TABLES_PER_SEGMENT + 1):
        if pos >= len(payload):
            break
        if pos + 17 > len(payload) or payload[pos] >> 4 > 1 or payload[pos] & 0x0F > 3:
            raise _refuse(PhotoRefusal.MALFORMED)
        symbols = sum(payload[pos + 1 : pos + 17])
        if symbols > 256:
            raise _refuse(PhotoRefusal.MALFORMED)
        pos += 17 + symbols
    else:
        raise _refuse(PhotoRefusal.MALFORMED)
    if pos != len(payload) or not payload:
        raise _refuse(PhotoRefusal.MALFORMED)


def _check_table(code: int, payload: bytes) -> None:
    if code == _DQT:
        _check_quantisation_tables(payload)
    elif code == _DHT:
        _check_huffman_tables(payload)
    elif len(payload) != 2:  # DRI
        raise _refuse(PhotoRefusal.MALFORMED)


def _check_scan_header(payload: bytes) -> None:
    components = payload[0] if payload else 0
    if not 1 <= components <= 4 or len(payload) != 1 + 2 * components + 3:
        raise _refuse(PhotoRefusal.MALFORMED)


def _inspect_jpeg(data: bytes, limits: PhotoLimits) -> tuple[int, int]:
    pos = 2  # past SOI
    frame: tuple[int, int] | None = None
    scans = 0
    jfif_seen = False
    for _ in range(_MAX_JPEG_MARKERS):
        code, pos = _marker_at(data, pos)
        if code == _EOI:
            if frame is None or scans == 0:
                raise _refuse(PhotoRefusal.MALFORMED)
            if pos != len(data):
                raise _refuse(PhotoRefusal.MALFORMED)  # bytes after the image
            return frame
        if code == _APP0:
            payload, pos = _segment(data, pos)
            if jfif_seen or frame is not None:
                raise _refuse(PhotoRefusal.CARRIES_METADATA)
            _check_jfif_header(payload)
            jfif_seen = True
        elif code in (_DQT, _DHT, _DRI):
            payload, pos = _segment(data, pos)
            _check_table(code, payload)
        elif code in _SOF_BASELINE_OR_PROGRESSIVE:
            if frame is not None:
                raise _refuse(PhotoRefusal.MALFORMED)
            payload, pos = _segment(data, pos)
            frame = _read_frame(payload, limits)
        elif code == _SOS:
            if frame is None:
                raise _refuse(PhotoRefusal.MALFORMED)
            payload, pos = _segment(data, pos)
            _check_scan_header(payload)
            scans += 1
            found = _SCAN_MARKER.search(data, pos)
            if found is None:
                raise _refuse(PhotoRefusal.TRUNCATED)
            pos = found.start()
        elif code == 0xFE or 0xE1 <= code <= 0xEF:
            raise _refuse(PhotoRefusal.CARRIES_METADATA)  # comment or application segment
        else:
            raise _refuse(PhotoRefusal.UNSUPPORTED)
    raise _refuse(PhotoRefusal.MALFORMED)


# WebP ---------------------------------------------------------------------------------------


def _u16(data: bytes, pos: int) -> int:
    return int.from_bytes(data[pos : pos + 2], "little")


def _u24(data: bytes, pos: int) -> int:
    return int.from_bytes(data[pos : pos + 3], "little")


def _u32(data: bytes, pos: int) -> int:
    return int.from_bytes(data[pos : pos + 4], "little")


def _lossy_dimensions(body: bytes) -> tuple[int, int]:
    if len(body) < 10 or body[0] & 1 or body[3:6] != b"\x9d\x01\x2a":
        raise _refuse(PhotoRefusal.MALFORMED)  # not a key frame
    return _u16(body, 6) & 0x3FFF, _u16(body, 8) & 0x3FFF


def _lossless_dimensions(body: bytes) -> tuple[int, int]:
    if len(body) < 5 or body[0] != 0x2F:
        raise _refuse(PhotoRefusal.MALFORMED)
    bits = _u32(body, 1)
    if bits >> 29:
        raise _refuse(PhotoRefusal.UNSUPPORTED)  # a version this gate does not know
    return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1


def _read_extended_header(body: bytes, limits: PhotoLimits) -> tuple[int, int]:
    if len(body) != 10:
        raise _refuse(PhotoRefusal.MALFORMED)
    flags = body[0]
    if flags & _VP8X_FLAGS_METADATA:
        raise _refuse(PhotoRefusal.CARRIES_METADATA)
    if flags & _VP8X_FLAG_ANIMATION:
        raise _refuse(PhotoRefusal.UNSUPPORTED)
    if flags & _VP8X_FLAGS_RESERVED or any(body[1:4]):
        raise _refuse(PhotoRefusal.MALFORMED)
    width, height = _u24(body, 4) + 1, _u24(body, 7) + 1
    _check_dimensions(width, height, limits)
    return width, height


def _webp_chunks(data: bytes) -> Iterator[tuple[bytes, bytes]]:
    """Yield `(fourcc, body)` for each chunk, refusing a size that leaves the buffer."""

    size = len(data)
    if size < 20:
        raise _refuse(PhotoRefusal.TRUNCATED)
    declared = _u32(data, 4)
    if declared + 8 > size:
        raise _refuse(PhotoRefusal.TRUNCATED)
    if declared + 8 != size:
        raise _refuse(PhotoRefusal.MALFORMED)  # the header lies, or bytes follow the file
    pos = 12
    for _ in range(_MAX_WEBP_CHUNKS + 1):
        if pos == size:
            return
        if pos + 8 > size:
            raise _refuse(PhotoRefusal.TRUNCATED)
        length = _u32(data, pos + 4)
        end = pos + 8 + length
        padded = end + (length & 1)
        if padded > size:
            raise _refuse(PhotoRefusal.TRUNCATED)
        if length & 1 and data[end] != 0:
            raise _refuse(PhotoRefusal.MALFORMED)
        yield data[pos : pos + 4], data[pos + 8 : end]
        pos = padded
    raise _refuse(PhotoRefusal.MALFORMED)  # more chunks than a photo has


def _inspect_webp(data: bytes, limits: PhotoLimits) -> tuple[int, int]:
    canvas: tuple[int, int] | None = None
    image: tuple[int, int] | None = None
    alpha_seen = False
    for index, (fourcc, body) in enumerate(_webp_chunks(data)):
        if fourcc in _WEBP_METADATA_CHUNKS:
            raise _refuse(PhotoRefusal.CARRIES_METADATA)
        if fourcc in _WEBP_ANIMATION_CHUNKS:
            raise _refuse(PhotoRefusal.UNSUPPORTED)
        if fourcc == b"VP8X" and index == 0:
            canvas = _read_extended_header(body, limits)
        elif fourcc == b"ALPH" and canvas is not None and image is None and not alpha_seen:
            alpha_seen = True
        elif fourcc in (b"VP8 ", b"VP8L") and image is None:
            image = _lossy_dimensions(body) if fourcc == b"VP8 " else _lossless_dimensions(body)
            _check_dimensions(*image, limits)
        else:
            raise _refuse(PhotoRefusal.UNSUPPORTED)
    if image is None:
        raise _refuse(PhotoRefusal.MALFORMED)
    if canvas is not None and canvas != image:
        raise _refuse(PhotoRefusal.MALFORMED)  # the header lies about the picture
    return image

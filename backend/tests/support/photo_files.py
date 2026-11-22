"""Builders for JPEG and WebP files that are valid at the container level, and for hostile variants.

Nothing here encodes a picture: the scan data is a few arbitrary bytes, because the format gate
under test reads markers and never decodes. A builder gives a file the gate accepts; a test then
breaks one thing.
"""

import struct

GPS_EXIF = (
    b"Exif\x00\x00MM\x00*\x00\x00\x00\x08\x00\x01\x88\x25\x00\x04\x00\x00\x00\x01\x00\x00\x00\x1a"
    b"GPS 59.3293 N 18.0686 E"
)
XMP_PACKET = b"http://ns.adobe.com/xap/1.0/\x00<x:xmpmeta><exif:GPSLatitude>59.3</exif:GPSLatitude></x:xmpmeta>"


def segment(code: int, payload: bytes) -> bytes:
    return bytes([0xFF, code]) + (len(payload) + 2).to_bytes(2, "big") + payload


JFIF = segment(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")
QUANTISATION = segment(0xDB, b"\x00" + bytes(range(64)))
HUFFMAN = segment(0xC4, b"\x00" + bytes([0, 1] + [0] * 14) + b"\x05")
SCAN_DATA = b"\x12\x34\xff\x00\x56\xff\xd0\x78"


def frame(
    width: int, height: int, *, components: int = 3, code: int = 0xC0, depth: int = 8
) -> bytes:
    body = bytes([depth]) + struct.pack(">HH", height, width) + bytes([components])
    for index in range(components):
        body += bytes([index + 1, 0x11, 0])
    return segment(code, body)


def scan(components: int = 3) -> bytes:
    body = bytes([components])
    for index in range(components):
        body += bytes([index + 1, 0x00])
    return segment(0xDA, body + bytes([0, 63, 0]))


def jpeg(
    width: int = 640,
    height: int = 480,
    *,
    headers: tuple[bytes, ...] = (JFIF,),
    between: bytes = b"",
    entropy: bytes = SCAN_DATA,
    tail: bytes = b"",
    end: bool = True,
    **frame_options: int,
) -> bytes:
    """SOI, headers, tables, frame, scan, entropy data, optional `between` (before EOI) and EOI."""

    components = frame_options.get("components", 3)
    data = b"\xff\xd8" + b"".join(headers) + QUANTISATION + HUFFMAN
    data += frame(width, height, **frame_options) + scan(components) + entropy + between
    return data + (b"\xff\xd9" if end else b"") + tail


def progressive_jpeg() -> bytes:
    second = HUFFMAN + scan() + b"\x9a\xbc"
    return jpeg(code=0xC2, between=second)


def gps_jpeg() -> bytes:
    return jpeg(headers=(JFIF, segment(0xE1, GPS_EXIF)))


# WebP ---------------------------------------------------------------------------------------


def chunk(fourcc: bytes, body: bytes) -> bytes:
    return fourcc + struct.pack("<I", len(body)) + body + (b"\x00" if len(body) & 1 else b"")


def riff(*chunks: bytes) -> bytes:
    payload = b"WEBP" + b"".join(chunks)
    return b"RIFF" + struct.pack("<I", len(payload)) + payload


def lossy_body(width: int, height: int) -> bytes:
    return b"\x30\x01\x00\x9d\x01\x2a" + struct.pack("<HH", width, height) + b"\x00\x11\x22\x33"


def lossless_body(width: int, height: int) -> bytes:
    bits = (width - 1) | ((height - 1) << 14)
    return b"\x2f" + struct.pack("<I", bits) + b"\x07\x08\x09"


def vp8x_body(width: int, height: int, flags: int = 0) -> bytes:
    return (
        bytes([flags, 0, 0, 0])
        + (width - 1).to_bytes(3, "little")
        + (height - 1).to_bytes(3, "little")
    )


def lossy_webp(width: int = 640, height: int = 480) -> bytes:
    return riff(chunk(b"VP8 ", lossy_body(width, height)))


def lossless_webp(width: int = 640, height: int = 480) -> bytes:
    return riff(chunk(b"VP8L", lossless_body(width, height)))


def extended_webp(width: int = 640, height: int = 480, flags: int = 0x10, *extra: bytes) -> bytes:
    return riff(
        chunk(b"VP8X", vp8x_body(width, height, flags)),
        chunk(b"ALPH", b"\x00\x01\x02"),
        chunk(b"VP8 ", lossy_body(width, height)),
        *extra,
    )

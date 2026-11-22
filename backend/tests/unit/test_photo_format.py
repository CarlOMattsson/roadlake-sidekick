"""The photo format gate: accepts clean JPEG and WebP, refuses metadata and anything odd."""

import random
import time

import pytest

from sidekick.journal.domain.photo_format import (
    JPEG,
    PHOTO_LIMITS,
    THUMBNAIL_LIMITS,
    WEBP,
    PhotoInfo,
    PhotoLimits,
    PhotoRefusal,
    PhotoRefusedError,
    inspect_photo,
)
from tests.support import photo_files as files

R = PhotoRefusal


def refusal_of(data: bytes, limits: PhotoLimits = PHOTO_LIMITS) -> PhotoRefusal:
    with pytest.raises(PhotoRefusedError) as raised:
        inspect_photo(data, limits)
    return raised.value.refusal


# Accepted ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "media_type"),
    [
        (files.jpeg(), JPEG),
        (files.jpeg(headers=()), JPEG),
        (files.jpeg(components=1), JPEG),
        (files.progressive_jpeg(), JPEG),
        (files.jpeg(entropy=files.SCAN_DATA + b"\xff\xff\xff\xd0"), JPEG),
        (files.jpeg(headers=(files.JFIF, files.segment(0xDD, b"\x00\x10"))), JPEG),
        (files.lossy_webp(), WEBP),
        (files.lossless_webp(), WEBP),
        (files.extended_webp(), WEBP),
    ],
)
def test_a_clean_container_is_accepted(data: bytes, media_type: str) -> None:
    info = inspect_photo(data)
    assert info == PhotoInfo(media_type, 640, 480, len(data))


def test_the_edge_limit_is_inclusive_and_one_more_is_refused() -> None:
    assert inspect_photo(files.jpeg(2048, 1)).width == 2048
    assert inspect_photo(files.lossy_webp(1, 2048)).height == 2048
    assert refusal_of(files.jpeg(2049, 100)) is R.TOO_MANY_PIXELS
    assert refusal_of(files.lossless_webp(100, 2049)) is R.TOO_MANY_PIXELS


def test_the_thumbnail_limits_are_tighter() -> None:
    assert inspect_photo(files.jpeg(320, 240), THUMBNAIL_LIMITS).width == 320
    assert refusal_of(files.jpeg(321, 240), THUMBNAIL_LIMITS) is R.TOO_MANY_PIXELS


def test_the_byte_limit_is_inclusive_and_one_more_is_refused() -> None:
    base = files.jpeg()
    exact = files.jpeg(entropy=bytes(PHOTO_LIMITS.max_bytes - len(base) + len(files.SCAN_DATA)))
    assert len(exact) == PHOTO_LIMITS.max_bytes
    assert inspect_photo(exact).byte_size == PHOTO_LIMITS.max_bytes
    assert refusal_of(exact + b"\x00") is R.TOO_MANY_BYTES


# Metadata ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "header",
    [
        files.segment(0xE1, files.GPS_EXIF),
        files.segment(0xE1, files.XMP_PACKET),
        files.segment(0xE2, b"ICC_PROFILE\x00\x01\x01" + bytes(40)),
        files.segment(0xED, b"Photoshop 3.0\x008BIM"),
        files.segment(0xEE, b"Adobe\x00\x64\x00\x00\x00\x00\x01"),
        files.segment(0xEF, b"x"),
        files.segment(0xFE, b"a comment that names a place"),
        files.segment(0xE0, b"JFXX\x00\x10thumbnail"),
        files.segment(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x02\x02" + bytes(12)),
    ],
)
def test_a_jpeg_carrying_metadata_is_refused(header: bytes) -> None:
    assert refusal_of(files.jpeg(headers=(files.JFIF, header))) is R.CARRIES_METADATA
    assert refusal_of(files.jpeg(headers=(header,))) is R.CARRIES_METADATA


def test_a_second_jfif_header_is_refused() -> None:
    assert refusal_of(files.jpeg(headers=(files.JFIF, files.JFIF))) is R.CARRIES_METADATA


def test_metadata_hidden_after_the_scan_is_refused() -> None:
    exif = files.segment(0xE1, files.GPS_EXIF)
    assert refusal_of(files.jpeg(between=exif)) is R.CARRIES_METADATA
    assert (
        refusal_of(files.jpeg(code=0xC2, between=files.segment(0xFE, b"c"))) is R.CARRIES_METADATA
    )


@pytest.mark.parametrize("flag", [0x04, 0x08, 0x20])
def test_a_webp_that_announces_metadata_is_refused(flag: int) -> None:
    assert refusal_of(files.extended_webp(flags=flag)) is R.CARRIES_METADATA


@pytest.mark.parametrize("fourcc", [b"EXIF", b"XMP ", b"ICCP"])
def test_a_webp_metadata_chunk_is_refused_wherever_it_sits(fourcc: bytes) -> None:
    body = files.GPS_EXIF
    assert refusal_of(files.extended_webp(640, 480, 0x10, files.chunk(fourcc, body))) is (
        R.CARRIES_METADATA
    )
    before = files.riff(
        files.chunk(b"VP8X", files.vp8x_body(640, 480)),
        files.chunk(fourcc, body),
        files.chunk(b"VP8 ", files.lossy_body(640, 480)),
    )
    assert refusal_of(before) is R.CARRIES_METADATA
    assert refusal_of(files.riff(files.chunk(fourcc, body), files.chunk(b"VP8L", b"x"))) is (
        R.CARRIES_METADATA
    )


def test_an_animated_webp_is_refused() -> None:
    assert refusal_of(files.extended_webp(flags=0x02)) is R.UNSUPPORTED
    assert refusal_of(files.riff(files.chunk(b"ANMF", bytes(16)))) is R.UNSUPPORTED


# Lies, truncation and trailing bytes -----------------------------------------------------------


@pytest.mark.parametrize("data", [files.jpeg(), files.progressive_jpeg(), files.gps_jpeg()])
def test_every_truncated_prefix_of_a_jpeg_is_refused(data: bytes) -> None:
    for size in range(len(data)):
        assert refusal_of(data[:size]) in {
            R.TRUNCATED,
            R.UNRECOGNISED,
            R.MALFORMED,
            R.CARRIES_METADATA,
        }


@pytest.mark.parametrize("data", [files.lossy_webp(), files.lossless_webp(), files.extended_webp()])
def test_every_truncated_prefix_of_a_webp_is_refused(data: bytes) -> None:
    for size in range(len(data)):
        assert refusal_of(data[:size]) in {
            R.TRUNCATED,
            R.UNRECOGNISED,
            R.MALFORMED,
            R.CARRIES_METADATA,
        }


def test_a_jpeg_without_an_end_marker_is_truncated() -> None:
    assert refusal_of(files.jpeg(end=False)) is R.TRUNCATED


@pytest.mark.parametrize(
    "tail",
    [b"\x00", b"PK\x03\x04" + bytes(30), b"\x89PNG\r\n\x1a\n" + bytes(20), files.jpeg()],
)
def test_bytes_after_the_end_of_a_jpeg_are_refused(tail: bytes) -> None:
    assert refusal_of(files.jpeg(tail=tail)) is R.MALFORMED


def test_a_polyglot_with_an_archive_in_front_is_not_a_photo() -> None:
    assert refusal_of(b"PK\x03\x04" + files.jpeg()) is R.UNRECOGNISED
    assert refusal_of(b"GIF89a" + files.jpeg()) is R.UNRECOGNISED


def test_a_riff_size_that_lies_is_refused() -> None:
    data = bytearray(files.lossy_webp())
    declared = int.from_bytes(data[4:8], "little")
    data[4:8] = (declared + 1).to_bytes(4, "little")
    assert refusal_of(bytes(data)) is R.TRUNCATED
    data[4:8] = (declared - 2).to_bytes(4, "little")
    assert refusal_of(bytes(data)) is R.MALFORMED
    assert refusal_of(files.lossy_webp() + b"\x00\x00") is R.MALFORMED
    data[4:8] = b"\xff\xff\xff\xff"
    assert refusal_of(bytes(data)) is R.TRUNCATED


def test_a_webp_chunk_size_that_leaves_the_buffer_is_refused() -> None:
    data = bytearray(files.lossy_webp())
    data[16:20] = b"\xff\xff\xff\xff"
    assert refusal_of(bytes(data)) is R.TRUNCATED


def test_a_webp_that_says_one_size_and_holds_another_is_refused() -> None:
    lying = files.riff(
        files.chunk(b"VP8X", files.vp8x_body(100, 100)),
        files.chunk(b"VP8 ", files.lossy_body(2000, 2000)),
    )
    assert refusal_of(lying) is R.MALFORMED


def test_a_webp_padding_byte_must_be_zero() -> None:
    body = files.lossless_body(10, 10) + b"\x00"  # an odd length, so the chunk is padded
    clean = files.riff(files.chunk(b"VP8L", body))
    assert inspect_photo(clean).width == 10
    dirty = bytearray(clean)
    dirty[-1] = 0x41
    assert refusal_of(bytes(dirty)) is R.MALFORMED


# Dimension bombs and odd structure -------------------------------------------------------------


def test_a_dimension_bomb_is_refused_before_anything_else_is_read() -> None:
    assert refusal_of(files.jpeg(65535, 65535)) is R.TOO_MANY_PIXELS
    assert refusal_of(files.riff(files.chunk(b"VP8X", files.vp8x_body(1 << 24, 1 << 24)))) is (
        R.TOO_MANY_PIXELS
    )
    assert refusal_of(files.lossless_webp(16384, 16384)) is R.TOO_MANY_PIXELS
    assert refusal_of(files.lossy_webp(16383, 1)) is R.TOO_MANY_PIXELS


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (files.jpeg(0, 480), R.MALFORMED),
        (files.jpeg(640, 0), R.MALFORMED),
        (files.jpeg(depth=12), R.MALFORMED),
        (files.jpeg(components=4), R.UNSUPPORTED),
        (files.jpeg(code=0xC3), R.UNSUPPORTED),
        (files.jpeg(code=0xC9), R.UNSUPPORTED),
        (files.jpeg(code=0xC7), R.UNSUPPORTED),
        (files.jpeg(headers=(files.segment(0xF5, b"x"),)), R.UNSUPPORTED),
        (files.jpeg(headers=(files.segment(0xDC, b"\x01\x00"),)), R.UNSUPPORTED),
        (files.jpeg(headers=(b"\xff\x02",)), R.UNSUPPORTED),
        (files.jpeg(headers=(b"\xff\xd0",)), R.UNSUPPORTED),
        (files.jpeg(headers=(b"\xff\xd8",)), R.UNSUPPORTED),
        (files.jpeg(headers=(files.segment(0xDB, b"\x00" + bytes(10)),)), R.MALFORMED),
        (files.jpeg(headers=(files.segment(0xC4, bytes([0] + [255] * 16)),)), R.MALFORMED),
        (files.jpeg(headers=(files.segment(0xDD, b"\x00"),)), R.MALFORMED),
        (b"\xff\xd8\xff", R.TRUNCATED),
        (b"\xff\xd8\xff\xd9", R.MALFORMED),
    ],
)
def test_a_malformed_or_unsupported_jpeg_is_refused(data: bytes, expected: PhotoRefusal) -> None:
    assert refusal_of(data) is expected


def test_a_segment_with_more_tables_than_a_photo_needs_is_refused() -> None:
    table = b"\x00" + bytes(64)
    assert inspect_photo(files.jpeg(headers=(files.segment(0xDB, table * 4),))).width == 640
    assert refusal_of(files.jpeg(headers=(files.segment(0xDB, table * 5),))) is R.MALFORMED
    huffman = b"\x00" + bytes(16)
    assert inspect_photo(files.jpeg(headers=(files.segment(0xC4, huffman * 4),))).width == 640
    assert refusal_of(files.jpeg(headers=(files.segment(0xC4, huffman * 5),))) is R.MALFORMED


def test_a_scan_before_the_frame_is_refused() -> None:
    data = b"\xff\xd8" + files.scan() + b"\x00\xff\xd9"
    assert refusal_of(data) is R.MALFORMED


def test_a_second_frame_is_refused() -> None:
    assert refusal_of(files.jpeg(headers=(files.frame(10, 10),))) is R.MALFORMED


def test_a_jpeg_without_a_scan_is_refused() -> None:
    data = b"\xff\xd8" + files.QUANTISATION + files.frame(10, 10) + b"\xff\xd9"
    assert refusal_of(data) is R.MALFORMED


@pytest.mark.parametrize("length", [0, 1])
def test_a_segment_length_below_its_own_size_is_refused(length: int) -> None:
    data = b"\xff\xd8\xff\xdb" + length.to_bytes(2, "big") + bytes(20)
    assert refusal_of(data) is R.MALFORMED


def test_a_segment_longer_than_the_file_is_truncated() -> None:
    assert refusal_of(b"\xff\xd8\xff\xdb\xff\xff" + bytes(20)) is R.TRUNCATED


def test_a_frame_whose_length_does_not_match_its_components_is_refused() -> None:
    bad = files.segment(0xC0, bytes([8, 1, 224, 2, 128, 3]) + bytes(3))
    assert refusal_of(b"\xff\xd8" + bad + files.scan() + b"\xff\xd9") is R.MALFORMED


def test_a_flood_of_markers_stops_at_the_bound() -> None:
    flood = files.segment(0xDD, b"\x00\x10") * 600
    assert refusal_of(files.jpeg(headers=(flood,))) is R.MALFORMED


def test_a_flood_of_chunks_stops_at_the_bound() -> None:
    flood = files.chunk(b"ALPH", b"ab") * 50
    data = files.riff(files.chunk(b"VP8X", files.vp8x_body(10, 10, 0x10)), flood)
    assert refusal_of(data) in {R.UNSUPPORTED, R.MALFORMED}


def _lossy(body: bytes) -> bytes:
    return files.riff(files.chunk(b"VP8 ", body))


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (_lossy(b"\x31\x01\x00\x9d\x01\x2a" + bytes(8)), R.MALFORMED),  # not a key frame
        (_lossy(b"\x30\x01\x00\x00\x00\x00" + bytes(8)), R.MALFORMED),  # no start code
        (_lossy(b"\x30\x01"), R.MALFORMED),
        (_lossy(files.lossy_body(0, 5)), R.MALFORMED),
        (files.riff(files.chunk(b"VP8L", b"\x00" + bytes(8))), R.MALFORMED),  # wrong signature
        (files.riff(files.chunk(b"VP8L", b"\x2f")), R.MALFORMED),
        (files.riff(files.chunk(b"VP8L", b"\x2f\x00\x00\x00\x20" + bytes(4))), R.UNSUPPORTED),
        (files.riff(files.chunk(b"JUNK", b"abcd")), R.UNSUPPORTED),
        (files.riff(files.chunk(b"ALPH", b"ab")), R.UNSUPPORTED),
        (files.riff(files.chunk(b"VP8 ", files.lossy_body(10, 10)) * 2), R.UNSUPPORTED),
        (files.riff(files.chunk(b"VP8X", b"short")), R.MALFORMED),
        (files.riff(files.chunk(b"VP8X", files.vp8x_body(10, 10, 0xC0))), R.MALFORMED),
        (files.riff(files.chunk(b"VP8X", files.vp8x_body(10, 10))), R.MALFORMED),  # no image
        (files.riff(), R.TRUNCATED),
    ],
)
def test_a_malformed_webp_is_refused(data: bytes, expected: PhotoRefusal) -> None:
    assert refusal_of(data) is expected


@pytest.mark.parametrize(
    "data", [b"", b"\x00", b"GIF89a" + bytes(30), b"\x89PNG\r\n\x1a\n" + bytes(30)]
)
def test_other_types_are_not_photos(data: bytes) -> None:
    assert refusal_of(data) is R.UNRECOGNISED


def test_riff_that_is_not_webp_is_not_a_photo() -> None:
    assert refusal_of(b"RIFF\x24\x00\x00\x00WAVEfmt " + bytes(32)) is R.UNRECOGNISED


# The refusal itself ----------------------------------------------------------------------------


def test_the_refusal_is_a_fixed_word_that_holds_nothing_of_the_file() -> None:
    with pytest.raises(PhotoRefusedError) as raised:
        inspect_photo(files.gps_jpeg())
    error = raised.value
    assert str(error) == "carries_metadata"
    assert error.code == "photo_refused"
    assert error.http_status == 422
    assert "GPS" not in repr(error) and "59.3" not in repr(error)


# Fuzzing ---------------------------------------------------------------------------------------

SEEDS = {
    "baseline": files.jpeg(),
    "progressive": files.progressive_jpeg(),
    "gray": files.jpeg(components=1),
    "gps": files.gps_jpeg(),
    "xmp": files.jpeg(headers=(files.JFIF, files.segment(0xE1, files.XMP_PACKET))),
    "lossy": files.lossy_webp(),
    "lossless": files.lossless_webp(),
    "extended": files.extended_webp(),
    "exif_chunk": files.extended_webp(640, 480, 0x18, files.chunk(b"EXIF", files.GPS_EXIF)),
}


def _assert_gate_outcome(data: bytes) -> None:
    """Whatever the bytes, the gate returns a photo within the limits or raises its own refusal."""

    try:
        info = inspect_photo(data)
    except PhotoRefusedError:
        return
    assert info.media_type in {JPEG, WEBP}
    assert 1 <= info.width <= PHOTO_LIMITS.max_edge
    assert 1 <= info.height <= PHOTO_LIMITS.max_edge
    assert info.byte_size == len(data) <= PHOTO_LIMITS.max_bytes


@pytest.mark.parametrize("name", sorted(SEEDS))
def test_fuzz_every_single_byte_mutation_ends_in_a_photo_or_a_refusal(name: str) -> None:
    seed = SEEDS[name]
    for position in range(len(seed)):
        for value in (0x00, 0x01, 0x7F, 0x80, 0xFF, seed[position] ^ 0x01):
            mutated = bytearray(seed)
            mutated[position] = value
            _assert_gate_outcome(bytes(mutated))
            if name in {"gps", "xmp", "exif_chunk"}:
                try:
                    inspect_photo(bytes(mutated))
                except PhotoRefusedError:
                    continue
                pytest.fail(f"{name}: a one-byte change at {position} let metadata through")


@pytest.mark.parametrize("name", sorted(SEEDS))
def test_fuzz_random_mutations_and_splices_end_in_a_photo_or_a_refusal(name: str) -> None:
    rng = random.Random(f"photo-{name}")  # noqa: S311 - a fixed seed makes the corpus repeatable
    seed = SEEDS[name]
    others = [value for key, value in sorted(SEEDS.items()) if key != name]
    for _ in range(1500):
        data = bytearray(seed)
        for _ in range(rng.randint(1, 8)):
            if not data:
                break
            kind = rng.randrange(4)
            position = rng.randrange(len(data))
            if kind == 0:
                data[position] = rng.randrange(256)
            elif kind == 1:
                del data[position : position + rng.randint(1, 12)]
            elif kind == 2:
                data[position:position] = bytes(
                    rng.randrange(256) for _ in range(rng.randint(1, 12))
                )
            else:
                donor = rng.choice(others)
                start = rng.randrange(len(donor))
                data[position:position] = donor[start : start + rng.randint(1, 40)]
        _assert_gate_outcome(bytes(data))


def test_fuzz_random_bytes_behind_a_valid_signature() -> None:
    rng = random.Random("photo-noise")  # noqa: S311
    for _ in range(2000):
        noise = bytes(rng.randrange(256) for _ in range(rng.randint(0, 200)))
        _assert_gate_outcome(b"\xff\xd8\xff" + noise)
        _assert_gate_outcome(b"RIFF" + noise[:4].ljust(4, b"\x00") + b"WEBP" + noise)


def test_a_large_hostile_buffer_is_judged_in_bounded_time() -> None:
    start = time.monotonic()
    for hostile in (
        b"\xff\xd8\xff" + b"\xff" * (3 * 1024 * 1024),
        files.jpeg(entropy=b"\xff\x00" * (2 * 1024 * 1024)),
        files.jpeg(entropy=b"\xff\xd0" * (2 * 1024 * 1024)),
        files.jpeg(entropy=b"\xff" * (3 * 1024 * 1024)),
        files.jpeg(headers=(files.JFIF, b"\xff" * (3 * 1024 * 1024))),
    ):
        _assert_gate_outcome(hostile)
    assert time.monotonic() - start < 5

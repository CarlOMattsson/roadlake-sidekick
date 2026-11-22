# ADR-014: Journal photos are content-addressed files with metadata in PostgreSQL

- Status: Accepted (D-098, 2026-11-22)
- Date: 2026-11-22
- Owners: Sidekick application maintainers

## Context

A journal entry or a journal day can carry photos the owner adds. Sidekick needs a storage model that the backup, export, restore and
trash paths can carry, and that does not bring an image decoder into the backend. Photos are private: they may carry location and
device metadata, and they must never leak into logs or memory. This is independent of the automations in ADR-013.

## Decision

### Metadata in PostgreSQL, blobs on a volume

- Metadata lives in `journal_attachments`, owner-scoped with the same composite-key pattern as the other tables. A photo belongs to
  exactly one of a journal entry or a journal day (a CHECK). It holds the media type (`image/jpeg` or `image/webp`), byte size (at most
  4 MiB), width and height (at most 4096), the SHA-256 digest of the stored bytes, a thumbnail digest and size (thumbnail at most
  320 px and 128 KiB), optional alt text with who wrote it (`you` or `claude`), an optional `taken_at` only when the client sends it, a
  position and the usual version and timestamps. GPS and EXIF are never stored.
- Blobs are immutable files on a `media` volume, mounted read-write in `api` and read-only in `backup`, at
  `<owner-hmac>/<aa>/<sha256>`. They are named by content, so the same bytes are stored once.
- A write is a temporary file, fsync, rename, and then the row INSERT in one transaction. A crash can leave an orphan file. A sweep
  removes files that have no row and are older than 24 hours, and never removes a file that a retained backup lists.

### No server-side decoding

- The client optimises the image before upload: it downscales and re-encodes it to a long edge of at most 2048 px and at most 4 MiB
  (JPEG or WebP), which also strips metadata, and sends the thumbnail. The MCP App does this with a canvas and the Android app with a
  bitmap. A larger photo is optimised, not refused, on the client.
- The server never decodes an image. A small pure parser reads only container markers. It checks the type, the dimensions and the
  sizes and **refuses** a JPEG APP1 segment (Exif and XMP) and WebP EXIF and XMP chunks, anything over the limits, a truncated file or a
  header that lies about its size. The server's strict parser is the backstop: it refuses what a client should already have removed,
  so location data cannot be stored even by a client that does not strip it. The parser has a fuzz corpus that includes a GPS-tagged
  JPEG, an XMP packet, a truncated file, a dimension bomb and polyglot files.
- That canvas and bitmap re-encoding drops metadata is ASSUMED until a test with a GPS-tagged JPEG shows it.

### Trash and erasure

- A photo is a trashable record kind. It is hidden while its entry is in the trash and comes back with the entry.
- Emptying the trash erases trashed photos and the photos of trashed entries: the rows and, once no row refers to them, the blobs. The
  entry row stays, as today. This is the one place where journal content can be erased, and it is the owner's decision (Q6, D-098). The
  runtime role gets DELETE on this table only.

### Backup, export and restore

- The owner backup JSON lists the attachment rows. The blobs go into a sibling directory, one encrypted token per blob (each at most
  4 MiB, so the in-memory model of the bundle still holds). The backup is incremental by digest, so the 512 MiB bundle ceiling applies to
  records only.
- Update snapshots stay as they are: they are database dumps only, because no migration touches blobs.
- Restore restores the media archive, and an admin command hashes every referenced blob and reports a mismatch.
- The owner export gains a format with a directory or archive holding the export file and `media/<sha256>.<ext>`.

### Memory and logs

- Photos and alt text are never sent to Hindsight. ADR-008's closed document set cannot represent them, and a test pins that.
- Logs carry the kind, byte counts and the outcome. They never carry bytes, alt text, dimensions tied to an id, or digests.

### Upload and display

- Android uploads through a companion multipart endpoint under `companion:journal:write`. The MCP App uses an app-only
  `add_journal_photo` that takes base64; the size a host allows in one tool call is OPEN and decides whether a thumbnail
  and the photo go in one call or two. Through Claude's own chat attachments is OPEN: a model is assumed unable to pass the bytes of an
  attachment into a tool argument.
- Display uses an app-only `get_journal_photo(id, size)` that returns base64 through the host, because the MCP App has no direct
  channel (D-088). Updating alt text and position is app-only; removal goes through the existing trash tools.
- Face photos come only from images the owner adds. Fetching photos from Slack is later and needs its own decision.

## Alternatives rejected

- **`bytea` in PostgreSQL:** the backup bundle and the update snapshot both hold their data in memory under a 512 MiB ceiling, which
  photos would pass within about a year.
- **An S3-compatible store:** a new dependency for every self-hosted installation.
- **Server-side decoding with Pillow:** image decoders are attack surface and bring a steady stream of security fixes.
- **Refusing photos that are too large:** the client optimises them instead; refusal stays only as the server's backstop.
- **Sending photos or alt text to memory:** never, by decision.

## Consequences

- The backup and export formats and the restore script depend on content-addressed blobs; changing the addressing later is a data
  migration.
- Each retained backup pins the blobs it lists, so disk use can exceed the live set until old backups are rotated.
- A client that does not strip metadata gets a clear refusal rather than a stored location.
- The journal record gains an additive attachment summary (a count and ids) and the contract review covers it.
- Customers who add no photos run no new process; the `media` volume is empty.

## Evidence

Planned. The implementation lands after this record; the section is completed with the paths when they exist.

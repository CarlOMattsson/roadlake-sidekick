"""The tool annotations every curated tool shares, defined once.

`READ` is a read-only tool, `WRITE` an idempotent non-destructive write and `DESTRUCTIVE` a write a
host may ask before running (it discards or consumes something).
"""

READ = {
    "readOnlyHint": True,
    "openWorldHint": False,
    "destructiveHint": False,
    "idempotentHint": True,
}
WRITE = {
    "readOnlyHint": False,
    "openWorldHint": False,
    "destructiveHint": False,
    "idempotentHint": True,
}
DESTRUCTIVE = {
    "readOnlyHint": False,
    "openWorldHint": False,
    "destructiveHint": True,
    "idempotentHint": True,
}

/**
 * Idempotency keys for durable writes. One key belongs to one user action: retrying the same
 * action (same target, version and changes) reuses its key so the server replays the result
 * instead of writing twice. Any different action, including the same change against a newer
 * version after a reload, gets a fresh key.
 */
export type PendingKey = { signature: string; key: string };

export function keyFor(
  pending: PendingKey | undefined,
  signature: string,
): PendingKey {
  if (pending?.signature === signature) return pending;
  return { signature, key: newIdempotencyKey() };
}

/** RFC 4122 version 4 from getRandomValues, which also works outside secure contexts. */
function newIdempotencyKey(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6]! & 0x0f) | 0x40;
  bytes[8] = (bytes[8]! & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0"));
  return [
    hex.slice(0, 4).join(""),
    hex.slice(4, 6).join(""),
    hex.slice(6, 8).join(""),
    hex.slice(8, 10).join(""),
    hex.slice(10, 16).join(""),
  ].join("-");
}

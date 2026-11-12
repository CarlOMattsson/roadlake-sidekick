/**
 * What one hand-written entry may weigh. The backend accepts 1 to 100 000 characters of text and 200 of title
 * (`WriteEntryBody`, `UpdateEntryBody`), but it also caps the whole JSON body of a journal write at 256 KiB
 * (`MAX_JOURNAL_BODY_BYTES`), and the Android companion (`RequestPolicy.MAX_BODY_BYTES`) refuses the same size. Both
 * count bytes, so å/ä/ö (2 bytes), emoji (4 bytes) and escaped newlines or quotes (2 bytes) use the budget faster than
 * ASCII does. The form measures the body it will send, so it never lets through what a lower layer would refuse.
 */
export const TITLE_MAX = 200;
export const TEXT_MAX = 100_000;
/** Keep in step with `MAX_JOURNAL_BODY_BYTES` in backend/src/sidekick/api/companion_rooms.py and `RequestPolicy.MAX_BODY_BYTES`. */
export const BODY_MAX_BYTES = 256 * 1024;
/** Room for the date, the idempotency key, the version and the JSON keys around the title and text. */
const ENVELOPE_BYTES = 2 * 1024;

const encoder = new TextEncoder();

function jsonBytes(value: string): number {
  return encoder.encode(JSON.stringify(value)).length;
}

/** True when the title and text, as they will be written in the JSON body, fit in what the layers below accept. */
export function entryFitsBody(title: string, text: string): boolean {
  return jsonBytes(title) + jsonBytes(text) <= BODY_MAX_BYTES - ENVELOPE_BYTES;
}

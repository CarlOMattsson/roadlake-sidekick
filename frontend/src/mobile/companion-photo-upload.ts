/**
 * The Journal room's photo upload on the phone (ADR-014). The room calls the app-only `add_journal_photo` with the
 * shrunk photo and thumbnail as base64, as it does in Claude; the phone cannot send that as JSON (the companion route
 * takes a multipart form), so the transport hands the same fields to the native side, which builds the form and sends
 * it with the credential (`SidekickNative.uploadJournalPhoto`). No path, header or URL is chosen here, and nothing is
 * queued: a photo needs the network, and the room keeps the file and the key to try again.
 *
 * Only a photo on a day (`journal_date`) is taken for now. Arguments outside the closed list are refused before
 * anything is sent.
 */
import { dateOf, type Args, type PlanHelpers } from "./companion-plan";
import type { PhotoUploadOptions } from "./sidekick-native";

const KEYS = [
  "journal_date",
  "photo",
  "thumbnail",
  "alt_text",
  "idempotency_key",
] as const;
const BASE64 = /^[A-Za-z0-9+/]+={0,2}$/;
/** The server's own limit on a caption (MAX_ALT_TEXT). */
const CAPTION_MAX = 500;

/** What the native side is asked to send for one `add_journal_photo` call, or the closed `validation_error`. */
export function photoUploadOf(args: Args, h: PlanHelpers): PhotoUploadOptions {
  h.onlyKeys(args, KEYS);
  const journalDate = dateOf(args.journal_date, h);
  const { photo, thumbnail, alt_text: altText, idempotency_key: key } = args;
  if (
    typeof photo !== "string" ||
    !BASE64.test(photo) ||
    typeof thumbnail !== "string" ||
    !BASE64.test(thumbnail) ||
    typeof key !== "string" ||
    key.length < 8 ||
    (altText !== undefined &&
      altText !== null &&
      (typeof altText !== "string" || altText.length > CAPTION_MAX))
  )
    return h.invalid();
  return {
    journalDate,
    photo,
    thumbnail,
    ...(typeof altText === "string" && altText ? { altText } : {}),
    idempotencyKey: key,
  };
}

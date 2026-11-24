/**
 * The Journal room's photo calls (ADR-014): adding a photo to a day and reading one back as thumbnail or as the full
 * file. Both tools are app-only and answer the app with base64; the phone answers them with its own routes. Offered
 * only where the host answers them; the transport leaves them out otherwise, and the day shows no photo block.
 */
import type {
  JournalPhotoRecord,
  ToolResults,
} from "../../lib/mcp/tool-results.generated";
import type { RoomTransport } from "../mcp-apps/room-types";

export type { JournalPhotoRecord };

/** The photo and thumbnail the client made (photo-shrink.ts) and the words the owner gave, for one day. */
export type PhotoUpload = {
  journalDate: string;
  /** Base64 of the shrunk JPEG. */
  photo: string;
  thumbnail: string;
  altText?: string;
};

export type PhotoFile = {
  photo: JournalPhotoRecord;
  /** Base64 of the thumbnail or of the file, no `data:` prefix. */
  data: string;
};

/**
 * One tool call carries the photo and its thumbnail as base64, and the server reads at most 1 MiB of it: 600 KiB of
 * photo and at most 128 KiB of thumbnail make about 970 KiB of base64.
 */
export const TOOL_CALL_PHOTO_BYTES = 600 * 1024;

/** What a day read carries of its photos: the ids of those on the day itself; an older server sends none. */
export type DayPhotoIds = {
  day_attachments?: ToolResults["get_journal_day"]["day_attachments"];
};

export type PhotoTransport = {
  /** The most bytes of photo this host takes in one call; the day shrinks the picture to it. */
  maxPhotoBytes?: () => number;
  /** Adds a photo to a day (add_journal_photo). Absent: the day offers no photos. */
  addDayPhoto?: (
    input: PhotoUpload,
    idempotencyKey: string,
  ) => Promise<{ photo: JournalPhotoRecord }>;
  /** One photo's thumbnail or full file (get_journal_photo). */
  readPhoto?: (id: string, size: "thumb" | "photo") => Promise<PhotoFile>;
};

/** The photo calls over the host's tools/call, or nothing when the host does not answer both of them. */
export function createPhotoTransport(
  call: RoomTransport["call"],
  enabled: boolean,
): PhotoTransport {
  if (!enabled) return {};
  return {
    maxPhotoBytes: () => TOOL_CALL_PHOTO_BYTES,
    addDayPhoto: (input, idempotencyKey) =>
      call<ToolResults["add_journal_photo"]>("add_journal_photo", {
        journal_date: input.journalDate,
        photo: input.photo,
        thumbnail: input.thumbnail,
        ...(input.altText ? { alt_text: input.altText } : {}),
        idempotency_key: idempotencyKey,
      }),
    readPhoto: (id, size) =>
      call<ToolResults["get_journal_photo"]>("get_journal_photo", {
        photo_id: id,
        size,
      }).then(({ photo, data }) => ({ photo, data })),
  };
}

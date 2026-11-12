import { ROOM_IDS, type RoomId } from "./router";

/**
 * The rooms this instance shows. It is a Sidekick setting, SIDEKICK_ENABLED_ROOMS, which the backend writes
 * into the app document as `<meta name="sidekick-rooms" content="work,journal">`. A room that is off has no tools
 * on the server, so the app leaves it out of its navigation and draws no link to it. Its data is kept.
 * Every room when the meta is missing (a host that does not declare it, or an older server on the phone) and
 * "work" always, since an instance cannot do without it. Read at call time, like `appLocale`.
 */
export function enabledRooms(doc: Document = document): readonly RoomId[] {
  const declared = doc.querySelector<HTMLMetaElement>(
    'meta[name="sidekick-rooms"]',
  )?.content;
  if (declared === undefined) return ROOM_IDS;
  const named = declared.split(",").map((name) => name.trim());
  return ROOM_IDS.filter((room) => room === "work" || named.includes(room));
}

/**
 * Declares the rooms in the document, as the backend does in the app document. The phone has no such document, so it
 * writes the same meta from the server's `enabled_rooms` and every `roomEnabled` reads it. `undefined` (the server did
 * not say) removes the meta: every room.
 */
export function declareEnabledRooms(
  rooms: readonly string[] | undefined,
  doc: Document = document,
): void {
  let meta = doc.querySelector<HTMLMetaElement>('meta[name="sidekick-rooms"]');
  if (rooms === undefined) {
    meta?.remove();
    return;
  }
  if (!meta) {
    meta = doc.createElement("meta");
    meta.name = "sidekick-rooms";
    doc.head.append(meta);
  }
  meta.content = rooms.join(",");
}

/** Whether `room` is on. A cross link, a menu entry or a chip that leads to a room that is off is not drawn. */
export function roomEnabled(room: RoomId, doc: Document = document): boolean {
  return enabledRooms(doc).includes(room);
}

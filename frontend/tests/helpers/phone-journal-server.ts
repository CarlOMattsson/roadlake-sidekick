/**
 * A phone and a server for the journal tests, between `CompanionRoomTransport` and the room.
 *
 * The server keeps the owner's entries and answers the journal routes with the answers the real backend gave
 * (tests/fixtures/companion-journal.json, recorded by backend/tests/api/test_companion_journal_recording.py, which
 * fails when the shape of an answer changes): the recorded entry, day, source and empty day are filled with what the
 * request carried, nothing is invented around them. The phone in front of it applies the limits of the Kotlin side
 * (`RequestPolicy`, `UrlConnectionTransport`), so a request or an answer the real phone would refuse fails here too.
 * This is a simulated phone, not a device: the Kotlin limits are pinned by their own JVM tests.
 */
import type {
  NativeRequest,
  NativeResponse,
} from "../../src/mobile/sidekick-native";
import recording from "../fixtures/companion-journal.json";

type Json = Record<string, unknown>;

/** `RequestPolicy`: companion routes only, plain segments, a bounded query, a body of at most 256 KiB. */
const MAX_BODY_BYTES = 256 * 1024;
const MAX_SEGMENTS = 6;
const MAX_QUERY_VALUE = 512;
const MAX_CURSOR = 2048;
const SEGMENT = /^[A-Za-z0-9_-]{1,64}$/;
const QUERY_KEY = /^[A-Za-z0-9_]{1,40}$/;
const IDEMPOTENCY_KEY = /^[A-Za-z0-9._:-]{8,128}$/;
/** `UrlConnectionTransport`: an answer above this is refused as `response_too_large`. */
export const MAX_RESPONSE_BYTES = 2 * 1024 * 1024;

const bytes = (text: string) => new TextEncoder().encode(text).length;

/** What the plugin refuses before it sends, as the Kotlin `RequestPolicy` does; throws the closed code. */
function checkLikeThePhone(request: NativeRequest) {
  const refuse = (code: string): never => {
    throw Object.assign(new Error(code), { code });
  };
  const prefix = "/companion/v1/";
  if (!request.path.startsWith(prefix)) refuse("path_refused");
  const segments = request.path.slice(prefix.length).split("/");
  if (segments.length > MAX_SEGMENTS || segments.some((s) => !SEGMENT.test(s)))
    refuse("path_refused");
  for (const [key, value] of Object.entries(request.query ?? {})) {
    if (!QUERY_KEY.test(key)) refuse("bad_request");
    for (const item of Array.isArray(value) ? value : [value])
      if (item.length > (key === "cursor" ? MAX_CURSOR : MAX_QUERY_VALUE))
        refuse("bad_request");
  }
  if (
    request.idempotencyKey !== undefined &&
    !IDEMPOTENCY_KEY.test(request.idempotencyKey)
  )
    refuse("bad_request");
  if (request.body !== undefined) {
    if (request.method === "GET") refuse("bad_request");
    if (bytes(JSON.stringify(request.body)) > MAX_BODY_BYTES)
      refuse("bad_request");
  }
}

type Stored = { entry: Json; text: string };

export type PhoneJournalServer = {
  /** The plugin's `request`: the phone's checks, then the server, then the phone's cap on the answer. */
  request: (request: NativeRequest) => Promise<NativeResponse>;
  /** Every request that reached the server, in order. */
  served: NativeRequest[];
  /** The entries the server holds (the owner's data, which outlives the app's restart). */
  entries: () => Stored[];
};

/** A server with no entries. The same server serves every app start of one test. */
export function phoneJournalServer(): PhoneJournalServer {
  const stored: Stored[] = [];
  const written = new Map<string, Json>();
  const served: NativeRequest[] = [];
  const recordedEntry = (recording.write as { entry: Json }).entry;
  const recordedSource = (recording.source as { source: Json }).source;
  const notFound = (): NativeResponse => ({
    status: 404,
    body: { code: "not_found" },
  });

  function answer(request: NativeRequest): NativeResponse {
    const path = request.path.replace("/companion/v1/journal/", "");
    const [kind, id] = path.split("/");
    if (request.method === "POST" && kind === "entries" && id === undefined) {
      const key = request.idempotencyKey ?? "";
      const replay = written.get(key);
      if (replay) return { status: 200, body: { entry: replay } };
      const body = request.body as {
        journal_date: string;
        title: string;
        source_text: string;
        occurred_at?: string;
      };
      const entry = {
        ...recordedEntry,
        id: crypto.randomUUID(),
        source_id: crypto.randomUUID(),
        journal_date: body.journal_date,
        occurred_at: body.occurred_at ?? null,
        title: body.title,
        // A hand-written entry: the server saves no summary and no key points of its own.
        summary: null,
        key_points: [],
        version: 1,
      };
      stored.push({ entry, text: body.source_text });
      written.set(key, entry);
      return { status: 200, body: { entry } };
    }
    if (request.method !== "GET") return notFound();
    if (kind === "days" && id !== undefined) {
      const entries = stored
        .filter((item) => item.entry.journal_date === id)
        .map((item) => item.entry);
      if (entries.length === 0)
        return {
          status: 200,
          body: { ...recording.emptyDay, journal_date: id },
        };
      return {
        status: 200,
        body: { ...recording.day, journal_date: id, entries },
      };
    }
    if (kind === "entries" && id !== undefined) {
      const item = stored.find((s) => s.entry.id === id);
      return item ? { status: 200, body: { entry: item.entry } } : notFound();
    }
    if (kind === "sources" && id !== undefined) {
      const item = stored.find((s) => s.entry.source_id === id);
      return item
        ? {
            status: 200,
            body: {
              source: {
                ...recordedSource,
                id,
                journal_date: item.entry.journal_date,
                raw_text:
                  request.query?.include_content === "false" ? null : item.text,
              },
            },
          }
        : notFound();
    }
    return notFound();
  }

  return {
    served,
    entries: () => stored,
    request: (request) => {
      checkLikeThePhone(request);
      served.push(request);
      // The wire: the answer is JSON text, which the phone cuts off above its cap.
      const response = answer(request);
      const wire = JSON.stringify(response.body);
      if (bytes(wire) > MAX_RESPONSE_BYTES)
        throw Object.assign(new Error("response_too_large"), {
          code: "response_too_large",
        });
      return Promise.resolve({
        status: response.status,
        body: JSON.parse(wire) as unknown,
      });
    },
  };
}

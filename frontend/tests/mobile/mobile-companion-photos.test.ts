import { describe, expect, it } from "vitest";

import { HostToolError } from "@/features/mcp-apps/bridge";
import {
  CompanionNetworkError,
  CompanionRoomTransport,
} from "@/mobile/companion-transport";
import { fakeNative } from "@tests/helpers/fake-native";

const PHOTO_ID = "019f0000-0000-7000-8000-0000000000f1";
const KEY = "photo-key-0123456789";
const DAY = "2026-11-22";

const upload = {
  journal_date: DAY,
  photo: "UEhPVE8=",
  thumbnail: "VEhVTUI=",
  alt_text: "A bridge at dusk",
  idempotency_key: KEY,
};

function setup() {
  const native = fakeNative(() => ({ status: 200, body: { ok: true } }));
  return { native, transport: new CompanionRoomTransport(native) };
}

describe("Journal photos over the companion transport", () => {
  it("offers both photo tools", () => {
    const { transport } = setup();
    expect(transport.supportsTool("add_journal_photo")).toBe(true);
    expect(transport.supportsTool("get_journal_photo")).toBe(true);
    // Changing or trashing a photo is not in the app yet.
    expect(transport.supportsTool("update_journal_photo")).toBe(false);
    expect(transport.supportsTool("trash_journal_photo")).toBe(false);
  });

  it("maps get_journal_photo to GET with the photo in the path and the size as the query", async () => {
    const { native, transport } = setup();
    await transport.call("get_journal_photo", {
      photo_id: PHOTO_ID.toUpperCase(),
      size: "thumb",
    });
    await transport.call("get_journal_photo", { photo_id: PHOTO_ID });
    expect(native.requests).toEqual([
      {
        method: "GET",
        path: `/companion/v1/journal/photos/${PHOTO_ID}`,
        query: { size: "thumb" },
      },
      { method: "GET", path: `/companion/v1/journal/photos/${PHOTO_ID}` },
    ]);
  });

  it.each([
    { photo_id: "not-a-uuid" },
    { photo_id: PHOTO_ID, size: "full" },
    { photo_id: PHOTO_ID, extra: "x" },
  ])("refuses %j before anything is sent", async (args) => {
    const { native, transport } = setup();
    await expect(transport.call("get_journal_photo", args)).rejects.toThrow(
      HostToolError,
    );
    expect(native.requests).toEqual([]);
  });

  it("sends add_journal_photo to the native upload with the day, both files, the caption and the key", async () => {
    const { native, transport } = setup();
    native.uploadJournalPhoto.mockResolvedValueOnce({
      status: 200,
      body: { photo: { id: PHOTO_ID } },
    });
    const answer = await transport.call("add_journal_photo", upload);
    expect(answer).toEqual({ photo: { id: PHOTO_ID } });
    expect(native.uploadJournalPhoto).toHaveBeenCalledWith({
      journalDate: DAY,
      photo: "UEhPVE8=",
      thumbnail: "VEhVTUI=",
      altText: "A bridge at dusk",
      idempotencyKey: KEY,
    });
    // The upload is not a JSON request.
    expect(native.requests).toEqual([]);
  });

  it("leaves the caption out when there is none", async () => {
    const { native, transport } = setup();
    native.uploadJournalPhoto.mockResolvedValueOnce({ status: 200, body: {} });
    await transport.call("add_journal_photo", {
      ...upload,
      alt_text: undefined,
    });
    expect(native.uploadJournalPhoto.mock.calls[0]?.[0]).not.toHaveProperty(
      "altText",
    );
  });

  it.each([
    { ...upload, entry_id: PHOTO_ID },
    { ...upload, journal_date: "yesterday" },
    { ...upload, photo: "not base64!" },
    { ...upload, thumbnail: 12 },
    { ...upload, idempotency_key: "short" },
    { ...upload, alt_text: "x".repeat(501) },
  ])("refuses an upload with %j before anything is sent", async (args) => {
    const { native, transport } = setup();
    await expect(transport.call("add_journal_photo", args)).rejects.toThrow(
      HostToolError,
    );
    expect(native.uploadJournalPhoto).not.toHaveBeenCalled();
  });

  it("answers the server's closed code when it refuses the photo", async () => {
    const { native, transport } = setup();
    native.uploadJournalPhoto.mockResolvedValueOnce({
      status: 422,
      body: { code: "validation_error" },
    });
    await expect(transport.call("add_journal_photo", upload)).rejects.toThrow(
      expect.objectContaining({ code: "validation_error" }),
    );
    native.uploadJournalPhoto.mockResolvedValueOnce({ status: 403, body: {} });
    await expect(transport.call("add_journal_photo", upload)).rejects.toThrow(
      expect.objectContaining({ code: "forbidden" }),
    );
  });

  it("fails as a connection failure when no answer came, and keeps nothing in an outbox", async () => {
    const { native, transport } = setup();
    native.uploadJournalPhoto.mockRejectedValueOnce(
      Object.assign(new Error("x"), { code: "network" }),
    );
    await expect(transport.call("add_journal_photo", upload)).rejects.toThrow(
      CompanionNetworkError,
    );
    expect(native.queueRecordWrite).not.toHaveBeenCalled();
  });

  it("answers any other native fault without a code", async () => {
    const { native, transport } = setup();
    native.uploadJournalPhoto.mockRejectedValueOnce(
      Object.assign(new Error("x"), { code: "not_paired" }),
    );
    await expect(transport.call("add_journal_photo", upload)).rejects.toThrow(
      HostToolError,
    );
  });

  it("fails without a code when the phone build has no upload", async () => {
    const native = fakeNative(() => ({ status: 200, body: {} }));
    const transport = new CompanionRoomTransport({
      request: native.request,
    });
    await expect(transport.call("add_journal_photo", upload)).rejects.toThrow(
      HostToolError,
    );
  });
});

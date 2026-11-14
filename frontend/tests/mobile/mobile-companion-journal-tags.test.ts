import { describe, expect, it } from "vitest";

import { toolOffered } from "@/features/mcp-apps/tool-support";
import { CompanionRoomTransport } from "@/mobile/companion-transport";
import { fakeNative, ok } from "@tests/helpers/fake-native";

const ENTRY_ID = "019f0000-0000-7000-8000-0000000000d1";

function phone() {
  return new CompanionRoomTransport(fakeNative(() => ok({})));
}

// The companion routes take no tags, so the Journal room must find no tag filter and no tag editing on the phone.
describe("Journal tags over the companion transport", () => {
  it("has no list_tags", () => {
    expect(toolOffered(phone(), "list_tags")).toBe(false);
  });

  it("answers the tagged read and the tag write no, and the plain ones yes", () => {
    const transport = phone();
    expect(toolOffered(transport, "list_journal_entries", { tags: [] })).toBe(
      false,
    );
    expect(
      toolOffered(transport, "list_journal_entries", {
        from_date: "2026-11-01",
        to_date: "2026-11-07",
      }),
    ).toBe(true);
    expect(toolOffered(transport, "update_journal_entry", { tags: [] })).toBe(
      false,
    );
    expect(
      toolOffered(transport, "update_journal_entry", {
        title: "T",
        key_points: [],
      }),
    ).toBe(true);
  });

  it("refuses tags before any request is made", async () => {
    const native = fakeNative(() => ok({}));
    const transport = new CompanionRoomTransport(native);
    await expect(
      transport.call("update_journal_entry", {
        entry_id: ENTRY_ID,
        expected_version: 1,
        idempotency_key: "key-0123456789",
        tags: ["viktig"],
      }),
    ).rejects.toBeInstanceOf(Error);
    await expect(
      transport.call("list_journal_entries", {
        from_date: "2026-11-01",
        to_date: "2026-11-07",
        tags: ["viktig"],
      }),
    ).rejects.toBeInstanceOf(Error);
    expect(native.requests).toHaveLength(0);
  });
});

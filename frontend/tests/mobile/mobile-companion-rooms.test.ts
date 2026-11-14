import { describe, expect, it } from "vitest";

import { HostToolError } from "@/features/mcp-apps/bridge";
import {
  COMPANION_TOOLS,
  CompanionRoomTransport,
  NotInAppError,
} from "@/mobile/companion-transport";
import { JOURNAL_ROUTES, JOURNAL_TOOLS } from "@/mobile/companion-journal";
import { SHOPPING_ROUTES, SHOPPING_TOOLS } from "@/mobile/companion-shopping";
import { fakeNative, ok } from "@tests/helpers/fake-native";

const LIST_ID = "019f0000-0000-7000-8000-0000000000b1";
const ITEM_ID = "019f0000-0000-7000-8000-0000000000c1";
const ENTRY_ID = "019f0000-0000-7000-8000-0000000000d1";
const CONTACT_ID = "019f0000-0000-7000-8000-0000000000e1";
const KEY = "key-0123456789";

function setup(status = 200, body: unknown = { ok: true }) {
  const native = fakeNative(() => ({ status, body }));
  return { native, transport: new CompanionRoomTransport(native) };
}

describe("Shopping over the companion transport", () => {
  it("lists the tools it answers, and only those", () => {
    const { transport } = setup();
    for (const tool of SHOPPING_TOOLS) {
      expect(COMPANION_TOOLS).toContain(tool);
      expect(transport.supportsTool(tool)).toBe(true);
    }
    // The recipient search and the bulk purchase are not in the app.
    expect(transport.supportsTool("list_contacts")).toBe(false);
    expect(transport.supportsTool("set_shopping_items_purchased")).toBe(false);
    expect(Object.keys(SHOPPING_ROUTES).sort()).toEqual(
      [...SHOPPING_TOOLS].sort(),
    );
  });

  it("maps list_shopping_lists to GET with the query", async () => {
    const { native, transport } = setup();
    await transport.call("list_shopping_lists", {
      include_archived: true,
      limit: 50,
      offset: 0,
    });
    expect(native.requests).toEqual([
      {
        method: "GET",
        path: "/companion/v1/shopping/lists",
        query: { include_archived: "true", limit: "50", offset: "0" },
      },
    ]);
  });

  it("maps get_shopping_list to GET with the list in the path and the rest as the query", async () => {
    const { native, transport } = setup();
    await transport.call("get_shopping_list", {
      list_id: LIST_ID,
      on_date: "2026-11-09",
      limit: 100,
      offset: 0,
      store: "ICA",
    });
    await transport.call("get_shopping_list", { list_id: LIST_ID });
    expect(native.requests).toEqual([
      {
        method: "GET",
        path: `/companion/v1/shopping/lists/${LIST_ID}`,
        query: {
          on_date: "2026-11-09",
          limit: "100",
          offset: "0",
          store: "ICA",
        },
      },
      { method: "GET", path: `/companion/v1/shopping/lists/${LIST_ID}` },
    ]);
  });

  it.each([
    [
      "create_shopping_list",
      { name: "Fest" },
      "/companion/v1/shopping/lists",
      { name: "Fest" },
    ],
    [
      "update_shopping_list",
      { list_id: LIST_ID, name: "Fest", archived: false, version: 2 },
      `/companion/v1/shopping/lists/${LIST_ID}/update`,
      { name: "Fest", archived: false, version: 2 },
    ],
    [
      "add_shopping_items",
      {
        list_id: LIST_ID,
        items: [{ name: "Mjölk", client_ref: "0" }],
        merge_duplicates: true,
      },
      `/companion/v1/shopping/lists/${LIST_ID}/items`,
      { items: [{ name: "Mjölk", client_ref: "0" }], merge_duplicates: true },
    ],
    [
      "update_shopping_item",
      { item_id: ITEM_ID, item: { name: "Mjölk", quantity: "2" }, version: 3 },
      `/companion/v1/shopping/items/${ITEM_ID}/update`,
      { item: { name: "Mjölk", quantity: "2" }, version: 3 },
    ],
    [
      "set_shopping_item_purchased",
      { item_id: ITEM_ID, purchased: true, version: 3 },
      `/companion/v1/shopping/items/${ITEM_ID}/purchased`,
      { purchased: true, version: 3 },
    ],
  ])(
    "maps %s to POST with the body and the room's Idempotency-Key",
    async (name, args, path, body) => {
      const { native, transport } = setup();
      await transport.call(name, { ...args, idempotency_key: KEY });
      expect(native.requests).toEqual([
        { method: "POST", path, body, idempotencyKey: KEY },
      ]);
    },
  );

  it("leaves merge_duplicates out of the body when it was not given", async () => {
    const { native, transport } = setup();
    await transport.call("add_shopping_items", {
      list_id: LIST_ID,
      items: [{ name: "Ägg" }],
      idempotency_key: KEY,
    });
    expect(native.requests[0]?.body).toEqual({ items: [{ name: "Ägg" }] });
  });

  it.each([
    [
      "an argument outside the route",
      "create_shopping_list",
      { name: "x", extra: 1 },
    ],
    ["a list id that is not a uuid", "get_shopping_list", { list_id: "../x" }],
    [
      "a bad date",
      "get_shopping_list",
      { list_id: LIST_ID, on_date: "2026-13-40" },
    ],
    ["an unknown query key", "list_shopping_lists", { q: "x" }],
    [
      "a version of 0",
      "update_shopping_item",
      { item_id: ITEM_ID, item: {}, version: 0, idempotency_key: KEY },
    ],
    [
      "an item that is not an object",
      "update_shopping_item",
      { item_id: ITEM_ID, item: "x", version: 1, idempotency_key: KEY },
    ],
    [
      "no items",
      "add_shopping_items",
      { list_id: LIST_ID, items: [], idempotency_key: KEY },
    ],
    [
      "a key that is too short",
      "create_shopping_list",
      { name: "x", idempotency_key: "short" },
    ],
    [
      "a purchased that is not a boolean",
      "set_shopping_item_purchased",
      { item_id: ITEM_ID, purchased: "yes", version: 1, idempotency_key: KEY },
    ],
  ])("refuses %s before anything is sent", async (_label, name, args) => {
    const { native, transport } = setup();
    await expect(transport.call(name, args)).rejects.toMatchObject({
      code: "validation_error",
    });
    expect(native.requests).toHaveLength(0);
  });
});

describe("Journal over the companion transport", () => {
  it("lists the tools it answers, and the AI and review tools are not among them", () => {
    const { transport } = setup();
    for (const tool of JOURNAL_TOOLS) {
      expect(COMPANION_TOOLS).toContain(tool);
      expect(transport.supportsTool(tool)).toBe(true);
    }
    for (const tool of [
      "list_pending_journal",
      "get_journal_draft",
      "update_journal_draft",
      "reject_journal_draft",
      "finalize_journal_draft",
      "get_daily_journal_summary",
      "set_daily_journal_summary",
      "create_journal_source",
      "create_manual_journal_entry",
    ])
      expect(transport.supportsTool(tool)).toBe(false);
    expect(Object.keys(JOURNAL_ROUTES).sort()).toEqual(
      [...JOURNAL_TOOLS].sort(),
    );
  });

  it("maps get_journal_day to GET with the date in the path", async () => {
    const { native, transport } = setup();
    await transport.call("get_journal_day", {
      journal_date: "2026-11-09",
      include_content: true,
      limit: 50,
      cursor: null,
    });
    expect(native.requests).toEqual([
      {
        method: "GET",
        path: "/companion/v1/journal/days/2026-11-09",
        query: { include_content: "true", limit: "50" },
      },
    ]);
  });

  it("maps list_journal_entries and get_journal_entry to GET", async () => {
    const { native, transport } = setup();
    await transport.call("list_journal_entries", {
      from_date: "2026-11-03",
      to_date: "2026-11-09",
      include_content: false,
      limit: 50,
    });
    await transport.call("get_journal_entry", {
      entry_id: ENTRY_ID,
      include_content: true,
    });
    expect(native.requests).toEqual([
      {
        method: "GET",
        path: "/companion/v1/journal/entries",
        query: {
          from_date: "2026-11-03",
          to_date: "2026-11-09",
          include_content: "false",
          limit: "50",
        },
      },
      {
        method: "GET",
        path: `/companion/v1/journal/entries/${ENTRY_ID}`,
        query: { include_content: "true" },
      },
    ]);
  });

  it("maps get_journal_source to GET with the source in the path and refuses a path in its place", async () => {
    const { native, transport } = setup();
    await transport.call("get_journal_source", {
      source_id: ENTRY_ID,
      include_content: true,
    });
    expect(native.requests).toEqual([
      {
        method: "GET",
        path: `/companion/v1/journal/sources/${ENTRY_ID}`,
        query: { include_content: "true" },
      },
    ]);
    await expect(
      transport.call("get_journal_source", { source_id: "../entries" }),
    ).rejects.toMatchObject({ code: "validation_error" });
    expect(native.requests).toHaveLength(1);
  });

  it("maps write_journal_entry to POST /entries with every field but the key, null and undefined left out", async () => {
    const { native, transport } = setup();
    await transport.call("write_journal_entry", {
      journal_date: "2026-11-09",
      title: "Dag",
      source_text: "Idag hände saker.",
      occurred_at: undefined,
      summary: null,
      key_points: [{ kind: "fact", text: "Saker" }],
      contact_ids: [CONTACT_ID],
      language: "sv",
      idempotency_key: KEY,
    });
    expect(native.requests).toEqual([
      {
        method: "POST",
        path: "/companion/v1/journal/entries",
        body: {
          journal_date: "2026-11-09",
          title: "Dag",
          source_text: "Idag hände saker.",
          key_points: [{ kind: "fact", text: "Saker" }],
          contact_ids: [CONTACT_ID],
          language: "sv",
        },
        idempotencyKey: KEY,
      },
    ]);
  });

  it("maps update_journal_entry to POST .../update with expected_version as version", async () => {
    const { native, transport } = setup();
    await transport.call("update_journal_entry", {
      entry_id: ENTRY_ID,
      expected_version: 4,
      idempotency_key: KEY,
      title: "Ny rubrik",
      summary: null,
      append_text: "Mer text",
    });
    expect(native.requests).toEqual([
      {
        method: "POST",
        path: `/companion/v1/journal/entries/${ENTRY_ID}/update`,
        body: {
          version: 4,
          title: "Ny rubrik",
          summary: null,
          append_text: "Mer text",
        },
        idempotencyKey: KEY,
      },
    ]);
  });

  it.each([
    ["a bad day", "get_journal_day", { journal_date: "2026-02-30" }],
    ["a day with a path in it", "get_journal_day", { journal_date: "../x" }],
    [
      "include_archived (not supported)",
      "list_journal_entries",
      { include_archived: true },
    ],
    ["an entry id that is not a uuid", "get_journal_entry", { entry_id: "1" }],
    [
      "a write without a title",
      "write_journal_entry",
      { journal_date: "2026-11-09", source_text: "x", idempotency_key: KEY },
    ],
    [
      "an unknown write field",
      "write_journal_entry",
      {
        journal_date: "2026-11-09",
        title: "t",
        source_text: "x",
        source_id: "s",
        idempotency_key: KEY,
      },
    ],
    [
      "an update without a valid version",
      "update_journal_entry",
      { entry_id: ENTRY_ID, expected_version: 0, idempotency_key: KEY },
    ],
    [
      "the body's own name for the version",
      "update_journal_entry",
      { entry_id: ENTRY_ID, version: 1, idempotency_key: KEY },
    ],
    ...[
      "add_contact_ids",
      "remove_contact_ids",
      "add_project_ids",
      "remove_project_ids",
    ].map(
      (field) =>
        [
          `the link change ${field} (the Dagbok device has no right to links)`,
          "update_journal_entry",
          {
            entry_id: ENTRY_ID,
            expected_version: 1,
            [field]: [CONTACT_ID],
            idempotency_key: KEY,
          },
        ] as [string, string, Record<string, unknown>],
    ),
  ])("refuses %s before anything is sent", async (_label, name, args) => {
    const { native, transport } = setup();
    await expect(transport.call(name, args)).rejects.toMatchObject({
      code: "validation_error",
    });
    expect(native.requests).toHaveLength(0);
  });
});

describe("Journal links", () => {
  it("answers no to an entry update that names a link change, and yes to one that does not", () => {
    const { transport } = setup();
    for (const field of [
      "add_contact_ids",
      "remove_contact_ids",
      "add_project_ids",
      "remove_project_ids",
    ])
      expect(
        transport.supportsCall("update_journal_entry", { [field]: [] }),
      ).toBe(false);
    expect(
      transport.supportsCall("update_journal_entry", { append_text: "x" }),
    ).toBe(true);
  });
});

describe("Shopping and Journal writes: keys and errors", () => {
  it("sends the same key when a write is retried after no answer came, and a new one after it was settled", async () => {
    let fail = true;
    const native = fakeNative(() => {
      if (fail) throw new Error("offline");
      return ok({ entry: { id: ENTRY_ID, version: 5 } });
    });
    const transport = new CompanionRoomTransport(native);
    const args = {
      entry_id: ENTRY_ID,
      expected_version: 4,
      append_text: "Mer",
    };

    await expect(
      transport.call("update_journal_entry", args),
    ).rejects.toBeInstanceOf(HostToolError);
    fail = false;
    await transport.call("update_journal_entry", args);
    await transport.call("update_journal_entry", args);

    const keys = native.requests.map((r) => r.idempotencyKey);
    expect(keys[0]).toMatch(/^[0-9a-f-]{36}$/);
    expect(keys[1]).toBe(keys[0]);
    // The second answer settled the action: the next try is a new action.
    expect(keys[2]).not.toBe(keys[0]);
  });

  it("keeps the key of a shopping write over a 5xx answer", async () => {
    const native = fakeNative(() => ({ status: 503, body: {} }));
    const transport = new CompanionRoomTransport(native);
    const args = { item_id: ITEM_ID, purchased: true, version: 1 };
    await expect(
      transport.call("set_shopping_item_purchased", args),
    ).rejects.toBeInstanceOf(HostToolError);
    await expect(
      transport.call("set_shopping_item_purchased", args),
    ).rejects.toBeInstanceOf(HostToolError);
    expect(native.requests[1]?.idempotencyKey).toBe(
      native.requests[0]?.idempotencyKey,
    );
  });

  it.each([
    [409, { code: "conflict" }, "conflict"],
    [404, { code: "not_found" }, "not_found"],
    [403, {}, "forbidden"],
    [403, { code: "scope_missing" }, "scope_missing"],
  ])("lets a %s answer through as the code %s", async (status, body, code) => {
    const { transport } = setup(status, body);
    await expect(
      transport.call("update_shopping_item", {
        item_id: ITEM_ID,
        item: { name: "x" },
        version: 1,
        idempotency_key: KEY,
      }),
    ).rejects.toMatchObject({ code });
    await expect(
      transport.call("get_journal_entry", { entry_id: ENTRY_ID }),
    ).rejects.toMatchObject({ code });
  });

  it.each([
    "list_contacts",
    "set_shopping_items_purchased",
    "list_pending_journal",
    "get_journal_draft",
    "finalize_journal_draft",
    "set_daily_journal_summary",
    "create_manual_journal_entry",
  ])("answers %s with NotInAppError and sends nothing", async (name) => {
    const { native, transport } = setup();
    await expect(transport.call(name, {})).rejects.toBeInstanceOf(
      NotInAppError,
    );
    expect(native.requests).toHaveLength(0);
  });
});

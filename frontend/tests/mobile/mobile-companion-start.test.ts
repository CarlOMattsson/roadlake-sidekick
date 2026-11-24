import { describe, expect, it } from "vitest";

import { HostToolError } from "@/features/mcp-apps/bridge";
import { START_ROUTES, START_TOOLS } from "@/mobile/companion-start";
import {
  CompanionRoomTransport,
  NotInAppError,
} from "@/mobile/companion-transport";
import { fakeNative, ok } from "@tests/helpers/fake-native";
import { KEY } from "@tests/helpers/companion-transport-fixtures";

const SUGGESTION = "019f0000-0000-7000-8000-000000000071";
const OTHER = "019f0000-0000-7000-8000-000000000072";
const AUTOMATION = "019F0000-0000-7000-8000-000000000800";
const DIGEST = "a".repeat(64);

function phone(answer = ok({ items: [] })) {
  const native = fakeNative(() => answer);
  return { native, transport: new CompanionRoomTransport(native) };
}

async function refusal(
  transport: CompanionRoomTransport,
  name: string,
  args: object,
) {
  return transport.call(name, args).catch((error: unknown) => error);
}

describe("the Start tools over the companion routes", () => {
  it("answers exactly the tools of its closed list, each with one route", () => {
    const transport = phone().transport;
    expect([...START_TOOLS].sort()).toEqual(Object.keys(START_ROUTES).sort());
    for (const tool of START_TOOLS)
      expect(transport.supportsTool(tool)).toBe(true);
    // What the phone does not serve, a room hides by asking.
    for (const tool of [
      "list_automations",
      "get_automation",
      "approve_automation",
      "skip_ready_conversation",
    ])
      expect(transport.supportsTool(tool)).toBe(false);
  });

  it("maps get_start to GET /start with no arguments", async () => {
    const { native, transport } = phone(ok({ day: "2026-11-23" }));

    expect(await transport.call("get_start", {})).toEqual({
      day: "2026-11-23",
    });
    expect(native.requests).toEqual([
      { method: "GET", path: "/companion/v1/start" },
    ]);
    expect(await refusal(transport, "get_start", { day: "x" })).toBeInstanceOf(
      HostToolError,
    );
    expect(native.requests).toHaveLength(1);
  });

  it("maps list_suggestions to GET /suggestions with its own query keys", async () => {
    const { native, transport } = phone();

    await transport.call("list_suggestions", {
      limit: 25,
      cursor: "abc",
      group: "all",
      state: null,
      automation_id: AUTOMATION,
    });

    expect(native.requests).toEqual([
      {
        method: "GET",
        path: "/companion/v1/suggestions",
        query: {
          limit: "25",
          cursor: "abc",
          group: "all",
          automation_id: AUTOMATION.toLowerCase(),
        },
      },
    ]);
    expect(
      await refusal(transport, "list_suggestions", { limit: 25, sort: "x" }),
    ).toMatchObject({ code: "validation_error" });
    expect(
      await refusal(transport, "list_suggestions", { automation_id: "nope" }),
    ).toMatchObject({ code: "validation_error" });
    expect(native.requests).toHaveLength(1);
  });

  it("maps get_suggestion to GET /suggestions/{id}, and refuses another argument", async () => {
    const { native, transport } = phone();

    await transport.call("get_suggestion", { suggestion_id: SUGGESTION });

    expect(native.requests).toEqual([
      { method: "GET", path: `/companion/v1/suggestions/${SUGGESTION}` },
    ]);
    expect(
      await refusal(transport, "get_suggestion", {
        suggestion_id: SUGGESTION,
        state: "pending",
      }),
    ).toMatchObject({ code: "validation_error" });
    expect(
      await refusal(transport, "get_suggestion", { suggestion_id: "../x" }),
    ).toMatchObject({ code: "validation_error" });
    expect(native.requests).toHaveLength(1);
  });

  it("maps decide_suggestions to POST /suggestions/decisions with the room's key", async () => {
    const { native, transport } = phone();
    const items = [
      { suggestion_id: SUGGESTION, expected_version: 2, decision: "approve" },
      {
        suggestion_id: OTHER,
        expected_version: 1,
        decision: "approve",
        confirmed: true,
      },
    ];

    await transport.call("decide_suggestions", {
      items,
      idempotency_key: KEY,
    });

    expect(native.requests).toEqual([
      {
        method: "POST",
        path: "/companion/v1/suggestions/decisions",
        body: { items },
        idempotencyKey: KEY,
      },
    ]);
  });

  it("refuses edits, a fourth card and other bad decisions before anything is sent", async () => {
    const { native, transport } = phone();
    const card = (n: number) => ({
      suggestion_id: `019f0000-0000-7000-8000-00000000009${n}`,
      expected_version: 1,
      decision: "approve",
    });
    const bad: object[] = [
      { items: [{ ...card(1), edits: { title: "x" } }] },
      { items: [{ ...card(1), edits: undefined }] },
      { items: [card(1), card(2), card(3), card(4)] },
      { items: [] },
      { items: "x" },
      { items: [{ ...card(1), decision: "undo" }] },
      { items: [{ ...card(1), expected_version: 0 }] },
      { items: [{ ...card(1), confirmed: "yes" }] },
      { items: [{ ...card(1), suggestion_id: "not-a-uuid" }] },
      { items: [card(1)], decision_ticket: "t" },
    ];

    for (const args of bad)
      expect(
        await refusal(transport, "decide_suggestions", args),
      ).toMatchObject({ code: "validation_error" });
    expect(native.requests).toEqual([]);
  });

  it("takes three cards in one decision", async () => {
    const { native, transport } = phone();
    const card = (n: number) => ({
      suggestion_id: `019f0000-0000-7000-8000-00000000009${n}`,
      expected_version: 1,
      decision: "dismiss",
    });

    await transport.call("decide_suggestions", {
      items: [card(1), card(2), card(3)],
    });

    expect(native.requests).toHaveLength(1);
    expect(native.requests[0]?.idempotencyKey).toBeTruthy();
  });

  it("maps approve_suggestion_group to POST /suggestions/group-approvals without a decision ticket", async () => {
    const { native, transport } = phone();

    await transport.call("approve_suggestion_group", {
      group_digest: DIGEST,
      suggestion_ids: [SUGGESTION.toUpperCase(), OTHER],
      idempotency_key: KEY,
    });

    expect(native.requests).toEqual([
      {
        method: "POST",
        path: "/companion/v1/suggestions/group-approvals",
        body: { group_digest: DIGEST, suggestion_ids: [SUGGESTION, OTHER] },
        idempotencyKey: KEY,
      },
    ]);
    for (const args of [
      {
        group_digest: DIGEST,
        suggestion_ids: [SUGGESTION],
        decision_ticket: "t",
      },
      { group_digest: "short", suggestion_ids: [SUGGESTION] },
      { group_digest: DIGEST, suggestion_ids: [] },
      { group_digest: DIGEST, suggestion_ids: ["x"] },
      { suggestion_ids: [SUGGESTION] },
    ])
      expect(
        await refusal(transport, "approve_suggestion_group", args),
      ).toMatchObject({ code: "validation_error" });
    expect(native.requests).toHaveLength(1);
  });

  it("maps undo_suggestion to POST /suggestions/{id}/undo with the version", async () => {
    const { native, transport } = phone();

    await transport.call("undo_suggestion", {
      suggestion_id: SUGGESTION,
      expected_version: 3,
      idempotency_key: KEY,
    });

    expect(native.requests).toEqual([
      {
        method: "POST",
        path: `/companion/v1/suggestions/${SUGGESTION}/undo`,
        body: { expected_version: 3 },
        idempotencyKey: KEY,
      },
    ]);
    expect(
      await refusal(transport, "undo_suggestion", {
        suggestion_id: SUGGESTION,
        expected_version: 0,
      }),
    ).toMatchObject({ code: "validation_error" });
  });

  it("keeps one key for a retry of the same decision until it is settled", async () => {
    const answers = [503, 200];
    const native = fakeNative(() => ({
      status: answers.shift() ?? 200,
      body: { items: [] },
    }));
    const transport = new CompanionRoomTransport(native);
    const args = {
      items: [
        { suggestion_id: SUGGESTION, expected_version: 1, decision: "approve" },
      ],
    };

    await transport.call("decide_suggestions", args).catch(() => undefined);
    await transport.call("decide_suggestions", args);

    expect(native.requests[0]?.idempotencyKey).toBe(
      native.requests[1]?.idempotencyKey,
    );
  });

  it("answers a missing capability as the closed forbidden code, not as a crash", async () => {
    const native = fakeNative(() => ({
      status: 403,
      body: { code: "forbidden", reason: "capability_missing" },
    }));
    const transport = new CompanionRoomTransport(native);

    const error = await refusal(transport, "decide_suggestions", {
      items: [
        { suggestion_id: SUGGESTION, expected_version: 1, decision: "approve" },
      ],
    });

    expect(error).toBeInstanceOf(HostToolError);
    expect(error).not.toBeInstanceOf(NotInAppError);
    expect((error as HostToolError).code).toBe("forbidden");
  });
});

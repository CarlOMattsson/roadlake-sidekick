import { afterEach, describe, expect, it, vi } from "vitest";
import {
  APP_ORIGIN_META,
  createHostBridge,
  HostToolError,
  MCP_APPS_PROTOCOL_VERSION,
} from "@/features/mcp-apps/bridge";

// Decision tickets (issue #53): the server hands out one-shot proofs of a decision the owner made in the
// result `_meta`; the bridge keeps them internally and sends one back as `decision_ticket`.

const TICKETS = "com.roadlake.sidekick/decisionTickets";

type Sent = {
  id?: number;
  method?: string;
  params?: {
    name?: string;
    arguments?: Record<string, unknown>;
    _meta?: unknown;
  };
};
type Answer = {
  structuredContent?: unknown;
  isError?: boolean;
  _meta?: object;
};

const sent: Sent[] = [];
/** Answers queued per tools/call, in order; an empty queue answers with an empty success. */
let answers: Answer[] = [];

function toHost(data: object) {
  window.dispatchEvent(
    new MessageEvent("message", {
      data: { jsonrpc: "2.0", ...data },
      source: window,
    }),
  );
}

function ticketMeta(tickets: unknown): object {
  return { [TICKETS]: tickets };
}

function toolResultNotification(meta: object | undefined) {
  toHost({
    method: "ui/notifications/tool-result",
    params: { structuredContent: { shown: true }, isError: false, _meta: meta },
  });
}

function errorAnswer(code: string, reason?: string): Answer {
  return {
    isError: true,
    structuredContent: reason === undefined ? { code } : { code, reason },
  };
}

async function startBridge() {
  vi.spyOn(window, "postMessage").mockImplementation((message: unknown) => {
    const request = message as Sent;
    sent.push(request);
    if (request.method === "ui/initialize") {
      queueMicrotask(() =>
        toHost({
          id: request.id,
          result: {
            protocolVersion: MCP_APPS_PROTOCOL_VERSION,
            hostContext: {},
          },
        }),
      );
    } else if (request.method === "tools/call") {
      const answer = answers.shift() ?? { structuredContent: {} };
      queueMicrotask(() => toHost({ id: request.id, result: answer }));
    }
  });
  const bridge = createHostBridge({ name: "Test app", version: "1.0.0" });
  await bridge.initialize();
  sent.length = 0;
  return bridge;
}

function toolCalls(): Sent[] {
  return sent.filter((m) => m.method === "tools/call");
}

afterEach(() => {
  sent.length = 0;
  answers = [];
  vi.restoreAllMocks();
});

describe("decision ticket", () => {
  it("sends a ticket from a tool-result notification with the decision, and the origin mark too", async () => {
    const bridge = await startBridge();
    toolResultNotification(ticketMeta({ "approve_ai_plan:t1": "ticket-a" }));

    await bridge.call("approve_ai_plan", { task_id: "t1" });

    const [call] = toolCalls();
    expect(call?.params?.name).toBe("approve_ai_plan");
    expect(call?.params?.arguments).toEqual({
      task_id: "t1",
      decision_ticket: "ticket-a",
    });
    expect(call?.params?._meta).toEqual(APP_ORIGIN_META);
  });

  it("takes tickets from a tools/call answer, one per object", async () => {
    const bridge = await startBridge();
    answers = [
      {
        structuredContent: { plan: true },
        _meta: ticketMeta({
          "approve_ai_plan:t1": "ticket-approve",
          "run_ai_plan:t1": "ticket-run",
        }),
      },
    ];
    await bridge.call("get_ai_plan", { task_id: "t1" });

    await bridge.call("run_ai_plan", { task_id: "t1" });
    await bridge.call("approve_ai_plan", { task_id: "t1" });

    const [, run, approve] = toolCalls();
    expect(run?.params?.arguments).toEqual({
      task_id: "t1",
      decision_ticket: "ticket-run",
    });
    expect(approve?.params?.arguments).toEqual({
      task_id: "t1",
      decision_ticket: "ticket-approve",
    });
  });

  it.each([
    ["approve_automation", "automation_id", "a7"],
    ["approve_suggestion_group", "group_digest", "d9"],
  ])("binds %s to its own object argument", async (tool, arg, id) => {
    const bridge = await startBridge();
    toolResultNotification(ticketMeta({ [`${tool}:${id}`]: "ticket-x" }));

    await bridge.call(tool, { [arg]: id });

    expect(toolCalls()[0]?.params?.arguments).toEqual({
      [arg]: id,
      decision_ticket: "ticket-x",
    });
  });

  it("never sends a ticket to another tool or for another object", async () => {
    const bridge = await startBridge();
    toolResultNotification(
      ticketMeta({
        "approve_ai_plan:t1": "ticket-a",
        "approve_automation:a1": "ticket-b",
      }),
    );

    await bridge.call("update_task", { id: "t1" });
    await bridge.call("approve_ai_plan", { task_id: "t2" });
    await bridge.call("get_ai_plan", { task_id: "t1" });
    await bridge.call("run_ai_plan", { task_id: "t1" });
    await bridge.call("approve_automation", { automation_id: "a2" });

    for (const call of toolCalls())
      expect(call.params?.arguments).not.toHaveProperty("decision_ticket");
  });

  it("uses a ticket once: a second decision without a new ticket sends none", async () => {
    const bridge = await startBridge();
    toolResultNotification(ticketMeta({ "approve_ai_plan:t1": "ticket-a" }));

    await bridge.call("approve_ai_plan", { task_id: "t1" });
    await bridge.call("approve_ai_plan", { task_id: "t1" });

    const [first, second] = toolCalls();
    expect(first?.params?.arguments).toHaveProperty("decision_ticket");
    expect(second?.params?.arguments).toEqual({ task_id: "t1" });
  });

  it("ignores malformed, oversized and non-string tickets", async () => {
    const bridge = await startBridge();
    toolResultNotification(ticketMeta("not-an-object"));
    toolResultNotification(ticketMeta(["approve_ai_plan:t1"]));
    toolResultNotification(
      ticketMeta({
        "approve_ai_plan:t1": "x".repeat(161),
        "approve_ai_plan:t2": 42,
        "approve_ai_plan:t3": "",
        "approve_ai_plan:t4": { nested: "ticket" },
      }),
    );
    toolResultNotification(undefined);
    const tooMany: Record<string, string> = {};
    for (let i = 0; i < 201; i++) tooMany[`approve_ai_plan:m${i}`] = "t";
    toolResultNotification(ticketMeta(tooMany));

    for (const id of ["t1", "t2", "t3", "t4", "m0"])
      await bridge.call("approve_ai_plan", { task_id: id }).catch(() => {});

    expect(toolCalls()).toHaveLength(5);
    for (const call of toolCalls())
      expect(call.params?.arguments).not.toHaveProperty("decision_ticket");
  });

  it("accepts a ticket of exactly 160 characters", async () => {
    const bridge = await startBridge();
    const ticket = "y".repeat(160);
    toolResultNotification(ticketMeta({ "approve_ai_plan:t1": ticket }));

    await bridge.call("approve_ai_plan", { task_id: "t1" });

    expect(toolCalls()[0]?.params?.arguments?.decision_ticket).toBe(ticket);
  });

  it("does not hand the ticket to tool-result listeners", async () => {
    const bridge = await startBridge();
    const seen: unknown[] = [];
    bridge.onToolResult((result) => seen.push(result));

    toolResultNotification(
      ticketMeta({ "approve_ai_plan:t1": "secret-ticket" }),
    );

    expect(seen).toEqual([
      { structuredContent: { shown: true }, isError: false },
    ]);
    expect(JSON.stringify(seen)).not.toContain("secret-ticket");
  });
});

describe("decision ticket refresh on app_only", () => {
  it.each([
    [
      "approve_ai_plan",
      { task_id: "t1" },
      "get_ai_plan",
      { task_id: "t1" },
      "approve_ai_plan:t1",
    ],
    [
      "run_ai_plan",
      { task_id: "t1" },
      "get_ai_plan",
      { task_id: "t1" },
      "run_ai_plan:t1",
    ],
    [
      "approve_automation",
      { automation_id: "a1" },
      "get_automation",
      { automation_id: "a1" },
      "approve_automation:a1",
    ],
    [
      "approve_suggestion_group",
      { group_digest: "d1" },
      "list_suggestions",
      {},
      "approve_suggestion_group:d1",
    ],
  ])(
    "%s: reads fresh tickets once, then decides again with the new ticket",
    async (tool, args, readTool, readArgs, key) => {
      const bridge = await startBridge();
      answers = [
        errorAnswer("forbidden", "app_only"),
        { structuredContent: {}, _meta: ticketMeta({ [key]: "fresh" }) },
        { structuredContent: { done: true } },
      ];

      await expect(bridge.call(tool, args)).resolves.toEqual({ done: true });

      const calls = toolCalls();
      expect(calls.map((c) => c.params?.name)).toEqual([tool, readTool, tool]);
      expect(calls[0]?.params?.arguments).toEqual(args);
      expect(calls[1]?.params?.arguments).toEqual(readArgs);
      expect(calls[2]?.params?.arguments).toEqual({
        ...args,
        decision_ticket: "fresh",
      });
    },
  );

  it("tries only once more: a second app_only is thrown, with no further calls", async () => {
    const bridge = await startBridge();
    answers = [
      errorAnswer("forbidden", "app_only"),
      { structuredContent: {} },
      errorAnswer("forbidden", "app_only"),
    ];

    const failure = await bridge
      .call("approve_ai_plan", { task_id: "t1" })
      .catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(HostToolError);
    expect((failure as HostToolError).reason).toBe("app_only");
    expect(toolCalls().map((c) => c.params?.name)).toEqual([
      "approve_ai_plan",
      "get_ai_plan",
      "approve_ai_plan",
    ]);
  });

  it("throws the original error when the refresh read fails", async () => {
    const bridge = await startBridge();
    answers = [errorAnswer("forbidden", "app_only"), errorAnswer("not_found")];

    const failure = await bridge
      .call("approve_automation", { automation_id: "a1" })
      .catch((error: unknown) => error);

    expect((failure as HostToolError).reason).toBe("app_only");
    expect(toolCalls()).toHaveLength(2);
  });

  it("does not refresh on other errors such as conflict", async () => {
    const bridge = await startBridge();
    answers = [errorAnswer("conflict")];

    const failure = await bridge
      .call("approve_ai_plan", { task_id: "t1" })
      .catch((error: unknown) => error);

    expect((failure as HostToolError).code).toBe("conflict");
    expect(toolCalls()).toHaveLength(1);
  });

  it("does not refresh for tools that take no ticket", async () => {
    const bridge = await startBridge();
    answers = [errorAnswer("forbidden", "app_only")];

    const failure = await bridge
      .call("move_to_trash", { id: "1" })
      .catch((error: unknown) => error);

    expect((failure as HostToolError).reason).toBe("app_only");
    expect(toolCalls()).toHaveLength(1);
  });
});

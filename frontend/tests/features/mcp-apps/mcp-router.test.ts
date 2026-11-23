import { expect, it } from "vitest";
import {
  isRoomId,
  routeFor,
  routeForShape,
  routeForTool,
  TOOL_ROUTES,
} from "@/features/mcp-apps/router";
import { readRepoFile } from "@tests/helpers/source-files";

type ContractTool = {
  name: string;
  _meta?: { ui?: { resourceUri?: string } };
};

function contractTools(): ContractTool[] {
  return JSON.parse(
    readRepoFile("contracts/mcp-tools.generated.json"),
  ) as ContractTool[];
}

// N3: a new opener tool without a routerpost must fail here, not silently draw nothing.
it("has a route for every tool that declares a resourceUri", () => {
  const openers = contractTools().filter(
    (tool) => tool._meta?.ui?.resourceUri !== undefined,
  );
  expect(openers.length).toBeGreaterThan(10);
  const missing = openers
    .map((tool) => tool.name)
    .filter((name) => routeForTool(name) === undefined);
  expect(missing).toEqual([]);
});

it("only routes tool names that exist in the contract", () => {
  const names = new Set(contractTools().map((tool) => tool.name));
  const unknown = Object.keys(TOOL_ROUTES).filter((name) => !names.has(name));
  expect(unknown).toEqual([]);
});

it("routes the contact tools to Contacts although their resource is the Work app", () => {
  for (const name of [
    "list_contacts",
    "get_contact_context",
    "create_contact",
    "update_contact",
  ])
    expect(routeForTool(name)?.room).toBe("contacts");
});

it("maps each opener family to its room", () => {
  expect(routeForTool("get_work_board")).toEqual({
    room: "work",
    view: "board",
  });
  expect(routeForTool("get_journal_day")).toEqual({
    room: "journal",
    view: "day",
  });
  expect(routeForTool("get_shopping_list")).toEqual({
    room: "shopping",
    view: "list",
  });
  expect(routeForTool("list_trash")).toEqual({
    room: "control",
    view: "trash",
  });
  expect(routeForTool("get_review_queue")).toEqual({
    room: "work",
    view: "review",
  });
});

it("returns undefined for an unknown, empty or non-string name", () => {
  expect(routeForTool("delete_everything")).toBeUndefined();
  expect(routeForTool("")).toBeUndefined();
  expect(routeForTool(undefined)).toBeUndefined();
  expect(routeForTool(7)).toBeUndefined();
  expect(routeForTool("toString")).toBeUndefined();
  expect(routeForTool("__proto__")).toBeUndefined();
});

it("accepts a tool name the host has namespaced", () => {
  expect(routeForTool("sidekick__get_task")).toEqual({
    room: "work",
    view: "task",
  });
  expect(routeForTool("sidekick:get_task")?.room).toBe("work");
  expect(routeForTool("sidekick.unknown_tool")).toBeUndefined();
});

it("accepts a namespace that ends in an underscore", () => {
  expect(routeForTool("my_server___get_task")).toEqual({
    room: "work",
    view: "task",
  });
  expect(routeForTool("_____list_trash")?.room).toBe("control");
});

const workItem = { kind: "task", id: "t1", title: "Ring", status: "todo" };

const SHAPES: [string, unknown, { room: string; view: string }][] = [
  [
    "work_changes card",
    { card: { kind: "work_changes", items: [], total: 0, truncated: false } },
    { room: "work", view: "changes" },
  ],
  [
    "review queue",
    {
      tasks: [],
      scope: "suggested",
      remaining_total: 0,
      bucket_counts: {},
      next_cursor: null,
    },
    { room: "work", view: "review" },
  ],
  ["task", { task: { id: "t1" } }, { room: "work", view: "task" }],
  ["project", { project: { id: "p1" } }, { room: "work", view: "project" }],
  [
    "contact with context",
    {
      contact: { id: "c1" },
      projects: { items: [] },
      tasks: { items: [] },
      journal_entries: [],
    },
    { room: "contacts", view: "contact" },
  ],
  [
    "bare contact",
    { contact: { id: "c1" } },
    { room: "contacts", view: "compact" },
  ],
  [
    "contact list",
    { contacts: [{ id: "c1", display_name: "Anna" }] },
    { room: "contacts", view: "list" },
  ],
  [
    "journal day",
    { journal_date: "2026-11-03", entries: [], summary: {} },
    { room: "journal", view: "day" },
  ],
  [
    "journal entry",
    { entry: { id: "e1" } },
    { room: "journal", view: "entry" },
  ],
  [
    "journal draft",
    { draft: { id: "d1" }, source: {} },
    { room: "journal", view: "draft" },
  ],
  [
    "pending journal",
    { items: [{ source_id: "s1", journal_date: "2026-11-03", state: "open" }] },
    { room: "journal", view: "pending" },
  ],
  [
    "shopping list",
    { shopping_list: { id: "l1" }, items: [], store: null },
    { room: "shopping", view: "list" },
  ],
  [
    "shopping batch",
    { items: [{ item: { name: "Mjölk" }, merged: false }], list_name: "Mat" },
    { room: "shopping", view: "batch" },
  ],
  [
    "shopping update",
    { item: { name: "Mjölk" }, list_name: "Mat" },
    { room: "shopping", view: "batch" },
  ],
  [
    "memory status",
    { settings: {}, provider: "hindsight", sources: [] },
    { room: "control", view: "memory" },
  ],
  ["recent changes", { changes: [] }, { room: "control", view: "changes" }],
  ["trash", { items: [], has_more: false }, { room: "control", view: "trash" }],
  [
    "assistant activity",
    {
      items: [{ source: "mcp", state: "ok", operation: "x", summary: "y" }],
      next_cursor: null,
    },
    { room: "control", view: "activity" },
  ],
  [
    "hierarchy",
    { nodes: [], truncated: false },
    { room: "work", view: "hierarchy" },
  ],
  ["board", { columns: { todo: [workItem] } }, { room: "work", view: "board" }],
  [
    "agenda",
    { items: [workItem], filters: {}, next_cursor: null },
    { room: "work", view: "agenda" },
  ],
  [
    "empty agenda",
    { items: [], filters: {}, next_cursor: null },
    { room: "work", view: "agenda" },
  ],
];

it.each(SHAPES)(
  "reads the shape of %s when the tool name is missing",
  (_n, data, route) => {
    expect(routeForShape(data)).toEqual(route);
    expect(routeFor({ structuredContent: data })).toEqual(route);
  },
);

it("routes the suggestion tools to Start, and not the app-only group approval", () => {
  expect(routeForTool("list_suggestions")).toEqual({
    room: "start",
    view: "suggestions",
  });
  expect(routeForTool("get_suggestion")).toEqual({
    room: "start",
    view: "suggestion",
  });
  expect(routeForTool("decide_suggestions")).toEqual({
    room: "start",
    view: "decided",
  });
  expect(routeForTool("undo_suggestion")).toEqual({
    room: "start",
    view: "decided",
  });
  expect(routeForTool("approve_suggestion_group")).toBeUndefined();
});

it("reads the shapes of the suggestion results, before the shapes that share items", () => {
  const inbox = { room: "start", view: "suggestions" };
  expect(routeForShape({ groups: [], items: [], hidden: 0 })).toEqual(inbox);
  expect(
    routeForShape({ groups: [{ count: 1 }], items: [{ id: "s1" }], hidden: 2 }),
  ).toEqual(inbox);
  expect(routeForShape({ suggestion: { id: "s1" } })).toEqual({
    room: "start",
    view: "suggestion",
  });
  const decided = { room: "start", view: "decided" };
  expect(
    routeForShape({
      items: [
        { suggestion_id: "s1", state: "applied" },
        { suggestion_id: "s2", state: "pending", error_code: "stale" },
      ],
    }),
  ).toEqual(decided);
  expect(
    routeForShape({ suggestion_id: "s1", state: "undone", trashed: null }),
  ).toEqual(decided);
  // An empty items list or items of another kind are not a decision.
  expect(routeForShape({ items: [{ suggestion_id: "s1" }] })).toBeUndefined();
  expect(
    routeForShape({ suggestion_id: "s1", state: "undone" }),
  ).toBeUndefined();
});

it("does not mistake a work item list for pending journal or activity", () => {
  const workList = {
    items: [{ ...{ kind: "task", id: "t", title: "x", status: "todo" } }],
  };
  expect(routeForShape(workList)?.room).toBe("work");
});

it("returns undefined for an unknown shape, a non-object and an error", () => {
  expect(routeForShape({ unrelated: true })).toBeUndefined();
  expect(routeForShape({ items: [{ nothing: 1 }] })).toBeUndefined();
  expect(routeForShape(null)).toBeUndefined();
  expect(routeForShape("text")).toBeUndefined();
  expect(routeForShape([workItem])).toBeUndefined();
  expect(
    routeFor({ structuredContent: { task: { id: "t1" } }, isError: true }),
  ).toBeUndefined();
  expect(routeFor({})).toBeUndefined();
});

it("prefers the tool name over the shape", () => {
  // create_contact answers a bare contact, but the shape alone is ambiguous with get_contact_context.
  expect(
    routeFor({
      toolName: "get_task",
      structuredContent: { contact: { id: "c" } },
    }),
  ).toEqual({ room: "work", view: "task" });
});

it("falls back to the shape when the name is unknown", () => {
  expect(
    routeFor({
      toolName: "mystery",
      structuredContent: { task: { id: "t1" } },
    }),
  ).toEqual({ room: "work", view: "task" });
});

it("recognises room ids", () => {
  expect(isRoomId("contacts")).toBe(true);
  expect(isRoomId("home")).toBe(false);
  expect(isRoomId(undefined)).toBe(false);
});

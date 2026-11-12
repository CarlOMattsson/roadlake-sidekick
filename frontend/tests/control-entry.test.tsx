import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  afterAll,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

type ToolResultListener = (result: {
  structuredContent: unknown;
  isError: boolean;
}) => void;

type HostContextListener = (context: {
  toolInfo?: { tool?: { name?: string } };
}) => void;

// The bridge is the only thing mocked: sidekick-entry runs at import time and binds its listeners here.
// `call` is shared, so each test can route the app's tools/call answers by tool name.
const host = vi.hoisted(() => ({
  toolResult: [] as ToolResultListener[],
  hostContext: [] as HostContextListener[],
  initialize: vi.fn(),
  call: vi.fn<
    (name: string, args: Record<string, unknown>) => Promise<unknown>
  >(),
  updateModelContext: vi.fn<(summary: string) => Promise<void>>(),
}));

vi.mock("@/features/mcp-apps/bridge", () => ({
  createHostBridge: () => ({
    initialize: host.initialize,
    call: host.call,
    updateModelContext: host.updateModelContext,
    getFeatures: () => ({
      serverTools: false,
      message: false,
      openLinks: false,
    }),
    sendMessage: vi.fn().mockResolvedValue(false),
    onToolResult: (listener: ToolResultListener) => {
      host.toolResult.push(listener);
    },
    onHostContext: (listener: HostContextListener) => {
      host.hostContext.push(listener);
    },
    onTeardown: () => undefined,
  }),
}));

const ID_TASK = "019f0000-0000-7000-8000-000000000101";
const ID_ITEM = "019f0000-0000-7000-8000-0000000000a1";
const KEY =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
// A UUID v4 idempotency key: any value of this shape is accepted, the exact key is not known in advance.
const ANY_KEY = expect.stringMatching(KEY) as string;

const trashed = {
  items: [
    {
      kind: "task",
      id: ID_TASK,
      label: "Förbered pitchen",
      trashed_at: "2026-10-31T13:30:00Z",
      version: 4,
    },
  ],
  has_more: false,
  next_cursor: null,
};

const changes = {
  changes: [
    {
      kind: "task",
      id: ID_TASK,
      title: "Förbered pitchen",
      version: 5,
      action: "trashed",
      state: "trashed",
      occurred_at: "2026-10-31T13:30:00Z",
    },
  ],
};

const purchased = {
  changes: [
    {
      kind: "shopping_item",
      id: ID_ITEM,
      title: "Milk",
      version: 3,
      action: "purchased",
      state: "active",
      occurred_at: "2026-10-31T12:00:00Z",
      undo_tool: "set_shopping_item_purchased",
    },
  ],
};

const reopened = {
  changes: [
    {
      ...purchased.changes[0],
      action: "reopened",
    },
  ],
};

const memoryOn = {
  settings: {
    journal: true,
    contacts: false,
    projects: false,
    tasks: false,
    paused: false,
    version: 2,
  },
  provider: "hindsight",
  sources: [],
};

const activityList = {
  items: [
    {
      id: "019f0000-0000-7000-8000-000000000201",
      category: "task_maintenance",
      source: "assistant",
      operation: "update_task",
      state: "applied",
      aggregate_type: "task",
      summary: "Flyttade Förbered pitchen till Klar",
      occurred_at: "2026-10-31T13:30:00Z",
    },
  ],
  next_cursor: null,
};

const memoryOff = {
  settings: {
    journal: false,
    contacts: false,
    projects: false,
    tasks: false,
    paused: false,
    version: 3,
  },
  provider: "hindsight",
  sources: [],
};

afterAll(() => {
  document.head.innerHTML = "";
});

beforeAll(async () => {
  // The app reads its language once, when sidekick-entry is imported, so the Sidekick setting goes in first.
  document.head.innerHTML = '<meta name="sidekick-app-locale" content="sv">';
  document.body.innerHTML = '<div id="root"></div>';
  host.initialize.mockResolvedValue({ locale: "sv-SE" });
  await import("@/features/mcp-apps/sidekick-entry");
});

beforeEach(() => {
  host.call.mockReset();
  host.updateModelContext.mockReset();
  host.updateModelContext.mockResolvedValue(undefined);
});

/** Routes the app's tools/call by tool name. An unexpected tool fails the call, so it shows up. */
function answer(answers: Record<string, unknown>) {
  host.call.mockImplementation((name: string) =>
    name in answers
      ? Promise.resolve(answers[name])
      : Promise.reject(new Error(`unexpected tool ${name}`)),
  );
}

/**
 * Delivers one tool result to the mounted app, as the host does after a model tool call. The host
 * names the tool in its host context. Without a name the app routes by shape, which every answer
 * but an error has; an error has no shape, so the error cases pass the tool that failed.
 */
function deliver(structuredContent: unknown, isError = false, tool?: string) {
  act(() => {
    for (const listener of host.hostContext)
      listener({
        toolInfo: tool === undefined ? undefined : { tool: { name: tool } },
      });
    for (const listener of host.toolResult)
      listener({ structuredContent, isError });
  });
}

describe("control entry before and at the first answer", () => {
  it("shows the waiting state before the first tool result", async () => {
    const waiting = await screen.findByRole("status");
    expect(waiting).toHaveAttribute("aria-busy", "true");
  });

  it("shows the failure as an alert when the first answer is an error", async () => {
    deliver({ code: "forbidden" }, true, "list_trash");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Papperskorgen kunde inte hämtas",
    );
  });

  // The order of these three matters: the module keeps its state, and the last one ends with a card.
  it("Försök igen after a failed read keeps the error notice and never shows the error text", async () => {
    const user = userEvent.setup();
    deliver({ code: "forbidden" }, true, "list_trash");
    host.call.mockRejectedValueOnce(new Error("upstream detail"));

    await user.click(
      await screen.findByRole("button", { name: "Försök igen" }),
    );
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Papperskorgen kunde inte hämtas",
    );
    expect(screen.getByRole("alert")).not.toHaveTextContent("upstream detail");
    expect(
      screen.getByRole("button", { name: "Försök igen" }),
    ).toBeInTheDocument();
  });

  it("Försök igen after a failed first answer reads the card's view and shows it", async () => {
    const user = userEvent.setup();
    deliver({ code: "forbidden" }, true, "list_trash");
    answer({ list_trash: trashed });

    await user.click(
      await screen.findByRole("button", { name: "Försök igen" }),
    );

    expect(host.call).toHaveBeenLastCalledWith("list_trash", {});
    expect(
      await screen.findByRole("heading", { name: "Borttaget" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("control entry shows the card for each answer", () => {
  it("list_trash shows the trash heading, the count as a meta line and its rows", () => {
    deliver(trashed);
    expect(
      screen.getByRole("heading", { name: "Borttaget" }),
    ).toBeInTheDocument();
    expect(document.querySelector("p.control-meta")).toHaveTextContent(
      /^\d+ (borttagen|borttagna) · kan återställas$/,
    );
    expect(screen.getByText("Förbered pitchen")).toBeInTheDocument();
  });

  it("list_recent_changes shows the changes heading and its rows", () => {
    deliver(changes);
    expect(
      screen.getByRole("heading", { name: "Historik" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Förbered pitchen")).toBeInTheDocument();
  });

  it("get_memory_status shows that memory is on", () => {
    deliver(memoryOn);
    expect(
      screen.getByRole("heading", { name: "Minnet är på" }),
    ).toBeInTheDocument();
  });

  it("get_memory_status with the fake provider says it is a test service, not that memory is on", () => {
    deliver({ ...memoryOn, provider: "fake" });
    expect(
      screen.getByRole("heading", { name: "Minnet använder en testtjänst" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Minnet är på" }),
    ).not.toBeInTheDocument();
  });

  it("a new answer replaces the card that was shown", () => {
    deliver(trashed);
    expect(
      screen.getByRole("heading", { name: "Borttaget" }),
    ).toBeInTheDocument();
    deliver(changes);
    expect(
      screen.getByRole("heading", { name: "Historik" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Borttaget" }),
    ).not.toBeInTheDocument();
  });
});

describe("control entry actions call the existing tools with exact arguments", () => {
  it("Återställ calls restore_from_trash with the item's kind, id and version", async () => {
    const user = userEvent.setup();
    answer({ restore_from_trash: {} });
    deliver(trashed);

    await user.click(
      screen.getByRole("button", { name: "Återställ Förbered pitchen" }),
    );

    expect(host.call).toHaveBeenCalledTimes(1);
    expect(host.call).toHaveBeenCalledWith("restore_from_trash", {
      kind: "task",
      record_id: ID_TASK,
      version: 4,
      idempotency_key: ANY_KEY,
    });
  });

  it("Återställ tells the host model one generic sentence, never the title", async () => {
    const user = userEvent.setup();
    answer({ restore_from_trash: {} });
    deliver(trashed);

    await user.click(
      screen.getByRole("button", { name: "Återställ Förbered pitchen" }),
    );

    expect(host.updateModelContext).toHaveBeenCalledTimes(1);
    expect(host.updateModelContext).toHaveBeenCalledWith(
      "Användaren återställde en post ur papperskorgen i kortet.",
    );
    expect(host.updateModelContext.mock.calls[0]?.[0]).not.toContain(
      "Förbered",
    );
  });

  it("Ångra on a purchase calls set_shopping_item_purchased with purchased false", async () => {
    const user = userEvent.setup();
    answer({ set_shopping_item_purchased: {}, list_recent_changes: purchased });
    deliver(purchased);

    await user.click(screen.getByRole("button", { name: "Ångra Milk" }));

    expect(host.call).toHaveBeenCalledWith("set_shopping_item_purchased", {
      item_id: ID_ITEM,
      purchased: false,
      version: 3,
      idempotency_key: ANY_KEY,
    });
    expect(await screen.findByRole("status")).toHaveTextContent(
      "“Milk” är inte längre köpt.",
    );
  });

  it("Ångra on a put-back calls set_shopping_item_purchased with purchased true", async () => {
    const user = userEvent.setup();
    answer({ set_shopping_item_purchased: {}, list_recent_changes: reopened });
    deliver(reopened);

    await user.click(screen.getByRole("button", { name: "Ångra Milk" }));

    expect(host.call).toHaveBeenCalledWith("set_shopping_item_purchased", {
      item_id: ID_ITEM,
      purchased: true,
      version: 3,
      idempotency_key: ANY_KEY,
    });
  });

  it("a domain switched on calls set_memory_settings with journal true and no confirm", async () => {
    const user = userEvent.setup();
    answer({
      set_memory_settings: {
        status: "updated",
        settings: memoryOn.settings,
        turning_off: [],
      },
      get_memory_status: memoryOn,
    });
    deliver(memoryOff);

    await user.click(screen.getByRole("switch", { name: "Dagbok: av" }));

    expect(host.call).toHaveBeenCalledWith("set_memory_settings", {
      expected_version: 3,
      journal: true,
    });
    const args = host.call.mock.calls.find(
      ([name]) => name === "set_memory_settings",
    )?.[1] as Record<string, unknown>;
    expect(args).not.toHaveProperty("confirm");
    expect(
      await screen.findByRole("heading", { name: "Minnet är på" }),
    ).toBeInTheDocument();
  });

  it("pause calls set_memory_settings with paused true", async () => {
    const user = userEvent.setup();
    answer({
      set_memory_settings: {
        status: "updated",
        settings: { ...memoryOn.settings, paused: true },
        turning_off: [],
      },
      get_memory_status: memoryOn,
    });
    deliver(memoryOn);

    await user.click(screen.getByRole("button", { name: "Pausa minnet" }));

    expect(host.call).toHaveBeenCalledWith("set_memory_settings", {
      expected_version: 2,
      paused: true,
    });
  });

  it("turning a domain off asks first, and only the owner's confirmation sends confirm", async () => {
    const user = userEvent.setup();
    const confirmation = {
      status: "needs_confirmation",
      settings: memoryOn.settings,
      turning_off: [{ domain: "journal", documents: 4 }],
    };
    host.call.mockImplementation(
      (name: string, args: Record<string, unknown>) => {
        if (name === "set_memory_settings")
          return Promise.resolve(
            args.confirm === true
              ? {
                  status: "updated",
                  settings: memoryOff.settings,
                  turning_off: [],
                }
              : confirmation,
          );
        if (name === "get_memory_status") return Promise.resolve(memoryOff);
        return Promise.reject(new Error(`unexpected tool ${name}`));
      },
    );
    deliver(memoryOn);

    await user.click(screen.getByRole("switch", { name: "Dagbok: på" }));

    expect(await screen.findByText("Slå av dagboken?")).toBeInTheDocument();
    expect(host.call).toHaveBeenCalledWith("set_memory_settings", {
      expected_version: 2,
      journal: false,
    });
    const first = host.call.mock.calls.find(
      ([name]) => name === "set_memory_settings",
    )?.[1] as Record<string, unknown>;
    expect(first).not.toHaveProperty("confirm");

    await user.click(
      screen.getByRole("button", {
        name: "Ja, radera minnet av dagboken",
      }),
    );

    expect(host.call).toHaveBeenCalledWith("set_memory_settings", {
      expected_version: 2,
      journal: false,
      confirm: true,
    });
    const confirmed = host.call.mock.calls.filter(
      ([name, args]) => name === "set_memory_settings" && args.confirm === true,
    );
    expect(confirmed).toHaveLength(1);
  });

  it("Avbryt in the confirmation sends nothing more", async () => {
    const user = userEvent.setup();
    host.call.mockResolvedValue({
      status: "needs_confirmation",
      settings: memoryOn.settings,
      turning_off: [{ domain: "journal", documents: null }],
    });
    deliver(memoryOn);

    await user.click(screen.getByRole("switch", { name: "Dagbok: på" }));
    const dialog = await screen.findByRole("group", {
      name: "Slå av dagboken?",
    });
    const before = host.call.mock.calls.length;

    await user.click(within(dialog).getByRole("button", { name: "Avbryt" }));

    expect(host.call.mock.calls.length).toBe(before);
    expect(screen.queryByText("Slå av dagboken?")).not.toBeInTheDocument();
  });

  it("choosing a view reads it once, with the tool that belongs to it", async () => {
    const user = userEvent.setup();
    answer({
      list_recent_changes: changes,
      list_assistant_activity: activityList,
      list_trash: trashed,
      get_memory_status: memoryOn,
    });

    deliver(trashed);
    await user.click(screen.getByRole("button", { name: "Historik" }));
    expect(host.call).toHaveBeenCalledWith("list_recent_changes", {
      limit: 20,
    });
    expect(host.call).toHaveBeenCalledWith("list_assistant_activity", {
      limit: 25,
    });

    deliver(changes);
    await user.click(screen.getByRole("button", { name: "Borttaget" }));
    expect(host.call).toHaveBeenLastCalledWith("list_trash", {});

    deliver(changes);
    await user.click(screen.getByRole("button", { name: "Sidekicks minne" }));
    expect(host.call).toHaveBeenLastCalledWith("get_memory_status", {});
  });

  it("choosing Historik reads both parts and merges them, and never changes anything", async () => {
    const user = userEvent.setup();
    answer({
      list_trash: trashed,
      list_recent_changes: changes,
      list_assistant_activity: activityList,
    });

    deliver(trashed);
    await user.click(screen.getByRole("button", { name: "Historik" }));
    expect(
      await screen.findByText("Flyttade Förbered pitchen till Klar"),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("heading", { name: "Historik" }),
    ).toBeInTheDocument();
    expect(host.updateModelContext).not.toHaveBeenCalled();
  });

  it("an answer with only the changes reads the activity for itself", async () => {
    answer({ list_assistant_activity: activityList });

    deliver(changes);

    expect(
      await screen.findByText("Flyttade Förbered pitchen till Klar"),
    ).toBeInTheDocument();
    expect(host.call).toHaveBeenCalledWith("list_assistant_activity", {
      limit: 25,
    });
    expect(host.call).not.toHaveBeenCalledWith(
      "list_recent_changes",
      expect.anything(),
    );
  });
});

describe("control entry shows History for list_assistant_activity", () => {
  it("an activity answer shows the history heading and its rows, with no action buttons", () => {
    deliver(activityList);

    expect(
      screen.getByRole("heading", { name: "Historik" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Flyttade Förbered pitchen till Klar"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Återställ Förbered pitchen" }),
    ).not.toBeInTheDocument();
  });
});

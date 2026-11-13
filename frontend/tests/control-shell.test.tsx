import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  ControlApp,
  viewOf,
  type ControlData,
  type ControlViewName,
} from "@/features/control-app/control-app";
import { controlSv } from "@/features/control-app/labels";
import type {
  ActivityList,
  ChangesList,
  ControlTransport,
  MemoryStatus,
  TrashItem,
  TrashList,
} from "@/features/control-app/transport";

const now = () => new Date("2026-11-01T10:00:00Z");

const trashed: TrashList = {
  items: [
    {
      kind: "task",
      id: "019f0000-0000-7000-8000-000000000101",
      label: "Förbered pitchen",
      trashed_at: "2026-10-31T13:30:00Z",
      version: 4,
    },
  ],
  has_more: false,
  next_cursor: null,
};

const emptyTrash: TrashList = { items: [], has_more: false, next_cursor: null };

const changes: ChangesList = {
  changes: [
    {
      kind: "task",
      id: "019f0000-0000-7000-8000-000000000101",
      title: "Förbered pitchen",
      version: 5,
      action: "trashed",
      state: "trashed",
      occurred_at: "2026-10-31T13:30:00Z",
    },
  ],
};

const memoryOn: MemoryStatus = {
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

const memoryOff: MemoryStatus = {
  settings: {
    journal: false,
    contacts: false,
    projects: false,
    tasks: false,
    paused: false,
    version: 0,
  },
  provider: "hindsight",
  sources: [],
};

const emptyActivity: ActivityList = { items: [], next_cursor: null };

const activity: ActivityList = {
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

function makeTransport(
  overrides: Partial<ControlTransport> = {},
): ControlTransport {
  return {
    trash: vi.fn(() => Promise.resolve(emptyTrash)),
    restore: vi.fn(() => Promise.resolve({})),
    changes: vi.fn(() => Promise.resolve(changes)),
    undoPurchase: vi.fn(() => Promise.resolve({})),
    memoryStatus: vi.fn(() => Promise.resolve(memoryOn)),
    setMemory: vi.fn(),
    activity: vi.fn(() => Promise.resolve(emptyActivity)),
    ...overrides,
  };
}

function renderApp(
  transport: ControlTransport,
  initialView: ControlViewName,
  initialData: ControlData,
) {
  return render(
    <ControlApp
      transport={transport}
      labels={controlSv}
      initialView={initialView}
      initialData={initialData}
      now={now}
    />,
  );
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function viewButton(name: string) {
  return screen.getByRole("button", { name });
}

describe("viewOf", () => {
  it("reads a list_trash answer as the trash view", () => {
    expect(viewOf(trashed)).toEqual({ view: "trash", data: trashed });
  });

  it("reads an empty trash answer as the trash view too", () => {
    expect(viewOf(emptyTrash)).toEqual({ view: "trash", data: emptyTrash });
  });

  it("reads a list_recent_changes answer as the history view, also when empty", () => {
    expect(viewOf(changes)).toEqual({ view: "history", data: { changes } });
    expect(viewOf({ changes: [] })).toEqual({
      view: "history",
      data: { changes: { changes: [] } },
    });
  });

  it("reads a get_memory_status answer as the memory view", () => {
    expect(viewOf(memoryOn)).toEqual({ view: "memory", data: memoryOn });
  });

  it("reads a list_assistant_activity answer as the history view, also when empty", () => {
    expect(viewOf(activity)).toEqual({ view: "history", data: { activity } });
    expect(viewOf(emptyActivity)).toEqual({
      view: "history",
      data: { activity: emptyActivity },
    });
  });

  it("does not take an activity answer with next_cursor for the trash", () => {
    expect(viewOf({ items: [{ id: "a" }], next_cursor: null })).toBeUndefined();
  });

  it("gives undefined for null, a string and an empty object", () => {
    expect(viewOf(null)).toBeUndefined();
    expect(viewOf("trash")).toBeUndefined();
    expect(viewOf({})).toBeUndefined();
  });
});

describe("ControlApp heading and switch", () => {
  it("shows the heading of the initial trash view and the count as a meta line", () => {
    renderApp(makeTransport(), "trash", { trash: trashed });
    expect(
      screen.getByRole("heading", { name: "Borttaget" }),
    ).toBeInTheDocument();
    expect(document.querySelector(".control-meta")).toHaveTextContent(
      /^\d+ (borttagen|borttagna) · kan återställas$/,
    );
  });

  it("shows the heading of the initial history view", () => {
    renderApp(makeTransport(), "history", { changes, activity });
    expect(
      screen.getByRole("heading", { name: "Historik" }),
    ).toBeInTheDocument();
  });

  it("shows that memory is on for the initial memory view", () => {
    renderApp(makeTransport(), "memory", { memory: memoryOn });
    expect(
      screen.getByRole("heading", { name: "Minnet är på" }),
    ).toBeInTheDocument();
  });

  it("shows the test-service heading for the fake provider instead of memory is on", () => {
    renderApp(makeTransport(), "memory", {
      memory: { ...memoryOn, provider: "fake" },
    });
    expect(
      screen.getByRole("heading", { name: "Minnet använder en testtjänst" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Minnet är på" }),
    ).not.toBeInTheDocument();
  });

  it("shows that memory is off when every domain is off", () => {
    renderApp(makeTransport(), "memory", { memory: memoryOff });
    expect(
      screen.getByRole("heading", { name: "Minnet är av" }),
    ).toBeInTheDocument();
  });

  it("shows three visible view buttons and presses the chosen one", () => {
    renderApp(makeTransport(), "history", { changes, activity });
    const group = within(
      screen.getByRole("group", { name: "Minne och kontroll" }),
    );
    expect(group.getAllByRole("button").map((b) => b.textContent)).toEqual([
      "Borttaget",
      "Historik",
      "Sidekicks minne",
    ]);
    expect(viewButton("Borttaget")).toHaveAttribute("aria-pressed", "false");
    expect(viewButton("Historik")).toHaveAttribute("aria-pressed", "true");
    expect(viewButton("Sidekicks minne")).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("draws the name as a visible h2 under the Back row in the full view, with no sentence under the tabs", () => {
    render(
      <ControlApp
        transport={makeTransport()}
        labels={controlSv}
        initialView="history"
        initialData={{ changes, activity }}
        now={now}
        heading
      />,
    );

    expect(document.querySelector(".control-intro")).toBeNull();
    expect(document.querySelector("h2.control-title")).toHaveTextContent(
      controlSv.title,
    );
    expect(document.querySelectorAll("h2.control-title")).toHaveLength(1);
  });

  it("reads the changes view once and keeps it when the owner switches back and forth", async () => {
    const user = userEvent.setup();
    const transport = makeTransport();
    renderApp(transport, "trash", { trash: trashed });

    await user.click(viewButton("Historik"));
    expect(
      await screen.findByRole("heading", { name: "Historik" }),
    ).toBeInTheDocument();
    expect(transport.changes).toHaveBeenCalledTimes(1);

    await user.click(viewButton("Borttaget"));
    await user.click(viewButton("Historik"));
    expect(
      screen.getByRole("heading", { name: "Historik" }),
    ).toBeInTheDocument();
    expect(transport.changes).toHaveBeenCalledTimes(1);
  });

  it("shows a read error as an alert and reads again from the retry button", async () => {
    const user = userEvent.setup();
    const transport = makeTransport({
      changes: vi
        .fn()
        .mockRejectedValueOnce(new Error("boom"))
        .mockResolvedValueOnce(changes),
      activity: vi
        .fn()
        .mockRejectedValueOnce(new Error("boom"))
        .mockResolvedValueOnce(emptyActivity),
    });
    renderApp(transport, "trash", { trash: trashed });

    await user.click(viewButton("Historik"));
    const alert = await screen.findByRole("alert");
    expect(alert).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Försök igen" }));
    expect(
      await screen.findByRole("heading", { name: "Historik" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(transport.changes).toHaveBeenCalledTimes(2);
  });

  it("shows what was read when only one part of History fails, with no error card", async () => {
    const user = userEvent.setup();
    const transport = makeTransport({
      changes: vi.fn(() => Promise.reject(new Error("boom"))),
      activity: vi.fn(() => Promise.resolve(activity)),
    });
    renderApp(transport, "trash", { trash: trashed });

    await user.click(viewButton("Historik"));

    expect(
      await screen.findByText("Flyttade Förbered pitchen till Klar"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("reads only the missing part when the tool answer brought the other", async () => {
    const transport = makeTransport({
      activity: vi.fn(() => Promise.resolve(activity)),
    });
    renderApp(transport, "history", { changes });

    expect(
      await screen.findByText("Flyttade Förbered pitchen till Klar"),
    ).toBeInTheDocument();
    expect(transport.changes).not.toHaveBeenCalled();
    expect(transport.activity).toHaveBeenCalledTimes(1);
  });

  it("drops the answer of an older read when another view was chosen meanwhile", async () => {
    const user = userEvent.setup();
    const slowChanges = deferred<ChangesList>();
    const slowMemory = deferred<MemoryStatus>();
    const transport = makeTransport({
      changes: vi
        .fn()
        .mockReturnValueOnce(slowChanges.promise)
        .mockResolvedValue(changes),
      memoryStatus: vi.fn(() => slowMemory.promise),
    });
    renderApp(transport, "trash", { trash: trashed });

    await user.click(viewButton("Historik"));
    await user.click(viewButton("Sidekicks minne"));

    await act(async () => {
      slowMemory.resolve(memoryOn);
      await Promise.resolve();
    });
    expect(
      await screen.findByRole("heading", { name: "Minnet är på" }),
    ).toBeInTheDocument();

    await act(async () => {
      slowChanges.resolve(changes);
      await Promise.resolve();
    });
    expect(
      screen.getByRole("heading", { name: "Minnet är på" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Historik" }),
    ).not.toBeInTheDocument();

    // The late answer was dropped, not kept: the changes view is read again when chosen.
    await user.click(viewButton("Historik"));
    expect(
      await screen.findByRole("heading", { name: "Historik" }),
    ).toBeInTheDocument();
    expect(transport.changes).toHaveBeenCalledTimes(2);
  });
});

// A view reports its own changes (restore, memory switch) up to the card, so coming back shows them.
describe("ControlApp keeps what the owner changed in a view", () => {
  it("a restored item stays gone when the owner comes back to the trash", async () => {
    const user = userEvent.setup();
    const transport = makeTransport();
    renderApp(transport, "trash", { trash: trashed });

    await user.click(
      screen.getByRole("button", { name: "Återställ Förbered pitchen" }),
    );
    // Leave the tab as soon as the restore is saved, with no wait for a frame or a timer: the view tells the card in the
    // same step that removes the row, so the change follows it to the other tab and back.
    await screen.findByText(controlSv.restored("Förbered pitchen"));
    await user.click(viewButton("Historik"));
    await screen.findByRole("heading", { name: "Historik" });
    await user.click(viewButton("Borttaget"));

    expect(
      screen.queryByRole("button", { name: "Återställ Förbered pitchen" }),
    ).not.toBeInTheDocument();
  });

  it("a restore made in History stays when the owner leaves the tab as soon as the list is read again", async () => {
    const user = userEvent.setup();
    const [trashing] = changes.changes;
    if (!trashing) throw new Error("fixture has no change");
    const restoredList: ChangesList = {
      changes: [{ ...trashing, state: "active" }],
    };
    const transport = makeTransport({
      changes: vi.fn(() => Promise.resolve(restoredList)),
    });
    renderApp(transport, "history", { changes });

    await user.click(
      await screen.findByRole("button", { name: "Återställ Förbered pitchen" }),
    );
    // The row has lost its button once History has read the list again; leave the tab at that moment, with no wait for
    // a frame or a timer, and come back.
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "Återställ Förbered pitchen" }),
      ).not.toBeInTheDocument(),
    );
    await user.click(viewButton("Borttaget"));
    await user.click(viewButton("Historik"));

    expect(
      await screen.findByRole("heading", { name: "Historik" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Återställ Förbered pitchen" }),
    ).not.toBeInTheDocument();
  });

  it("a memory switch stays when the owner comes back to memory", async () => {
    const user = userEvent.setup();
    const transport = makeTransport({
      memoryStatus: vi.fn(() => Promise.resolve(memoryOn)),
      setMemory: vi.fn(() =>
        Promise.resolve({
          status: "updated" as const,
          settings: memoryOn.settings,
          turning_off: [],
        }),
      ),
    });
    renderApp(transport, "memory", { memory: memoryOff });

    await user.click(screen.getByRole("switch", { name: "Dagbok: av" }));
    await screen.findByRole("heading", { name: "Minnet är på" });
    await user.click(viewButton("Historik"));
    await screen.findByRole("heading", { name: "Historik" });
    await user.click(viewButton("Sidekicks minne"));

    expect(
      screen.getByRole("heading", { name: "Minnet är på" }),
    ).toBeInTheDocument();
  });

  it("shows three views, and reads both History parts only when it is chosen", async () => {
    const user = userEvent.setup();
    const transport = makeTransport();
    renderApp(transport, "trash", { trash: trashed });

    const tabs = screen
      .getAllByRole("button")
      .map((button) => button.textContent)
      .filter((text) =>
        ["Borttaget", "Historik", "Sidekicks minne"].includes(text ?? ""),
      );
    expect(tabs).toEqual(["Borttaget", "Historik", "Sidekicks minne"]);
    expect(transport.activity).not.toHaveBeenCalled();

    await user.click(viewButton("Historik"));
    await screen.findByRole("heading", { name: "Historik" });
    expect(transport.activity).toHaveBeenCalledTimes(1);
    expect(transport.changes).toHaveBeenCalledTimes(1);
  });

  it("keeps the activity view when the owner comes back to it", async () => {
    const user = userEvent.setup();
    const transport = makeTransport({
      activity: vi.fn(() => Promise.resolve(activity)),
    });
    renderApp(transport, "trash", { trash: trashed });

    await user.click(viewButton("Historik"));
    await screen.findByText("Flyttade Förbered pitchen till Klar");
    await user.click(viewButton("Borttaget"));
    await user.click(viewButton("Historik"));

    expect(
      screen.getByText("Flyttade Förbered pitchen till Klar"),
    ).toBeInTheDocument();
    expect(transport.activity).toHaveBeenCalledTimes(1);
  });

  it("keeps Show all open when the owner comes back to the tab", async () => {
    const user = userEvent.setup();
    const items: TrashItem[] = Array.from({ length: 6 }, (_, index) => ({
      kind: "task",
      id: `019f0000-0000-7000-8000-00000000030${index}`,
      label: `Post ${index + 1}`,
      trashed_at: "2026-10-31T13:30:00Z",
      version: 4,
    }));
    const transport = makeTransport();
    renderApp(transport, "trash", {
      trash: { items, has_more: false, next_cursor: null },
    });

    expect(screen.queryByText("Post 5")).not.toBeInTheDocument();
    await user.click(viewButton("Visa alla (6)"));
    expect(screen.getByText("Post 5")).toBeInTheDocument();

    await user.click(viewButton("Historik"));
    await user.click(viewButton("Borttaget"));

    expect(screen.getByText("Post 5")).toBeInTheDocument();
    expect(viewButton("Visa färre")).toHaveAttribute("aria-expanded", "true");
  });
});

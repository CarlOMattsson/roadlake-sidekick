import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { HistoryView } from "@/features/control-app/history-view";
import { controlSv } from "@/features/control-app/labels";
import { MemoryView } from "@/features/control-app/memory-view";
import { TrashView } from "@/features/control-app/trash-view";
import type {
  ChangeRecord,
  ControlTransport,
  MemoryStatus,
  SetMemoryResult,
  TrashList,
} from "@/features/control-app/transport";

// The sentences that go to the host model after an owner change in the card. They are generic:
// no title, no id and no content (see docs/decisions/log.md D-058). Each view sends one only when its write was saved.
const RESTORED = "Användaren återställde en post ur papperskorgen i kortet.";
const UNDONE = "Användaren ångrade en ändring i kortet.";
const PAUSED = "Användaren pausade minnet i kortet.";
const RESUMED = "Användaren återupptog minnet i kortet.";
const MEMORY_CHANGED = "Användaren ändrade minnesinställningarna i kortet.";

const now = () => new Date("2026-11-01T10:00:00Z");
const TASK_ID = "019f0000-0000-7000-8000-000000000101";
const ITEM_ID = "019f0000-0000-7000-8000-0000000000a1";

const trashed: TrashList = {
  items: [
    {
      kind: "task",
      id: TASK_ID,
      label: "Förbered pitchen",
      trashed_at: "2026-10-31T13:30:00Z",
      version: 4,
    },
  ],
  has_more: false,
  next_cursor: null,
};

const purchase: ChangeRecord = {
  kind: "shopping_item",
  id: ITEM_ID,
  title: "Milk",
  version: 3,
  action: "purchased",
  state: "active",
  occurred_at: "2026-10-31T12:00:00Z",
  undo_tool: "set_shopping_item_purchased",
};

const memory = (paused: boolean, version: number): MemoryStatus => ({
  settings: {
    journal: true,
    contacts: false,
    projects: false,
    tasks: false,
    paused,
    version,
  },
  provider: "hindsight",
  sources: [],
});

function makeTransport(
  overrides: Partial<ControlTransport> = {},
): ControlTransport {
  return {
    trash: vi.fn(() =>
      Promise.resolve({ items: [], has_more: false, next_cursor: null }),
    ),
    restore: vi.fn(() => Promise.resolve({})),
    changes: vi.fn(() => Promise.resolve({ changes: [] })),
    undoPurchase: vi.fn(() => Promise.resolve({})),
    memoryStatus: vi.fn(() => Promise.resolve(memory(false, 2))),
    setMemory: vi.fn(),
    activity: vi.fn(() => Promise.resolve({ items: [], next_cursor: null })),
    ...overrides,
  };
}

describe("trash: a saved restore tells the host model once", () => {
  it("sends the generic sentence, never the title", async () => {
    const user = userEvent.setup();
    const onModelContext = vi.fn();
    render(
      <TrashView
        initial={trashed}
        transport={makeTransport()}
        labels={controlSv}
        now={now}
        onModelContext={onModelContext}
      />,
    );

    await user.click(
      screen.getByRole("button", { name: "Återställ Förbered pitchen" }),
    );

    expect(onModelContext).toHaveBeenCalledTimes(1);
    expect(onModelContext).toHaveBeenCalledWith(RESTORED);
    expect(onModelContext.mock.calls[0]?.[0]).not.toContain("Förbered");
  });

  it("sends nothing when the restore fails", async () => {
    const user = userEvent.setup();
    const onModelContext = vi.fn();
    const transport = makeTransport({
      restore: vi.fn(() =>
        Promise.reject(
          Object.assign(new Error("forbidden"), { code: "forbidden" }),
        ),
      ),
    });
    render(
      <TrashView
        initial={trashed}
        transport={transport}
        labels={controlSv}
        now={now}
        onModelContext={onModelContext}
      />,
    );

    await user.click(
      screen.getByRole("button", { name: "Återställ Förbered pitchen" }),
    );

    expect(
      await screen.findByText("Du saknar behörighet att återställa den."),
    ).toBeInTheDocument();
    expect(onModelContext).not.toHaveBeenCalled();
  });

  it("works without a host that takes the sentence (the prop is optional)", async () => {
    const user = userEvent.setup();
    render(
      <TrashView
        initial={trashed}
        transport={makeTransport()}
        labels={controlSv}
        now={now}
      />,
    );

    await user.click(
      screen.getByRole("button", { name: "Återställ Förbered pitchen" }),
    );

    expect(
      await screen.findByText("Återställd: “Förbered pitchen”"),
    ).toBeInTheDocument();
  });
});

describe("changes: a saved undo tells the host model once", () => {
  it("sends the generic sentence after the purchase is put back", async () => {
    const user = userEvent.setup();
    const onModelContext = vi.fn();
    render(
      <HistoryView
        changes={{ changes: [purchase] }}
        transport={makeTransport()}
        labels={controlSv}
        now={now}
        onModelContext={onModelContext}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Ångra Milk" }));

    expect(onModelContext).toHaveBeenCalledTimes(1);
    expect(onModelContext).toHaveBeenCalledWith(UNDONE);
    expect(onModelContext.mock.calls[0]?.[0]).not.toContain("Milk");
  });

  it("sends nothing when the undo hits a conflict", async () => {
    const user = userEvent.setup();
    const onModelContext = vi.fn();
    const transport = makeTransport({
      undoPurchase: vi.fn(() =>
        Promise.reject(
          Object.assign(new Error("conflict"), { code: "conflict" }),
        ),
      ),
    });
    render(
      <HistoryView
        changes={{ changes: [purchase] }}
        transport={transport}
        labels={controlSv}
        now={now}
        onModelContext={onModelContext}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Ångra Milk" }));

    expect(
      await screen.findByText(
        "“Milk” har ändrats på annat håll. Listan är uppdaterad – tryck igen.",
      ),
    ).toBeInTheDocument();
    expect(onModelContext).not.toHaveBeenCalled();
  });
});

describe("memory: a saved change tells the host model once", () => {
  it("sends the pause sentence when the owner pauses", async () => {
    const user = userEvent.setup();
    const onModelContext = vi.fn();
    const transport = makeTransport({
      setMemory: vi.fn(
        (): Promise<SetMemoryResult> =>
          Promise.resolve({
            status: "updated",
            settings: memory(true, 3).settings,
            turning_off: [],
          }),
      ),
      memoryStatus: vi.fn(() => Promise.resolve(memory(true, 3))),
    });
    render(
      <MemoryView
        initial={memory(false, 2)}
        transport={transport}
        labels={controlSv}
        onModelContext={onModelContext}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Pausa minnet" }));

    expect(await screen.findByText("Sparat.")).toBeInTheDocument();
    expect(onModelContext).toHaveBeenCalledTimes(1);
    expect(onModelContext).toHaveBeenCalledWith(PAUSED);
  });

  it("sends the resume sentence when the owner resumes", async () => {
    const user = userEvent.setup();
    const onModelContext = vi.fn();
    const transport = makeTransport({
      setMemory: vi.fn(
        (): Promise<SetMemoryResult> =>
          Promise.resolve({
            status: "updated",
            settings: memory(false, 3).settings,
            turning_off: [],
          }),
      ),
      memoryStatus: vi.fn(() => Promise.resolve(memory(false, 3))),
    });
    render(
      <MemoryView
        initial={memory(true, 2)}
        transport={transport}
        labels={controlSv}
        onModelContext={onModelContext}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Återuppta minnet" }));

    expect(await screen.findByText("Sparat.")).toBeInTheDocument();
    expect(onModelContext).toHaveBeenCalledWith(RESUMED);
  });

  it("sends the general sentence when a domain is switched on", async () => {
    const user = userEvent.setup();
    const onModelContext = vi.fn();
    const transport = makeTransport({
      setMemory: vi.fn(
        (): Promise<SetMemoryResult> =>
          Promise.resolve({
            status: "updated",
            settings: memory(false, 3).settings,
            turning_off: [],
          }),
      ),
      memoryStatus: vi.fn(() => Promise.resolve(memory(false, 3))),
    });
    render(
      <MemoryView
        initial={memory(false, 2)}
        transport={transport}
        labels={controlSv}
        onModelContext={onModelContext}
      />,
    );

    await user.click(screen.getByRole("switch", { name: "Kontakter: av" }));

    expect(await screen.findByText("Sparat.")).toBeInTheDocument();
    expect(onModelContext).toHaveBeenCalledWith(MEMORY_CHANGED);
  });

  it("sends nothing while the host only asks for confirmation", async () => {
    const user = userEvent.setup();
    const onModelContext = vi.fn();
    const transport = makeTransport({
      setMemory: vi.fn(
        (): Promise<SetMemoryResult> =>
          Promise.resolve({
            status: "needs_confirmation",
            settings: memory(false, 2).settings,
            turning_off: [{ domain: "journal", documents: 3 }],
          }),
      ),
    });
    render(
      <MemoryView
        initial={memory(false, 2)}
        transport={transport}
        labels={controlSv}
        onModelContext={onModelContext}
      />,
    );

    await user.click(screen.getByRole("switch", { name: "Dagbok: på" }));

    expect(
      await screen.findByRole("group", { name: "Slå av dagboken?" }),
    ).toBeInTheDocument();
    expect(onModelContext).not.toHaveBeenCalled();
  });

  it("sends nothing when the host reports the setting unchanged", async () => {
    const user = userEvent.setup();
    const onModelContext = vi.fn();
    const transport = makeTransport({
      setMemory: vi.fn(
        (): Promise<SetMemoryResult> =>
          Promise.resolve({
            status: "unchanged",
            settings: memory(true, 2).settings,
            turning_off: [],
          }),
      ),
    });
    render(
      <MemoryView
        initial={memory(false, 2)}
        transport={transport}
        labels={controlSv}
        onModelContext={onModelContext}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Pausa minnet" }));

    expect(await screen.findByText("Sparat.")).toBeInTheDocument();
    expect(onModelContext).not.toHaveBeenCalled();
  });
});

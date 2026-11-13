import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, type Mock } from "vitest";

import { controlEn, controlSv } from "@/features/control-app/labels";
import { HistoryView } from "@/features/control-app/history-view";
import { RESTORED_MS } from "@/features/control-app/use-receipts";
import type {
  ActivityList,
  ActivityRecord,
  ChangeRecord,
  ChangesList,
  ControlTransport,
} from "@/features/control-app/transport";

/** A row's meta line, matched on its whole text: each "·" part is a span of its own. */
const metaLine = (text: string) => (_: string, el: Element | null) =>
  !!el?.classList.contains("control-row-secondary") && el.textContent === text;

const now = () => new Date("2026-11-01T10:00:00Z");

type UndoPurchase = (change: ChangeRecord, key: string) => Promise<unknown>;

/** An error as the app client throws it: only the closed code is read by the view. */
function fail(code: string): Error {
  return Object.assign(new Error(code), { code });
}

const UNDO = "set_shopping_item_purchased";

/** A purchase of a shopping item that can be undone with the existing tool. */
const bought: ChangeRecord = {
  kind: "shopping_item",
  id: "019f0000-0000-7000-8000-0000000003a1",
  title: "Mjölk",
  version: 2,
  action: "purchased",
  state: "active",
  occurred_at: "2026-10-31T13:30:00Z",
  undo_tool: UNDO,
};

const other: ChangeRecord = {
  kind: "task",
  id: "019f0000-0000-7000-8000-0000000003b1",
  title: "Ring Anna",
  version: 3,
  action: "updated",
  state: "active",
  occurred_at: "2026-11-01T08:05:00Z",
};

/** A transport where only changes and undoPurchase matter here. The list read again is empty by default. */
function makeTransport(
  undoPurchase: Mock<UndoPurchase> = vi.fn<UndoPurchase>(() =>
    Promise.resolve({}),
  ),
) {
  const transport = {
    trash: vi.fn(() =>
      Promise.resolve({ items: [], has_more: false, next_cursor: null }),
    ),
    restore: vi.fn(() => Promise.resolve({})),
    changes: vi.fn(
      (): Promise<ChangesList> => Promise.resolve({ changes: [] }),
    ),
    undoPurchase,
    memoryStatus: vi.fn(),
    setMemory: vi.fn(),
    activity: vi.fn(),
  };
  return transport;
}

function renderChanges(
  changes: ChangesList | undefined,
  transport: ControlTransport,
  activity?: ActivityList,
) {
  return render(
    <HistoryView
      changes={changes}
      activity={activity}
      transport={transport}
      labels={controlSv}
      now={now}
    />,
  );
}

describe("HistoryView rows", () => {
  it("shows the title and a meta line with kind, action and time", () => {
    const transport = makeTransport();
    renderChanges({ changes: [bought, other] }, transport);

    expect(screen.getByText("Mjölk")).toBeInTheDocument();
    expect(
      screen.getByText(metaLine("Inköpsvara · köpt · igår 14:30")),
    ).toBeInTheDocument();
    expect(screen.getByText("Ring Anna")).toBeInTheDocument();
    expect(
      screen.getByText(metaLine("Uppgift · ändrad · idag 09:05")),
    ).toBeInTheDocument();
  });

  it("names who made a change, Du or Claude, and says nothing when it is unknown", () => {
    const transport = makeTransport();
    renderChanges(
      {
        changes: [
          { ...other, actor: "you" },
          { ...bought, actor: "claude" },
          {
            ...other,
            id: "019f0000-0000-7000-8000-0000000003b2",
            actor: "unknown",
          },
        ],
      },
      transport,
    );

    expect(
      screen.getByText(metaLine("Uppgift · ändrad · Du · idag 09:05")),
    ).toBeInTheDocument();
    expect(
      screen.getByText(metaLine("Inköpsvara · köpt · Claude · igår 14:30")),
    ).toBeInTheDocument();
    expect(
      screen.getByText(metaLine("Uppgift · ändrad · idag 09:05")),
    ).toBeInTheDocument();
  });

  it("names the actor in English as You or Claude", () => {
    const transport = makeTransport();
    render(
      <HistoryView
        changes={{
          changes: [
            { ...other, actor: "you" },
            { ...bought, actor: "claude" },
          ],
        }}
        transport={transport}
        labels={controlEn}
        now={now}
      />,
    );

    expect(
      screen.getByText(
        (_, el) =>
          !!el?.classList.contains("control-row-secondary") &&
          /· You ·/.test(el.textContent ?? ""),
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        (_, el) =>
          !!el?.classList.contains("control-row-secondary") &&
          /· Claude ·/.test(el.textContent ?? ""),
      ),
    ).toBeInTheDocument();
  });

  it("shows Undo only for an active shopping item with the purchase tool", () => {
    const transport = makeTransport();
    renderChanges({ changes: [bought, other] }, transport);

    const undo = screen.getByRole("button", { name: "Ångra Mjölk" });
    expect(undo).toBeInTheDocument();
    // A quiet row button, not a compact secondary.
    expect(undo).toHaveClass(
      "sk-btn--secondary",
      "sk-btn--compact",
      "control-row-btn",
    );
    expect(
      screen.queryByRole("button", { name: "Ångra Ring Anna" }),
    ).toBeNull();
    expect(screen.getAllByRole("button")).toHaveLength(1);
  });

  it("shows no Undo for a shopping item whose undo tool is not the purchase tool", () => {
    const transport = makeTransport();
    const foreign: ChangeRecord = { ...bought, undo_tool: "some_other_tool" };
    renderChanges({ changes: [foreign] }, transport);

    expect(screen.queryByRole("button", { name: /Ångra/ })).toBeNull();
  });

  it("shows Restore, and no Undo, for a trashed row, and says it is now in the trash", () => {
    const transport = makeTransport();
    const trashedBought: ChangeRecord = {
      ...bought,
      id: "019f0000-0000-7000-8000-0000000003c1",
      title: "Smör",
      state: "trashed",
    };
    renderChanges({ changes: [trashedBought] }, transport);

    expect(screen.queryByRole("button", { name: /Ångra/ })).toBeNull();
    const restore = screen.getByRole("button", { name: "Återställ Smör" });
    expect(restore).toBeInTheDocument();
    // A quiet row button, not a compact secondary.
    expect(restore).toHaveClass(
      "sk-btn--secondary",
      "sk-btn--compact",
      "control-row-btn",
    );
    expect(
      screen.getByText(
        metaLine("Inköpsvara · köpt · igår 14:30 · ligger nu i papperskorgen"),
      ),
    ).toBeInTheDocument();
  });

  it("restores a trashed row with restore_from_trash's write, at the version the row shows", async () => {
    const transport = makeTransport();
    const trashing: ChangeRecord = {
      ...other,
      id: "019f0000-0000-7000-8000-0000000003c3",
      title: "Ring Bo",
      version: 5,
      action: "trashed",
      state: "trashed",
    };
    renderChanges({ changes: [trashing] }, transport);

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Återställ Ring Bo" }));

    expect(transport.restore).toHaveBeenCalledTimes(1);
    expect(transport.restore).toHaveBeenCalledWith(
      {
        kind: "task",
        id: "019f0000-0000-7000-8000-0000000003c3",
        label: "Ring Bo",
        trashed_at: null,
        version: 5,
      },
      expect.any(String),
    );
    expect(transport.undoPurchase).not.toHaveBeenCalled();
    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent("Återställd");
    expect(
      within(status.closest("li") as HTMLElement).queryByRole("button"),
    ).toBeNull();
  });

  it("shows nothing at the end of a row with no action", () => {
    const transport = makeTransport();
    renderChanges({ changes: [other] }, transport);

    expect(screen.queryByText("Be Claude ändra")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
    expect(document.querySelector(".control-row-action")).toBeNull();
  });

  it("does not repeat the trash note when the change itself is the trashing", () => {
    const transport = makeTransport();
    const trashing: ChangeRecord = {
      ...bought,
      id: "019f0000-0000-7000-8000-0000000003c2",
      title: "Bröd",
      action: "trashed",
      state: "trashed",
    };
    renderChanges({ changes: [trashing] }, transport);

    expect(
      screen.getByText(metaLine("Inköpsvara · borttagen · igår 14:30")),
    ).toBeInTheDocument();
    expect(screen.queryByText(/ligger nu i papperskorgen/)).toBeNull();
    expect(screen.queryByRole("button", { name: /Ångra/ })).toBeNull();
  });

  it("says there is no history when both parts are empty, with a hint", () => {
    const transport = makeTransport();
    renderChanges({ changes: [] }, transport, {
      items: [],
      next_cursor: null,
    });

    expect(screen.getByText("Ingen historik ännu.")).toBeInTheDocument();
    expect(
      screen.getByText("Det du eller Claude ändrar visas här."),
    ).toBeInTheDocument();
  });

  it("has a screen reader heading and no visible one", () => {
    renderChanges({ changes: [other] }, makeTransport());

    const heading = screen.getByRole("heading", { name: "Historik" });
    expect(heading).toHaveClass("control-sr-only");
  });
});

describe("HistoryView undo", () => {
  it("undoes a purchase with the listed change, says it is no longer bought and reads the list again", async () => {
    const transport = makeTransport();
    const reread: ChangesList = { changes: [other] };
    transport.changes.mockResolvedValueOnce(reread);
    renderChanges({ changes: [bought] }, transport);

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Ångra Mjölk" }));

    expect(transport.undoPurchase).toHaveBeenCalledTimes(1);
    expect(transport.undoPurchase.mock.calls[0]?.[0]).toEqual(bought);
    expect(transport.undoPurchase.mock.calls[0]?.[1]).toEqual(
      expect.any(String),
    );

    // The row stays on its place with a receipt and no button, even though the list read again no longer holds it.
    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent("Inte längre köpt");
    const row = status.closest("li") as HTMLElement;
    expect(row).toHaveTextContent("Mjölk");
    expect(within(row).queryByRole("button")).toBeNull();
    expect(transport.changes).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("Ring Anna")).toBeInTheDocument();
    expect(screen.getByText("Mjölk")).toBeInTheDocument();
  });

  it("takes the receipt away after RESTORED_MS and the row goes with it when the list no longer holds it", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const transport = makeTransport();
      transport.changes.mockResolvedValueOnce({ changes: [other] });
      renderChanges({ changes: [bought] }, transport);

      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      await user.click(screen.getByRole("button", { name: "Ångra Mjölk" }));
      await screen.findByText("Ring Anna");
      expect(screen.getByRole("status")).toHaveTextContent("Inte längre köpt");

      act(() => {
        vi.advanceTimersByTime(RESTORED_MS + 100);
      });

      expect(screen.queryByRole("status")).toBeNull();
      expect(screen.queryByText("Mjölk")).not.toBeInTheDocument();
      expect(screen.getByText("Ring Anna")).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("puts a change back with the same tool and says it is bought again", async () => {
    const transport = makeTransport();
    const reopened: ChangeRecord = {
      ...bought,
      id: "019f0000-0000-7000-8000-0000000003d1",
      action: "reopened",
    };
    renderChanges({ changes: [reopened] }, transport);

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Ångra Mjölk" }));

    expect(transport.undoPurchase.mock.calls[0]?.[0]).toEqual(reopened);
    expect(await screen.findByRole("status")).toHaveTextContent("Köpt igen");
    expect(transport.changes).toHaveBeenCalledTimes(1);
  });

  it("on a conflict says the item changed elsewhere and reads the list again", async () => {
    const undoPurchase = vi.fn<UndoPurchase>(() =>
      Promise.reject(fail("conflict")),
    );
    const transport = makeTransport(undoPurchase);
    transport.changes.mockResolvedValueOnce({ changes: [other] });
    renderChanges({ changes: [bought] }, transport);

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Ångra Mjölk" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      controlSv.undoConflict("Mjölk"),
    );
    expect(transport.changes).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("Ring Anna")).toBeInTheDocument();
  });

  it("on forbidden says so and does not read the list again", async () => {
    const undoPurchase = vi.fn<UndoPurchase>(() =>
      Promise.reject(fail("forbidden")),
    );
    const transport = makeTransport(undoPurchase);
    renderChanges({ changes: [bought] }, transport);

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Ångra Mjölk" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      controlSv.undoForbidden,
    );
    expect(transport.changes).not.toHaveBeenCalled();
    expect(screen.getByText("Mjölk")).toBeInTheDocument();
  });

  it("keeps the old rows when the undo is done but the list cannot be read again", async () => {
    const transport = makeTransport();
    transport.changes.mockRejectedValueOnce(new Error("offline"));
    renderChanges({ changes: [bought] }, transport);

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Ångra Mjölk" }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Inte längre köpt",
    );
    expect(transport.changes).toHaveBeenCalledTimes(1);
    const list = screen.getByRole("list", { name: "Historik" });
    expect(within(list).getByText("Mjölk")).toBeInTheDocument();
  });

  it("names the item in the conflict and says to press again", async () => {
    const undoPurchase = vi.fn<UndoPurchase>(() =>
      Promise.reject(fail("conflict")),
    );
    const transport = makeTransport(undoPurchase);
    renderChanges({ changes: [bought] }, transport);

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Ångra Mjölk" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "”Mjölk” har ändrats på annat håll. Listan är uppdaterad – tryck igen.",
    );
  });
});

describe("HistoryView undo labels", () => {
  it("every undo button says Ångra, for a purchase and for a put-back alike", () => {
    const transport = makeTransport();
    const reopened: ChangeRecord = {
      ...bought,
      id: "019f0000-0000-7000-8000-0000000003d2",
      title: "Smör",
      action: "reopened",
    };
    renderChanges({ changes: [bought, reopened] }, transport);

    expect(
      screen.getByRole("button", { name: "Ångra Mjölk" }),
    ).toHaveTextContent("Ångra");
    expect(
      screen.getByRole("button", { name: "Ångra Smör" }),
    ).toHaveTextContent("Ångra");
  });
});

describe("HistoryView focus after a write", () => {
  it("moves focus to the undo button of the row that took its place", async () => {
    const reopened: ChangeRecord = {
      ...bought,
      id: "019f0000-0000-7000-8000-0000000003d2",
      title: "Smör",
      action: "reopened",
    };
    const transport = makeTransport();
    transport.changes.mockResolvedValueOnce({ changes: [reopened] });
    renderChanges({ changes: [bought, reopened] }, transport);

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Ångra Mjölk" }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Ångra Smör" })).toHaveFocus(),
    );
  });

  it("moves focus to the heading when no row with a button is left", async () => {
    const transport = makeTransport();
    transport.changes.mockResolvedValueOnce({ changes: [other] });
    renderChanges({ changes: [bought, other] }, transport);

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Ångra Mjölk" }));

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Historik" })).toHaveFocus(),
    );
  });

  it("keeps focus on the same row's button after a failed undo", async () => {
    const undoPurchase = vi.fn<UndoPurchase>(() =>
      Promise.reject(fail("internal_error")),
    );
    const transport = makeTransport(undoPurchase);
    renderChanges({ changes: [bought, other] }, transport);

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Ångra Mjölk" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      controlSv.undoFailed,
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Ångra Mjölk" })).toHaveFocus(),
    );
  });
});

function entry(overrides: Partial<ActivityRecord> = {}): ActivityRecord {
  return {
    id: "019f0000-0000-7000-8000-000000000201",
    category: "task_maintenance",
    source: "assistant",
    operation: "update_task",
    state: "applied",
    aggregate_type: "task",
    summary: "Flyttade Förbered pitchen till Klar",
    occurred_at: "2026-11-01T09:55:00Z",
    ...overrides,
  };
}

describe("HistoryView merges changes and activity", () => {
  it("lists both in one list, newest first, with unique rows", () => {
    renderChanges({ changes: [bought, other] }, makeTransport(), {
      items: [entry()],
      next_cursor: null,
    });

    const list = screen.getByRole("list", { name: "Historik" });
    const primaries = within(list)
      .getAllByRole("listitem")
      .map((row) => row.querySelector(".control-row-primary")?.textContent);
    // activity 09:55, other 08:05, bought yesterday
    expect(primaries).toEqual([
      "Flyttade Förbered pitchen till Klar",
      "Ring Anna",
      "Mjölk",
    ]);
  });

  it("shows an activity row as summary plus source, state and time, with no button", () => {
    renderChanges({ changes: [] }, makeTransport(), {
      items: [entry({ state: "review" }), entry({ id: "2", summary: "  " })],
      next_cursor: null,
    });

    expect(
      screen.getByText(metaLine("Claude · att granska · för 5 min sedan")),
    ).toBeInTheDocument();
    expect(screen.getByText("Uppgift")).toBeInTheDocument();
    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });

  it("keeps Undo on the change row while activity rows have none", () => {
    renderChanges({ changes: [bought] }, makeTransport(), {
      items: [entry()],
      next_cursor: null,
    });

    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(
      screen.getByRole("button", { name: "Ångra Mjölk" }),
    ).toBeInTheDocument();
  });

  it("shows the list when only one part is there", () => {
    renderChanges(undefined, makeTransport(), {
      items: [entry()],
      next_cursor: null,
    });
    expect(
      screen.getByText("Flyttade Förbered pitchen till Klar"),
    ).toBeInTheDocument();
  });

  it("folds rows past the first four behind Show all", () => {
    const items = Array.from({ length: 7 }, (_, index) =>
      entry({ id: `row-${index}`, summary: `Rad ${index}` }),
    );
    renderChanges({ changes: [] }, makeTransport(), {
      items,
      next_cursor: null,
    });

    expect(screen.queryByText("Rad 4")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Visa alla (7)" }),
    ).toBeInTheDocument();
  });

  it("lists every row in the full view, with no Show all", () => {
    const items = Array.from({ length: 7 }, (_, index) =>
      entry({ id: `row-${index}`, summary: `Rad ${index}` }),
    );
    render(
      <HistoryView
        changes={{ changes: [] }}
        activity={{ items, next_cursor: null }}
        transport={makeTransport()}
        labels={controlSv}
        now={now}
        full
      />,
    );

    expect(screen.getByText("Rad 6")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Visa alla/ })).toBeNull();
  });

  it("says the list is cut only when there is a next cursor", () => {
    const { unmount } = renderChanges({ changes: [] }, makeTransport(), {
      items: [entry()],
      next_cursor: "next-page",
    });
    expect(
      screen.getByText("Listan är avkortad. Bara de senaste posterna visas."),
    ).toBeInTheDocument();
    unmount();

    renderChanges({ changes: [] }, makeTransport(), {
      items: [entry()],
      next_cursor: null,
    });
    expect(screen.queryByText(/avkortad/)).not.toBeInTheDocument();
  });
});

describe("HistoryView empty state and who acted", () => {
  const nothing = { changes: [] };
  const noActivity = { items: [], next_cursor: null };

  it("offers an example for Claude that sends through the host's chat", async () => {
    const sendMessage = vi.fn(() => Promise.resolve(true));
    render(
      <HistoryView
        changes={nothing}
        activity={noActivity}
        transport={makeTransport()}
        labels={controlSv}
        now={now}
        sendMessage={sendMessage}
      />,
    );

    expect(screen.getByText("Säg till Claude:")).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", {
        name: "Skicka till Claude: Lägg till mjölk på inköpslistan",
      }),
    );
    expect(sendMessage).toHaveBeenCalledWith("Lägg till mjölk på inköpslistan");
  });

  it("shows the example as plain text when the host has no chat, in English too", () => {
    render(
      <HistoryView
        changes={nothing}
        activity={noActivity}
        transport={makeTransport()}
        labels={controlEn}
        now={now}
      />,
    );

    expect(
      screen.getByText("Ask Claude in the Claude app:"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("“Add milk to my shopping list”"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Send to Claude/ })).toBeNull();
  });

  it("names who made an activity entry first on its meta line: You or Claude", () => {
    renderChanges(nothing, makeTransport(), {
      items: [
        entry({ source: "user", summary: "Du ändrade en rad" }),
        entry({
          id: "019f0000-0000-7000-8000-000000000202",
          source: "assistant",
          summary: "Claude ändrade en rad",
          occurred_at: "2026-11-01T09:50:00Z",
        }),
      ],
      next_cursor: null,
    });

    const metaOf = (summary: string) =>
      screen
        .getByText(summary)
        .closest("li")!
        .querySelector(".control-row-secondary")!.textContent;
    expect(metaOf("Du ändrade en rad")).toMatch(/^Du /);
    expect(metaOf("Claude ändrade en rad")).toMatch(/^Claude /);
  });
});

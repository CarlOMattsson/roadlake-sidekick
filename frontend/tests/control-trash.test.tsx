import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi, type Mock } from "vitest";

import { controlSv } from "@/features/control-app/labels";
import { RESTORED_MS } from "@/features/control-app/use-receipts";
import { TrashView } from "@/features/control-app/trash-view";
import type {
  ControlTransport,
  TrashItem,
  TrashList,
} from "@/features/control-app/transport";

/** A row's meta line, matched on its whole text: each "·" part is a span of its own. */
const metaLine = (text: string) => (_: string, el: Element | null) =>
  !!el?.classList.contains("control-row-secondary") && el.textContent === text;

const now = () => new Date("2026-11-01T10:00:00Z");

type Restore = (item: TrashItem, key: string) => Promise<unknown>;

/** An error as the app client throws it: only the closed code is read by the view. */
function fail(code: string): Error {
  return Object.assign(new Error(code), { code });
}

const task: TrashItem = {
  kind: "task",
  id: "019f0000-0000-7000-8000-000000000101",
  label: "Förbered pitchen",
  trashed_at: "2026-10-31T13:30:00Z",
  version: 4,
};

const note: TrashItem = {
  kind: "journal_entry",
  id: "019f0000-0000-7000-8000-000000000102",
  label: "Kort dagbok",
  trashed_at: "2026-10-31T13:30:00Z",
  version: 2,
};

/** A transport where only trash and restore matter here. The list read again is empty by default. */
function makeTransport(
  restore: Mock<Restore> = vi.fn<Restore>(() => Promise.resolve({})),
) {
  const transport = {
    trash: vi.fn(
      (): Promise<TrashList> =>
        Promise.resolve({ items: [], has_more: false, next_cursor: null }),
    ),
    restore,
    changes: vi.fn(() => Promise.resolve({ changes: [] })),
    undoPurchase: vi.fn(() => Promise.resolve({})),
    memoryStatus: vi.fn(),
    setMemory: vi.fn(),
    activity: vi.fn(),
  };
  return transport;
}

function renderTrash(initial: TrashList, transport: ControlTransport) {
  return render(
    <TrashView
      initial={initial}
      transport={transport}
      labels={controlSv}
      now={now}
    />,
  );
}

describe("TrashView rows", () => {
  it("shows the title, the kind and when it was trashed", () => {
    const transport = makeTransport();
    renderTrash(
      { items: [task], has_more: false, next_cursor: null },
      transport,
    );

    expect(screen.getByText("Förbered pitchen")).toBeInTheDocument();
    expect(
      screen.getByText(metaLine("Uppgift · borttagen igår 14:30")),
    ).toBeInTheDocument();
    const restore = screen.getByRole("button", {
      name: "Återställ Förbered pitchen",
    });
    expect(restore).toBeVisible();
    // Restore is a compact secondary button (a frame and the text colour), in the row's action column.
    expect(restore).toHaveClass(
      "sk-btn--secondary",
      "sk-btn--compact",
      "control-row-btn",
    );
    expect(restore).not.toHaveClass("sk-btn--quiet");
  });

  it("says the title is hidden when the caller may not read it", () => {
    const hidden: TrashItem = { ...task, label: null };
    const transport = makeTransport();
    renderTrash(
      { items: [hidden], has_more: false, next_cursor: null },
      transport,
    );

    expect(screen.getByText("Titeln är dold")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Återställ Titeln är dold" }),
    ).toBeInTheDocument();
  });

  it("shows three rows, then all of them after Visa alla", async () => {
    const items: TrashItem[] = Array.from({ length: 7 }, (_, index) => ({
      ...task,
      id: `019f0000-0000-7000-8000-00000000020${index}`,
      label: `Post ${index + 1}`,
    }));
    const transport = makeTransport();
    renderTrash({ items, has_more: false, next_cursor: null }, transport);

    const list = screen.getByRole("list", { name: "Borttaget" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(3);
    expect(screen.queryByText("Post 4")).not.toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Visa alla (7)" }));

    expect(within(list).getAllByRole("listitem")).toHaveLength(7);
    expect(screen.getByText("Post 7")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Visa färre" }),
    ).toBeInTheDocument();
  });

  it("lists every row it holds in the full view, with no Visa alla", () => {
    const items: TrashItem[] = Array.from({ length: 7 }, (_, index) => ({
      ...task,
      id: `019f0000-0000-7000-8000-00000000022${index}`,
      label: `Post ${index + 1}`,
    }));
    render(
      <TrashView
        initial={{ items, has_more: false, next_cursor: null }}
        transport={makeTransport()}
        labels={controlSv}
        now={now}
        full
      />,
    );

    expect(
      within(screen.getByRole("list", { name: "Borttaget" })).getAllByRole(
        "listitem",
      ),
    ).toHaveLength(7);
    expect(screen.queryByRole("button", { name: /Visa alla/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Visa färre" })).toBeNull();
  });

  it("does not claim an exact count while the server holds more rows", () => {
    const items: TrashItem[] = Array.from({ length: 5 }, (_, index) => ({
      ...task,
      id: `019f0000-0000-7000-8000-00000000023${index}`,
      label: `Post ${index + 1}`,
    }));
    const { container } = renderTrash(
      { items, has_more: true, next_cursor: "page-2" },
      makeTransport(),
    );

    expect(container.querySelector("p.control-meta")).toHaveTextContent(
      "5+ borttagna · kan återställas",
    );
    expect(
      screen.getByRole("button", { name: "Visa alla (5+)" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Visa fler" }),
    ).toBeInTheDocument();
  });

  it("drops Visa alla once the receipt of a restore has gone and the rows are at the limit", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const items: TrashItem[] = Array.from({ length: 4 }, (_, index) => ({
        ...task,
        id: `019f0000-0000-7000-8000-00000000021${index}`,
        label: `Post ${index + 1}`,
      }));
      const transport = makeTransport();
      renderTrash({ items, has_more: false, next_cursor: null }, transport);

      expect(
        screen.getByRole("button", { name: "Visa alla (4)" }),
      ).toBeInTheDocument();
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      await user.click(
        screen.getByRole("button", { name: "Återställ Post 1" }),
      );
      await screen.findByRole("status");
      act(() => {
        vi.advanceTimersByTime(RESTORED_MS + 100);
      });

      expect(screen.queryByRole("button", { name: /Visa alla/ })).toBeNull();
      expect(
        within(screen.getByRole("list", { name: "Borttaget" })).getAllByRole(
          "listitem",
        ),
      ).toHaveLength(3);
    } finally {
      vi.useRealTimers();
    }
  });

  it("counts only the rows still in the trash in Visa alla while a restore receipt stands", async () => {
    const items: TrashItem[] = Array.from({ length: 5 }, (_, index) => ({
      ...task,
      id: `019f0000-0000-7000-8000-00000000022${index}`,
      label: `Post ${index + 1}`,
    }));
    renderTrash({ items, has_more: false, next_cursor: null }, makeTransport());

    expect(
      screen.getByRole("button", { name: "Visa alla (5)" }),
    ).toBeInTheDocument();
    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Återställ Post 1" }));
    await screen.findByRole("status");

    // Five rows stand on screen (four in the trash and the receipt), but only four are in the trash.
    expect(
      screen.getByRole("button", { name: "Visa alla (4)" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Visa alla (5)" })).toBeNull();
  });

  it("says the trash is empty when there are no rows", () => {
    const transport = makeTransport();
    renderTrash({ items: [], has_more: false, next_cursor: null }, transport);

    expect(screen.getByText("Inget borttaget.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Återställ/ })).toBeNull();
  });

  it("offers no way to empty the trash or delete for good", () => {
    const transport = makeTransport();
    renderTrash(
      { items: [task, note], has_more: false, next_cursor: null },
      transport,
    );

    expect(
      screen.getByRole("button", { name: "Återställ Förbered pitchen" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /töm|radera|ta bort|permanent/i }),
    ).toBeNull();
  });
});

describe("TrashView restore", () => {
  it("restores the exact item the list showed and answers in its row", async () => {
    const transport = makeTransport();
    renderTrash(
      { items: [task, note], has_more: false, next_cursor: null },
      transport,
    );

    const user = userEvent.setup();
    await user.click(
      screen.getByRole("button", { name: "Återställ Förbered pitchen" }),
    );

    expect(transport.restore).toHaveBeenCalledTimes(1);
    expect(transport.restore.mock.calls[0]?.[0]).toEqual(task);
    expect(transport.restore.mock.calls[0]?.[1]).toEqual(expect.any(String));

    // The row stays on its place: its meta line is the receipt, and it has no button any more.
    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent("Återställd");
    const row = status.closest("li");
    expect(row).toHaveTextContent("Förbered pitchen");
    expect(within(row as HTMLElement).queryByRole("button")).toBeNull();
    const rows = screen.getAllByRole("listitem");
    expect(rows[0]).toBe(row);
    expect(rows[1]).toHaveTextContent("Kort dagbok");
    // The count is of the rows still in the trash.
    expect(screen.getByText("1 borttagen · kan återställas")).toBeVisible();
    expect(transport.trash).not.toHaveBeenCalled();
  });

  it("says the item was restored when its title is hidden", async () => {
    const hidden: TrashItem = { ...task, label: null };
    const transport = makeTransport();
    renderTrash(
      { items: [hidden], has_more: false, next_cursor: null },
      transport,
    );

    const user = userEvent.setup();
    await user.click(
      screen.getByRole("button", { name: "Återställ Titeln är dold" }),
    );

    expect(await screen.findByRole("status")).toHaveTextContent("Återställd");
    expect(screen.getByText(controlSv.hiddenTitle)).toBeInTheDocument();
  });

  it("on a conflict says so, reads the list again and shows the new list", async () => {
    const restore = vi.fn<Restore>(() => Promise.reject(fail("conflict")));
    const transport = makeTransport(restore);
    const other: TrashItem = { ...note, label: "Ny post från annat håll" };
    transport.trash.mockResolvedValueOnce({
      items: [other],
      has_more: false,
      next_cursor: null,
    });
    renderTrash(
      { items: [task], has_more: false, next_cursor: null },
      transport,
    );

    const user = userEvent.setup();
    await user.click(
      screen.getByRole("button", { name: "Återställ Förbered pitchen" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      controlSv.restoreConflict("Förbered pitchen"),
    );
    expect(transport.trash).toHaveBeenCalledTimes(1);
    expect(
      await screen.findByText("Ny post från annat håll"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Förbered pitchen")).not.toBeInTheDocument();
  });

  it("on not_found says the item is gone, reads the list again and shows the new list", async () => {
    const restore = vi.fn<Restore>(() => Promise.reject(fail("not_found")));
    const transport = makeTransport(restore);
    transport.trash.mockResolvedValueOnce({
      items: [note],
      has_more: false,
      next_cursor: null,
    });
    renderTrash(
      { items: [task], has_more: false, next_cursor: null },
      transport,
    );

    const user = userEvent.setup();
    await user.click(
      screen.getByRole("button", { name: "Återställ Förbered pitchen" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      controlSv.restoreGone,
    );
    expect(transport.trash).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("Kort dagbok")).toBeInTheDocument();
    expect(screen.queryByText("Förbered pitchen")).not.toBeInTheDocument();
  });

  it("on forbidden says so and does not read the list again", async () => {
    const restore = vi.fn<Restore>(() => Promise.reject(fail("forbidden")));
    const transport = makeTransport(restore);
    renderTrash(
      { items: [task], has_more: false, next_cursor: null },
      transport,
    );

    const user = userEvent.setup();
    await user.click(
      screen.getByRole("button", { name: "Återställ Förbered pitchen" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      controlSv.restoreForbidden,
    );
    expect(transport.trash).not.toHaveBeenCalled();
    expect(screen.getByText("Förbered pitchen")).toBeInTheDocument();
  });

  it("on another error says it failed, and a retry sends the same idempotency key", async () => {
    const restore = vi
      .fn<Restore>()
      .mockRejectedValueOnce(fail("internal_error"))
      .mockResolvedValueOnce({});
    const transport = makeTransport(restore);
    renderTrash(
      { items: [task], has_more: false, next_cursor: null },
      transport,
    );

    const user = userEvent.setup();
    await user.click(
      screen.getByRole("button", { name: "Återställ Förbered pitchen" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      controlSv.restoreFailed,
    );
    expect(transport.trash).not.toHaveBeenCalled();
    expect(screen.getByText("Förbered pitchen")).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "Återställ Förbered pitchen" }),
    );

    expect(await screen.findByRole("status")).toHaveTextContent("Återställd");
    expect(restore).toHaveBeenCalledTimes(2);
    expect(restore.mock.calls[0]?.[0]).toEqual(task);
    expect(restore.mock.calls[1]?.[0]).toEqual(task);
    expect(restore.mock.calls[0]?.[1]).toEqual(expect.any(String));
    expect(restore.mock.calls[1]?.[1]).toBe(restore.mock.calls[0]?.[1]);
  });

  it("names the item in the conflict and says to press Återställ again", async () => {
    const restore = vi.fn<Restore>(() => Promise.reject(fail("conflict")));
    const transport = makeTransport(restore);
    renderTrash(
      { items: [task], has_more: false, next_cursor: null },
      transport,
    );

    const user = userEvent.setup();
    await user.click(
      screen.getByRole("button", { name: "Återställ Förbered pitchen" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "”Förbered pitchen” har ändrats på annat håll. Listan är uppdaterad – tryck Återställ igen.",
    );
  });

  it("says Posten in the conflict when the title is hidden", async () => {
    const restore = vi.fn<Restore>(() => Promise.reject(fail("conflict")));
    const transport = makeTransport(restore);
    renderTrash(
      { items: [{ ...task, label: null }], has_more: false, next_cursor: null },
      transport,
    );

    const user = userEvent.setup();
    await user.click(
      screen.getByRole("button", { name: "Återställ Titeln är dold" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Posten har ändrats på annat håll. Listan är uppdaterad – tryck Återställ igen.",
    );
  });
});

describe("TrashView heading", () => {
  it("keeps the tab name as the heading and shows the number of items as one meta line after it", () => {
    const transport = makeTransport();
    const { container } = renderTrash(
      { items: [task, note], has_more: false, next_cursor: null },
      transport,
    );

    expect(
      screen.getByRole("heading", { level: 2, name: "Borttaget" }),
    ).toBeInTheDocument();
    const meta = container.querySelector("p.control-meta");
    expect(meta).toHaveTextContent("2 borttagna · kan återställas");
    expect(screen.getByRole("heading", { level: 2 }).nextElementSibling).toBe(
      meta,
    );
  });

  it("hides the zero count in an empty trash: the heading is the tab name, the empty state explains", () => {
    const transport = makeTransport();
    renderTrash({ items: [], has_more: false, next_cursor: null }, transport);

    expect(screen.queryByText(/0 borttagna/)).toBeNull();
    expect(document.querySelector("p.control-meta")).toBeNull();
    expect(
      screen.getByRole("heading", { level: 2, name: "Borttaget" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Inget borttaget.")).toBeInTheDocument();
  });
});

describe("TrashView receipt", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("takes the restored row away after RESTORED_MS and shows the empty state when it was the last", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderTrash(
      { items: [task], has_more: false, next_cursor: null },
      makeTransport(),
    );

    await user.click(
      screen.getByRole("button", { name: "Återställ Förbered pitchen" }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent("Återställd");

    act(() => {
      vi.advanceTimersByTime(RESTORED_MS - 100);
    });
    expect(screen.getByRole("status")).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(200);
    });

    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByText("Förbered pitchen")).not.toBeInTheDocument();
    expect(screen.getByText("Inget borttaget.")).toBeInTheDocument();
  });

  it("keeps each restored row on its place while the next ones are restored", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderTrash(
      { items: [task, note], has_more: false, next_cursor: null },
      makeTransport(),
    );

    await user.click(
      screen.getByRole("button", { name: "Återställ Kort dagbok" }),
    );
    await screen.findByRole("status");
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    await user.click(
      screen.getByRole("button", { name: "Återställ Förbered pitchen" }),
    );
    await waitFor(() => expect(screen.getAllByRole("status")).toHaveLength(2));
    const titles = () =>
      screen
        .getAllByRole("listitem")
        .map((row) => row.querySelector(".control-row-primary")?.textContent);
    expect(titles()).toEqual(["Förbered pitchen", "Kort dagbok"]);

    // The first receipt ends 2 s before the second.
    act(() => {
      vi.advanceTimersByTime(2100);
    });
    expect(titles()).toEqual(["Förbered pitchen"]);
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(screen.getByText("Inget borttaget.")).toBeInTheDocument();
  });
});

describe("TrashView focus after a write", () => {
  it("moves focus to the Restore button of the row that took its place", async () => {
    const transport = makeTransport();
    renderTrash(
      { items: [task, note], has_more: false, next_cursor: null },
      transport,
    );

    const user = userEvent.setup();
    await user.click(
      screen.getByRole("button", { name: "Återställ Förbered pitchen" }),
    );

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Återställ Kort dagbok" }),
      ).toHaveFocus(),
    );
  });

  it("moves focus to the previous row when the last row is restored", async () => {
    const transport = makeTransport();
    renderTrash(
      { items: [task, note], has_more: false, next_cursor: null },
      transport,
    );

    const user = userEvent.setup();
    await user.click(
      screen.getByRole("button", { name: "Återställ Kort dagbok" }),
    );

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Återställ Förbered pitchen" }),
      ).toHaveFocus(),
    );
  });

  it("moves focus to the heading when no row with a button is left", async () => {
    const transport = makeTransport();
    renderTrash(
      { items: [task], has_more: false, next_cursor: null },
      transport,
    );

    const user = userEvent.setup();
    await user.click(
      screen.getByRole("button", { name: "Återställ Förbered pitchen" }),
    );

    await waitFor(() =>
      expect(
        screen.getByRole("heading", { level: 2, name: "Borttaget" }),
      ).toHaveFocus(),
    );
  });

  it("keeps focus on the same row's button after a failed restore", async () => {
    const restore = vi
      .fn<Restore>()
      .mockRejectedValueOnce(fail("internal_error"));
    const transport = makeTransport(restore);
    renderTrash(
      { items: [task, note], has_more: false, next_cursor: null },
      transport,
    );

    const user = userEvent.setup();
    await user.click(
      screen.getByRole("button", { name: "Återställ Förbered pitchen" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      controlSv.restoreFailed,
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Återställ Förbered pitchen" }),
      ).toHaveFocus(),
    );
  });

  it("says a failed restore in the family's write error row, with a Försök igen that restores again", async () => {
    const restore = vi
      .fn<Restore>()
      .mockRejectedValueOnce(fail("internal_error"))
      .mockResolvedValueOnce({});
    renderTrash(
      { items: [task], has_more: false, next_cursor: null },
      makeTransport(restore),
    );

    const user = userEvent.setup();
    await user.click(
      screen.getByRole("button", { name: "Återställ Förbered pitchen" }),
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveClass("sk-error--row");
    expect(alert).toHaveTextContent(controlSv.restoreFailed);
    // The line is the sentence and the button says the rest: the sentence does not.
    expect(controlSv.restoreFailed).not.toMatch(/försök igen/i);
    await user.click(
      within(alert).getByRole("button", { name: "Försök igen" }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent("Återställd");
    expect(restore).toHaveBeenCalledTimes(2);
    expect(restore.mock.calls[1]?.[1]).toBe(restore.mock.calls[0]?.[1]);
  });

  it("shows a failed restore in the row it was on, not at the top of the list", async () => {
    const restore = vi
      .fn<Restore>()
      .mockRejectedValueOnce(fail("internal_error"));
    renderTrash(
      { items: [task, note], has_more: false, next_cursor: null },
      makeTransport(restore),
    );

    await userEvent.click(
      screen.getByRole("button", { name: "Återställ Kort dagbok" }),
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(controlSv.restoreFailed);
    expect(alert.closest("li")).toHaveTextContent("Kort dagbok");
    expect(alert.closest("li")).not.toHaveTextContent("Förbered pitchen");
  });

  it("says a neuter kind was deleted in the neuter form", () => {
    renderTrash(
      {
        items: [
          {
            kind: "project",
            id: "019f0000-0000-7000-8000-000000000104",
            label: "Köksrenovering",
            trashed_at: "2026-10-31T13:30:00Z",
            version: 1,
          },
        ],
        has_more: false,
        next_cursor: null,
      },
      makeTransport(),
    );
    expect(
      screen.getByText(metaLine("Projekt · borttaget igår 14:30")),
    ).toBeInTheDocument();
  });
});

describe("TrashView paging", () => {
  const older: TrashItem = {
    kind: "task",
    id: "019f0000-0000-7000-8000-000000000103",
    label: "Äldre uppgift",
    trashed_at: "2026-10-20T09:00:00Z",
    version: 1,
  };
  const firstPage: TrashList = {
    items: [task, note],
    has_more: true,
    next_cursor: "page-2",
  };

  it("offers Visa fler only while the server has another page", () => {
    const transport = makeTransport();
    const { unmount } = renderTrash(firstPage, transport);
    expect(
      screen.getByRole("button", { name: controlSv.trashMore }),
    ).toBeInTheDocument();
    unmount();

    renderTrash(
      { ...firstPage, has_more: false, next_cursor: null },
      transport,
    );
    expect(
      screen.queryByRole("button", { name: controlSv.trashMore }),
    ).toBeNull();
  });

  it("asks for the next page with the cursor and appends it without repeating a row", async () => {
    const user = userEvent.setup();
    const transport = makeTransport();
    transport.trash.mockResolvedValueOnce({
      items: [note, older],
      has_more: false,
      next_cursor: null,
    });
    renderTrash(firstPage, transport);

    await user.click(screen.getByRole("button", { name: controlSv.trashMore }));

    expect(transport.trash).toHaveBeenCalledExactlyOnceWith("page-2");
    await waitFor(() =>
      expect(screen.getByText("Äldre uppgift")).toBeInTheDocument(),
    );
    expect(screen.getAllByText("Kort dagbok")).toHaveLength(1);
    expect(
      screen.queryByRole("button", { name: controlSv.trashMore }),
    ).toBeNull();
  });

  it("says so, keeps the rows and lets the owner try again when a page fails", async () => {
    const user = userEvent.setup();
    const transport = makeTransport();
    transport.trash
      .mockRejectedValueOnce(fail("unavailable"))
      .mockResolvedValueOnce({
        items: [older],
        has_more: false,
        next_cursor: null,
      });
    renderTrash(firstPage, transport);

    await user.click(screen.getByRole("button", { name: controlSv.trashMore }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      controlSv.trashMoreFailed,
    );
    expect(screen.getByText("Förbered pitchen")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: controlSv.trashMore }));
    await waitFor(() =>
      expect(screen.getByText("Äldre uppgift")).toBeInTheDocument(),
    );
    expect(screen.queryByRole("alert")).toBeNull();
    expect(transport.trash).toHaveBeenNthCalledWith(2, "page-2");
  });

  it("drops a page that arrives after the list was read again", async () => {
    const user = userEvent.setup();
    const transport = makeTransport();
    let deliver: (page: TrashList) => void = () => undefined;
    transport.trash.mockReturnValueOnce(
      new Promise<TrashList>((resolve) => {
        deliver = resolve;
      }),
    );
    const view = renderTrash(firstPage, transport);

    await user.click(screen.getByRole("button", { name: controlSv.trashMore }));
    view.rerender(
      <TrashView
        initial={{ items: [task], has_more: false, next_cursor: null }}
        transport={transport}
        labels={controlSv}
        now={now}
      />,
    );
    deliver({ items: [older], has_more: false, next_cursor: null });

    await waitFor(() =>
      expect(screen.getByText("Förbered pitchen")).toBeInTheDocument(),
    );
    expect(screen.queryByText("Äldre uppgift")).toBeNull();
  });
});

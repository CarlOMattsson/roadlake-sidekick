import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi, type Mock } from "vitest";

import {
  controlEn,
  controlSv,
  type ControlLabels,
} from "@/features/control-app/labels";
import type { RoomTarget } from "@/features/mcp-apps/room-types";
import { RECEIPT_MS } from "@/features/mcp-apps/ui/receipt";
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
    trash: vi.fn((): Promise<TrashList> =>
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

function renderTrash(
  initial: TrashList,
  transport: ControlTransport,
  onOpen?: (target: RoomTarget) => void,
  labels: ControlLabels = controlSv,
  onOpenFull?: () => void,
) {
  return render(
    <TrashView
      initial={initial}
      transport={transport}
      labels={labels}
      now={now}
      onOpen={onOpen}
      onOpenFull={onOpenFull}
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

  it("lists three rows and ends with the open link that names the rest", async () => {
    const items: TrashItem[] = Array.from({ length: 7 }, (_, index) => ({
      ...task,
      id: `019f0000-0000-7000-8000-00000000020${index}`,
      label: `Post ${index + 1}`,
    }));
    const onOpenFull = vi.fn();
    renderTrash(
      { items, has_more: false, next_cursor: null },
      makeTransport(),
      undefined,
      controlSv,
      onOpenFull,
    );

    const list = screen.getByRole("list", { name: "Borttaget" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(3);
    expect(screen.queryByText("Post 4")).not.toBeInTheDocument();

    // One main link, last in the card: the phrase, then what is left out, then the arrow.
    const open = screen.getByRole("button", { name: /Öppna Borttaget/ });
    expect(open).toHaveTextContent("Öppna Borttaget · 4 till");
    expect(open.querySelector("svg")).not.toBeNull();
    expect(
      screen.queryByRole("button", { name: /Visa alla|Visa färre/ }),
    ).toBeNull();
    await userEvent.setup().click(open);
    expect(onOpenFull).toHaveBeenCalledOnce();
  });

  it("lists every row and has no link where the card cannot open the full view", () => {
    const items: TrashItem[] = Array.from({ length: 5 }, (_, index) => ({
      ...task,
      id: `019f0000-0000-7000-8000-00000000026${index}`,
      label: `Post ${index + 1}`,
    }));
    renderTrash({ items, has_more: false, next_cursor: null }, makeTransport());

    expect(
      within(screen.getByRole("list", { name: "Borttaget" })).getAllByRole(
        "listitem",
      ),
    ).toHaveLength(5);
    expect(
      screen.queryByRole("button", { name: /Öppna Borttaget/ }),
    ).toBeNull();
  });

  it("lists every row it holds in the full view, with no open link", () => {
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
    expect(
      screen.queryByRole("button", { name: /Öppna Borttaget/ }),
    ).toBeNull();
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
      undefined,
      controlSv,
      vi.fn(),
    );

    expect(container.querySelector("p.control-meta")).toHaveTextContent(
      "5+ borttagna · kan återställas",
    );
    expect(
      screen.getByRole("button", { name: /Öppna Borttaget/ }),
    ).toHaveTextContent("Öppna Borttaget · 2+ till");
    // The next page is for the full view: the inline card leaves the rest behind its link.
    expect(screen.queryByRole("button", { name: "Visa fler" })).toBeNull();
  });

  it("counts the rows still in the trash in the open link after a restore", async () => {
    const items: TrashItem[] = Array.from({ length: 5 }, (_, index) => ({
      ...task,
      id: `019f0000-0000-7000-8000-00000000022${index}`,
      label: `Post ${index + 1}`,
    }));
    renderTrash(
      { items, has_more: false, next_cursor: null },
      makeTransport(),
      undefined,
      controlSv,
      vi.fn(),
    );

    expect(
      screen.getByRole("button", { name: /Öppna Borttaget/ }),
    ).toHaveTextContent("· 2 till");
    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Återställ Post 1" }));
    await screen.findByText("Återställd: Post 1");

    // Four rows are left in the trash, three of them listed: one is behind the link. The restored row is gone.
    expect(
      screen.getByRole("button", { name: /Öppna Borttaget/ }),
    ).toHaveTextContent("· 1 till");
    expect(screen.queryByText("Post 1")).toBeNull();
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
  it("restores the exact item the list showed and answers in the receipt bar", async () => {
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

    // The receipt says what happened in a status region; the row is gone from the list at once, nothing in it moves.
    const receipt = (
      await screen.findByText("Återställd: Förbered pitchen")
    ).closest(".sk-receipt");
    expect(receipt?.closest("[role='status']")).not.toBeNull();
    expect(
      within(screen.getByRole("list", { name: "Borttaget" })).queryByText(
        "Förbered pitchen",
      ),
    ).toBeNull();
    const rows = screen.getAllByRole("listitem");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent("Kort dagbok");
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

    expect(await screen.findByText("Återställd")).toBeInTheDocument();
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

    expect(
      await screen.findByText("Återställd: Förbered pitchen"),
    ).toBeInTheDocument();
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

  it("goes away by itself after RECEIPT_MS and leaves the empty state when it was the last row", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderTrash(
      { items: [task], has_more: false, next_cursor: null },
      makeTransport(),
    );

    await user.click(
      screen.getByRole("button", { name: "Återställ Förbered pitchen" }),
    );
    expect(
      await screen.findByText("Återställd: Förbered pitchen"),
    ).toBeInTheDocument();
    expect(screen.getByText("Inget borttaget.")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(RECEIPT_MS - 100);
    });
    expect(
      screen.getByText("Återställd: Förbered pitchen"),
    ).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(200);
    });

    expect(screen.queryByText("Återställd: Förbered pitchen")).toBeNull();
    expect(screen.getByText("Inget borttaget.")).toBeInTheDocument();
  });

  it("shows one receipt at a time: a second restore replaces the first", async () => {
    const user = userEvent.setup();
    renderTrash(
      { items: [task, note], has_more: false, next_cursor: null },
      makeTransport(),
    );

    await user.click(
      screen.getByRole("button", { name: "Återställ Kort dagbok" }),
    );
    await screen.findByText("Återställd: Kort dagbok");
    await user.click(
      screen.getByRole("button", { name: "Återställ Förbered pitchen" }),
    );

    expect(
      await screen.findByText("Återställd: Förbered pitchen"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Återställd: Kort dagbok")).toBeNull();
  });
});

describe("TrashView restored receipt", () => {
  const project: TrashItem = {
    ...task,
    kind: "project",
    id: "019f0000-0000-7000-8000-000000000103",
    label: "Köksrenovering",
  };
  const step: TrashItem = {
    ...task,
    kind: "step",
    id: "019f0000-0000-7000-8000-000000000104",
    label: "Köp färg",
  };

  /** Restores the row and returns the receipt bar that says so. */
  async function restoreRow(
    items: TrashItem[],
    title: string,
    onOpen?: (target: RoomTarget) => void,
    labels?: ControlLabels,
    restoreLabel = `Återställ ${title}`,
    message = `Återställd: ${title}`,
  ) {
    renderTrash(
      { items, has_more: false, next_cursor: null },
      makeTransport(),
      onOpen,
      labels,
    );
    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: restoreLabel }));
    return (await screen.findByText(message)).closest(
      ".sk-receipt",
    ) as HTMLElement;
  }

  it("names the restored record in the receipt", async () => {
    expect(await restoreRow([project], "Köksrenovering")).toHaveTextContent(
      "Återställd: Köksrenovering",
    );
  });

  it("names the restored record in English", async () => {
    expect(
      await restoreRow(
        [task],
        "Förbered pitchen",
        undefined,
        controlEn,
        "Restore Förbered pitchen",
        "Restored: Förbered pitchen",
      ),
    ).toHaveTextContent("Restored: Förbered pitchen");
  });

  it("offers Visa to the restored record's room, and the bar closes when it is used", async () => {
    const onOpen = vi.fn();
    const bar = await restoreRow([task, note], "Förbered pitchen", onOpen);
    await userEvent
      .setup()
      .click(within(bar).getByRole("button", { name: "Visa" }));
    expect(onOpen).toHaveBeenCalledExactlyOnceWith({
      room: "work",
      view: "task",
      id: task.id,
      label: "Förbered pitchen",
    });
    expect(screen.queryByText("Återställd: Förbered pitchen")).toBeNull();
  });

  it("opens a restored journal entry without carrying its title", async () => {
    const onOpen = vi.fn();
    const bar = await restoreRow([note], "Kort dagbok", onOpen);
    await userEvent
      .setup()
      .click(within(bar).getByRole("button", { name: "Visa" }));
    expect(onOpen).toHaveBeenCalledExactlyOnceWith({
      room: "journal",
      view: "entry",
      id: note.id,
    });
  });

  it("has no link for a record no room opens", async () => {
    const bar = await restoreRow([step], "Köp färg", vi.fn());
    expect(within(bar).queryByRole("button")).toBeNull();
  });

  it("has no link without a room to navigate with", async () => {
    const bar = await restoreRow([task], "Förbered pitchen");
    expect(within(bar).queryByRole("button")).toBeNull();
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
    expect(
      await screen.findByText("Återställd: Förbered pitchen"),
    ).toBeInTheDocument();
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

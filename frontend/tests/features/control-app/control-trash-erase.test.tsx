import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi, type Mock } from "vitest";

import {
  controlEn,
  controlSv,
  type ControlLabels,
} from "@/features/control-app/labels";
import { TrashView } from "@/features/control-app/trash-view";
import type {
  EmptyResult,
  TrashItem,
  TrashList,
  TrashTransport,
} from "@/features/control-app/transport";

const now = () => new Date("2026-11-01T10:00:00Z");

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

const second: TrashItem = {
  ...task,
  id: "019f0000-0000-7000-8000-000000000103",
  label: "Boka lokal",
  version: 2,
};

const note: TrashItem = {
  kind: "journal_entry",
  id: "019f0000-0000-7000-8000-000000000102",
  label: "Kort dagbok",
  trashed_at: "2026-10-31T13:30:00Z",
  version: 2,
};

const goods: TrashItem = {
  kind: "shopping_item",
  id: "019f0000-0000-7000-8000-000000000104",
  label: "Mjölk",
  trashed_at: "2026-10-31T13:30:00Z",
  version: 1,
};

type Erase = (item: TrashItem, key: string) => Promise<unknown>;
type Empty = (key: string) => Promise<EmptyResult>;

/** What the transport answers when the list is read again; empty unless a test says otherwise. */
function makeTransport(
  options: {
    erase?: Mock<Erase> | null;
    empty?: Mock<Empty> | null;
    again?: TrashList;
  } = {},
) {
  const erase =
    options.erase === null
      ? undefined
      : (options.erase ??
        vi.fn<Erase>(() => Promise.resolve({ removed: true })));
  const empty =
    options.empty === null
      ? undefined
      : (options.empty ??
        vi.fn<Empty>(() => Promise.resolve({ removed: 2, kept: 0 })));
  const transport = {
    trash: vi.fn((): Promise<TrashList> =>
      Promise.resolve(
        options.again ?? { items: [], has_more: false, next_cursor: null },
      ),
    ),
    restore: vi.fn(() => Promise.resolve({})),
    ...(erase ? { erase } : {}),
    ...(empty ? { empty } : {}),
  } satisfies TrashTransport;
  return { transport, erase, empty };
}

function renderTrash(
  items: TrashItem[],
  transport: TrashTransport,
  labels: ControlLabels = controlSv,
  has_more = false,
) {
  return render(
    <TrashView
      initial={{
        items,
        has_more,
        next_cursor: has_more ? "page-2" : null,
      }}
      transport={transport}
      labels={labels}
      now={now}
      full
    />,
  );
}

afterEach(() => cleanup());

describe("Radera för gott on a task row", () => {
  it("asks first, names the task and that it cannot be undone, and calls nothing yet", async () => {
    const user = userEvent.setup();
    const { transport, erase } = makeTransport();
    renderTrash([task], transport);

    await user.click(
      screen.getByRole("button", { name: "Radera Förbered pitchen för gott" }),
    );

    const question = screen.getByRole("group", {
      name: "Radera ”Förbered pitchen” för gott? Det går inte att ångra.",
    });
    expect(question).toHaveFocus();
    expect(erase).not.toHaveBeenCalled();
    // The other buttons wait while the question stands open.
    expect(
      screen.getByRole("button", { name: "Återställ Förbered pitchen" }),
    ).toBeDisabled();
  });

  it("calls erase with the row and one key only after Radera", async () => {
    const user = userEvent.setup();
    const { transport, erase } = makeTransport();
    renderTrash([task], transport);

    await user.click(
      screen.getByRole("button", { name: "Radera Förbered pitchen för gott" }),
    );
    await user.click(screen.getByRole("button", { name: "Radera" }));

    await waitFor(() => expect(erase).toHaveBeenCalledTimes(1));
    expect(erase).toHaveBeenCalledWith(task, expect.any(String));
    // The row stays a moment as a receipt, with no buttons, then goes.
    expect(await screen.findByText("Uppgift · raderad för gott")).toBeVisible();
    expect(screen.queryByRole("button", { name: /Radera/ })).toBeNull();
  });

  it("calls nothing on Avbryt and gives the focus back to the button", async () => {
    const user = userEvent.setup();
    const { transport, erase } = makeTransport();
    renderTrash([task], transport);
    const open = screen.getByRole("button", {
      name: "Radera Förbered pitchen för gott",
    });

    await user.click(open);
    await user.click(screen.getByRole("button", { name: "Avbryt" }));

    expect(erase).not.toHaveBeenCalled();
    expect(screen.queryByRole("group")).toBeNull();
    await waitFor(() => expect(open).toHaveFocus());
    expect(open).toBeEnabled();
  });

  it("calls nothing on Escape either", async () => {
    const user = userEvent.setup();
    const { transport, erase } = makeTransport();
    renderTrash([task], transport);

    await user.click(
      screen.getByRole("button", { name: "Radera Förbered pitchen för gott" }),
    );
    await user.keyboard("{Escape}");

    expect(erase).not.toHaveBeenCalled();
    expect(screen.queryByRole("group")).toBeNull();
  });

  it("reads the list again and says why on a conflict", async () => {
    const user = userEvent.setup();
    const { transport } = makeTransport({
      erase: vi.fn<Erase>(() => Promise.reject(fail("conflict"))),
      again: { items: [task], has_more: false, next_cursor: null },
    });
    renderTrash([task], transport);

    await user.click(
      screen.getByRole("button", { name: "Radera Förbered pitchen för gott" }),
    );
    await user.click(screen.getByRole("button", { name: "Radera" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Kan inte raderas: uppgiften har steg eller länkar kvar, eller ändrades. Ta bort dem i Claude.",
    );
    await waitFor(() => expect(transport.trash).toHaveBeenCalledTimes(1));
    // The row is still there, and its buttons are back.
    expect(
      screen.getByRole("button", { name: "Radera Förbered pitchen för gott" }),
    ).toBeEnabled();
  });

  it("says it in English too", async () => {
    const user = userEvent.setup();
    const { transport } = makeTransport({
      erase: vi.fn<Erase>(() => Promise.reject(fail("conflict"))),
      again: { items: [task], has_more: false, next_cursor: null },
    });
    renderTrash([task], transport, controlEn);

    await user.click(
      screen.getByRole("button", {
        name: "Delete Förbered pitchen permanently",
      }),
    );
    expect(
      screen.getByRole("group", {
        name: "Delete “Förbered pitchen” permanently? This can’t be undone.",
      }),
    ).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Delete" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Can’t delete: the task still has steps or links, or it was changed. Remove them in Claude.",
    );
  });

  it("offers a retry after a plain failure and keeps the row", async () => {
    const user = userEvent.setup();
    const { transport, erase } = makeTransport({
      erase: vi.fn<Erase>(() => Promise.reject(fail("unavailable"))),
    });
    renderTrash([task], transport);

    await user.click(
      screen.getByRole("button", { name: "Radera Förbered pitchen för gott" }),
    );
    await user.click(screen.getByRole("button", { name: "Radera" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Det gick inte att radera.",
    );
    expect(screen.getByText("Förbered pitchen")).toBeVisible();
    expect(screen.getByRole("button", { name: "Försök igen" })).toBeVisible();
    expect(erase).toHaveBeenCalledTimes(1);
  });
});

describe("what cannot be deleted for good", () => {
  it("gives a journal entry and a shopping item no delete button, and says why", () => {
    const { transport } = makeTransport();
    renderTrash([note, goods, task], transport);

    expect(
      screen.queryByRole("button", { name: /Radera Kort dagbok/ }),
    ).toBeNull();
    expect(screen.queryByRole("button", { name: /Radera Mjölk/ })).toBeNull();
    expect(
      screen.getByRole("button", { name: "Återställ Kort dagbok" }),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Radera Förbered pitchen för gott" }),
    ).toBeVisible();
    expect(
      screen.getByText(
        "Dagboksinlägg och varor kan inte raderas för gott, bara återställas.",
      ),
    ).toBeVisible();
  });

  it("offers no deleting at all where the transport has none (Claude)", () => {
    const { transport } = makeTransport({ erase: null, empty: null });
    renderTrash([note, task], transport);

    expect(screen.queryByRole("button", { name: /Radera/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Töm/ })).toBeNull();
    expect(screen.queryByText(/kan inte raderas för gott/)).toBeNull();
    expect(
      screen.getByRole("button", { name: "Återställ Förbered pitchen" }),
    ).toBeVisible();
  });

  it("offers no Töm papperskorgen when the trash holds no task", () => {
    const { transport } = makeTransport();
    renderTrash([note, goods], transport);

    expect(
      screen.queryByRole("button", { name: "Töm papperskorgen" }),
    ).toBeNull();
  });
});

describe("Töm papperskorgen", () => {
  it("asks first with the number of tasks and calls nothing yet", async () => {
    const user = userEvent.setup();
    const { transport, empty } = makeTransport();
    renderTrash([task, second, note], transport);

    await user.click(screen.getByRole("button", { name: "Töm papperskorgen" }));

    expect(
      screen.getByRole("group", {
        name: "Radera 2 uppgifter för gott? Dagboksinlägg och varor ligger kvar. Det går inte att ångra.",
      }),
    ).toHaveFocus();
    expect(empty).not.toHaveBeenCalled();
  });

  it("says at least N while the server holds more rows", async () => {
    const user = userEvent.setup();
    const { transport } = makeTransport();
    renderTrash([task, second], transport, controlSv, true);

    await user.click(screen.getByRole("button", { name: "Töm papperskorgen" }));

    expect(
      screen.getByText(/^Radera minst 2 uppgifter för gott\?/),
    ).toBeVisible();
  });

  it("calls nothing on Avbryt", async () => {
    const user = userEvent.setup();
    const { transport, empty } = makeTransport();
    renderTrash([task, second], transport);
    const open = screen.getByRole("button", { name: "Töm papperskorgen" });

    await user.click(open);
    await user.click(screen.getByRole("button", { name: "Avbryt" }));

    expect(empty).not.toHaveBeenCalled();
    expect(screen.queryByRole("group")).toBeNull();
    await waitFor(() => expect(open).toHaveFocus());
  });

  it("calls empty once after Radera, reads the list again and says what went and what stayed", async () => {
    const user = userEvent.setup();
    const { transport, empty } = makeTransport({
      empty: vi.fn<Empty>(() => Promise.resolve({ removed: 1, kept: 1 })),
      again: { items: [second, note], has_more: false, next_cursor: null },
    });
    renderTrash([task, second, note], transport);

    await user.click(screen.getByRole("button", { name: "Töm papperskorgen" }));
    await user.click(screen.getByRole("button", { name: "Radera" }));

    await waitFor(() => expect(empty).toHaveBeenCalledTimes(1));
    expect(empty).toHaveBeenCalledWith(expect.any(String));
    expect(
      await screen.findByText("1 raderad, 1 kunde inte raderas"),
    ).toBeVisible();
    expect(transport.trash).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Förbered pitchen")).toBeNull();
    expect(screen.getByText("Boka lokal")).toBeVisible();
  });

  it("says it in English too", async () => {
    const user = userEvent.setup();
    const { transport } = makeTransport({
      empty: vi.fn<Empty>(() => Promise.resolve({ removed: 2, kept: 0 })),
    });
    renderTrash([task, second], transport, controlEn);

    await user.click(screen.getByRole("button", { name: "Empty the trash" }));
    expect(
      screen.getByRole("group", {
        name: "Delete 2 tasks permanently? Journal entries and shopping items stay. This can’t be undone.",
      }),
    ).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Delete" }));

    expect(await screen.findByText("2 deleted")).toBeVisible();
  });
});

import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { RoomSurfaceContext } from "@/features/mcp-apps/ui/room-context";
import { ContactsView } from "@/features/work-app/contacts/contacts-list";
import { workEn } from "@/features/work-app/shared/labels";
import type {
  WorkContactsFrame,
  WorkContactSummary,
  WorkFrame,
  WorkTransport,
} from "@/features/work-app/transport/transport";

// The Contact list in a wide frame (desktop spec 2.2, 2.3 and 2.6). These are simulated hosts: the shell's head
// place is a div, and jsdom has no layout. They do not stand in for a real Claude or Android host.

function contact(name: string): WorkContactSummary {
  return { id: `id-${name}`, display_name: name, archived: false };
}

const ANNA = contact("Anna Andersson");
const BO = contact("Bo Berg");
const CECILIA = contact("Cecilia Ek");
const ROWS = [ANNA, BO, CECILIA];

const frame: WorkContactsFrame = {
  kind: "contacts",
  q: "",
  includeArchived: false,
  page: { items: ROWS, next_cursor: null, q: "", includeArchived: false },
};

const transport = {
  listContacts: vi.fn(),
  createContact: vi.fn(),
} as unknown as WorkTransport;

function renderList({
  slot,
  pane,
}: {
  slot?: HTMLElement;
  pane?: "list";
} = {}) {
  const onOpen = vi.fn<(frame: WorkFrame, label?: string) => void>();
  render(
    <RoomSurfaceContext.Provider
      value={{ active: true, framed: true, headSlot: slot ?? null, pane }}
    >
      <ContactsView
        frame={frame}
        onChange={vi.fn()}
        transport={transport}
        labels={workEn}
        moves={0}
        onOpen={onOpen}
        shortcuts
      />
    </RoomSurfaceContext.Provider>,
  );
  return { onOpen };
}

let slot: HTMLElement;
beforeEach(() => {
  slot = document.createElement("div");
  document.body.append(slot);
});
afterEach(() => {
  cleanup();
  slot.remove();
  delete document.documentElement.dataset.hostPointer;
});

it("draws search, + and ⋯ in the shell's head place, and leaves the field alone at the top of the list", () => {
  renderList({ slot });
  const head = within(slot);
  expect(
    head.getByRole("button", { name: workEn.searchContacts }),
  ).toBeVisible();
  expect(head.getByRole("button", { name: workEn.newContact })).toBeVisible();
  expect(head.getByRole("button", { name: workEn.moreActions })).toBeVisible();
  // The list holds the field and its rows, with no + or ⋯ of its own.
  const article = document.querySelector<HTMLElement>("article.work-contacts")!;
  expect(
    within(article).getByRole("searchbox", { name: workEn.searchContacts }),
  ).toBeVisible();
  expect(
    within(article).queryByRole("button", { name: workEn.newContact }),
  ).toBeNull();
  expect(
    within(article).queryByRole("button", { name: workEn.moreActions }),
  ).toBeNull();
});

it("keeps today's head (field, + and ⋯ in the list) when the shell has no place for one", () => {
  renderList();
  const article = document.querySelector<HTMLElement>("article.work-contacts")!;
  const head = article.querySelector(".work-contacts-head")!;
  expect(
    within(head as HTMLElement).getByRole("button", {
      name: workEn.newContact,
    }),
  ).toBeVisible();
  expect(
    within(head as HTMLElement).getByRole("button", {
      name: workEn.moreActions,
    }),
  ).toBeVisible();
  expect(document.querySelector(".sk-room-head")).toBeNull();
});

it("opens the new-Contact field from the head's + and gives the focus back to it on Esc", async () => {
  const user = userEvent.setup();
  renderList({ slot });
  const plus = within(slot).getByRole("button", { name: workEn.newContact });
  expect(plus).toHaveAttribute("aria-expanded", "false");
  await user.click(plus);
  expect(plus).toHaveAttribute("aria-expanded", "true");
  const field = screen.getByRole("textbox", { name: workEn.newContact });
  expect(field).toHaveFocus();
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("textbox", { name: workEn.newContact })).toBeNull();
  expect(plus).toHaveAttribute("aria-expanded", "false");
  expect(plus).toHaveFocus();
});

it("opens the field with n, and sends the focus into an open one", async () => {
  const user = userEvent.setup();
  renderList({ slot });
  await user.keyboard("n");
  const field = screen.getByRole("textbox", { name: workEn.newContact });
  expect(field).toHaveFocus();
  await user.click(screen.getByRole("searchbox"));
  await user.keyboard("{Escape}");
  (document.activeElement as HTMLElement).blur();
  await user.keyboard("n");
  expect(field).toHaveFocus();
});

it("moves the focus to the search field with / from the head", async () => {
  const user = userEvent.setup();
  renderList({ slot });
  await user.keyboard("/");
  expect(screen.getByRole("searchbox")).toHaveFocus();
});

it("opens ⋯ as a menu that Esc closes with the focus back on ⋯", async () => {
  const user = userEvent.setup();
  renderList({ slot });
  const more = within(slot).getByRole("button", { name: workEn.moreActions });
  await user.click(more);
  expect(more).toHaveAttribute("aria-expanded", "true");
  expect(
    screen.getByRole("switch", { name: workEn.showArchived }),
  ).toBeVisible();
  await user.keyboard("{Escape}");
  expect(more).toHaveAttribute("aria-expanded", "false");
  expect(more).toHaveFocus();
});

it("opens ⋯ with the arrow key, as every room's ⋯ does", async () => {
  const user = userEvent.setup();
  renderList({ slot });
  const more = within(slot).getByRole("button", { name: workEn.moreActions });
  more.focus();
  await user.keyboard("{ArrowDown}");
  expect(more).toHaveAttribute("aria-expanded", "true");
});

it("goes from the search field to the first row with ↓ or Enter, and back with ↑ on the first row", async () => {
  const user = userEvent.setup();
  renderList();
  const search = screen.getByRole("searchbox");
  const rows = () =>
    ROWS.map((row) => screen.getByRole("button", { name: row.display_name }));
  search.focus();
  await user.keyboard("{ArrowDown}");
  expect(rows()[0]).toHaveFocus();
  await user.keyboard("{ArrowUp}");
  expect(search).toHaveFocus();
  await user.keyboard("{Enter}");
  expect(rows()[0]).toHaveFocus();
  await user.keyboard("{ArrowDown}{ArrowDown}");
  expect(rows()[2]).toHaveFocus();
  await user.keyboard("{ArrowDown}");
  expect(rows()[2]).toHaveFocus();
  await user.keyboard("{ArrowUp}");
  expect(rows()[1]).toHaveFocus();
});

it("steps between rows with j and k without opening them in a single column", async () => {
  const user = userEvent.setup();
  const { onOpen } = renderList();
  const rows = ROWS.map((row) =>
    screen.getByRole("button", { name: row.display_name }),
  );
  await user.keyboard("j");
  expect(rows[0]).toHaveFocus();
  await user.keyboard("j");
  expect(rows[1]).toHaveFocus();
  await user.keyboard("k");
  expect(rows[0]).toHaveFocus();
  expect(onOpen).not.toHaveBeenCalled();
});

it("opens each Contact beside the list as j, k and the arrows step to it, named for the Back", async () => {
  const user = userEvent.setup();
  const { onOpen } = renderList({ pane: "list" });
  await user.keyboard("j");
  expect(onOpen).toHaveBeenLastCalledWith(
    { kind: "contact", id: ANNA.id },
    ANNA.display_name,
  );
  await user.keyboard("j");
  expect(onOpen).toHaveBeenLastCalledWith(
    { kind: "contact", id: BO.id },
    BO.display_name,
  );
  await user.keyboard("{ArrowDown}");
  expect(onOpen).toHaveBeenLastCalledWith(
    { kind: "contact", id: CECILIA.id },
    CECILIA.display_name,
  );
  // At the last row there is nowhere to step: nothing is opened again.
  onOpen.mockClear();
  await user.keyboard("j");
  expect(onOpen).not.toHaveBeenCalled();
});

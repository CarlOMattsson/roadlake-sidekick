import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, expect, it, vi } from "vitest";
import type { HostFeatures } from "@/features/mcp-apps/bridge";
import {
  SidekickShell,
  STALE_AFTER_MS,
} from "@/features/mcp-apps/sidekick-shell";
import {
  SIDEKICK_ROOMS,
  RoomHostContext,
  type RoomHost,
} from "@/features/mcp-apps/sidekick-rooms";
import type { NavEntry } from "@/features/mcp-apps/nav-state";
import { shoppingEn } from "@/features/shopping-app/labels";

// Item 4 of the round-1 fixes: a re-read must not reset the view. The real ShoppingRoom, inside the
// real shell and adapter, keeps what the user typed when the shell asks it to read again.

const LOCAL: HostFeatures = {
  serverTools: true,
  message: true,
  openLinks: true,
};
const list = {
  id: "019f0000-0000-7000-8000-000000000001",
  name: "Veckohandel",
  version: 1,
  archived: false,
  created_at: "2026-10-24T12:00:00Z",
  updated_at: "2026-10-24T12:00:00Z",
};
const detail = {
  shopping_list: list,
  evaluated_on: "2026-10-24",
  next_offset: null,
  items: [],
};
const start: NavEntry = {
  room: "shopping",
  view: "list",
  data: detail,
  resultId: 1,
};

const calls: string[] = [];
const call = vi.fn(async (name: string) => {
  await Promise.resolve();
  calls.push(name);
  if (name === "list_shopping_lists")
    return { lists: [list], next_offset: null };
  if (name === "get_shopping_list") return detail;
  if (name === "list_contacts") return { contacts: [], next_cursor: null };
  throw new Error(`unexpected ${name}`);
});
const host: RoomHost = {
  transport: {
    call: call as unknown as RoomHost["transport"]["call"],
    requestDisplayMode: vi.fn().mockResolvedValue("fullscreen"),
    updateModelContext: vi.fn().mockResolvedValue(undefined),
  },
  fullscreenAvailable: () => false,
  onExpand: vi.fn(),
};

beforeAll(() => {
  document.head.innerHTML = '<meta name="sidekick-app-locale" content="en">';
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  calls.length = 0;
  call.mockClear();
});

it("keeps the typed shopping text when the shell reads the room again after a long absence", async () => {
  vi.useFakeTimers({ toFake: ["Date"] });
  const user = userEvent.setup({ advanceTimers: () => undefined });
  render(
    <RoomHostContext.Provider value={host}>
      <SidekickShell
        locale="en"
        rooms={SIDEKICK_ROOMS}
        start={start}
        full
        features={LOCAL}
      />
    </RoomHostContext.Provider>,
  );
  const reads = () =>
    calls.filter((name) => name === "get_shopping_list").length;
  // The opening result carries the list: no first read of it.
  await waitFor(() =>
    expect(screen.queryByText(shoppingEn.loading)).not.toBeInTheDocument(),
  );
  expect(reads()).toBe(0);
  // The list is empty: "+ Add item" opens the create field in the list. The field is the textbox, not the row
  // button that shares its label.
  await user.click(screen.getByRole("button", { name: shoppingEn.addItem }));
  const quick = screen.getByRole("textbox", { name: shoppingEn.addItem });
  await user.type(quick, "Bröd");
  const before = reads();

  fireEvent.click(screen.getByRole("button", { name: "Contacts" }));
  act(() => {
    vi.setSystemTime(Date.now() + STALE_AFTER_MS + 1000);
  });
  fireEvent.click(screen.getByRole("button", { name: "Shopping" }));

  await waitFor(() => expect(reads()).toBeGreaterThan(before));
  await waitFor(() =>
    expect(screen.queryByText(shoppingEn.loading)).not.toBeInTheDocument(),
  );
  // The same field, not a new one, still holds the text.
  expect(screen.getByRole("textbox", { name: shoppingEn.addItem })).toBe(quick);
  expect(quick).toHaveValue("Bröd");
});

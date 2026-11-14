import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  COMPACT_ROWS,
  ShoppingView,
} from "@/features/shopping-app/shopping-view";
import { shoppingEn, shoppingSv } from "@/features/shopping-app/labels";
import { elementWithText } from "@tests/helpers/exact-text";
import type {
  ShoppingDetail,
  ShoppingList,
  ShoppingTransport,
} from "@/features/shopping-app/transport";

function listOf(n: number, name: string, over: Partial<ShoppingList> = {}) {
  return {
    id: `019f0000-0000-7000-8000-${String(n).padStart(12, "0")}`,
    name,
    version: 1,
    archived: false,
    created_at: "2026-10-24T12:00:00Z",
    updated_at: "2026-10-24T12:00:00Z",
    ...over,
  } as ShoppingList;
}

function detailOf(list: ShoppingList): ShoppingDetail {
  return {
    shopping_list: list,
    evaluated_on: "2026-10-24",
    next_offset: null,
    items: [],
  };
}

/** A transport whose list page is `lists`; reading a list answers that list's detail. */
function adapter(lists: ShoppingList[], over: Partial<ShoppingTransport> = {}) {
  return {
    lists: vi.fn().mockResolvedValue({ lists, next_offset: null }),
    get: vi.fn((id: string) => {
      const list = lists.find((entry) => entry.id === id) ?? lists[0]!;
      return Promise.resolve(detailOf(list));
    }),
    contacts: vi.fn().mockResolvedValue({ contacts: [] }),
    create: vi.fn(),
    rename: vi.fn(),
    add: vi.fn(),
    update: vi.fn(),
    purchase: vi.fn(),
    ...over,
  } as ShoppingTransport;
}

/** Waits until the first read has finished, so the rows can be tapped. */
async function row(name: string) {
  // A row's name holds the list name and its meta line ("7 left · updated today"), so it is matched by the start.
  const button = await screen.findByRole("button", {
    name: new RegExp(`^${name}`),
  });
  await waitFor(() => expect(button).toBeEnabled());
  return button;
}

describe("no list chosen: the lists are rows to tap", () => {
  it("shows every list as a row, and no create form or select before 'New list' is opened", async () => {
    const lists = [listOf(1, "Weekly shopping"), listOf(2, "IKEA someday")];
    render(<ShoppingView transport={adapter(lists)} labels={shoppingEn} />);
    await row("Weekly shopping");
    await row("IKEA someday");
    expect(
      screen.getByRole("heading", { name: shoppingEn.lists }),
    ).toBeInTheDocument();
    expect(screen.queryByText(shoppingEn.hint)).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("combobox")).toBeNull();
    const newList = screen.getByRole("button", { name: shoppingEn.newList });
    expect(newList).toHaveAttribute("aria-expanded", "false");
  });

  it("the + opens the create field in place, with focus and the example text", async () => {
    const user = userEvent.setup();
    const lists = [listOf(1, "Weekly shopping"), listOf(2, "IKEA someday")];
    render(<ShoppingView transport={adapter(lists)} labels={shoppingEn} />);
    await row("Weekly shopping");
    const newList = screen.getByRole("button", { name: shoppingEn.newList });
    await user.click(newList);
    expect(newList).toHaveAttribute("aria-expanded", "true");
    const field = screen.getByRole("textbox", { name: shoppingEn.newList });
    expect(field).toHaveFocus();
    expect(field).toHaveAttribute("placeholder", shoppingEn.newListPlaceholder);
  });

  it("Enter in the create field creates through the transport and opens the new list", async () => {
    const user = userEvent.setup();
    const garden = listOf(9, "Garden");
    const create = vi.fn().mockResolvedValue({ shopping_list: garden });
    const lists = [listOf(1, "Weekly shopping"), listOf(2, "IKEA someday")];
    const transport = adapter([...lists, garden], { create });
    render(<ShoppingView transport={transport} labels={shoppingEn} />);
    await row("Weekly shopping");
    await user.click(screen.getByRole("button", { name: shoppingEn.newList }));
    await user.type(
      screen.getByRole("textbox", { name: shoppingEn.newList }),
      "Garden{Enter}",
    );
    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    expect(create.mock.calls[0]![0]).toBe("Garden");
    expect(
      await screen.findByRole("heading", { name: "Garden" }),
    ).toBeInTheDocument();
  });

  it("Esc closes the create field and the focus goes back to the +", async () => {
    const user = userEvent.setup();
    const lists = [listOf(1, "Weekly shopping"), listOf(2, "IKEA someday")];
    render(<ShoppingView transport={adapter(lists)} labels={shoppingEn} />);
    await row("Weekly shopping");
    const newList = screen.getByRole("button", { name: shoppingEn.newList });
    await user.click(newList);
    expect(
      screen.getByRole("textbox", { name: shoppingEn.newList }),
    ).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(newList).toHaveAttribute("aria-expanded", "false");
    expect(newList).toHaveFocus();
  });

  it("a row names the list, what is left and when it changed", async () => {
    const lists = [
      listOf(1, "Weekly shopping", { open_count: 7 }),
      listOf(2, "Done list", { open_count: 0 }),
    ];
    render(<ShoppingView transport={adapter(lists)} labels={shoppingEn} />);
    expect(await row("Weekly shopping")).toHaveTextContent("7 left · updated");
    expect(await row("Done list")).toHaveTextContent("Nothing left");
  });

  it("the picker and its meta line are Swedish with Swedish labels", async () => {
    const lists = [
      listOf(1, "Veckohandling", { open_count: 7 }),
      listOf(2, "Klart", { open_count: 0 }),
    ];
    render(<ShoppingView transport={adapter(lists)} labels={shoppingSv} />);
    expect(await row("Veckohandling")).toHaveTextContent("7 kvar · uppdaterad");
    expect(await row("Klart")).toHaveTextContent("Inget kvar");
    expect(screen.getByRole("heading", { name: "Listor" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Ny lista" }),
    ).toBeInTheDocument();
  });

  it("tapping a row reads that list and shows it; 'All lists' returns to the rows", async () => {
    const user = userEvent.setup();
    const lists = [listOf(1, "Weekly shopping"), listOf(2, "IKEA someday")];
    const transport = adapter(lists);
    render(<ShoppingView transport={transport} labels={shoppingEn} />);
    await user.click(await row("IKEA someday"));
    expect(
      await screen.findByRole("heading", { name: "IKEA someday" }),
    ).toBeInTheDocument();
    expect(transport.get).toHaveBeenLastCalledWith(lists[1]!.id, 0, undefined);
    const back = screen.getByRole("button", {
      name: `Tillbaka till ${shoppingEn.backToLists}`,
    });
    await user.click(back);
    await row("Weekly shopping");
    expect(screen.queryByRole("heading", { name: "IKEA someday" })).toBeNull();
    expect(
      screen.queryByRole("button", {
        name: `Tillbaka till ${shoppingEn.backToLists}`,
      }),
    ).toBeNull();
  });

  it("with a list chosen, 'All lists' is in the room and the list view keeps its create form and select", async () => {
    const lists = [listOf(1, "Weekly shopping")];
    const transport = adapter(lists, {
      lists: vi.fn().mockResolvedValue({
        lists: [...lists, listOf(2, "IKEA someday")],
        next_offset: null,
      }),
    });
    render(
      <ShoppingView
        transport={transport}
        labels={shoppingEn}
        initial={detailOf(lists[0]!)}
      />,
    );
    expect(
      await screen.findByRole("heading", { name: "Weekly shopping" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: `Tillbaka till ${shoppingEn.backToLists}`,
      }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(shoppingEn.listName)).toBeInTheDocument();
    expect(screen.getByLabelText(shoppingEn.select)).toBeInTheDocument();
  });

  it("a fullscreen view lists every row, without 'Show all'", async () => {
    const lists = Array.from({ length: COMPACT_ROWS + 2 }, (_, index) =>
      listOf(index + 1, `Lista ${index + 1}`),
    );
    render(
      <ShoppingView
        transport={adapter(lists)}
        labels={shoppingEn}
        fullscreen
      />,
    );
    await row("Lista 1");
    expect(screen.getAllByRole("listitem")).toHaveLength(lists.length);
    expect(
      screen.queryByRole("button", { name: shoppingEn.showAll(lists.length) }),
    ).toBeNull();
  });

  it("inline, more than COMPACT_ROWS lists show the first rows and 'Show all' expands them", async () => {
    const user = userEvent.setup();
    const lists = Array.from({ length: COMPACT_ROWS + 2 }, (_, index) =>
      listOf(index + 1, `Lista ${index + 1}`),
    );
    render(<ShoppingView transport={adapter(lists)} labels={shoppingEn} />);
    await row("Lista 1");
    expect(screen.getAllByRole("listitem")).toHaveLength(COMPACT_ROWS);
    const showAll = screen.getByRole("button", {
      name: shoppingEn.showAll(lists.length),
    });
    await user.click(showAll);
    expect(screen.getAllByRole("listitem")).toHaveLength(lists.length);
    await user.click(
      screen.getByRole("button", { name: shoppingEn.showFewer }),
    );
    expect(screen.getAllByRole("listitem")).toHaveLength(COMPACT_ROWS);
  });

  it("exactly one list opens at once, and 'All lists' then shows the row instead of opening it again", async () => {
    const user = userEvent.setup();
    const only = listOf(1, "Weekly shopping");
    const transport = adapter([only]);
    render(<ShoppingView transport={transport} labels={shoppingEn} />);
    expect(
      await screen.findByRole("heading", { name: "Weekly shopping" }),
    ).toBeInTheDocument();
    // The list view is shown, not the picker: no "New list" button and no row for the list.
    expect(
      screen.queryByRole("button", { name: shoppingEn.newList }),
    ).toBeNull();
    await user.click(
      screen.getByRole("button", {
        name: `Tillbaka till ${shoppingEn.backToLists}`,
      }),
    );
    await row("Weekly shopping");
    expect(
      screen.queryByRole("heading", { name: "Weekly shopping" }),
    ).toBeNull();
  });

  it("with no lists, a short note and a tip show, and the + opens the create field; Enter creates", async () => {
    const user = userEvent.setup();
    const create = vi
      .fn()
      .mockResolvedValue({ shopping_list: listOf(9, "Garden") });
    render(
      <ShoppingView transport={adapter([], { create })} labels={shoppingEn} />,
    );
    expect(await screen.findByText(shoppingEn.noLists)).toBeInTheDocument();
    expect(screen.getByText(shoppingEn.pickerHint)).toBeInTheDocument();
    // The field is not drawn until the + is pressed.
    expect(screen.queryByRole("textbox")).toBeNull();
    await user.click(screen.getByRole("button", { name: shoppingEn.newList }));
    await user.type(
      screen.getByRole("textbox", { name: shoppingEn.newList }),
      "Garden{Enter}",
    );
    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    expect(create.mock.calls[0]![0]).toBe("Garden");
  });

  it("archived lists wait last behind a folded 'Archived (N)'", async () => {
    const user = userEvent.setup();
    const lists = [
      listOf(1, "Old list", { archived: true }),
      listOf(2, "Weekly shopping"),
    ];
    render(<ShoppingView transport={adapter(lists)} labels={shoppingEn} />);
    await row("Weekly shopping");
    expect(screen.queryByRole("button", { name: /^Old list/ })).toBeNull();
    const fold = elementWithText(shoppingEn.archivedLists(1), "button");
    expect(fold).toHaveAttribute("aria-expanded", "false");
    await user.click(fold);
    expect(fold).toHaveAttribute("aria-expanded", "true");
    expect(await row("Old list")).toBeInTheDocument();
    // The group names them, so the row does not repeat "Archived".
    expect(
      screen.getByRole("button", { name: /^Old list/ }),
    ).not.toHaveTextContent(/archived/i);
  });

  it("has no archived group when no list is archived, and says it in Swedish", async () => {
    const user = userEvent.setup();
    const { unmount } = render(
      <ShoppingView
        transport={adapter([listOf(2, "Weekly shopping"), listOf(3, "Garden")])}
        labels={shoppingEn}
      />,
    );
    await row("Weekly shopping");
    expect(screen.queryByText(/^Archived/)).toBeNull();
    unmount();
    render(
      <ShoppingView
        transport={adapter([
          listOf(1, "Julklappar", { archived: true }),
          listOf(2, "Veckohandling"),
        ])}
        labels={shoppingSv}
      />,
    );
    await row("Veckohandling");
    await user.click(elementWithText("Arkiverade (1)", "button"));
    await row("Julklappar");
  });
});

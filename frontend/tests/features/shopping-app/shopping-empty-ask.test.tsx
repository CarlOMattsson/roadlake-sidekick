import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { ShoppingView } from "@/features/shopping-app/shopping-view";
import { ShoppingCard } from "@/features/shopping-app/shopping-card";
import { shoppingEn, shoppingSv } from "@/features/shopping-app/labels";
import type {
  ShoppingDetail,
  ShoppingTransport,
} from "@/features/shopping-app/transport";

const list = {
  id: "019f0000-0000-7000-8000-000000000001",
  name: "Garden",
  version: 1,
  archived: false,
  created_at: "2026-10-24T12:00:00Z",
  updated_at: "2026-10-24T12:00:00Z",
};
const empty: ShoppingDetail = {
  shopping_list: list,
  evaluated_on: "2026-10-24",
  next_offset: null,
  items: [],
};

function adapter(
  lists: unknown[] = [],
  detail: ShoppingDetail = empty,
): ShoppingTransport {
  return {
    lists: vi.fn().mockResolvedValue({ lists, next_offset: null }),
    get: vi.fn().mockResolvedValue(detail),
    create: vi.fn(),
    rename: vi.fn(),
    add: vi.fn(),
    update: vi.fn(),
    purchase: vi.fn(),
  } as ShoppingTransport;
}

it("no lists: the shared empty state offers a button that sends the example to Claude", async () => {
  const sendMessage = vi.fn().mockResolvedValue(true);
  const user = userEvent.setup();
  render(
    <ShoppingView
      transport={adapter()}
      labels={shoppingSv}
      sendMessage={sendMessage}
    />,
  );
  expect(await screen.findByText(shoppingSv.noLists)).toBeInTheDocument();
  expect(screen.getByText(shoppingSv.pickerHint)).toBeInTheDocument();
  await user.click(
    screen.getByRole("button", {
      name: "Skicka till Claude: Lägg till mjölk och ägg på inköpslistan",
    }),
  );
  expect(sendMessage).toHaveBeenCalledWith(
    "Lägg till mjölk och ägg på inköpslistan",
  );
});

it("no lists, and a host without messages: the example is text with nothing to press", async () => {
  render(<ShoppingView transport={adapter()} labels={shoppingEn} />);
  expect(await screen.findByText(shoppingEn.noLists)).toBeInTheDocument();
  expect(
    screen.getByText(`“${shoppingEn.emptyListsExample}”`),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /^Send to Claude/ }),
  ).not.toBeInTheDocument();
});

it("an empty list says what to ask for, with the list's name", async () => {
  const sendMessage = vi.fn().mockResolvedValue(true);
  const user = userEvent.setup();
  render(
    <ShoppingView
      transport={adapter([list])}
      labels={shoppingEn}
      initial={empty}
      sendMessage={sendMessage}
    />,
  );
  await waitFor(() =>
    expect(screen.queryByRole("status")).not.toBeInTheDocument(),
  );
  expect(screen.getByText(shoppingEn.empty)).toBeInTheDocument();
  await user.click(
    screen.getByRole("button", {
      name: "Send to Claude: Add coffee to Garden",
    }),
  );
  expect(sendMessage).toHaveBeenCalledWith("Add coffee to Garden");
});

it("the inline card's empty state carries the same ask", async () => {
  const sendMessage = vi.fn().mockResolvedValue(true);
  const user = userEvent.setup();
  render(
    <ShoppingCard
      detail={empty}
      labels={shoppingSv}
      onOpen={() => undefined}
      sendMessage={sendMessage}
    />,
  );
  await user.click(
    screen.getByRole("button", {
      name: "Skicka till Claude: Lägg till kaffe på listan Garden",
    }),
  );
  expect(sendMessage).toHaveBeenCalledWith("Lägg till kaffe på listan Garden");
});

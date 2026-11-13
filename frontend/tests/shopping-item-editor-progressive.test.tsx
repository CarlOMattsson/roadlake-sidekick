import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ItemEditor } from "@/features/shopping-app/shopping-view-parts/item-editor";
import { shoppingEn, shoppingSv } from "@/features/shopping-app/labels";
import type { ShoppingLabels } from "@/features/shopping-app/labels";
import type { ShoppingItem } from "@/features/shopping-app/transport";

function item(over: Partial<ShoppingItem> = {}): ShoppingItem {
  return {
    id: "019f0000-0000-7000-8000-0000000000a0",
    list_id: "019f0000-0000-7000-8000-000000000001",
    name: "Milk",
    quantity: "2",
    unit: "l",
    note: null,
    occasion: null,
    offer: null,
    offer_status: "none",
    product_url: null,
    purchased: false,
    purchased_at: null,
    recipient_contact_id: null,
    store: "ICA MAXI 4",
    target_date: null,
    created_at: "2026-10-24T12:00:00Z",
    updated_at: "2026-10-24T12:00:00Z",
    version: 1,
    ...over,
  };
}

function renderEditor(
  value: ShoppingItem,
  labels: ShoppingLabels = shoppingEn,
  onSave = vi.fn(),
) {
  render(
    <ItemEditor
      item={value}
      labels={labels}
      busy={false}
      focusFirst={false}
      contacts={vi.fn().mockResolvedValue({ contacts: [] })}
      onCancel={vi.fn()}
      onSave={onSave}
    />,
  );
  return onSave;
}

/** The container of the fields behind "More fields". */
function extra(): HTMLElement {
  const element = document.querySelector<HTMLElement>(".shopping-editor-extra");
  if (!element) throw new Error("no .shopping-editor-extra");
  return element;
}

describe("the item change form shows the main fields first", () => {
  it("starts with item, quantity, unit and store; More fields is closed and the rest is hidden", () => {
    renderEditor(item());
    expect(screen.getByLabelText(shoppingEn.name)).toBeVisible();
    expect(screen.getByLabelText(shoppingEn.quantity)).toBeVisible();
    expect(screen.getByLabelText(shoppingEn.unit)).toBeVisible();
    expect(screen.getByLabelText(shoppingEn.store)).toBeVisible();
    const more = screen.getByRole("button", { name: shoppingEn.moreFields });
    expect(more).toHaveAttribute("aria-expanded", "false");
    expect(extra()).toHaveAttribute("hidden");
    expect(screen.getByLabelText(shoppingEn.note)).not.toBeVisible();
    expect(screen.queryByText(/filled$/)).toBeNull();
  });

  it("More fields opens the extra fields and closes them again", async () => {
    const user = userEvent.setup();
    renderEditor(item());
    const more = screen.getByRole("button", { name: shoppingEn.moreFields });
    await user.click(more);
    expect(more).toHaveAttribute("aria-expanded", "true");
    expect(extra()).not.toHaveAttribute("hidden");
    expect(screen.getByLabelText(shoppingEn.note)).toBeVisible();
    expect(screen.getByLabelText(shoppingEn.occasion)).toBeVisible();
    expect(
      screen.getByRole("button", { name: shoppingEn.searchContact }),
    ).toBeVisible();
    await user.click(more);
    expect(more).toHaveAttribute("aria-expanded", "false");
    expect(extra()).toHaveAttribute("hidden");
  });

  it("the closed toggle says '2 filled' when two extra fields hold a value", () => {
    renderEditor(item({ note: "Organic", occasion: "Birthday" }));
    expect(
      screen.getByRole("button", { name: /^More fields/ }),
    ).toHaveTextContent(shoppingEn.moreFieldsFilled(2));
    expect(screen.getByText("2 filled")).toBeInTheDocument();
  });

  it("Save with More fields closed still sends the unchanged extra values", async () => {
    const user = userEvent.setup();
    const onSave = renderEditor(
      item({ note: "Organic", occasion: "Birthday", product_url: null }),
    );
    await user.clear(screen.getByLabelText(shoppingEn.name));
    await user.type(screen.getByLabelText(shoppingEn.name), "Oat milk");
    await user.click(screen.getByRole("button", { name: shoppingEn.save }));
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave.mock.calls[0]![0]).toMatchObject({
      name: "Oat milk",
      quantity: "2",
      unit: "l",
      store: "ICA MAXI 4",
      note: "Organic",
      occasion: "Birthday",
      product_url: null,
      offer: null,
    });
  });

  it("the toggle and its count are Swedish with Swedish labels", () => {
    renderEditor(item({ note: "Eko", occasion: "Födelsedag" }), shoppingSv);
    const more = screen.getByRole("button", { name: /^Fler fält/ });
    expect(more).toHaveAttribute("aria-expanded", "false");
    expect(more).toHaveTextContent(shoppingSv.moreFieldsFilled(2));
    expect(more).toHaveTextContent("2 ifyllda");
  });
});

describe("the recipient of a gift item", () => {
  const linked = {
    recipient_contact_id: "019f0000-0000-7000-8000-0000000000c1",
  };

  it("shows the contact name where the recipient is not among the search hits", () => {
    renderEditor(item({ ...linked, recipient_contact_name: "Astrid Ek" }));
    expect(
      screen.getByRole("option", { name: "Astrid Ek", hidden: true }),
    ).toBeInTheDocument();
    expect(screen.queryByText(shoppingEn.linkedContact)).toBeNull();
  });

  it("falls back to the general label when the server sent no name", () => {
    renderEditor(item({ ...linked, recipient_contact_name: null }));
    expect(
      screen.getByRole("option", {
        name: shoppingEn.linkedContact,
        hidden: true,
      }),
    ).toBeInTheDocument();
  });

  it("falls back to the Swedish label when the name is missing", () => {
    renderEditor(item(linked), shoppingSv);
    expect(
      screen.getByRole("option", { name: "Nuvarande mottagare", hidden: true }),
    ).toBeInTheDocument();
  });
});

describe("the offer's fields are a fold of their own", () => {
  const offer = {
    price: "199.00",
    regular_price: "289.00",
    currency: "SEK",
    valid_from: "2026-11-01",
    valid_until: "2026-11-30",
    checked_on: "2026-11-05",
    source: "ica.se",
    source_url: null,
  };

  it("says what is saved on the closed toggle, in English and Swedish", async () => {
    const user = userEvent.setup();
    const { unmount } = render(
      <ItemEditor
        item={item({ offer, offer_status: "current" })}
        labels={shoppingEn}
        busy={false}
        focusFirst={false}
        contacts={undefined}
        onCancel={vi.fn()}
        onSave={vi.fn()}
      />,
    );
    await user.click(screen.getByRole("button", { name: /^More fields/ }));
    expect(
      screen.getByRole("button", { name: /^Offer: SEK\s199 until 30 Nov$/ }),
    ).toHaveAttribute("aria-expanded", "false");
    unmount();
    renderEditor(item({ offer, offer_status: "current" }), shoppingSv);
    await user.click(screen.getByRole("button", { name: /^Fler fält/ }));
    expect(
      screen.getByRole("button", {
        name: /^Erbjudande: 199\skr t\.o\.m\. 30 nov$/,
      }),
    ).toBeInTheDocument();
  });

  it("is only the word Offer when none is saved, and opens its fields on a tap", async () => {
    const user = userEvent.setup();
    renderEditor(item());
    await user.click(
      screen.getByRole("button", { name: shoppingEn.moreFields }),
    );
    const toggle = screen.getByRole("button", { name: shoppingEn.offer });
    expect(screen.getByLabelText(shoppingEn.price)).not.toBeVisible();
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByLabelText(shoppingEn.price)).toBeVisible();
    await user.click(toggle);
    expect(screen.getByLabelText(shoppingEn.price)).not.toBeVisible();
  });

  it("Save with the offer folded still sends it unchanged", async () => {
    const user = userEvent.setup();
    const onSave = renderEditor(item({ offer, offer_status: "current" }));
    await user.click(screen.getByRole("button", { name: shoppingEn.save }));
    expect(onSave.mock.calls[0]![0]).toMatchObject({
      offer: { price: "199", currency: "SEK", valid_until: "2026-11-30" },
    });
  });

  it("a wrong value in the folded offer opens it on Save", async () => {
    const user = userEvent.setup();
    const onSave = renderEditor(item({ offer, offer_status: "current" }));
    await user.click(screen.getByRole("button", { name: /^More fields/ }));
    await user.clear(screen.getByLabelText(shoppingEn.currency));
    await user.type(screen.getByLabelText(shoppingEn.currency), "kr");
    await user.click(screen.getByRole("button", { name: shoppingEn.save }));
    expect(onSave).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /^Offer: / })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });
});

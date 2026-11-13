import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ItemEditor } from "@/features/shopping-app/shopping-view-parts/item-editor";
import { shoppingEn, shoppingSv } from "@/features/shopping-app/labels";
import type { ShoppingLabels } from "@/features/shopping-app/labels";
import type {
  ShoppingInput,
  ShoppingItem,
} from "@/features/shopping-app/transport";

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
      screen.getByRole("button", { name: shoppingEn.chooseContact }),
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
  const anna = {
    id: "019f0000-0000-7000-8000-0000000000c2",
    display_name: "Anna Andersson",
  };

  /** The editor with a contact search that answers `hits`, or none at all (the mobile app) when `search` is false. */
  function renderGift(
    value: ShoppingItem,
    options: {
      labels?: ShoppingLabels;
      hits?: { id: string; display_name: string }[];
      search?: boolean;
    } = {},
  ) {
    const onSave = vi.fn<(value: ShoppingInput) => void>();
    const contacts = vi
      .fn()
      .mockResolvedValue({ contacts: options.hits ?? [] });
    render(
      <ItemEditor
        item={value}
        labels={options.labels ?? shoppingEn}
        busy={false}
        focusFirst={false}
        contacts={options.search === false ? undefined : contacts}
        onCancel={vi.fn()}
        onSave={onSave}
      />,
    );
    return { onSave, contacts };
  }

  function recipient(labels: ShoppingLabels = shoppingEn): HTMLElement {
    return screen.getByRole("group", { name: labels.recipient, hidden: true });
  }

  it("names the contact, with Change and Remove, where the server sent the name", () => {
    renderGift(item({ ...linked, recipient_contact_name: "Astrid Ek" }));
    const group = within(recipient());
    expect(group.getByText("Astrid Ek")).toBeInTheDocument();
    expect(
      group.getByRole("button", { name: "Change", hidden: true }),
    ).toBeInTheDocument();
    expect(
      group.getByRole("button", { name: "Remove", hidden: true }),
    ).toBeInTheDocument();
    // One control: no drop-down, no standing search field.
    expect(screen.queryByRole("combobox", { hidden: true })).toBeNull();
    expect(screen.queryByLabelText(shoppingEn.contactQuery)).toBeNull();
    expect(group.queryByText(shoppingEn.linkedContact)).toBeNull();
  });

  it("falls back to the general label when the server sent no name", () => {
    renderGift(item({ ...linked, recipient_contact_name: null }));
    expect(within(recipient()).getByText("Linked contact")).toBeInTheDocument();
  });

  it("falls back to the Swedish label when the name is missing", () => {
    renderGift(item(linked), { labels: shoppingSv });
    const group = within(recipient(shoppingSv));
    expect(group.getByText("Kopplad kontakt")).toBeInTheDocument();
    expect(
      group.getByRole("button", { name: "Byt", hidden: true }),
    ).toBeInTheDocument();
    expect(
      group.getByRole("button", { name: "Ta bort", hidden: true }),
    ).toBeInTheDocument();
  });

  it("offers one button to choose a contact when there is none, and no search until it is pressed", () => {
    renderGift(item());
    expect(
      within(recipient()).getByRole("button", {
        name: "Choose contact",
        hidden: true,
      }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText(shoppingEn.contactQuery)).toBeNull();
  });

  it("searches, picks a hit by pressing its name and saves that contact", async () => {
    const user = userEvent.setup();
    const { onSave, contacts } = renderGift(item(), { hits: [anna] });
    await user.click(screen.getByRole("button", { name: /^More fields/ }));
    await user.click(screen.getByRole("button", { name: "Choose contact" }));
    // The field takes the focus, and Enter searches (a sandboxed host never submits a form).
    const field = screen.getByLabelText(shoppingEn.contactQuery);
    expect(field).toHaveFocus();
    await user.type(field, "Anna{Enter}");
    expect(contacts).toHaveBeenCalledWith("Anna");
    await user.click(
      await screen.findByRole("button", { name: "Anna Andersson" }),
    );
    expect(screen.queryByLabelText(shoppingEn.contactQuery)).toBeNull();
    expect(within(recipient()).getByText("Anna Andersson")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(onSave.mock.calls[0]![0].recipient_contact_id).toBe(anna.id);
  });

  it("says when nothing was found, and closing the search keeps the earlier choice", async () => {
    const user = userEvent.setup();
    const { onSave } = renderGift(
      item({ ...linked, recipient_contact_name: "Astrid Ek" }),
    );
    await user.click(screen.getByRole("button", { name: /^More fields/ }));
    await user.click(screen.getByRole("button", { name: "Change" }));
    await user.type(screen.getByLabelText(shoppingEn.contactQuery), "Zed");
    await user.click(
      screen.getByRole("button", { name: shoppingEn.searchContact }),
    );
    expect(
      await screen.findByText(shoppingEn.noContactFound),
    ).toBeInTheDocument();
    // The search is left by its own ✕, so the change form around it keeps the one Cancel.
    expect(screen.queryByRole("button", { name: shoppingEn.close })).toBeNull();
    await user.click(
      screen.getByRole("button", { name: shoppingEn.cancelContactSearch }),
    );
    expect(within(recipient()).getByText("Astrid Ek")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(onSave.mock.calls[0]![0].recipient_contact_id).toBe(
      linked.recipient_contact_id,
    );
  });

  it("Escape leaves the search and keeps the change form open", async () => {
    const user = userEvent.setup();
    renderGift(item({ ...linked, recipient_contact_name: "Astrid Ek" }));
    await user.click(screen.getByRole("button", { name: /^More fields/ }));
    await user.click(screen.getByRole("button", { name: "Change" }));
    await user.type(
      screen.getByLabelText(shoppingEn.contactQuery),
      "Zed{Escape}",
    );
    expect(screen.queryByLabelText(shoppingEn.contactQuery)).toBeNull();
    expect(within(recipient()).getByText("Astrid Ek")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeInTheDocument();
  });

  it("Remove clears the recipient and saves none", async () => {
    const user = userEvent.setup();
    const { onSave } = renderGift(
      item({ ...linked, recipient_contact_name: "Astrid Ek" }),
    );
    await user.click(screen.getByRole("button", { name: /^More fields/ }));
    await user.click(screen.getByRole("button", { name: "Remove" }));
    expect(screen.queryByText("Astrid Ek")).toBeNull();
    expect(
      screen.getByRole("button", { name: "Choose contact" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(onSave.mock.calls[0]![0].recipient_contact_id).toBeNull();
  });

  it("without a contact search (the mobile app) keeps the name and offers Remove only", () => {
    renderGift(item({ ...linked, recipient_contact_name: "Astrid Ek" }), {
      search: false,
    });
    const group = within(recipient());
    expect(group.getByText("Astrid Ek")).toBeInTheDocument();
    expect(
      group.getByRole("button", { name: "Remove", hidden: true }),
    ).toBeInTheDocument();
    expect(
      group.queryByRole("button", { name: "Change", hidden: true }),
    ).toBeNull();
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

describe("the offer's prices follow the app's language", () => {
  const offer = {
    price: "19.9",
    regular_price: "289.00",
    currency: "SEK",
    valid_from: "2026-11-01",
    valid_until: "2026-11-30",
    checked_on: "2026-11-05",
    source: "ica.se",
    source_url: null,
  };
  const withOffer = () => item({ offer, offer_status: "current" });

  it("shows a stored price with the decimal comma in Swedish and the point in English", () => {
    const { unmount } = render(
      <ItemEditor
        item={withOffer()}
        labels={shoppingSv}
        busy={false}
        focusFirst={false}
        contacts={undefined}
        onCancel={vi.fn()}
        onSave={vi.fn()}
      />,
    );
    expect(screen.getByLabelText(shoppingSv.price)).toHaveValue("19,90");
    expect(screen.getByLabelText(shoppingSv.regular)).toHaveValue("289");
    unmount();
    renderEditor(withOffer());
    expect(screen.getByLabelText(shoppingEn.price)).toHaveValue("19.90");
    expect(screen.getByLabelText(shoppingEn.regular)).toHaveValue("289");
  });

  it("takes a comma or a point and sends the price with a point", async () => {
    const user = userEvent.setup();
    const onSave = renderEditor(withOffer(), shoppingSv);
    const price = screen.getByLabelText(shoppingSv.price);
    await user.clear(price);
    await user.type(price, "24,5");
    const regular = screen.getByLabelText(shoppingSv.regular);
    await user.clear(regular);
    await user.type(regular, "30.25");
    await user.click(screen.getByRole("button", { name: shoppingSv.save }));
    expect(onSave.mock.calls[0]![0]).toMatchObject({
      offer: { price: "24.5", regular_price: "30.25" },
    });
  });

  it("sends the stored price with a point when it was not touched", async () => {
    const user = userEvent.setup();
    const onSave = renderEditor(withOffer(), shoppingSv);
    await user.click(screen.getByRole("button", { name: shoppingSv.save }));
    expect(onSave.mock.calls[0]![0]).toMatchObject({
      offer: { price: "19.90", regular_price: "289" },
    });
  });

  it("shows the stored quantity without empty decimals and sends it with a point, whichever separator is typed", async () => {
    const user = userEvent.setup();
    const onSave = renderEditor(item({ quantity: "2.000" }), shoppingSv);
    const quantity = screen.getByLabelText(shoppingSv.quantity);
    expect(quantity).toHaveValue("2");
    await user.clear(quantity);
    await user.type(quantity, "1,5");
    await user.click(screen.getByRole("button", { name: shoppingSv.save }));
    expect(onSave.mock.calls[0]![0]).toMatchObject({ quantity: "1.5" });
    await user.clear(quantity);
    await user.type(quantity, "2.25");
    await user.click(screen.getByRole("button", { name: shoppingSv.save }));
    expect(onSave.mock.calls[1]![0]).toMatchObject({ quantity: "2.25" });
  });

  it("writes a stored quantity in the language's decimal style", () => {
    renderEditor(item({ quantity: "1.500" }), shoppingEn);
    expect(screen.getByLabelText(shoppingEn.quantity)).toHaveValue("1.5");
  });

  it("refuses a quantity that is not a number, and says so in the language", async () => {
    const user = userEvent.setup();
    const onSave = renderEditor(item(), shoppingSv);
    const quantity = screen.getByLabelText(shoppingSv.quantity);
    await user.clear(quantity);
    await user.type(quantity, "mycket");
    expect(quantity).toHaveProperty(
      "validationMessage",
      shoppingSv.quantityInvalid,
    );
    await user.click(screen.getByRole("button", { name: shoppingSv.save }));
    expect(onSave).not.toHaveBeenCalled();
  });

  it("refuses text that is not a price, and says so in the language", async () => {
    const user = userEvent.setup();
    const onSave = renderEditor(withOffer(), shoppingSv);
    const price = screen.getByLabelText(shoppingSv.price);
    await user.clear(price);
    await user.type(price, "gratis");
    expect(price).toHaveProperty("validationMessage", shoppingSv.priceInvalid);
    await user.click(screen.getByRole("button", { name: shoppingSv.save }));
    expect(onSave).not.toHaveBeenCalled();
    await user.clear(price);
    await user.type(price, "1,234");
    expect(price).toHaveProperty("validationMessage", shoppingSv.priceInvalid);
  });
});

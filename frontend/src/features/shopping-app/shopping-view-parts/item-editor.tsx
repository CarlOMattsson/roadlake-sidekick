import { useEffect, useId, useRef, useState } from "react";
import { flushSync } from "react-dom";
import type {
  ShoppingInput,
  ShoppingItem,
  ShoppingTransport,
} from "../transport";
import type { ShoppingLabels } from "../labels";
import { ChevronDownIcon } from "../../mcp-apps/ui/icons";
import { onEnterKey } from "../../mcp-apps/ui/enter-key";
import { KeyScope } from "../../mcp-apps/ui/key-scope";
import { OfferFields } from "./offer-fields";
import { RecipientField } from "./recipient-field";
import {
  formatQuantityNumber,
  parsePriceInput,
  parseQuantityInput,
} from "./helpers";

/** How many of the fields behind the `moreFields` toggle hold a value, so the closed toggle can say that something is there. */
function filledExtras(item: ShoppingItem): number {
  return [
    item.product_url,
    item.occasion,
    item.target_date,
    item.recipient_contact_id,
    item.note,
    item.offer,
  ].filter(Boolean).length;
}

/**
 * Whether Enter in `target` saves the form: a one-line field (not the note, a button, a box or the contact search,
 * which has its own Enter) that is not choosing from a list. An open combobox or a field with an active option takes
 * Enter for that option. The shop field's datalist cannot be asked, so Enter leaves it to the browser while the typed
 * text only matches suggestions that differ from it; once the text is a whole suggestion (or none), Enter saves.
 */
function savesOnEnter(target: EventTarget): boolean {
  if (!(target instanceof HTMLInputElement)) return false;
  if (["button", "checkbox", "radio", "submit", "file"].includes(target.type))
    return false;
  if (target.closest(".shopping-recipient-search")) return false;
  if (
    target.getAttribute("aria-expanded") === "true" ||
    target.getAttribute("aria-activedescendant")
  )
    return false;
  const typed = target.value.trim().toLowerCase();
  if (!target.list || !typed) return true;
  return ![...target.list.options].some((option) => {
    const suggestion = option.value.toLowerCase();
    return suggestion !== typed && suggestion.includes(typed);
  });
}

export function ItemEditor({
  item,
  labels: t,
  busy,
  focusFirst,
  contacts,
  lists,
  stores,
  onCancel,
  onSave,
  onTrash,
}: {
  item: ShoppingItem;
  labels: ShoppingLabels;
  busy: boolean;
  focusFirst: boolean;
  contacts: ShoppingTransport["contacts"];
  /** The active lists the item can be moved between; the choice is offered when there is more than one. */
  lists: { id: string; name: string }[];
  /** The shops the list's items already name, offered as the store field's suggestions. */
  stores: string[];
  onCancel: () => void;
  onSave: (value: ShoppingInput) => void;
  /** Deletes the item (to the trash, with Undo). Absent when the host offers no delete. */
  onTrash?: () => void;
}) {
  const form = useRef<HTMLFormElement>(null);
  const extraId = useId();
  const storesId = useId();
  // Progressive: the item, its amount and its shop first; the rest waits behind `moreFields`.
  const [extraOpen, setExtraOpen] = useState(false);
  // The offer's fields are a fold of their own inside it, closed until opened.
  const [offerOpen, setOfferOpen] = useState(false);
  const filled = filledExtras(item);
  useEffect(() => {
    if (focusFirst) form.current?.querySelector("input")?.focus();
    // The form opens under its row: Save and Cancel are brought into view, without a jump when they already show.
    form.current?.scrollIntoView?.({ block: "nearest" });
  }, [focusFirst]);
  // A host without a contact search (the mobile app) keeps a recipient that is already set, and offers no way to find one.
  const showRecipient =
    contacts !== undefined || item.recipient_contact_id != null;
  // Runs from the Save button's click, not from a submit event (no allow-forms in the App iframe).
  function save() {
    if (!form.current) return;
    // A wrong value behind the closed `moreFields` (or the closed offer) opens it first, so the browser can point at the field.
    const invalid = form.current.querySelector(
      "input:invalid, select:invalid, textarea:invalid",
    );
    if (invalid?.closest(".shopping-editor-extra"))
      flushSync(() => {
        setExtraOpen(true);
        if (invalid.closest(".shopping-editor-offer")) setOfferOpen(true);
      });
    if (!form.current.reportValidity()) return;
    const data = new FormData(form.current);
    const value = (name: string) => {
      const entry = data.get(name);
      return typeof entry === "string" ? entry.trim() : "";
    };
    const nullable = (name: string) => value(name) || null;
    // The quantity checks itself as it is typed, like the prices; it goes out with a point.
    const quantity = parseQuantityInput(value("quantity"));
    if (quantity === null) return;
    // The price fields check themselves as they are typed, so a value that gets here is a price; it goes out with a point.
    const price = (name: string) => parsePriceInput(value(name));
    const list = value("list_id");
    onSave({
      // Only a changed list is sent: it moves the item.
      ...(list && list !== item.list_id ? { list_id: list } : {}),
      name: value("name"),
      quantity,
      unit: nullable("unit"),
      store: nullable("store"),
      note: nullable("note"),
      product_url: nullable("product_url"),
      recipient_contact_id: nullable("recipient_contact_id"),
      occasion: nullable("occasion"),
      target_date: nullable("target_date"),
      offer: price("price")
        ? {
            price: price("price") ?? "",
            regular_price: price("regular_price"),
            currency: value("currency"),
            valid_from: value("valid_from"),
            valid_until: value("valid_until"),
            checked_on: value("checked_on"),
            source: value("source"),
            source_url: nullable("source_url"),
          }
        : null,
    });
  }
  return (
    <KeyScope
      as="form"
      ref={form}
      className="shopping-editor"
      onEscape={onCancel}
      // Enter in a one-line field saves, as Save does; Escape (above) cancels.
      onKeyDown={(event) => {
        if (savesOnEnter(event.target)) onEnterKey(event, save);
      }}
    >
      <fieldset disabled={busy}>
        {/* The row above already names the item: the legend is for screen readers, so the frame stays whole. */}
        <legend className="shopping-visually-hidden">
          {t.edit}: {item.name}
        </legend>
        <div className="shopping-editor-main">
          <label className="shopping-editor-name">
            {t.name}
            <input
              name="name"
              defaultValue={item.name}
              required
              maxLength={200}
            />
          </label>
          <label>
            {t.quantity}
            <input
              name="quantity"
              type="text"
              inputMode="decimal"
              autoComplete="off"
              defaultValue={formatQuantityNumber(item.quantity, t.dateLocale)}
              required
              onInput={(event) => {
                const field = event.currentTarget;
                field.setCustomValidity(
                  parseQuantityInput(field.value) ? "" : t.quantityInvalid,
                );
              }}
            />
          </label>
          <label>
            {t.unit}
            <input name="unit" defaultValue={item.unit ?? ""} maxLength={30} />
          </label>
          <label className="shopping-editor-store">
            {t.store}
            <input
              name="store"
              list={storesId}
              defaultValue={item.store ?? ""}
              maxLength={200}
            />
            <datalist id={storesId}>
              {stores.map((shop) => (
                <option key={shop} value={shop} />
              ))}
            </datalist>
          </label>
          {lists.length > 1 && (
            <label className="shopping-editor-list">
              {t.list}
              <select name="list_id" defaultValue={item.list_id}>
                {lists.map((entry) => (
                  <option key={entry.id} value={entry.id}>
                    {entry.name}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
        <button
          type="button"
          className="shopping-editor-more"
          aria-expanded={extraOpen}
          aria-controls={extraId}
          onClick={() => setExtraOpen(!extraOpen)}
        >
          <span>{t.moreFields}</span>
          {filled > 0 && (
            <span className="shopping-editor-filled">
              {t.moreFieldsFilled(filled)}
            </span>
          )}
          <ChevronDownIcon size={16} />
        </button>
        {/* Kept in the form while closed (hidden), so Save sends every field as it was read. */}
        <div id={extraId} className="shopping-editor-extra" hidden={!extraOpen}>
          <div className="shopping-grid">
            <label>
              {t.product}
              <input
                name="product_url"
                type="url"
                defaultValue={item.product_url ?? ""}
                maxLength={2000}
              />
            </label>
            <label>
              {t.occasion}
              <input
                name="occasion"
                defaultValue={item.occasion ?? ""}
                maxLength={200}
              />
            </label>
            <label>
              {t.target}
              <input
                name="target_date"
                type="date"
                defaultValue={item.target_date ?? ""}
              />
            </label>
            {showRecipient && (
              <RecipientField item={item} labels={t} contacts={contacts} />
            )}
          </div>
          <label>
            {t.note}
            <textarea
              name="note"
              defaultValue={item.note ?? ""}
              maxLength={2000}
            />
          </label>
          <OfferFields
            item={item}
            labels={t}
            open={offerOpen}
            onToggle={() => setOfferOpen(!offerOpen)}
          />
        </div>
        <div className="sk-form-actions">
          <button type="button" className="sk-btn--primary" onClick={save}>
            {t.save}
          </button>
          <button type="button" className="sk-btn--quiet" onClick={onCancel}>
            {t.cancel}
          </button>
          {onTrash && (
            <button
              type="button"
              className="sk-btn--danger"
              aria-label={t.deleteItemNamed(item.name)}
              onClick={onTrash}
            >
              {t.deleteItem}
            </button>
          )}
        </div>
      </fieldset>
    </KeyScope>
  );
}

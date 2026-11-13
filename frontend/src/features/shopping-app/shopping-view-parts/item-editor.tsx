import { useEffect, useId, useRef, useState } from "react";
import { flushSync } from "react-dom";
import type {
  ShoppingInput,
  ShoppingItem,
  ShoppingTransport,
} from "../transport";
import type { ShoppingLabels } from "../labels";
import { ChevronDownIcon } from "../../mcp-apps/ui/icons";
import { KeyScope } from "../../mcp-apps/ui/key-scope";
import { ErrorNotice } from "../../mcp-apps/ui/states";
import { OfferFields } from "./offer-fields";

/** How many of the fields behind "Fler fält" hold a value, so the closed toggle can say that something is there. */
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

export function ItemEditor({
  item,
  labels: t,
  busy,
  focusFirst,
  contacts,
  onCancel,
  onSave,
}: {
  item: ShoppingItem;
  labels: ShoppingLabels;
  busy: boolean;
  focusFirst: boolean;
  contacts: ShoppingTransport["contacts"];
  onCancel: () => void;
  onSave: (value: ShoppingInput) => void;
}) {
  const form = useRef<HTMLFormElement>(null);
  const extraId = useId();
  // Progressive: the item, its amount and its shop first; the rest waits behind "Fler fält".
  const [extraOpen, setExtraOpen] = useState(false);
  // The offer's fields are a fold of their own inside it, closed until opened.
  const [offerOpen, setOfferOpen] = useState(false);
  const filled = filledExtras(item);
  useEffect(() => {
    if (focusFirst) form.current?.querySelector("input")?.focus();
    // The form opens under its row: Save and Cancel are brought into view, without a jump when they already show.
    form.current?.scrollIntoView?.({ block: "nearest" });
  }, [focusFirst]);
  const [query, setQuery] = useState("");
  const [candidates, setCandidates] = useState<
    { id: string; display_name: string }[]
  >([]);
  const [contactError, setContactError] = useState(false);
  const [searching, setSearching] = useState(false);
  // A host without a contact search (the mobile app) keeps a recipient that is already set, and offers no way to find one.
  const canSearch = contacts !== undefined;
  const showRecipient = canSearch || item.recipient_contact_id != null;
  async function search() {
    if (!contacts) return;
    setSearching(true);
    setContactError(false);
    try {
      setCandidates((await contacts(query)).contacts);
    } catch {
      setContactError(true);
    } finally {
      setSearching(false);
    }
  }
  // Runs from the Save button's click, not from a submit event (no allow-forms in the App iframe).
  function save() {
    if (!form.current) return;
    // A wrong value behind the closed "Fler fält" (or the closed offer) opens it first, so the browser can point at the field.
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
    onSave({
      name: value("name"),
      quantity: value("quantity"),
      unit: nullable("unit"),
      store: nullable("store"),
      note: nullable("note"),
      product_url: nullable("product_url"),
      recipient_contact_id: nullable("recipient_contact_id"),
      occasion: nullable("occasion"),
      target_date: nullable("target_date"),
      offer: value("price")
        ? {
            price: value("price"),
            regular_price: nullable("regular_price"),
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
              defaultValue={item.quantity}
              type="number"
              inputMode="decimal"
              min="0.001"
              max="999999.999"
              step="0.001"
              required
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
              defaultValue={item.store ?? ""}
              maxLength={200}
            />
          </label>
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
              <label>
                {t.recipient}
                <select
                  name="recipient_contact_id"
                  defaultValue={item.recipient_contact_id ?? ""}
                >
                  <option value="">{t.noRecipient}</option>
                  {item.recipient_contact_id &&
                    !candidates.some(
                      (entry) => entry.id === item.recipient_contact_id,
                    ) && (
                      <option value={item.recipient_contact_id}>
                        {item.recipient_contact_name ?? t.linkedContact}
                      </option>
                    )}
                  {candidates.map((entry) => (
                    <option value={entry.id} key={entry.id}>
                      {entry.display_name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {canSearch && (
              <>
                <label>
                  {t.contactQuery}
                  <input
                    value={query}
                    maxLength={200}
                    onChange={(e) => setQuery(e.target.value)}
                  />
                </label>
                <button
                  type="button"
                  disabled={searching || !query.trim()}
                  onClick={() => void search()}
                >
                  {t.searchContact}
                </button>
                {contactError && (
                  <ErrorNotice
                    placement="row"
                    locale={t.dateLocale}
                    message={t.contactSearchFailed}
                    retrying={searching}
                    onRetry={() => void search()}
                  />
                )}
              </>
            )}
          </div>
          {canSearch && <p>{t.recipientHint}</p>}
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
        </div>
      </fieldset>
    </KeyScope>
  );
}

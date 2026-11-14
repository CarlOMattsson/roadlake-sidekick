import { useId } from "react";
import type { ShoppingItem } from "../transport";
import type { ShoppingLabels } from "../labels";
import { localDay } from "../transport";
import { ChevronDownIcon } from "../../mcp-apps/ui/icons";
import { formatPriceNumber, offerSummary, parsePriceInput } from "./helpers";

/**
 * A price field as text, so the decimal comma works in Swedish: it shows the stored price in the list's style and
 * accepts a comma or a point. The browser's own number field would follow the browser's language instead.
 */
function PriceField({
  name,
  label,
  stored,
  labels: t,
}: {
  name: string;
  label: string;
  stored: string | null | undefined;
  labels: ShoppingLabels;
}) {
  return (
    <label>
      {label}
      <input
        name={name}
        type="text"
        inputMode="decimal"
        autoComplete="off"
        defaultValue={stored ? formatPriceNumber(stored, t.dateLocale) : ""}
        onInput={(event) => {
          const field = event.currentTarget;
          field.setCustomValidity(
            field.value.trim() === "" || parsePriceInput(field.value)
              ? ""
              : t.priceInvalid,
          );
        }}
      />
    </label>
  );
}

/**
 * The offer's fields in the change form, folded into a part of their own. The closed toggle says what is saved
 * (`offerSummary`); the fields stay in the form while it is closed (hidden), so Save sends
 * every one as it was read.
 */
export function OfferFields({
  item,
  labels: t,
  open,
  onToggle,
}: {
  item: ShoppingItem;
  labels: ShoppingLabels;
  open: boolean;
  onToggle: () => void;
}) {
  const bodyId = useId();
  return (
    <div className="shopping-editor-offer">
      <button
        type="button"
        className="shopping-editor-more"
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={onToggle}
      >
        <span>{offerSummary(item, t)}</span>
        <ChevronDownIcon size={16} />
      </button>
      <div id={bodyId} role="group" aria-label={t.offer} hidden={!open}>
        <p>{t.offerHint}</p>
        <div className="shopping-grid">
          <PriceField
            name="price"
            label={t.price}
            stored={item.offer?.price}
            labels={t}
          />
          <PriceField
            name="regular_price"
            label={t.regular}
            stored={item.offer?.regular_price}
            labels={t}
          />
          <label>
            {t.currency}
            <input
              name="currency"
              defaultValue={item.offer?.currency ?? "SEK"}
              pattern="[A-Z]{3}"
              maxLength={3}
            />
          </label>
          <label>
            {t.from}
            <input
              name="valid_from"
              type="date"
              defaultValue={item.offer?.valid_from ?? ""}
            />
          </label>
          <label>
            {t.until}
            <input
              name="valid_until"
              type="date"
              defaultValue={item.offer?.valid_until ?? ""}
            />
          </label>
          <label>
            {t.checked}
            <input
              name="checked_on"
              type="date"
              max={localDay()}
              defaultValue={item.offer?.checked_on ?? localDay()}
            />
          </label>
          <label>
            {t.source}
            <input
              name="source"
              maxLength={200}
              defaultValue={item.offer?.source ?? ""}
            />
          </label>
          <label>
            {t.sourceUrl}
            <input
              name="source_url"
              type="url"
              maxLength={2000}
              defaultValue={item.offer?.source_url ?? ""}
            />
          </label>
        </div>
      </div>
    </div>
  );
}

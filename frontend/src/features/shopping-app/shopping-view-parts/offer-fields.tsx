import { useId } from "react";
import type { ShoppingItem } from "../transport";
import type { ShoppingLabels } from "../labels";
import { localDay } from "../transport";
import { ChevronDownIcon } from "../../mcp-apps/ui/icons";
import { offerSummary } from "./helpers";

/** A stored price without empty decimals ("199.00" reads "199", "199.50" reads "199.5"), still a plain number the field accepts. */
function plainPrice(value: string | null | undefined): string {
  if (!value) return "";
  return value.includes(".") ? value.replace(/\.?0+$/, "") : value;
}

/**
 * The offer's fields in the change form, folded into a part of their own. The closed toggle says what is saved
 * ("Erbjudande: 199 kr t.o.m. 30 nov"); the fields stay in the form while it is closed (hidden), so Save sends
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
          <label>
            {t.price}
            <input
              name="price"
              type="number"
              min="0.01"
              max="99999999.99"
              step="0.01"
              defaultValue={plainPrice(item.offer?.price)}
            />
          </label>
          <label>
            {t.regular}
            <input
              name="regular_price"
              type="number"
              min="0.01"
              max="99999999.99"
              step="0.01"
              defaultValue={plainPrice(item.offer?.regular_price)}
            />
          </label>
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

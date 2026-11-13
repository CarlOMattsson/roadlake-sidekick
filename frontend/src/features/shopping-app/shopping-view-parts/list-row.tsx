import type { ShoppingItem } from "../transport";
import { cardItemText } from "../shopping-card";
import { StatusGlyph } from "../../mcp-apps/ui/status-glyph";
import { boughtOnText, formatCalendarDate, formatPriceNumber } from "./helpers";
import { ItemEditor } from "./item-editor";
import {
  heldStatus,
  heldWord,
  isHolding,
  queuedMark,
  rowFailure,
  undoButton,
  useRowUndo,
} from "./row-parts";
import type { RowEnv } from "./row-parts";

/**
 * One row of the list view (the card): a checkbox, the item's text and an Edit button. Open items under a store
 * heading do not repeat the store (`grouped`); purchased items have no heading.
 */
export function ListRow({
  item,
  grouped,
  inPlace,
  env,
}: {
  item: ShoppingItem;
  grouped: boolean;
  inPlace: boolean;
  env: RowEnv;
}) {
  const { labels: t, held, rowQueue } = env;
  const holding = isHolding(item, env, inPlace);
  const hold = useRowUndo(item, env, holding);
  const boughtOn = inPlace ? "" : boughtOnText(item, t);
  return (
    <li
      className={holding ? "shopping-held-item" : undefined}
      aria-busy={rowQueue.pending(item.id) > 0 || undefined}
    >
      <div className="shopping-toolbar">
        <label className="shopping-check">
          <input
            type="checkbox"
            checked={item.purchased}
            disabled={env.archived || item.id in env.waiting}
            onChange={() => env.onToggle(item)}
          />
          <StatusGlyph
            kind="task"
            status={item.purchased ? "completed" : "todo"}
          />
          {/* The status sits in the text column under the name, not as a flex sibling of the row. */}
          <span className="shopping-item-text">
            <span>{cardItemText(item, t.dateLocale)}</span>
            {/* A bought row needs no status line (its ticked box and the purchased section say it), except "Köpt" (or
                  "Inte köpt") while its Undo holds; the row's status below says it to assistive technology. */}
            {(!item.purchased || holding) && (
              <span
                className="shopping-status"
                aria-hidden={holding || undefined}
              >
                {holding ? heldWord(item, env) : t.wanted}
              </span>
            )}
            {/* Under "Köpta" the status line is the day it was bought. */}
            {boughtOn && <span className="shopping-status">{boughtOn}</span>}
            {queuedMark(item, env)}
          </span>
        </label>
        {/* Folded, the row is the name only; Edit is reached through "Show all". A held row has Undo instead. */}
        {holding
          ? undoButton(item, env, hold)
          : !env.folded && (
              <button
                disabled={env.busy || env.archived || item.id in env.waiting}
                onClick={() => env.onEdit(item)}
              >
                {t.edit}
              </button>
            )}
      </div>
      {holding && heldStatus(item, env)}
      {(inPlace || !held[item.id]) && rowFailure(item, env)}
      {item.store && !grouped && (
        <p>
          {t.store}: {item.store}
        </p>
      )}
      {item.occasion && (
        <p>
          {t.occasion}: {item.occasion}
        </p>
      )}
      {item.target_date && (
        <p>
          {t.target}: {formatCalendarDate(item.target_date, t.dateLocale)}
        </p>
      )}
      {item.note && <p className="shopping-note">{item.note}</p>}
      {item.offer && (
        <div className={`shopping-offer shopping-offer-${item.offer_status}`}>
          <strong>
            {t[item.offer_status]} ·{" "}
            {formatPriceNumber(item.offer.price, t.dateLocale)}{" "}
            {item.offer.currency}
          </strong>
          {item.offer.regular_price && (
            <span>
              {" "}
              ({t.regularPrice}:{" "}
              {formatPriceNumber(item.offer.regular_price, t.dateLocale)})
            </span>
          )}
          <p>
            {formatCalendarDate(item.offer.valid_from, t.dateLocale)} –{" "}
            {formatCalendarDate(item.offer.valid_until, t.dateLocale)} ·{" "}
            {t.source}: {item.offer.source} · {t.checked}:{" "}
            {formatCalendarDate(item.offer.checked_on, t.dateLocale)}
          </p>
        </div>
      )}
      {env.editing?.id === item.id && (
        <ItemEditor
          key={`${item.id}:${item.version}`}
          focusFirst={env.editorByKey.current}
          item={item}
          labels={t}
          busy={env.busy}
          contacts={env.contacts}
          onCancel={() => env.onEdit(null)}
          onSave={(input) => env.onSave(item, input, () => env.onEdit(null))}
        />
      )}
    </li>
  );
}

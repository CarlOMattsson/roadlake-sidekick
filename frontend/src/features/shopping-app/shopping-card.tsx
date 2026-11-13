import { AppFrame } from "../mcp-apps/ui/layout";
import { EmptyState } from "../mcp-apps/ui/states";
import { Progress } from "../mcp-apps/ui/progress";
import { CardFoot } from "../mcp-apps/ui/card";
import { ChevronRightIcon } from "../mcp-apps/ui/icons";
import type { ShoppingLabels } from "./labels";
import { emptyAsk } from "./shopping-view-parts/helpers";
import type { ShoppingDetail, ShoppingItem } from "./transport";
import "../mcp-apps/ui/tokens.css";
import "../mcp-apps/ui/family.css";
import "./shopping.css";

/** Open items named in the inline card. The rest are counted after "Open list", not listed. */
export const CARD_ITEM_COUNT = 4;

/**
 * A decimal quantity in the list's locale, without trailing zeros: "1.000" reads "1", "1.5" reads
 * "1,5" in Swedish and "1.5" in English. The decimals are kept as far as they go. A value that is
 * not a plain decimal is returned unchanged.
 */
export function formatQuantity(value: number | string, locale: string): string {
  const text = String(value);
  const match = /^-?\d+(?:\.(\d+))?$/.exec(text);
  if (!match) return text;
  const number = Number(text);
  if (!Number.isFinite(number)) return text;
  const decimals = match[1]?.length ?? 0;
  return new Intl.NumberFormat(locale, {
    maximumFractionDigits: Math.min(decimals, 20),
  }).format(number);
}

/**
 * Quantity and unit as text, for example "2 l", "1,5 l" or "12 st". A quantity has a unit (designsystem §1.6):
 * without one it counts pieces: "8 st" in Swedish, the bare number "8" in English. The locale is the list labels' dateLocale; it defaults to English.
 */
export function quantityText(item: ShoppingItem, locale = "en-GB"): string {
  const quantity = formatQuantity(item.quantity, locale);
  const unit = item.unit || (locale.startsWith("sv") ? "st" : "");
  return unit ? `${quantity} ${unit}` : quantity;
}

/**
 * Whether the quantity is only the stored default: 1 with no unit. "1 st" keeps its amount, since a
 * unit means someone set it.
 */
export function isDefaultAmount(item: ShoppingItem, locale: string): boolean {
  return !item.unit && formatQuantity(item.quantity, locale) === "1";
}

/**
 * One open item as text: "Milk · 2 l", or only the name when the item has no unit and a quantity of
 * one, so the standard count is not repeated as "Havregryn · 1". A unit keeps the quantity ("1 st").
 */
export function cardItemText(item: ShoppingItem, locale: string): string {
  if (isDefaultAmount(item, locale)) return item.name;
  return `${item.name} · ${quantityText(item, locale)}`;
}

/**
 * The card foot's "Open list · 2 more": a text button that opens the list, with the count of the items the
 * card leaves out after its name.
 */
export function OpenListButton({
  labels: t,
  hidden,
  hiddenText,
  onOpen,
}: {
  labels: ShoppingLabels;
  hidden: number;
  /** Says what the count after the name stands for: open items (the list card) or added ones (the batch card). */
  hiddenText: (count: number) => string;
  onOpen: () => void;
}) {
  return (
    <button
      type="button"
      className="shopping-card-open sk-btn--open"
      onClick={onOpen}
    >
      <span className="shopping-card-open-text">
        {t.openList}
        {hidden > 0 ? (
          <span className="shopping-card-more">{` · ${hiddenText(hidden)}`}</span>
        ) : null}
      </span>
      <ChevronRightIcon />
    </button>
  );
}

/**
 * Compact inline card for a shopping list. It names the list, shows "N of M bought" and the first
 * open items as text (with "· N more" in the foot link when some are not listed), and offers Open, which asks the host for
 * fullscreen. The card sizes to its content and has no inner scroll. The host decides the frame; the card is only shown when fullscreen
 * can be offered.
 */
export function ShoppingCard({
  detail,
  labels: t,
  onOpen,
  sendMessage,
}: {
  detail: ShoppingDetail;
  labels: ShoppingLabels;
  onOpen: () => void;
  /** Sends a message to Claude; absent when the host offers none (the empty state then shows its example as text). */
  sendMessage?: (text: string) => Promise<boolean>;
}) {
  const total = detail.items.length;
  const open = detail.items.filter((item) => !item.purchased);
  const shown = open.slice(0, CARD_ITEM_COUNT);
  // The open items the list leaves out: they are counted in the foot link, after its name.
  const hidden = open.length - shown.length;
  return (
    <section className="sidekick-shopping shopping-card" aria-label={t.title}>
      <AppFrame mode="inline">
        <div className="shopping-card-body sk-card">
          <p className="sk-eyebrow">{t.title}</p>
          <h2 className="shopping-card-title sk-card__title">
            {detail.shopping_list.name}
          </h2>
          {total > 0 ? (
            <Progress
              done={total - open.length}
              total={total}
              label={t.boughtOf(total - open.length, total)}
            />
          ) : null}
          {total === 0 ? (
            <EmptyState
              title={t.empty}
              ask={emptyAsk(
                t.dateLocale,
                t.emptyListExample(detail.shopping_list.name),
                sendMessage,
              )}
            />
          ) : open.length === 0 ? (
            <p className="shopping-card-status">{t.allBought}</p>
          ) : (
            <>
              <ul className="shopping-card-items">
                {shown.map((item) => (
                  <li key={item.id} className="shopping-card-item">
                    {cardItemText(item, t.dateLocale)}
                  </li>
                ))}
              </ul>
            </>
          )}
          <CardFoot>
            <OpenListButton
              labels={t}
              hidden={hidden}
              hiddenText={t.hiddenItems}
              onOpen={onOpen}
            />
          </CardFoot>
        </div>
      </AppFrame>
    </section>
  );
}

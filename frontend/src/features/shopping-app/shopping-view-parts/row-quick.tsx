import type { RefObject } from "react";
import type { ShoppingItem } from "../transport";
import { quantityText } from "../shopping-card";
import { KeyScope, onEscapeKey } from "../../mcp-apps/ui/key-scope";
import { MinusIcon, MoreIcon, PlusIcon } from "../../mcp-apps/ui/icons";
import type { RowEnv } from "./row-parts";

/** The lists an item can be moved to: the active ones other than its own. */
export function moveTargets(item: ShoppingItem, env: RowEnv) {
  return env.lists.filter((list) => list.id !== item.list_id);
}

/**
 * Whether an open row offers the quick changes (amount steps and the row menu): the host gave the actions, the row
 * can be changed and stands open in its place. A held or bought row has its Undo or its fold instead.
 */
export function hasQuickChanges(
  item: ShoppingItem,
  env: RowEnv,
  locked: boolean,
  holding: boolean,
) {
  return (
    Boolean(env.onStep && env.onMove) && !locked && !holding && !item.purchased
  );
}

/**
 * The row's trailing controls (store view): − and + for the amount, then ⋯ when there is a list to move the item to.
 * Each is a 44 px glyph button beside the row's own button, never inside it. The amount never goes under 1: − at 1 is
 * marked unavailable but stays focusable, so the focus does not drop out of the row. The amount is said politely after
 * each step, since the row shows it only as text.
 */
export function RowQuick({
  item,
  env,
  menuOpen,
  moreButton,
  onToggleMenu,
}: {
  item: ShoppingItem;
  env: RowEnv;
  menuOpen: boolean;
  moreButton: RefObject<HTMLButtonElement | null>;
  onToggleMenu: () => void;
}) {
  const { labels: t } = env;
  const atMinimum = Number(item.quantity) <= 1;
  return (
    <span className="shopping-quick">
      <button
        type="button"
        className="sk-iconbtn sk-iconbtn--row shopping-step"
        aria-label={t.decreaseQuantity(item.name)}
        aria-disabled={atMinimum || undefined}
        onClick={() => {
          if (!atMinimum) env.onStep?.(item, -1);
        }}
      >
        <MinusIcon />
      </button>
      <button
        type="button"
        className="sk-iconbtn sk-iconbtn--row shopping-step"
        aria-label={t.increaseQuantity(item.name)}
        onClick={() => env.onStep?.(item, 1)}
      >
        <PlusIcon />
      </button>
      {moveTargets(item, env).length > 0 && (
        <button
          ref={moreButton}
          type="button"
          className="sk-iconbtn sk-iconbtn--row shopping-row-more"
          aria-label={t.rowMenu(item.name)}
          aria-expanded={menuOpen}
          onClick={onToggleMenu}
          onKeyDown={(event) => {
            if (menuOpen) onEscapeKey(event, onToggleMenu);
          }}
        >
          <MoreIcon />
        </button>
      )}
      <span aria-live="polite" className="shopping-visually-hidden">
        {t.quantityNow(item.name, quantityText(item, t.dateLocale))}
      </span>
    </span>
  );
}

/** The row's menu, under the row: one entry per list the item can move to. Escape closes it. */
export function RowMenu({
  item,
  env,
  onClose,
  onEscape,
}: {
  item: ShoppingItem;
  env: RowEnv;
  onClose: () => void;
  onEscape: () => void;
}) {
  const { labels: t } = env;
  return (
    <KeyScope className="sk-menu-panel shopping-row-menu" onEscape={onEscape}>
      {moveTargets(item, env).map((list) => (
        <button
          key={list.id}
          type="button"
          className="sk-menu-item"
          onClick={() => {
            onClose();
            env.onMove?.(item, list);
          }}
        >
          {t.moveToList(list.name)}
        </button>
      ))}
    </KeyScope>
  );
}

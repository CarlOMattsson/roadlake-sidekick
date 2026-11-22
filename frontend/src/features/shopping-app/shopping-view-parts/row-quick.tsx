import type { RefObject } from "react";
import type { ShoppingItem } from "../transport";
import { quantityText } from "../shopping-card";
import { onEscapeKey } from "../../mcp-apps/ui/key-scope";
import { Menu, MenuItem, useMenuPopover } from "../../mcp-apps/ui/menu";
import {
  CloseIcon,
  MinusIcon,
  MoreIcon,
  PlusIcon,
} from "../../mcp-apps/ui/icons";
import type { RowEnv } from "./row-parts";

/** The lists an item can be moved to: the active ones other than its own. */
export function moveTargets(item: ShoppingItem, env: RowEnv) {
  return env.lists.filter((list) => list.id !== item.list_id);
}

/** Whether the row's ⋯ has anything to hold: a list to move the item to, or Delete. */
export function hasRowMenu(item: ShoppingItem, env: RowEnv) {
  return moveTargets(item, env).length > 0 || Boolean(env.onTrash);
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
  menuId,
  moreButton,
  onToggleMenu,
}: {
  item: ShoppingItem;
  env: RowEnv;
  menuOpen: boolean;
  /** The id of the row's menu, which ⋯ controls. */
  menuId: string;
  moreButton: RefObject<HTMLButtonElement | null>;
  onToggleMenu: () => void;
}) {
  const { labels: t } = env;
  const atMinimum = Number(item.quantity) <= 1;
  return (
    <span className="shopping-quick">
      {/* The folded card (one phone screen) leaves the steps to "Show all" and the full list: the name keeps the width. */}
      {!env.folded && (
        <>
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
        </>
      )}
      {hasRowMenu(item, env) && (
        <button
          ref={moreButton}
          type="button"
          className="sk-iconbtn sk-iconbtn--row shopping-row-more"
          aria-label={t.rowMenu(item.name)}
          aria-expanded={menuOpen}
          aria-controls={menuOpen ? menuId : undefined}
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

/**
 * The row's menu: the item's name as its head (so it is plain which row it belongs to), one entry per list the item
 * can move to, then Delete in the danger colour last. Delete needs no question first: the trash and Undo undo it.
 * It is the family's `Menu`: a popover at the row's ⋯ with a mouse or in a wide frame (Escape, Tab or a press outside
 * closes it, the focus on ⋯), and on a phone the panel under the row, as before, with its × (the popover has none). A chosen entry gives the row's place in the list to its neighbour (`onCloseEditor`).
 */
export function RowMenu({
  item,
  env,
  anchor,
  menuId,
  onClose,
}: {
  item: ShoppingItem;
  env: RowEnv;
  /** The row's ⋯: the menu stands at it and gives the focus back to it. */
  anchor: RefObject<HTMLButtonElement | null>;
  menuId: string;
  onClose: () => void;
}) {
  const { labels: t } = env;
  const popover = useMenuPopover();
  return (
    <Menu
      id={menuId}
      anchor={anchor}
      label={t.rowMenu(item.name)}
      panelClassName="sk-menu-panel shopping-row-menu"
      popoverClassName="sk-menu-popover shopping-row-popover"
      onClose={onClose}
    >
      <div className="shopping-row-menu-head">
        <p className="shopping-row-menu-name">{item.name}</p>
        {!popover && (
          <button
            type="button"
            className="sk-iconbtn shopping-row-menu-close"
            aria-label={t.closeMenu}
            onClick={() => {
              anchor.current?.focus();
              onClose();
            }}
          >
            <CloseIcon />
          </button>
        )}
      </div>
      {moveTargets(item, env).map((list) => (
        <MenuItem
          key={list.id}
          label={t.moveToList(list.name)}
          onChoose={() => {
            onClose();
            env.onCloseEditor(item.id);
            env.onMove?.(item, list);
          }}
        />
      ))}
      {env.onTrash && (
        <MenuItem
          danger
          label={t.deleteItem}
          disabled={env.busy}
          onChoose={() => {
            onClose();
            env.onTrash?.(item, () => env.onCloseEditor(item.id));
          }}
        />
      )}
    </Menu>
  );
}

import { useRef, useState } from "react";
import type { KeyboardEvent, MouseEvent } from "react";
import type { ShoppingItem } from "../transport";
import { isDefaultAmount, quantityText } from "../shopping-card";
import { ChevronRightIcon } from "../../mcp-apps/ui/icons";
import { StatusGlyph } from "../../mcp-apps/ui/status-glyph";
import { boughtOnText, buyAgainUsed, holdUsed, itemMeta } from "./helpers";
import { ItemEditor } from "./item-editor";
import { hasQuickChanges, hasRowMenu, RowMenu, RowQuick } from "./row-quick";
import { heldWord, isHolding, queuedMark, rowFailure } from "./row-parts";
import type { RowEnv } from "./row-parts";

/**
 * One large row per item of the store view: the ring marks it bought or open again, a tap on the rest of the row
 * opens its change form. A held row (its receipt, with Ångra, is in the view's bar) stays in its place at its height:
 * `bought` takes the amount's place on the title line and the row is muted. Under the `boughtCount` fold (inPlace false)
 * the same item is a plain bought row.
 */
export function StoreRow({
  item,
  inPlace,
  env,
}: {
  item: ShoppingItem;
  inPlace: boolean;
  env: RowEnv;
}) {
  const { labels: t, held, rowQueue } = env;
  const holding = isHolding(item, env, inPlace);
  const amount = isDefaultAmount(item, t.dateLocale)
    ? ""
    : quantityText(item, t.dateLocale);
  // Under the `boughtCount` fold a bought row says the day it was bought; in its place (held) it keeps the meta line it
  // had, so ticking it never changes its height. The folded card (one phone screen) draws the name and amount only;
  // the row opens the rest, as "Show all" and the full list show it.
  const meta = env.folded
    ? ""
    : item.purchased && !inPlace
      ? boughtOnText(item, t)
      : itemMeta(item, t);
  // A row that cannot be changed (an archived list, or a change still in the phone's outbox) cannot be opened either.
  const locked = env.archived || item.id in env.waiting;
  // An open row can step its amount and move to another list without opening the change form.
  const quick = hasQuickChanges(item, env, Boolean(locked), holding);
  // A held row that had the quick changes keeps their room, unseen, and says `bought` there: its text keeps the width
  // it had, so a long name wraps as before and the row keeps its height.
  const heldSlot = holding && !locked && Boolean(env.onStep && env.onMove);
  const [menuOpen, setMenuOpen] = useState(false);
  const moreButton = useRef<HTMLButtonElement>(null);
  return (
    <li
      className={`shopping-store-item${holding ? " shopping-held-item" : ""}${
        env.archived ? " shopping-store-item--archived" : ""
      }`}
      aria-busy={rowQueue.pending(item.id) > 0 || undefined}
    >
      {/* Arbetes grammar: two sibling buttons, never nested. The ring ticks; the rest of the row opens the
            change form, as a long press, a right click and Shift+F10 do. */}
      <div className="shopping-store-line">
        <button
          type="button"
          className="shopping-ring"
          disabled={locked}
          aria-label={(item.purchased ? t.markOpen : t.markBought)(item.name)}
          onClick={() => {
            // The tip names the ring too: the first tap on one has taught it.
            holdUsed();
            if (item.purchased) buyAgainUsed();
            env.onToggle(item);
          }}
        >
          <StatusGlyph
            kind="task"
            status={item.purchased ? "completed" : "todo"}
          />
        </button>
        {/* eslint-disable-next-line jsx-a11y/role-supports-aria-props -- aria-description is an ARIA 1.3 global attribute that this plugin's aria-query data does not know yet; the label files supply the text. */}
        <button
          type="button"
          className="shopping-store-row"
          ref={(node) => env.registerRow(item.id, node)}
          // A row waiting in the phone's outbox (a queued purchase, or an item added offline that the server has not
          // seen yet) cannot be changed until it is sent.
          disabled={locked}
          aria-keyshortcuts="Shift+F10"
          aria-description={env.holdTip}
          // A keyboard activation (detail 0) puts the focus on the form's first field, a tap or click does not.
          onClick={(event: MouseEvent) =>
            env.onOpenEditor(item, event.detail === 0)
          }
          onContextMenu={(event: MouseEvent) => {
            // A long press (or a right click) opens the same form.
            event.preventDefault();
            if (!(item.id in env.waiting)) env.onOpenEditor(item);
          }}
          onKeyDown={(event: KeyboardEvent<HTMLButtonElement>) => {
            if (
              event.key !== "ContextMenu" &&
              !(event.shiftKey && event.key === "F10")
            )
              return;
            event.preventDefault();
            env.onOpenEditor(item, true);
          }}
        >
          <span className="shopping-store-body">
            {/* The name and the amount share one baseline. */}
            <span className="shopping-store-text">
              <span className="shopping-store-name">{item.name}</span>
              {holding && !heldSlot ? (
                <span className="shopping-held" aria-hidden="true">
                  {amount
                    ? `${heldWord(item, env)} · ${amount}`
                    : heldWord(item, env)}
                </span>
              ) : (
                amount && <span className="shopping-store-qty">{amount}</span>
              )}
              {queuedMark(item, env)}
            </span>
            {/* What the shop needs to know without opening the form: occasion, date, offer, note. */}
            {meta && <span className="shopping-store-meta">{meta}</span>}
          </span>
          {/* The row opens the change form, so it ends in › as Arbetes rows; a row that cannot be opened has none, and
              a row with its own trailing controls leaves the room to them. */}
          {!locked && !quick && (
            <span className="shopping-chevron" aria-hidden="true">
              <ChevronRightIcon />
            </span>
          )}
        </button>
        {quick && (
          <RowQuick
            item={item}
            env={env}
            menuOpen={menuOpen}
            moreButton={moreButton}
            onToggleMenu={() => setMenuOpen((open) => !open)}
          />
        )}
        {heldSlot && (
          <span className="shopping-quick-held" aria-hidden="true">
            <span className="shopping-quick-held__room">
              <RowQuick
                item={item}
                env={env}
                menuOpen={false}
                moreButton={moreButton}
                onToggleMenu={() => undefined}
              />
            </span>
            <span className="shopping-held">{heldWord(item, env)}</span>
          </span>
        )}
      </div>
      {quick && menuOpen && hasRowMenu(item, env) && (
        <RowMenu
          item={item}
          env={env}
          onClose={() => setMenuOpen(false)}
          onEscape={() => {
            setMenuOpen(false);
            moreButton.current?.focus();
          }}
        />
      )}
      {(inPlace || !held[item.id]) && rowFailure(item, env)}
      {env.editing?.id === item.id && (
        <ItemEditor
          key={`${item.id}:${item.version}`}
          item={item}
          labels={t}
          busy={env.busy}
          focusFirst={env.editorByKey.current}
          contacts={env.contacts}
          lists={env.lists}
          stores={env.stores}
          onCancel={() => env.onCloseEditor(item.id)}
          onSave={(input) =>
            env.onSave(item, input, () => env.onCloseEditor(item.id))
          }
          onTrash={
            env.onTrash &&
            (() => env.onTrash?.(item, () => env.onCloseEditor(item.id)))
          }
        />
      )}
    </li>
  );
}

import type { KeyboardEvent, MouseEvent } from "react";
import type { ShoppingItem } from "../transport";
import { isDefaultAmount, quantityText } from "../shopping-card";
import { ChevronRightIcon } from "../../mcp-apps/ui/icons";
import { StatusGlyph } from "../../mcp-apps/ui/status-glyph";
import { holdUsed, itemMeta } from "./helpers";
import { ItemEditor } from "./item-editor";
import { queuedMark, rowFailure, undoButton } from "./row-parts";
import type { RowEnv } from "./row-parts";

/**
 * One large row per item of the store view: the ring marks it bought or open again, a tap on the rest of the row
 * opens its change form. While Undo holds, the meta line says "Köpt · 8 st" (the amount moves there) and Undo
 * stands in the trailing slot. A held row stands in its place with Undo; under "Köpta" (inPlace false) the same
 * item is a plain bought row.
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
  const holding = inPlace && item.purchased && Boolean(held[item.id]);
  const amount = isDefaultAmount(item, t.dateLocale)
    ? ""
    : quantityText(item, t.dateLocale);
  // A bought row is done: it keeps its name only.
  const meta = item.purchased ? "" : itemMeta(item, t);
  return (
    <li
      className={`shopping-store-item${holding ? " shopping-held-item" : ""}`}
      aria-busy={rowQueue.pending(item.id) > 0 || undefined}
    >
      {/* Arbetes grammar: two sibling buttons, never nested. The ring ticks; the rest of the row opens the
            change form, as a long press, a right click and Shift+F10 do. */}
      <div className="shopping-store-line">
        <button
          type="button"
          className="shopping-ring"
          disabled={env.archived || item.id in env.waiting}
          aria-label={(item.purchased ? t.markOpen : t.markBought)(item.name)}
          onClick={() => {
            // The tip names the ring too: the first tap on one has taught it.
            holdUsed();
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
          disabled={env.archived || item.id in env.waiting}
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
            {/* The name and the amount share one baseline ("Mjölk  2 l"). */}
            <span className="shopping-store-text">
              <span className="shopping-store-name">{item.name}</span>
              {holding ? (
                <span className="shopping-held">
                  {amount ? `${t.bought} · ${amount}` : t.bought}
                </span>
              ) : (
                amount && <span className="shopping-store-qty">{amount}</span>
              )}
              {queuedMark(item, env)}
            </span>
            {/* What the shop needs to know without opening the form: occasion, date, offer, note. */}
            {meta && <span className="shopping-store-meta">{meta}</span>}
          </span>
          {/* The row opens the change form, so it ends in › as Arbetes rows. */}
          <span className="shopping-chevron" aria-hidden="true">
            <ChevronRightIcon />
          </span>
        </button>
      </div>
      {holding && undoButton(item, env)}
      {(inPlace || !held[item.id]) && rowFailure(item, env)}
      {env.editing?.id === item.id && (
        <ItemEditor
          key={`${item.id}:${item.version}`}
          item={item}
          labels={t}
          busy={env.busy}
          focusFirst={env.editorByKey.current}
          contacts={env.contacts}
          onCancel={() => env.onCloseEditor(item.id)}
          onSave={(input) =>
            env.onSave(item, input, () => env.onCloseEditor(item.id))
          }
        />
      )}
    </li>
  );
}

import { useEffect } from "react";
import type { KeyboardEvent, RefObject } from "react";
import type { ShoppingDetail, ShoppingList } from "../transport";
import type { ShoppingLabels } from "../labels";
import { Progress } from "../../mcp-apps/ui/progress";
import { PlusIcon } from "../../mcp-apps/ui/icons";
import { CreateField } from "../../mcp-apps/ui/create-field";
import { formatCalendarDate } from "./helpers";

/**
 * The line under the header of a read list: the store view's progress stripe or, in the list view, the evaluated
 * date, then (list view) the archive button and the archived mark.
 */
export function ListSummary({
  labels: t,
  detail,
  list,
  storeMode,
  folded,
  purchasedCount,
  shopLabel,
  busy,
  onArchive,
}: {
  labels: ShoppingLabels;
  detail: ShoppingDetail;
  list: ShoppingList;
  storeMode: boolean;
  folded: boolean;
  purchasedCount: number;
  shopLabel?: string;
  busy: boolean;
  onArchive: () => void;
}) {
  return (
    <>
      {/* The list name (or the shop's "ICA · 8 left") is the title of the header row above, not repeated here. */}
      {storeMode ? (
        // Fullscreen: a full-width stripe under the list name (shopping.css, .shopping-progress). An empty list has
        // nothing to count (`boughtOf` with 0 of 0): its empty state says so instead.
        detail.items.length > 0 && (
          <div className="shopping-progress">
            <Progress
              done={purchasedCount}
              total={detail.items.length}
              label={
                shopLabel
                  ? list.name
                  : t.boughtOf(purchasedCount, detail.items.length)
              }
            />
          </div>
        )
      ) : folded ? null : (
        <p>
          {t.evaluated}: {formatCalendarDate(detail.evaluated_on, t.dateLocale)}
        </p>
      )}
      {/* The store view has no archive button, but an archived list says why its rows are still and offers Restore. */}
      {(!storeMode || list.archived) && (
        <div className="shopping-toolbar">
          {list.archived && <span>{t.archived}</span>}
          {(storeMode || !folded) && (
            <button disabled={busy} onClick={onArchive}>
              {list.archived ? t.restore : t.archive}
            </button>
          )}
        </div>
      )}
    </>
  );
}

/**
 * The create field stands first, 8 under the progress line and before the first shop. In fullscreen the + of the
 * Back row opens it; in a card the `addItem` row does, in the field's place (§3 Skapa). Enter
 * adds and keeps it open, Esc or × closes it and gives the focus back to what opened it. Esc closes it from
 * anywhere in the view, not only while the caret is in the field (the focus may have moved to a row or a button).
 */
export function AddItemField({
  labels: t,
  fullscreen,
  open,
  hasError,
  note,
  addButton,
  onCreate,
  onOpen,
  onClose,
}: {
  labels: ShoppingLabels;
  fullscreen: boolean;
  open: boolean;
  hasError: boolean;
  note: string;
  addButton: RefObject<HTMLButtonElement | null>;
  onCreate: (name: string) => Promise<boolean>;
  onOpen: () => void;
  onClose: () => void;
}) {
  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      // The field itself, and an open row form, handle their own Esc and mark the event as handled.
      if (event.key !== "Escape" || event.defaultPrevented) return;
      if (event.isComposing) return;
      event.preventDefault();
      onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);
  if (open)
    return (
      <div className="shopping-create">
        <CreateField
          label={t.addItem}
          placeholder={t.addItemPlaceholder}
          closeLabel={t.close}
          addLabel={t.addItemButton}
          errorLabel={t.saveFailed}
          note={hasError ? "" : note}
          onCreate={onCreate}
          onClose={onClose}
        />
      </div>
    );
  if (fullscreen) return null;
  return (
    <button
      ref={addButton}
      type="button"
      className="shopping-add-row"
      aria-expanded={false}
      onClick={onOpen}
    >
      <PlusIcon />
      {t.addItem}
    </button>
  );
}

/** The page switcher, shown only when the list spans more than one page. */
export function PageSwitcher({
  labels: t,
  offset,
  nextOffset,
  busy,
  onPage,
}: {
  labels: ShoppingLabels;
  offset: number;
  nextOffset: number | null;
  busy: boolean;
  onPage: (offset: number) => void;
}) {
  if (offset === 0 && nextOffset === null) return null;
  return (
    <div className="shopping-toolbar">
      <button
        disabled={busy || offset === 0}
        onClick={() => onPage(Math.max(0, offset - 100))}
      >
        {t.previous}
      </button>
      <span>
        {t.page} {Math.floor(offset / 100) + 1}
      </span>
      <button
        disabled={busy || nextOffset === null}
        onClick={() => onPage(nextOffset ?? 0)}
      >
        {t.next}
      </button>
    </div>
  );
}

/** The batch field of the list view: one line when folded, a text area otherwise, with the Add button. */
export function BatchForm({
  labels: t,
  folded,
  names,
  invalid,
  busy,
  onNames,
  onKeyDown,
  onAdd,
}: {
  labels: ShoppingLabels;
  folded: boolean;
  names: string;
  invalid: boolean;
  busy: boolean;
  onNames: (value: string) => void;
  onKeyDown: (event: KeyboardEvent<HTMLElement>) => void;
  onAdd: () => void;
}) {
  return (
    <form className="shopping-batch">
      {/* Folded, one line: the field is labelled by its name, and the button reads "Add" (the quick-add word). */}
      {folded ? (
        <input
          aria-label={t.batchShort}
          placeholder={t.batchPlaceholder}
          value={names}
          onChange={(e) => onNames(e.target.value)}
          onKeyDown={onKeyDown}
          maxLength={10050}
          required
        />
      ) : (
        <label>
          {t.batch}
          <textarea
            value={names}
            onChange={(e) => onNames(e.target.value)}
            onKeyDown={onKeyDown}
            maxLength={10050}
            required
            rows={4}
          />
        </label>
      )}
      {invalid && <p role="alert">{t.invalidBatch}</p>}
      <button
        type="button"
        className="sk-btn--primary"
        disabled={busy || !names.trim()}
        onClick={onAdd}
      >
        {folded ? t.addItemButton : t.add}
      </button>
    </form>
  );
}

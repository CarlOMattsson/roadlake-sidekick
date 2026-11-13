import { useEffect, useRef, useState } from "react";
import type { HostSettingsEntry } from "../../mcp-apps/room-types";
import type { ShoppingList } from "../transport";
import type { ShoppingLabels } from "../labels";
import { COMPACT_ROWS, emptyAsk, isEnter } from "./helpers";
import { ChevronRightIcon, MoreIcon, PlusIcon } from "../../mcp-apps/ui/icons";
import { CreateField } from "../../mcp-apps/ui/create-field";
import { onEscapeKey } from "../../mcp-apps/ui/key-scope";
import { EmptyState } from "../../mcp-apps/ui/states";
import { workDate } from "../../mcp-apps/ui/due";
import { Fold } from "../../mcp-apps/ui/fold";
import { MoreMenu } from "./more-menu";

/**
 * A one-field form that names a list (new list, or Edit list). Enter and the button submit through the
 * handlers, never through a submit event (no allow-forms in the App iframe).
 */
export function NameForm({
  labels: t,
  className,
  primary,
  value,
  buttonLabel,
  busy,
  onChange,
  onSubmit,
}: {
  labels: ShoppingLabels;
  className: string;
  /** The button is the form's primary action. */
  primary: boolean;
  value: string;
  buttonLabel: string;
  busy: boolean;
  onChange: (value: string) => void;
  onSubmit: () => void;
}) {
  return (
    <form className={className}>
      <label>
        {t.listName}
        <input
          required
          maxLength={200}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (!isEnter(e)) return;
            e.preventDefault();
            if (!e.shiftKey) onSubmit();
          }}
        />
      </label>
      <button
        type="button"
        className={primary ? "sk-btn--primary" : undefined}
        disabled={busy || !value.trim()}
        onClick={() => onSubmit()}
      >
        {buttonLabel}
      </button>
    </form>
  );
}

/** The previous and next page buttons of the lists; shown only when there is more than one page of lists. */
function ListPager({
  labels: t,
  busy,
  listOffset,
  nextLists,
  onOffset,
}: {
  labels: ShoppingLabels;
  busy: boolean;
  listOffset: number;
  nextLists: number | null;
  onOffset: (offset: number) => void;
}) {
  return (
    <>
      <button
        disabled={busy || listOffset === 0}
        onClick={() => onOffset(Math.max(0, listOffset - 50))}
      >
        {t.previous}
      </button>
      <button
        disabled={busy || nextLists === null}
        onClick={() => onOffset(nextLists ?? 0)}
      >
        {t.next}
      </button>
    </>
  );
}

type ListsView = {
  labels: ShoppingLabels;
  busy: boolean;
  lists: ShoppingList[];
  listOffset: number;
  nextLists: number | null;
  listName: string;
  onListName: (value: string) => void;
  onCreate: () => void;
  onOffset: (offset: number) => void;
};

/** "7 kvar · uppdaterad idag": what is left and when the list last changed. */
function listMeta(t: ShoppingLabels, entry: ShoppingList, now: Date): string {
  return [
    entry.open_count === undefined ? "" : t.listLeft(entry.open_count),
    t.listUpdated(workDate(entry.updated_at, now, t.dateLocale)),
  ]
    .filter(Boolean)
    .join(" · ");
}

/**
 * No list chosen (§3 Rumshuvud, as Kontakter): the heading "Listor" with + for a new list in its row, then one
 * row per list with "7 kvar · uppdaterad idag" and ›. The + opens the shared create field under the head; Enter
 * creates the list and opens it, Esc or × closes the field and gives the focus back to +.
 */
export function ListPicker({
  labels: t,
  busy,
  lists,
  listOffset,
  nextLists,
  onOffset,
  fullscreen,
  hasError,
  listsExpanded,
  archivedOpen,
  newOpen,
  onCreateNamed,
  onChoose,
  onListsExpanded,
  onArchivedOpen,
  onNewOpen,
  sendMessage,
  control,
}: Omit<ListsView, "listName" | "onListName" | "onCreate"> & {
  /**
   * The last entry of the picker's ⋯: "Minne och kontroll", or the host's own settings (the phone). The ⋯ holds it,
   * so it is one tap away also before any list exists. Absent: no ⋯ (the room cannot open Control).
   */
  control?: HostSettingsEntry;
  /** Sends a message to Claude; absent when the host offers none (the empty state then shows its example as text). */
  sendMessage?: (text: string) => Promise<boolean>;
  fullscreen: boolean;
  hasError: boolean;
  listsExpanded: boolean;
  archivedOpen: boolean;
  newOpen: boolean;
  onCreateNamed: (name: string) => Promise<boolean>;
  onChoose: (id: string) => void;
  onListsExpanded: (value: boolean) => void;
  onArchivedOpen: (value: boolean) => void;
  onNewOpen: (value: boolean) => void;
}) {
  const addButton = useRef<HTMLButtonElement>(null);
  const moreButton = useRef<HTMLButtonElement>(null);
  const [moreOpen, setMoreOpen] = useState(false);
  const refocusAdd = useRef(false);
  useEffect(() => {
    if (newOpen || !refocusAdd.current) return;
    refocusAdd.current = false;
    addButton.current?.focus();
  }, [newOpen]);
  const now = new Date();
  // The lists in use come first; the archived ones of the page wait last, behind a fold.
  const active = lists.filter((entry) => !entry.archived);
  const archived = lists.filter((entry) => entry.archived);
  const shown =
    fullscreen || listsExpanded ? active : active.slice(0, COMPACT_ROWS);
  const listRow = (entry: ShoppingList) => (
    <li key={entry.id}>
      <button
        type="button"
        className="shopping-list-row"
        disabled={busy}
        onClick={() => onChoose(entry.id)}
      >
        <span className="shopping-list-text">
          <span className="shopping-list-name">{entry.name}</span>
          <span className="shopping-list-meta">{listMeta(t, entry, now)}</span>
        </span>
        <span className="shopping-chevron" aria-hidden="true">
          <ChevronRightIcon />
        </span>
      </button>
    </li>
  );
  return (
    <div className="shopping-picker">
      <div className="shopping-picker-head">
        <h2 className="shopping-picker-title">{t.lists}</h2>
        <button
          ref={addButton}
          type="button"
          className="sk-iconbtn sk-iconbtn--primary shopping-picker-add"
          aria-label={t.newList}
          title={t.newList}
          aria-expanded={newOpen}
          disabled={busy && !newOpen}
          onClick={() => onNewOpen(!newOpen)}
        >
          <PlusIcon />
        </button>
        {control && fullscreen && (
          <button
            ref={moreButton}
            type="button"
            className="shopping-more-trigger sk-iconbtn"
            aria-label={t.moreActions}
            aria-expanded={moreOpen}
            onClick={() => setMoreOpen(!moreOpen)}
            onKeyDown={(event) => {
              if (moreOpen) onEscapeKey(event, () => setMoreOpen(false));
            }}
          >
            <MoreIcon />
          </button>
        )}
      </div>
      {control && fullscreen && moreOpen && (
        <MoreMenu
          control={control}
          onClose={() => setMoreOpen(false)}
          onEscape={() => {
            setMoreOpen(false);
            moreButton.current?.focus();
          }}
        />
      )}
      {newOpen && (
        <div className="shopping-create">
          <CreateField
            label={t.newList}
            placeholder={t.newListPlaceholder}
            closeLabel={t.close}
            addLabel={t.create}
            errorLabel={t.saveFailed}
            onCreate={onCreateNamed}
            onClose={() => {
              refocusAdd.current = true;
              onNewOpen(false);
            }}
          />
        </div>
      )}
      {shown.length > 0 && (
        <ul className="shopping-lists" aria-label={t.lists}>
          {shown.map(listRow)}
        </ul>
      )}
      {/* Inline, a card shows COMPACT_ROWS lists; the rest is one "Show all" row. Fullscreen lists them all. */}
      {!fullscreen && active.length > COMPACT_ROWS && (
        <div className="shopping-more">
          <button
            type="button"
            aria-expanded={listsExpanded}
            onClick={() => onListsExpanded(!listsExpanded)}
          >
            {listsExpanded ? t.showFewer : t.showAll(active.length)}
          </button>
        </div>
      )}
      {archived.length > 0 && (
        <div className="shopping-archived-lists">
          <Fold
            text={t.archivedLists(archived.length)}
            open={archivedOpen}
            onToggle={() => onArchivedOpen(!archivedOpen)}
          />
          {archivedOpen && (
            <ul
              className="shopping-lists"
              aria-label={t.archivedLists(archived.length)}
            >
              {archived.map(listRow)}
            </ul>
          )}
        </div>
      )}
      {!busy && lists.length === 0 && !hasError && (
        <EmptyState
          title={t.noLists}
          hint={t.pickerHint}
          ask={emptyAsk(t.dateLocale, t.emptyListsExample, sendMessage)}
        />
      )}
      {(listOffset > 0 || nextLists !== null) && (
        <div className="shopping-toolbar">
          <ListPager
            labels={t}
            busy={busy}
            listOffset={listOffset}
            nextLists={nextLists}
            onOffset={onOffset}
          />
        </div>
      )}
    </div>
  );
}

/**
 * A list is chosen inline: the create form and the list picker sit above it. Folded (inline) they wait for
 * "Show all".
 */
export function ListSwitcher({
  labels: t,
  busy,
  lists,
  listOffset,
  nextLists,
  listName,
  onListName,
  onCreate,
  onOffset,
  id,
  list,
  onSelect,
  onRefresh,
}: ListsView & {
  id: string;
  list: ShoppingList;
  onSelect: (id: string) => void;
  onRefresh: () => void;
}) {
  return (
    <>
      <NameForm
        labels={t}
        className="shopping-toolbar"
        primary={false}
        value={listName}
        buttonLabel={t.create}
        busy={busy}
        onChange={onListName}
        onSubmit={onCreate}
      />
      <div className="shopping-toolbar">
        <label>
          {t.select}
          <select
            value={id}
            disabled={busy}
            onChange={(e) => onSelect(e.target.value)}
          >
            <option value="">{t.select}</option>
            {!lists.some((entry) => entry.id === list.id) && (
              <option value={list.id}>{list.name}</option>
            )}
            {/* The archived lists stand last, as in the picker. */}
            {[...lists]
              .sort((a, b) => Number(a.archived) - Number(b.archived))
              .map((entry) => (
                <option key={entry.id} value={entry.id}>
                  {entry.name}
                  {entry.archived ? ` · ${t.archived}` : ""}
                </option>
              ))}
          </select>
        </label>
        <button disabled={busy} onClick={onRefresh}>
          {t.refresh}
        </button>
        {/* The list pager is shown only when there is more than one page of lists. */}
        {(listOffset > 0 || nextLists !== null) && (
          <ListPager
            labels={t}
            busy={busy}
            listOffset={listOffset}
            nextLists={nextLists}
            onOffset={onOffset}
          />
        )}
      </div>
    </>
  );
}

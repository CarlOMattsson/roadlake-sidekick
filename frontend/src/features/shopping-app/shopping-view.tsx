import { useMemo, useRef } from "react";
import type {
  ShoppingDetail,
  ShoppingItem,
  ShoppingTransport,
} from "./transport";
import type { ShoppingLabels } from "./labels";
import { finePointer } from "../mcp-apps/ui/shortcuts";
import { copyTime } from "../mcp-apps/app-timezone";
import { roomEnabled } from "../mcp-apps/enabled-rooms";
import { useMoreMark } from "../mcp-apps/update-reminder";
import { useLicenseMenu } from "../mcp-apps/license-mark";
import { controlEntry } from "../mcp-apps/ui/control-entry";
import { EmptyState } from "../mcp-apps/ui/states";
import { PlusIcon } from "../mcp-apps/ui/icons";
import type { HostSettingsEntry, RoomTarget } from "../mcp-apps/room-types";
import "../mcp-apps/ui/tokens.css";
import "../mcp-apps/ui/family.css";
import "./shopping.css";
import { deriveView } from "./shopping-view-parts/derive-view";
import { FailureNotice } from "./shopping-view-parts/failure-notice";
import { emptyAsk, intoView, wasHoldUsed } from "./shopping-view-parts/helpers";
import { ItemGroups, PurchasedFold } from "./shopping-view-parts/item-groups";
import {
  AddItemField,
  BatchForm,
  ListSummary,
  PageSwitcher,
} from "./shopping-view-parts/list-body";
import {
  ListPicker,
  ListSwitcher,
  NameForm,
} from "./shopping-view-parts/list-forms";
import type { RowEnv } from "./shopping-view-parts/row-parts";
import { ShoppingHeader } from "./shopping-view-parts/shopping-header";
import { useItemEditing } from "./shopping-view-parts/use-item-editing";
import { usePanels } from "./shopping-view-parts/use-panels";
import { usePurchases } from "./shopping-view-parts/use-purchases";
import { useShoppingRead } from "./shopping-view-parts/use-shopping-read";
import { useShoppingWrites } from "./shopping-view-parts/use-shopping-writes";
import { useWriteForms } from "./shopping-view-parts/use-write-forms";

// The compact-view budget and its grouping are part of this module's surface (the room and the tests use them).
export { COMPACT_ROWS, compactGroups } from "./shopping-view-parts/helpers";

/**
 * Both hosts use the same UI. The adapter alone decides HTTP versus tools/call. In fullscreen the
 * list opens as a store view (large purchase rows); list and item forms sit behind "Edit list".
 */
export function ShoppingView({
  transport,
  labels: t,
  initial,
  listId,
  fullscreen = false,
  store,
  compact = false,
  refreshKey,
  onNavigate,
  hostSettings,
  written: writtenFrom,
  onWritten,
  writtenTick,
  sendMessage,
}: {
  transport: ShoppingTransport;
  labels: ShoppingLabels;
  initial?: ShoppingDetail;
  /** The list to select and read on mount, for example the list of a batch result. */
  listId?: string;
  fullscreen?: boolean;
  /**
   * A change after mount reads the list again in place (the same read as Refresh). The value at mount is
   * not a request. Typed text, the open panels and the selection are kept.
   */
  refreshKey?: number;
  /**
   * The shop the list was read for. The view then shows that shop's items plus those with no shop as
   * the store view (large rows), also inline, and every re-read keeps the filter.
   */
  store?: string;
  /**
   * Inline on a host without fullscreen: a short list (COMPACT_ROWS open rows, the purchased items
   * folded) that fits a phone card. "Show all" expands the whole view in place, and "Show fewer" folds it again.
   */
  compact?: boolean;
  /** Opens another room; the list's ⋯ then ends with "Kontroll" (designsystem §3, Rumshuvud). */
  onNavigate?: (target: RoomTarget) => void;
  /** The host's own settings (the phone): the list's ⋯ ends with them instead of Control. */
  hostSettings?: HostSettingsEntry;
  /**
   * The confirmed rows, owned by the room: a later result for the same list never takes a row back to an older
   * version, also when the view is mounted again.
   */
  written?: Map<string, ShoppingItem>;
  /** Called when a purchase reply was stored in `written`, also by a view that has since been replaced. */
  onWritten?: () => void;
  /** Changes when `written` changed from outside this view: the rows are then taken from it again. */
  writtenTick?: number;
  /** Sends a message to Claude (ui/message); absent when the host offers none. The empty states then show their example as text. */
  sendMessage?: (text: string) => Promise<boolean>;
}) {
  // The row's hint: the long press on touch, the right click and Shift+F10 with a fine pointer.
  const holdTip = finePointer() ? t.holdKeys : t.holdTip;
  const read = useShoppingRead({
    transport,
    initial,
    listId,
    store,
    refreshKey,
    writtenFrom,
    writtenTick,
  });
  const { lists, listOffset, setListOffset, nextLists, id, setId } = read;
  const { offset, setOffset, detail, setDetail, busy, error, reload } = read;
  const { copiedAt } = read;
  const writes = useShoppingWrites(read);
  const { conflict, failedWrite, write } = writes;
  const { panels, setPanel, closeAll } = usePanels();
  const purchases = usePurchases({ transport, read, writes, onWritten });
  const { rowQueue, wanted, waiting, held, setHeld, togglePurchase } =
    purchases;
  const view = deriveView({
    labels: t,
    detail,
    id,
    wanted,
    waiting,
    held,
    fullscreen,
    compact,
    store,
    editOpen: panels.editOpen,
    expanded: panels.expanded,
  });
  const { list, items, purchased, settled, rows, storeMode, canAdd, folded } =
    view;
  const editor = useItemEditing(list?.archived);
  const { setEditing } = editor;
  const forms = useWriteForms({
    transport,
    labels: t,
    read,
    writes,
    store,
    addOpen: panels.addOpen,
    setPanel,
  });
  // The ⋯ menu in the header of the fullscreen view. It holds "Edit list" and closes when an item is chosen.
  const moreButton = useRef<HTMLButtonElement>(null);
  // The license coin asks (Control off): this ⋯ opens on its row.
  useLicenseMenu(moreButton, () => setPanel("moreOpen", true));
  const moreMark = useMoreMark(t.moreActions);
  // The last entry of the list's ⋯ (designsystem §3): the host's own settings (the phone), else "Kontroll" when the
  // room can open another room.
  const control = useMemo(() => {
    if (hostSettings) return hostSettings;
    if (!onNavigate || !roomEnabled("control")) return undefined;
    const entry = controlEntry(t.dateLocale.startsWith("sv") ? "sv" : "en");
    return { label: entry.label, onOpen: () => onNavigate(entry.target) };
  }, [hostSettings, onNavigate, t.dateLocale]);
  /** Chooses the list to read, or "" for the picker of all lists. The last list and its open panels are forgotten. */
  function chooseList(next: string) {
    setId(next);
    setOffset(0);
    setEditing(null);
    purchases.resetPurchases();
    setDetail(undefined);
    closeAll();
  }
  /** The select of the inline list switcher: another list, with the held rows and the open form forgotten. */
  function switchList(next: string) {
    setId(next);
    setOffset(0);
    setEditing(null);
    setHeld({});
    setDetail(undefined);
  }
  function goToPage(next: number) {
    setOffset(next);
    setEditing(null);
    setHeld({});
  }
  const rowEnv: RowEnv = {
    labels: t,
    holdTip,
    archived: list?.archived,
    busy,
    folded,
    held,
    rowQueue,
    waiting,
    conflict,
    error,
    failedWrite,
    editing: editor.editing,
    editorByKey: editor.editorByKey,
    registerRow: editor.registerRow,
    contacts: transport.contacts,
    onToggle: togglePurchase,
    onRelease: purchases.release,
    onRefresh: () => void reload(),
    onOpenEditor: editor.openEditor,
    onCloseEditor: editor.closeEditor,
    onEdit: setEditing,
    onSave: (item, input, done) =>
      void write(
        JSON.stringify(["update", item.id, item.version, input]),
        (key) => transport.update(item, input, key),
        done,
        item.id,
      ),
  };
  return (
    <section
      className={
        fullscreen
          ? "sidekick-shopping shopping-fullscreen"
          : `sidekick-shopping sk-card sk-card--root${folded ? " shopping-folded" : ""}`
      }
      aria-label={t.title}
    >
      <ShoppingHeader
        labels={t}
        id={id}
        list={list}
        headerTitle={view.headerTitle}
        busy={busy}
        fullscreen={fullscreen}
        canAdd={canAdd}
        addOpen={panels.addOpen}
        addButton={forms.addButton}
        moreOpen={panels.moreOpen}
        moreButton={moreButton}
        moreMark={moreMark}
        editOpen={panels.editOpen}
        control={control}
        showHint={Boolean(id) && !storeMode && !folded && !view.reading}
        onBack={() => chooseList("")}
        onToggleAdd={forms.toggleAddField}
        onToggleMore={() => setPanel("moreOpen", !panels.moreOpen)}
        onCloseMore={() => setPanel("moreOpen", false)}
        onToggleEdit={() => {
          if (!panels.editOpen && list) forms.setRenameName(list.name);
          setPanel("editOpen", !panels.editOpen);
          setPanel("moreOpen", false);
        }}
      />
      {error?.rowId === null && (
        <FailureNotice
          labels={t}
          retry={failedWrite ?? undefined}
          busy={busy}
          placement="card"
          onRefresh={() => void reload()}
        />
      )}
      {conflict &&
        !detail?.items.some((item) => item.id === conflict.rowId) && (
          <p role="alert" ref={intoView}>
            {t.conflict}
          </p>
        )}
      {/* No list chosen: the lists are rows to tap, and "New list" sits last behind a button. */}
      {!id && (
        <ListPicker
          labels={t}
          busy={busy}
          lists={lists}
          listOffset={listOffset}
          nextLists={nextLists}
          onOffset={setListOffset}
          fullscreen={fullscreen}
          hasError={Boolean(error)}
          listsExpanded={panels.listsExpanded}
          archivedOpen={panels.archivedOpen}
          newOpen={panels.newOpen}
          onCreateNamed={forms.createNamed}
          onChoose={chooseList}
          onListsExpanded={(value) => setPanel("listsExpanded", value)}
          onArchivedOpen={(value) => setPanel("archivedOpen", value)}
          onNewOpen={(value) => setPanel("newOpen", value)}
          sendMessage={sendMessage}
          control={control}
        />
      )}
      {/* Edit list (fullscreen): the field renames the open list with update_shopping_list. No create form, no picker. */}
      {list && panels.editOpen && (
        <NameForm
          labels={t}
          className="shopping-toolbar shopping-rename"
          primary
          value={forms.renameName}
          buttonLabel={t.save}
          busy={busy}
          onChange={forms.setRenameName}
          onSubmit={forms.rename}
        />
      )}
      {/* A list is chosen inline: the create form and the list picker sit above it. Folded (inline) they wait for "Show all". */}
      {id && list && !storeMode && !folded && !panels.editOpen && (
        <ListSwitcher
          labels={t}
          busy={busy}
          lists={lists}
          listOffset={listOffset}
          nextLists={nextLists}
          listName={forms.listName}
          onListName={forms.setListName}
          onCreate={forms.create}
          onOffset={setListOffset}
          id={id}
          list={list}
          onSelect={switchList}
          onRefresh={() => void reload()}
        />
      )}
      {/* The offline copy: the list as it was last read, said with when (the phone had no answer). */}
      {copiedAt !== null && (
        <p role="status">{t.offlineCopy(copyTime(copiedAt, t.dateLocale))}</p>
      )}
      <p aria-live="polite" className="shopping-visually-hidden">
        {items.some((item) => rowQueue.queued(item.id))
          ? t.queued
          : items.some((item) => item.id in waiting)
            ? t.waitingForNetwork
            : ""}
      </p>
      {busy && (
        <p role="status" className="shopping-loading">
          {t.loading}
        </p>
      )}
      {list && detail && (
        <>
          <ListSummary
            labels={t}
            detail={detail}
            list={list}
            storeMode={storeMode}
            folded={folded}
            purchasedCount={purchased.length}
            shopLabel={view.shopLabel}
            busy={busy}
            onArchive={() =>
              void write(
                JSON.stringify(["archive", list.id, list.version]),
                (key) => transport.rename(list, list.name, !list.archived, key),
              )
            }
          />
          {canAdd && (
            <AddItemField
              labels={t}
              fullscreen={fullscreen}
              open={panels.addOpen}
              hasError={Boolean(error)}
              note={forms.addNote}
              addButton={forms.addButton}
              onCreate={forms.addOne}
              onOpen={forms.openAddField}
              onClose={forms.closeAddField}
            />
          )}
          <ItemGroups
            shownGroups={view.shownGroups}
            rowCount={rows.length}
            shownCount={view.shownCount}
            folded={folded}
            compact={compact}
            expanded={panels.expanded}
            storeMode={storeMode}
            shopLabel={view.shopLabel}
            env={rowEnv}
            onExpanded={(value) => setPanel("expanded", value)}
          />
          {/* Everything bought: the fold alone would not say the list is done (the card says it too). */}
          {storeMode &&
            rows.length === 0 &&
            purchased.length > 0 &&
            !list.archived && (
              <p className="shopping-all-bought">{t.allBought}</p>
            )}
          <PurchasedFold
            purchased={settled}
            open={panels.boughtOpen}
            storeMode={storeMode}
            env={rowEnv}
            onToggle={() => setPanel("boughtOpen", !panels.boughtOpen)}
          />
          {/* Last in the list, after "Köpta (n)", as Arbetes tip stands after "Klar (n)". */}
          {storeMode && rows.length > 0 && !list.archived && !wasHoldUsed() && (
            <p className="shopping-hold-tip">{holdTip}</p>
          )}
          {/* An empty list says what it is for and how to fill it (§3 Tomt); in fullscreen, where + sits in the
              Back row, "+ Lägg till en vara" opens the same field here. Gone while the field is open. */}
          {!detail.items.length && !panels.addOpen && (
            <EmptyState
              title={t.empty}
              hint={list.archived ? undefined : t.emptyHint}
              ask={emptyAsk(
                t.dateLocale,
                t.emptyListExample(list.name),
                sendMessage,
              )}
            >
              {canAdd && fullscreen && !list.archived && (
                <button
                  type="button"
                  className="sk-action-row"
                  onClick={forms.openAddField}
                >
                  <PlusIcon />
                  {t.emptyAddItem}
                </button>
              )}
            </EmptyState>
          )}
          <PageSwitcher
            labels={t}
            offset={offset}
            nextOffset={detail.next_offset}
            busy={busy}
            onPage={goToPage}
          />
          {!list.archived && !storeMode && (
            <BatchForm
              labels={t}
              folded={folded}
              names={forms.names}
              invalid={forms.invalidBatch}
              busy={busy}
              onNames={forms.setNames}
              onKeyDown={forms.batchKeyDown}
              onAdd={() => forms.add()}
            />
          )}
        </>
      )}
    </section>
  );
}

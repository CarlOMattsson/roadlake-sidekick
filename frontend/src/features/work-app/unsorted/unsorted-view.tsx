import {
  Fragment,
  useEffect,
  type KeyboardEvent,
  useEffectEvent,
  useMemo,
  useRef,
  useState,
} from "react";
import { UndoMeta, fillLabel } from "../agenda/agenda-undo";
import {
  failureNotice,
  NoticeView,
  type BoardAction,
  type BoardNotice,
} from "../board/board";
import { RefreshIcon } from "../board/board-sections";
import { GroupSelect } from "../hierarchy/group-select";
import { groupSelectLabelsFor } from "../hierarchy/group-select-labels";
import {
  placeChanges,
  placeOf,
  placeTitle,
  useGroupChoices,
  type TaskPlace,
} from "../hierarchy/group-choices";
import type { WorkLabels } from "../shared/labels";
import { useSingleFlight } from "../shared/use-single-flight";
import { taskPlaceLabelsFor } from "../tasks/task-place-labels";
import { useToolSupport } from "../../mcp-apps/tool-support";
import { keyFor, type PendingKey } from "../../mcp-apps/idempotency";
import "./unsorted.css";
import { ChevronRightIcon } from "../../mcp-apps/ui/icons";
import { ReceiptBar, useReceipt } from "../../mcp-apps/ui/receipt";
import { rowReceipt, useUndoReceipts } from "../shared/use-undo-receipts";
import {
  domainAccentOf,
  writeFailure,
  type WorkDomain,
  type WorkTask,
  type WorkTransport,
} from "../transport/transport";

/**
 * The last sort of one Task: the Task as it was before the sort, the row it held, and the version the
 * sort left. Undo writes the place back to none against that version and puts the row back.
 */
type UnsortedUndo = {
  task: WorkTask;
  index: number;
  version: number;
  /** The name of the place the Task was sorted into; the Undo line shows it. */
  label: string;
};

/**
 * The To sort view (Att sortera): Tasks with no Domain, Project or Process, one page at a time, each
 * with one button per Domain and `choosePlace`, which unfolds the place picker (a Domain, Project or Process).
 * A tap or a choice sorts the Task there (update_task with placeChanges) and the row leaves when the reply
 * comes; the Undo line puts it back. The places are read (get_work_hierarchy) when a picker is first opened. Reads go through the bridge
 * (list_tasks with unsorted, list_domains); there is no app resource of its own. The fullscreen Work
 * app opens it from a row after the agenda, and in a wide frame from its own tab.
 *
 * In the tab (`onOpen` given) a row is a triage line (desktop spec 3.1): the title opens the Task, and with the focus in
 * the row 1–9 sort it into the Domain of that place and P unfolds the place picker. A wide frame lays the line out on
 * one row of 52 (unsorted.css); the phone keeps its stacked row.
 */
export function UnsortedView({
  transport,
  labels: t,
  onOpen,
  onSorted,
}: {
  transport: WorkTransport;
  labels: WorkLabels;
  /** Opens a Task from its title; absent: the title is text. */
  onOpen?: (task: WorkTask) => void;
  /** A sort or its Undo landed, so the count of Tasks to sort has changed. */
  onSorted?: () => void;
}) {
  const [items, setItems] = useState<WorkTask[]>();
  const [cursor, setCursor] = useState<string | null>(null);
  const [domains, setDomains] = useState<WorkDomain[]>();
  const [busy, setBusy] = useState<BoardAction | "idle">("idle");
  const [notice, setNotice] = useState<BoardNotice>();
  const [undo, setUndo] = useState<UnsortedUndo>();
  // The row whose place picker is unfolded; the places are read the first time one is.
  const [picking, setPicking] = useState<string>();
  const [pickerOpened, setPickerOpened] = useState(false);
  const choices = useGroupChoices(transport, pickerOpened);
  const offers = useToolSupport(transport);
  const words = taskPlaceLabelsFor(t.dateLocale);
  // The picker needs a write of the place and the read of the places; a host without them offers the Domain buttons only.
  const pickerOffered =
    offers("update_task", { changes: placeChanges(null) }) &&
    offers("get_work_hierarchy");
  // Synchronous guards before React re-renders: one read at a time (reload / more), and one write per
  // Task. Writes of different Tasks run side by side; a read and a write never overlap.
  const reading = useSingleFlight();
  const writes = useRef(new Set<string>());
  // The Task ids whose write is in flight; their rows are shown busy and their buttons disabled.
  const [writing, setWriting] = useState<ReadonlySet<string>>(new Set());
  // The list as it is now, so a sort that lands records the row's index at that moment.
  const itemsNow = useRef<WorkTask[] | undefined>(undefined);
  const mounted = useRef(true);
  // One key per attempt: a retry of the same write reuses it, as the agenda does.
  const pending = useRef(new Map<string, PendingKey>());
  // The write that "Try again" repeats after a failed change.
  const retryWrite = useRef<(() => void) | undefined>(undefined);
  // Triage: the place in the list whose title takes the focus once a sorted row has left (the next row moves up into it).
  const focusAt = useRef<number | undefined>(undefined);
  const listRef = useRef<HTMLUListElement>(null);
  useEffect(() => {
    const at = focusAt.current;
    if (at === undefined || !listRef.current) return;
    focusAt.current = undefined;
    const titles = listRef.current.querySelectorAll<HTMLButtonElement>(
      "li:not([data-undo]) .work-unsorted-open-task",
    );
    (titles[Math.min(at, titles.length - 1)] ?? undefined)?.focus();
  }, [items]);

  // The first read happens once, when the tab is first pressed.
  // eslint-disable-next-line react-hooks/immutability -- the first read runs from an effect after the render, when reload is declared.
  const readFirst = useEffectEvent(() => reload());
  useEffect(() => {
    mounted.current = true;
    readFirst();
    return () => {
      mounted.current = false;
    };
  }, []);

  function update(change: (all: WorkTask[]) => WorkTask[]) {
    itemsNow.current = change(itemsNow.current ?? []);
    setItems(itemsNow.current);
  }

  /** A read; it waits for no write, but is dropped while a write or another read runs. */
  function run(action: BoardAction, work: () => Promise<void>) {
    if (writes.current.size > 0 || !reading.enter()) return;
    setBusy(action);
    setNotice(undefined);
    void work().finally(() => {
      reading.leave();
      if (mounted.current) setBusy("idle");
    });
  }

  /** The first page of unsorted Tasks and the Domains; a refresh drops the Undo line. */
  function reload() {
    run("reload", async () => {
      try {
        const [page, list] = await Promise.all([
          transport.listUnsortedTasks(),
          transport.listDomains(),
        ]);
        if (mounted.current) {
          setUndo(undefined);
          update(() => page.items);
          setCursor(page.next_cursor);
          setDomains(list);
        }
      } catch (error) {
        if (mounted.current) setNotice(failureNotice(error, "reload"));
      }
    });
  }

  function loadMore() {
    if (!cursor) return;
    run("more", async () => {
      try {
        const later = await transport.listUnsortedTasks(cursor);
        if (mounted.current) {
          update((all) => [...all, ...later.items]);
          setCursor(later.next_cursor);
        }
      } catch (error) {
        if (mounted.current) setNotice(failureNotice(error, "more"));
      }
    });
  }

  function retry(action: BoardAction) {
    if (action === "move") retryWrite.current?.();
    else if (action === "more") loadMore();
    else reload();
  }

  /**
   * One write of one Task. Writes of other Tasks may run at the same time; the row stays where it is
   * (no optimistic removal) and is shown busy until the reply comes. Dropped while a read runs or while
   * the same Task is being written.
   */
  function write(id: string, work: () => Promise<void>) {
    if (reading.isRunning() || writes.current.has(id)) return false;
    writes.current.add(id);
    setWriting(new Set(writes.current));
    setNotice(undefined);
    void work().finally(() => {
      writes.current.delete(id);
      if (mounted.current) setWriting(new Set(writes.current));
    });
    return true;
  }

  /** Sorts one Task into one place against the version the row shows; the row leaves on success. */
  function sortInto(task: WorkTask, place: TaskPlace, label: string) {
    const changes = placeChanges(place);
    write(task.id, async () => {
      const signature = JSON.stringify([task.id, task.version, changes]);
      const attempt = keyFor(pending.current.get(task.id), signature);
      pending.current.set(task.id, attempt);
      try {
        const { task: stored } = await transport.updateTask(
          task.id,
          task.version,
          changes,
          attempt.key,
        );
        pending.current.delete(task.id);
        if (!mounted.current) return;
        const index = (itemsNow.current ?? []).findIndex(
          (item) => item.id === task.id,
        );
        // The focus was in the row (a key or a button of it): it goes on to the next row's title.
        if (
          onOpen &&
          listRef.current?.contains(document.activeElement) &&
          index >= 0
        )
          focusAt.current = index;
        update((all) => all.filter((item) => item.id !== task.id));
        setPicking(undefined);
        setUndo({ task, index, version: stored.version, label });
        onSorted?.();
      } catch (error) {
        if (writeFailure(error) !== "failed") pending.current.delete(task.id);
        retryWrite.current = () => sortInto(task, place, label);
        if (mounted.current) setNotice(failureNotice(error, "move"));
      }
    });
  }

  /**
   * Undo: the place is cleared again, against the version the sort left, with its own key. The reply
   * must show no place; the row goes back to the index it had.
   */
  function undoSort(entry: UnsortedUndo) {
    // Undo waits for every other write to finish, so the row goes back to a settled list.
    if (writes.current.size > 0) return;
    const changes = placeChanges(null);
    const undoKey = `undo:${entry.task.id}`;
    write(entry.task.id, async () => {
      const signature = JSON.stringify([entry.task.id, entry.version, changes]);
      const attempt = keyFor(pending.current.get(undoKey), signature);
      pending.current.set(undoKey, attempt);
      try {
        const { task } = await transport.updateTask(
          entry.task.id,
          entry.version,
          changes,
          attempt.key,
        );
        pending.current.delete(undoKey);
        if (placeOf(task) !== null) {
          // The reply still shows a place: a failure with "Try again", which gets a new key.
          throw new Error("undo not applied");
        }
        if (!mounted.current) return;
        // The row takes back the place of its Undo line.
        setUndo(undefined);
        onSorted?.();
        update((all) => {
          const list = all.filter((item) => item.id !== entry.task.id);
          list.splice(Math.min(entry.index, list.length), 0, {
            ...entry.task,
            version: task.version,
          });
          return list;
        });
      } catch (error) {
        if (writeFailure(error) !== "failed") pending.current.delete(undoKey);
        retryWrite.current = () => undoSort(entry);
        if (mounted.current) setNotice(failureNotice(error, "move"));
      }
    });
  }

  /** The triage keys of a row: 1–9 sort into that Domain, P unfolds the place picker. Never while typing. */
  function triageKey(event: KeyboardEvent<HTMLElement>, task: WorkTask) {
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    const target = event.target as HTMLElement;
    if (target.closest("input, select, textarea, [contenteditable]")) return;
    if (reads || writing.has(task.id)) return;
    if (/^[1-9]$/.test(event.key)) {
      const domain = domains?.[Number(event.key) - 1];
      if (!domain) return;
      event.preventDefault();
      sortInto(task, { kind: "domain", id: domain.id }, domain.name);
      return;
    }
    if (pickerOffered && event.key.toLowerCase() === "p") {
      event.preventDefault();
      setPicking(task.id);
      setPickerOpened(true);
    }
  }

  const reads = busy !== "idle";
  const moving = writing.size > 0;
  const disabled = reads || moving;
  const loading = reads || (items === undefined && !notice);
  const list = items ?? [];
  // The sorted row stays in its place with `movedTo` and `undo` in place of its Domain buttons (designsystem),
  // so it covers no row; while a write runs it says "Moving…" there, so a quick second tap lands where it aimed.
  const at = undo ? Math.min(Math.max(undo.index, 0), list.length) : -1;
  // The sort is confirmed in the receipt bar at the view's foot, with Ångra; the row keeps its state line until the
  // bar's time is up (designsystem §0.6).
  const receipt = useReceipt();
  const undos = useMemo(
    (): Record<string, UnsortedUndo> => (undo ? { sort: undo } : {}),
    [undo],
  );
  useUndoReceipts({
    undos,
    receipt,
    describe: (_key, entry) => ({
      message: rowReceipt(
        fillLabel(t.movedTo, { status: entry.label }),
        entry.task.title,
      ),
      undo: { label: t.agendaUndo, onUndo: () => undoSort(entry) },
    }),
    onEnd: () => setUndo(undefined),
  });
  const line = undo && (
    <li className="work-unsorted-row" data-undo="on">
      <p className="work-unsorted-title">{undo.task.title}</p>
      <UndoMeta
        text={fillLabel(t.movedTo, { status: undo.label })}
        moving={moving}
        labels={t}
      />
    </li>
  );

  return (
    <div
      className={
        onOpen ? "work-unsorted work-unsorted--triage" : "work-unsorted"
      }
    >
      <div className="work-unsorted-toolbar">
        <p className="work-unsorted-intro">{words.unsortedIntro}</p>
        <button
          type="button"
          className="work-unsorted-refresh sk-iconbtn sk-iconbtn--row"
          aria-label={t.refresh}
          disabled={disabled}
          onClick={reload}
        >
          <RefreshIcon />
        </button>
      </div>
      <NoticeView
        notice={notice}
        labels={t}
        onReload={reload}
        onRetry={retry}
      />
      {loading && <p role="status">{t.loading}</p>}
      {items !== undefined && items.length === 0 && !loading && (
        <p>{t.unsortedEmpty}</p>
      )}
      {domains !== undefined && domains.length === 0 && (
        <p>{t.unsortedNoDomains}</p>
      )}
      {(list.length > 0 || line) && (
        <ul
          ref={listRef}
          className="work-list work-unsorted-list"
          data-triage={onOpen ? "" : undefined}
        >
          {list.map((task, i) => (
            <Fragment key={task.id}>
              {i === at && line}
              <li
                className="work-unsorted-row"
                aria-busy={writing.has(task.id) || undefined}
                data-sk-row={onOpen ? "" : undefined}
              >
                {onOpen ? (
                  <p className="work-unsorted-title">
                    <button
                      type="button"
                      className="work-unsorted-open-task"
                      aria-keyshortcuts={keysOf(domains?.length ?? 0)}
                      onClick={() => onOpen(task)}
                      onKeyDown={(event) => triageKey(event, task)}
                    >
                      {task.title}
                    </button>
                  </p>
                ) : (
                  <p className="work-unsorted-title">{task.title}</p>
                )}
                {domains !== undefined && domains.length > 0 && (
                  <div
                    className="work-unsorted-domains"
                    role="group"
                    aria-label={t.unsortedRowFor(task.title)}
                  >
                    {domains.map((domain, place) => {
                      const accent = domainAccentOf(domain.accent);
                      const key = place < 9 ? String(place + 1) : undefined;
                      return (
                        <button
                          key={domain.id}
                          type="button"
                          className="work-unsorted-domain"
                          data-accent={accent ?? undefined}
                          aria-keyshortcuts={onOpen ? key : undefined}
                          title={
                            onOpen && key
                              ? `${domain.name} (${key})`
                              : undefined
                          }
                          disabled={reads || writing.has(task.id)}
                          onKeyDown={
                            onOpen
                              ? (event) => triageKey(event, task)
                              : undefined
                          }
                          onClick={() =>
                            sortInto(
                              task,
                              { kind: "domain", id: domain.id },
                              domain.name,
                            )
                          }
                        >
                          {domain.name}
                        </button>
                      );
                    })}
                  </div>
                )}
                {pickerOffered && (
                  <div className="work-unsorted-pick">
                    <button
                      type="button"
                      className="work-unsorted-pick-button"
                      aria-expanded={picking === task.id}
                      aria-keyshortcuts={onOpen ? "P" : undefined}
                      title={onOpen ? `${words.choosePlace} (P)` : undefined}
                      disabled={reads || writing.has(task.id)}
                      onKeyDown={
                        onOpen ? (event) => triageKey(event, task) : undefined
                      }
                      onClick={() => {
                        setPicking(picking === task.id ? undefined : task.id);
                        setPickerOpened(true);
                      }}
                    >
                      {words.choosePlace}
                    </button>
                    {picking === task.id && (
                      <GroupSelect
                        label={words.pickerFor(task.title)}
                        value={null}
                        choices={choices}
                        labels={groupSelectLabelsFor(t.dateLocale)}
                        disabled={reads || writing.has(task.id)}
                        onChange={(place) => {
                          if (place && choices.phase === "ready")
                            sortInto(
                              task,
                              place,
                              placeTitle(choices.domains, place) ?? "",
                            );
                        }}
                      />
                    )}
                  </div>
                )}
              </li>
            </Fragment>
          ))}
          {at === list.length && line}
        </ul>
      )}
      {cursor && (
        <button type="button" disabled={disabled} onClick={loadMore}>
          {t.more}
        </button>
      )}
      <ReceiptBar receipt={receipt} />
    </div>
  );
}

/** The keys a row's title announces: 1 up to the number of Domains (at most 9), and P. */
function keysOf(domains: number): string {
  const count = Math.min(domains, 9);
  return [...Array.from({ length: count }, (_, i) => String(i + 1)), "P"].join(
    " ",
  );
}

/**
 * The row above the agenda that opens the To sort view. The Work app shows it only when some Task is
 * unsorted. `more` is true when the count is a first page that has more after it, so it reads "N+".
 */
export function UnsortedOpenRow({
  count,
  more,
  labels: t,
  onOpen,
}: {
  count: number;
  more: boolean;
  labels: WorkLabels;
  onOpen: () => void;
}) {
  return (
    <div className="work-unsorted-open-row">
      <button type="button" className="work-unsorted-open" onClick={onOpen}>
        {t.unsortedOpen(more ? `${count}+` : String(count))}
        <ChevronRightIcon />
      </button>
    </div>
  );
}

import { useEffect, useRef, useState } from "react";
import { copyTime } from "../../mcp-apps/app-timezone";
import { WorkEmpty } from "../shared/work-empty";
import { type WorkLabels } from "../shared/labels";
import { RowMenuTip } from "../shared/row-menu";
import { cardKey } from "../shared/work-items";
import {
  type WorkAgendaFrame,
  type WorkFrame,
  type WorkTransport,
} from "../transport/transport";
import { isWaitingFilter, waitingLabelsFor } from "../shared/waiting";
import {
  filterTags,
  KnownTags,
  useWorkTags,
  withFilterTags,
  WorkTagFilter,
} from "../shared/work-tags";
import { AgendaFilterRow } from "./parts/agenda-filter-row";
import { AgendaNotice, type NoticeSource } from "./parts/agenda-notice";
import {
  AgendaSection,
  DoneTodaySection,
  WaitingSection,
} from "./parts/agenda-sections";
import { MoveAllUndo } from "./parts/move-all-overdue";
import type { AgendaRowContext } from "./parts/row-context";
import { SearchNoMatch } from "./parts/search-no-match";
import { useAgendaBulk } from "./parts/use-agenda-bulk";
import {
  useAgendaLayout,
  useAgendaQuery,
  type AgendaControls,
} from "./parts/use-agenda-layout";
import { useAgendaSelection } from "./parts/use-agenda-selection";
import { useMounted } from "../../mcp-apps/ui/use-mounted";
import { useAgendaSession } from "./parts/use-agenda-session";
import { useKeepFocus } from "./parts/use-keep-focus";
import { useOfflineAgenda } from "./parts/use-offline-agenda";
import { useRowMenu } from "./parts/use-row-menu";
import { useRowOffers } from "./parts/use-row-offers";
import { useRowState } from "./parts/use-row-state";
import { useRowWrites } from "./parts/use-row-writes";
import "./agenda.css";

export { SearchNoMatch };
export type { AgendaControls };

/**
 * The Work agenda, the fullscreen view: dated records in the groups Förfallna, Idag, Denna vecka, Nästa
 * vecka, Senare and Utan datum (`agendaSections`). Only Försenade shows its count; Idag also names its day. A record opens its Task or Project.
 * The glyph of a Task marks it done at once; the row's quick choices (a long press, Shift+F10 or the menu key; the row
 * has no ⋯) set any status and move its due date ("Tomorrow", "Next week", or a chosen day, 23:59).
 * Every change stays on its row as `completed` with `undo` for `UNDO_MS`, each row with its own Undo.
 * The Overdue group has one more control, `moveAllOverdue`, and an overdue row's `completed` in its quick choices
 * is a triage move too: the row stays in its group, muted with its new date or `completed`, and its date choices
 * are off until the list is read again.
 * Keys: j and k step through the records, x toggles done of the selected Task, 1 to 4 set its status. The filter
 * narrows the loaded page by title. The inline card is the read-only agenda summary in `inline-summary.tsx`.
 *
 * The view only composes: the optimistic row state, the reads, the row writes, the layout of the groups and the
 * selection live in the hooks of `agenda-parts/`, the groups and rows in its components.
 */
export function AgendaView({
  frame,
  onChange,
  transport,
  labels: t,
  moves,
  onOpen,
  shortcuts = false,
  now = new Date(),
  headingHidden = false,
  stale = false,
  onRead,
  controls,
  refreshKey,
  boardAvailable = true,
}: {
  frame: WorkAgendaFrame;
  onChange: (next: WorkAgendaFrame) => void;
  transport: WorkTransport;
  labels: WorkLabels;
  moves: number;
  onOpen: (frame: WorkFrame) => void;
  /** Turns on the window keys; only a fullscreen caller passes true (design language 3.8). */
  shortcuts?: boolean;
  /** The instant relative due dates are measured from; defaults to the current time, as the board does. */
  now?: Date;
  /** Hides the heading visually, kept for focus and assistive technology; the fullscreen shell passes true. */
  headingHidden?: boolean;
  /** A Task was saved since this agenda was read: it reads again once shown. */
  stale?: boolean;
  /** Called after a successful read, so the caller clears its `stale` mark. */
  onRead?: () => void;
  /** The filter text and the read-again request of the caller; absent, the agenda draws its own filter row. */
  controls?: AgendaControls;
  /** Reads again in place when it changes; the value at mount is not a request. Filter, selection and open rows stay. */
  refreshKey?: number;
  /** False when the host serves no Status tab: a ticked row then says only "Done", with no pointer to a view that is not there. */
  boardAvailable?: boolean;
}) {
  const offers = useRowOffers(transport);
  const heading = useRef<HTMLHeadingElement>(null);
  const root = useRef<HTMLElement>(null);
  const mounted = useMounted();
  const { page } = frame;
  const rows = useRowState({ items: page.items, root, mounted });
  const menu = useRowMenu(root);
  const { query, setQuery, clearSearch } = useAgendaQuery(controls);
  // The `doneToday` fold last in the Agenda is folded until opened, as the Work room's `completed` fold.
  const [doneOpen, setDoneOpen] = useState(false);

  useEffect(() => {
    if (moves > 0) heading.current?.focus({ preventScroll: true });
  }, [moves]);

  const session = useAgendaSession({
    transport,
    frame,
    onChange,
    onRead,
    rows,
    mounted,
    stale,
    refreshTick: controls?.refreshTick,
    refreshKey,
  });
  const keepFocus = useKeepFocus(root);
  const writes = useRowWrites({
    transport,
    labels: t,
    now,
    session,
    rows,
    mounted,
    keepFocus,
    closeMenu: menu.closeMenu,
  });
  const bulk = useAgendaBulk({
    transport,
    filters: frame.filters,
    now,
    session,
    rows,
    mounted,
  });

  const disabled = session.busy !== "idle";
  // The tags in use on Tasks and Projects, for the filter row and the labels of the rows' tags.
  const tagVocabulary = useWorkTags(transport, ["task", "project"]);
  const chosenTags = filterTags(frame.filters);
  const waitingView = isWaitingFilter(frame.filters);
  const wt = waitingLabelsFor(t.dateLocale);
  const layout = useAgendaLayout({
    items: page.items,
    query,
    now,
    locale: t.dateLocale,
    waitingView,
    rows,
    rowQueue: session.rowQueue,
  });
  const { visible } = layout;
  const { selected } = useAgendaSelection({
    stepping: layout.stepping,
    root,
    enabled: shortcuts && !waitingView,
    current: rows.current,
    statusOffered: offers.statusOffered,
    write: writes.write,
    toggleDone: writes.toggleDone,
  });

  // The phone's offline copy and outbox (the mobile app only): when this page was read, and the ticks still to send.
  const { copiedAt, sending } = useOfflineAgenda(transport, page);
  const doneTasks = new Set(sending);
  for (const record of page.items) {
    const item = rows.current(record);
    if (item.kind === "task" && item.status === "completed")
      doneTasks.add(item.id.toLowerCase());
  }

  const notice: NoticeSource = {
    notice: session.notice,
    onReload: session.reread,
    onRetry: session.retry,
  };
  // The Overdue group shows the notice of a failed `moveAllOverdue`; without the group (its Ångra failed) it stands above the groups.
  const overdueShown =
    !waitingView && layout.sections.some((s) => s.group === "overdue");

  const ctx: AgendaRowContext = {
    labels: t,
    now,
    disabled,
    boardAvailable,
    selected,
    rows,
    rowQueue: session.rowQueue,
    menu,
    offers,
    writes,
    onOpen,
    notice,
    sending,
    doneTasks,
  };

  return (
    <KnownTags.Provider value={tagVocabulary.suggestions}>
      <article ref={root} className="work-agenda">
        <h2
          ref={heading}
          tabIndex={-1}
          className={headingHidden ? "work-visually-hidden" : undefined}
        >
          {t.agenda}
        </h2>
        {!controls && (
          <AgendaFilterRow
            labels={t}
            query={query}
            onQuery={setQuery}
            disabled={disabled}
            onRefresh={session.reread}
          />
        )}
        {/* The tag filter reads the agenda again with every chosen tag; the search above narrows what it read. */}
        <WorkTagFilter
          options={tagVocabulary.options}
          selected={chosenTags}
          settled={!disabled}
          onChange={(tags) =>
            session.refilter(withFilterTags(frame.filters, tags))
          }
          locale={t.dateLocale}
        />
        {/* The offline copy: the agenda as it was last read, said with when (the phone had no answer). */}
        {copiedAt !== null && (
          <p role="status" className="work-agenda-offline">
            {t.offlineCopy(copyTime(copiedAt, t.dateLocale))}
          </p>
        )}
        <AgendaNotice spot="top" source={notice} labels={t} />
        {disabled && (
          <p role="status" className="work-agenda-loading">
            {t.loading}
          </p>
        )}
        {/* The waiting mark of a row sits inside its aria-busy row, where a screen reader may hold the news back: the
          announcement lives here, in a region that is always mounted and never busy. */}
        <p role="status" className="work-visually-hidden">
          {visible
            .filter((record) =>
              session.rowQueue.queued(cardKey(rows.current(record))),
            )
            .map((record) => `${rows.current(record).title}: ${t.queued}`)
            .join("; ")}
        </p>
        {!page.items.length &&
          (waitingView ? (
            <p>{wt.empty}</p>
          ) : chosenTags.length > 0 ? (
            // Nothing carries every chosen tag: the filter row above has Rensa.
            <p>{t.agendaNoMatches}</p>
          ) : (
            <WorkEmpty
              title={t.agendaEmpty}
              hint={t.agendaEmptyHint}
              labels={t}
            />
          ))}
        {page.items.length > 0 && !visible.length && (
          <SearchNoMatch query={query} labels={t} onClear={clearSearch} />
        )}
        {waitingView && visible.length > 0 && (
          <WaitingSection
            ctx={ctx}
            labels={wt}
            records={visible}
            reminded={bulk.reminded}
            onRemind={bulk.remind}
          />
        )}
        {/* The `undo` of `moveAllDone`: the moved Tasks have left the group, so it stands above the groups. */}
        {!overdueShown && (
          <AgendaNotice spot="moveAll" source={notice} labels={t} />
        )}
        {!waitingView && bulk.moveUndo && (
          <MoveAllUndo
            labels={t}
            count={bulk.moveUndo.count}
            disabled={disabled}
            onUndo={bulk.undoMoveAll}
            onExpire={bulk.dismissMoveUndo}
          />
        )}
        {/* The Undo (or "Moving…", or "Waiting…") takes the meta line of the row it belongs to, so it covers no row and moves none.
          A write with no row of its own (`moveAllOverdue`) shows none; the loading status speaks for it, and the
          Undo of the move is above. */}
        {(waitingView ? [] : layout.sections).map((section) => (
          <AgendaSection
            key={section.group}
            ctx={ctx}
            section={section}
            rows={layout.shown(section)}
            // Not while a search narrows the list: `moveAllOverdue` would read as moving the hits.
            moveAllOffered={offers.rescheduleOffered && query.trim() === ""}
            onMoveAll={bulk.moveAllOverdue}
          />
        ))}
        {layout.doneToday.length > 0 && (
          <DoneTodaySection
            ctx={ctx}
            done={layout.doneToday}
            open={doneOpen}
            onToggle={() => setDoneOpen((open) => !open)}
          />
        )}
        {page.next_cursor && (
          <button type="button" disabled={disabled} onClick={session.loadMore}>
            {t.more}
          </button>
        )}
        <AgendaNotice spot="more" source={notice} labels={t} />
        {!waitingView && visible.some(offers.rowHasChoices) && (
          <RowMenuTip labels={t} />
        )}
      </article>
    </KnownTags.Provider>
  );
}

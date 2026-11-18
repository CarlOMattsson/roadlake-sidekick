import { useEffect, useRef, useState } from "react";
import { WorkEmpty } from "../shared/work-empty";
import { workStatusLabel, type WorkLabels } from "../shared/labels";
import { cardKey, type BoardSegment } from "../shared/work-items";
import { RowMenuTip } from "../shared/row-menu";
import { UndoMeta } from "../agenda/agenda-undo";
import { SearchNoMatch } from "../agenda/agenda";
import {
  failureNotice,
  NoticeView,
  type BoardAction,
  type BoardNotice,
} from "./board-notice";
import { columnMore, type BoardUndo } from "./board-columns";
import { useDoneHandoff } from "../shared/done-handoff";
import { boardLabelsFor } from "./board-labels";
import {
  useBoardLayout,
  useColumnsOverflow,
  type BoardLayout,
} from "./board-layout";
import { RefreshButton } from "./board-sections";
import { ColumnsLayout, SingleLayout } from "./parts/board-layouts";
import { useBoardCore } from "./parts/use-board-core";
import { useBoardDrag } from "./parts/use-board-drag";
import { useBoardFocus } from "./parts/use-board-focus";
import { useBoardSearch } from "./parts/use-board-search";
import { useBoardSections, type Preview } from "./parts/use-board-sections";
import { useBoardWrites } from "./parts/use-board-writes";
import {
  filterTags,
  KnownTags,
  useWorkTags,
  withFilterTags,
  WorkTagFilter,
} from "../shared/work-tags";
import {
  isTaskStatus,
  type WorkBoardFrame,
  type WorkFrame,
  type WorkItemRecord,
  type WorkTransport,
} from "../transport/transport";

// The board's notice and layout types live in their own modules; the agenda and the shell import them from here.
export { failureNotice, NoticeView };
export type { BoardAction, BoardNotice, BoardLayout };
export { SINGLE_LAYOUT_MAX_WIDTH } from "./board-layout";
// The tab row's search, provided by the fullscreen shell around the Status tab.
export { BoardClearSearch, BoardQuery } from "./parts/board-search";

/**
 * The Work board: one column per Task status, each card a record. A Task moves between statuses
 * through its quick choices (a long press or Shift+F10), by dragging its handle, or with the Left and Right
 * arrow keys on the handle (Shift+Left and Shift+Right move the card the same way). A move is written
 * with the card's version and a key; a drag or arrow move shows the card in its target column while
 * the write is pending. The board is read again
 * after the server answers; a refused write puts the card back and keeps the conflict banner. A drop
 * inside one column sets that column's order, written only when the whole column is on the board.
 */
export function BoardView({
  frame,
  onChange,
  transport,
  labels: t,
  moves,
  onOpen,
  now = new Date(),
  headingHidden = false,
  stale = false,
  onRead,
  layout: layoutProp = "auto",
  refreshKey,
}: {
  frame: WorkBoardFrame;
  onChange: (next: WorkBoardFrame) => void;
  transport: WorkTransport;
  labels: WorkLabels;
  moves: number;
  onOpen: (frame: WorkFrame) => void;
  /** The instant card due dates are measured from; defaults to the time of this render. */
  now?: Date;
  /**
   * Hides the heading visually, kept for focus and assistive technology. The fullscreen shell passes
   * true: its tab strip already names the board.
   */
  headingHidden?: boolean;
  /** A Task was saved since this board was read: it reads again once shown. */
  stale?: boolean;
  /** Called after a successful read, so the caller clears its `stale` mark. */
  onRead?: () => void;
  /**
   * "columns" shows every status side by side; "single" lists them as sections, Klar folded (a phone). "auto" (the default) measures the board's own width when ResizeObserver
   * reports it: under 640 px it is "single". Until it reports, and in jsdom, "auto" is "columns".
   */
  layout?: "auto" | BoardLayout;
  /** Reads again in place when it changes; the value at mount is not a request. The chosen column stays. */
  refreshKey?: number;
}) {
  const [undos, setUndos] = useState<Record<string, BoardUndo>>({});
  const [preview, setPreview] = useState<Preview>();
  const [doneOpen, setDoneOpen] = useState(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const boardRoot = useRef<HTMLElement>(null);
  // The columns row, and whether columns lie beyond its right edge (the edge then fades, see work.css).
  const columnsRow = useRef<HTMLDivElement>(null);
  const columnsMore = useColumnsOverflow(columnsRow);
  const layout = useBoardLayout(layoutProp, boardRoot);
  const single = layout === "single";
  const core = useBoardCore({
    frame,
    onChange,
    transport,
    stale,
    onRead,
    refreshKey,
  });
  const { busy, notice, reload, loadMore, loadColumn } = core;
  const { query, clearSearch, searchText, needle } = useBoardSearch(core);
  const { page } = frame;
  const { anyCard, sections, columnSections, anyShown, waitingCards, queueOf } =
    useBoardSections({
      page,
      labels: t,
      single,
      needle,
      undos,
      preview,
      rowQueue: core.rowQueue,
    });
  const writes = useBoardWrites({
    core,
    frame,
    labels: t,
    single,
    shownOf: (key) =>
      sections.find(({ segment }) => segment.key === key)?.shown ?? [],
    undos,
    setUndos,
    setPreview,
  });
  const disabled = busy !== "idle";
  // The tags in use on Tasks and Projects, for the filter row and the labels of the cards' tags.
  const tagVocabulary = useWorkTags(transport, ["task", "project"]);
  const chosenTags = filterTags(frame.filters);
  /** Reads the board with every chosen tag; the frame takes them at once, so the chip shows pressed. */
  function chooseTags(tags: string[]) {
    core.commit({
      ...core.latest.current,
      filters: withFilterTags(core.latest.current.filters, tags),
    });
    reload();
  }
  const { drag, handleFor } = useBoardDrag({
    boardRoot,
    single,
    disabled,
    move: writes.move,
    reorder: writes.reorder,
    toggleDone: writes.toggleDone,
    taskCard: writes.taskCard,
  });
  useEffect(() => {
    if (moves > 0) heading.current?.focus({ preventScroll: true });
  }, [moves]);
  // A Task marked done in its own view comes back here: in its new place at once, with its Ångra where it was
  // (the single layout keeps the card in its section while the Ångra lasts, as after a move on the board).
  useDoneHandoff("board", ({ task, undo }) => {
    const offered = undo && isTaskStatus(undo.from) ? undo.from : undefined;
    if (undo && offered) {
      const index = sections
        .find(({ segment }) => segment.key === offered)
        ?.shown.findIndex((item) => item.id === task.id);
      setUndos((all) => ({
        ...all,
        [undo.key]: { ...undo, at: offered, index: Math.max(0, index ?? 0) },
      }));
    }
    core.placeTask(task, offered !== undefined);
  });
  useBoardFocus(core.focusWanted, boardRoot, heading, {
    page,
    preview,
    busy,
    undos,
  });

  /** The Undo of one card in place of its meta line, while it lasts. */
  function undoOf(item: WorkItemRecord) {
    const entry = undos[cardKey(item)];
    return (
      entry && (
        <UndoMeta
          text={entry.due ? entry.due.label : workStatusLabel(t, entry.to)}
          title={item.title}
          labels={t}
          disabled={disabled}
          onUndo={() => writes.undoMove(entry)}
          onExpire={() => writes.forget(entry.key)}
        />
      )
    );
  }
  const cardProps = {
    moreFor,
    labels: t,
    disabled,
    now,
    onOpen,
    onMove: writes.move,
    undoOf,
    queueOf,
  };
  // "No hit" is the truth when the whole board is loaded and was not narrowed by an earlier search, or when the server
  // has answered for the text typed (and nothing is being read); otherwise a page is still on its way.
  const searchSettled =
    (!page.next_cursor && !frame.search) ||
    (!disabled && searchText === (frame.search ?? ""));
  // In the fullscreen shell (the heading is hidden there), Uppdatera is an item of the tab row's "⋯" menu, which
  // reads the board again through refreshKey; the board then shows no Refresh of its own (designsystem §5).
  const refresh = headingHidden ? null : (
    <RefreshButton label={t.refresh} disabled={disabled} onClick={reload} />
  );
  const words = boardLabelsFor(t.dateLocale);
  /**
   * The "Visa fler" last in one column (or section): a Task status column reads its own next records, the Projects
   * column the board's next page (see columnMore). Null when the column is whole on the board.
   */
  function moreFor(segment: BoardSegment) {
    const how = columnMore(frame, segment.key);
    if (!how) return null;
    const status = isTaskStatus(segment.key) ? segment.key : undefined;
    return (
      <button
        type="button"
        className="sk-more work-column-more"
        disabled={disabled}
        aria-label={status ? words.showMoreIn(segment.label) : undefined}
        onClick={
          how === "status" && status ? () => loadColumn(status) : loadMore
        }
      >
        {status ? words.showMore : words.showMoreAll}
      </button>
    );
  }
  // One article for both layouts, so the measured root and the columns row survive a change of layout.
  return (
    <KnownTags.Provider value={tagVocabulary.suggestions}>
      <article ref={boardRoot} className="work-board" data-layout={layout}>
        <h2
          ref={heading}
          tabIndex={-1}
          className={headingHidden ? "work-visually-hidden" : undefined}
        >
          {t.board}
        </h2>
        {single || !refresh ? null : <p>{refresh}</p>}
        <WorkTagFilter
          options={tagVocabulary.options}
          selected={chosenTags}
          settled={!disabled}
          onChange={chooseTags}
          locale={t.dateLocale}
        />
        <NoticeView
          notice={notice}
          labels={t}
          onReload={reload}
          onRetry={writes.retry}
        />
        {/* Only a read holds the board: a card write adds no status line above the list, so the rows do not jump. */}
        {disabled && <p role="status">{t.loading}</p>}
        {/* The waiting mark of a card sits inside its aria-busy row, where a screen reader may hold the news back: the
          announcement lives here, in a region that is always mounted and never busy. */}
        <p role="status" className="work-visually-hidden">
          {waitingCards.map((item) => `${item.title}: ${t.queued}`).join("; ")}
        </p>
        {!anyCard && !needle && chosenTags.length === 0 ? (
          <WorkEmpty title={words.empty} hint={words.emptyHint} labels={t} />
        ) : !anyShown &&
          (needle ? searchSettled : single || chosenTags.length > 0) ? (
          needle ? (
            <SearchNoMatch query={query} labels={t} onClear={clearSearch} />
          ) : (
            <p>{t.agendaNoMatches}</p>
          )
        ) : null}
        <div
          ref={columnsRow}
          className="work-columns"
          lang={t.dateLocale.split("-")[0]}
          data-more={columnsMore && !single ? "end" : undefined}
        >
          {single ? (
            <SingleLayout
              {...cardProps}
              sections={sections}
              needle={needle}
              undos={undos}
              doneOpen={doneOpen}
              onToggleDone={() => setDoneOpen((open) => !open)}
              completeColumn={writes.completeColumn}
              toggleDone={writes.toggleDone}
              stepWithin={writes.stepWithin}
            />
          ) : (
            <ColumnsLayout
              {...cardProps}
              columns={columnSections}
              drag={drag}
              handleFor={handleFor}
            />
          )}
        </div>
        {single && refresh ? (
          <div className="work-board-foot">{refresh}</div>
        ) : null}
        {single && anyShown && <RowMenuTip labels={t} />}
      </article>
    </KnownTags.Provider>
  );
}

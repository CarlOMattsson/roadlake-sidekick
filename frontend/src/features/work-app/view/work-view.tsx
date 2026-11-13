import { useEffect, useEffectEvent } from "react";
import { roomEnabled } from "../../mcp-apps/enabled-rooms";
import { BackHeader } from "../../mcp-apps/ui/back-header";
import { AgendaView } from "../agenda/agenda";
import { BoardView } from "../board/board";
import { BoardSummary } from "../board/board-summary";
import { ContactCard } from "../contacts/contact-card";
import { HIERARCHY_MAX_ROWS, HierarchyView } from "../hierarchy/hierarchy-view";
import { ContactsView } from "../contacts/contacts-list";
import { AgendaSummary, ContactSummary } from "../inline/inline-summary";
import { cardLabelsEn } from "../shared/card-labels";
import { inlineSummaryLabelsEn } from "../inline/inline-summary-labels";
import { WorkCard } from "../inline/work-card";
import { parentLabel } from "./parts/frame-routing";
import type { BackTarget } from "./parts/frame-types";
import { ContactFrame } from "../contacts/contact-frame";
import {
  contactLinkCounts,
  projectInlineSummary,
  taskInlineSummary,
} from "../inline/inline-data";
import {
  ContactsRootSummary,
  InlineContactRoot,
  InlineRootSummary,
} from "../inline/inline-roots";
import { ProcessFrame } from "../hierarchy/process-frame";
import { ProjectFrame } from "../hierarchy/project-frame";
import { TaskFrame } from "../tasks/task-frame";
import { useFrameStack } from "./parts/use-frame-stack";
import type { WorkViewProps } from "./parts/work-view-props";
import "../shell/work.css";
import "../tasks/task-detail.css";

/** Both hosts use the same UI. The transport alone decides how data is read. */
export function WorkView({
  transport,
  initial,
  labels: t,
  cardLabels = cardLabelsEn,
  inlineLabels = inlineSummaryLabelsEn,
  fullscreen,
  opening = false,
  onModelContext,
  shortcuts = false,
  chrome = true,
  agendaControls,
  onStackDepth,
  onOpenJournalEntry,
  onOpenLink,
  onRoute,
  supportsTool,
  refreshKey,
  boardAvailable,
  hierarchyQuery,
  onListFilters,
}: WorkViewProps) {
  const {
    stack,
    top,
    session,
    moves,
    stale,
    setStale,
    editContactId,
    open,
    openContact,
    replaceFrame,
    back,
  } = useFrameStack({ initial, onStackDepth, onRoute });
  // The filters of the agenda or board at the bottom of the stack, told whenever they change (a tag chosen), so the
  // shell saves a view with the filters the list shows now.
  const root = stack[0];
  const listFilters =
    root?.kind === "agenda" || root?.kind === "board"
      ? root.filters
      : undefined;
  const filtersKey = listFilters ? JSON.stringify(listFilters) : undefined;
  const reportFilters = useEffectEvent(() => {
    if (listFilters) onListFilters?.(listFilters);
  });
  useEffect(() => {
    reportFilters();
  }, [filtersKey]);
  // Inline (fullscreen offered) and the Task or Project is the only frame: a summary, not the view.
  const summaryRoot = fullscreen !== undefined && stack.length === 1;
  // An inline Contact root is a card with no form; its visually hidden heading is the Contact label,
  // so screen readers announce the card, not the app name.
  const inlineContact =
    (top?.kind === "compact" || (top?.kind === "contact" && top.context)) &&
    summaryRoot;
  // A Contact on top names the view "Kontakt" (the header or the hidden heading), not the app name. A Task
  // or a Project names its own kind: in a framed room the hidden heading is all a screen reader hears of
  // the strip's app ("Arbete" while the strip says "Dagbok" or "Kontakter").
  const heading =
    top?.kind === "task"
      ? t.task
      : top?.kind === "project"
        ? t.project
        : top?.kind === "process"
          ? t.kindName.process
          : top?.kind === "contact" || top?.kind === "compact"
            ? t.contact
            : top?.kind === "contacts"
              ? t.contacts
              : t.title;
  // No "All contacts" link when the Contact list is one step back already (no second list is offered), or when
  // the contacts room is off on this instance.
  const contactsOpen =
    !roomEnabled("contacts") ||
    onRoute !== undefined ||
    stack.some((frame) => frame.kind === "contacts");
  const cards = cardLabels;
  // Inline, the view is the family's root card (sk-card--root) with the app name as its eyebrow. A summary
  // card is its own frame, and a Task, Project or Contact view has its own kind eyebrow, so those leave
  // the app name to assistive technology (visually hidden h1).
  const detailView =
    top?.kind === "task" ||
    top?.kind === "project" ||
    top?.kind === "process" ||
    top?.kind === "contact";
  const backTarget: BackTarget | undefined =
    stack.length > 1
      ? { label: parentLabel(stack.at(-2), t), onBack: back }
      : undefined;
  const ownBackRow = detailView;
  const showAppName =
    chrome &&
    !summaryRoot &&
    !detailView &&
    top?.kind !== "card" &&
    top?.kind !== "error";
  return (
    <section
      className={
        chrome ? "sidekick-work sk-card sk-card--root" : "sidekick-work"
      }
      aria-label={
        top?.kind === "contacts" && !summaryRoot ? t.contacts : t.title
      }
    >
      {showAppName ? (
        <header>
          <h1 className="sk-eyebrow">{heading}</h1>
        </header>
      ) : (
        <h1 className="work-visually-hidden">
          {inlineContact ? t.contact : heading}
        </h1>
      )}
      {/* A Task, Contact or Project draws the Back row itself, with its pen and ⋯ at the row's right. */}
      {stack.length > 1 && !ownBackRow && (
        <BackHeader label={parentLabel(stack.at(-2), t)} onBack={back} />
      )}
      {!top && <p>{t.empty}</p>}
      {top?.kind === "task" && fullscreen && summaryRoot && (
        <InlineRootSummary
          key={`${session}:${stack.length}:task-summary:${top.id}`}
          kind="task"
          id={top.id}
          initial={top.task ? taskInlineSummary(top.task) : undefined}
          transport={transport}
          labels={inlineLabels}
          onOpen={fullscreen}
          announce={onModelContext}
        />
      )}
      {top?.kind === "task" && !summaryRoot && (
        <TaskFrame
          key={`${session}:${stack.length}:task:${top.id}`}
          id={top.id}
          transport={transport}
          labels={t}
          moves={moves}
          onOpen={open}
          contactsOpen={contactsOpen}
          projectOpenable={supportsTool?.("get_project") !== false}
          refreshKey={refreshKey}
          onSaved={() => setStale(true)}
          back={backTarget}
        />
      )}
      {top?.kind === "contact" && top.context && fullscreen && summaryRoot && (
        // Inline: the result carried the context, so the compact card is drawn from it with no read.
        // The view with its editor and Archive appears in fullscreen, where it reads fresh data.
        <ContactSummary
          key={`${session}:${stack.length}:contact-context-summary:${top.id}`}
          kindLabel={t.contact}
          name={top.context.contact.display_name}
          email={top.context.contact.email}
          relationship={top.context.contact.relationship}
          organization={top.context.contact.organization}
          role={top.context.contact.role}
          counts={contactLinkCounts(top.context)}
          labels={inlineLabels}
          onOpen={fullscreen}
        />
      )}
      {top?.kind === "contact" &&
        !(top.context && fullscreen && summaryRoot) && (
          <ContactFrame
            key={`${session}:${stack.length}:contact:${top.id}`}
            id={top.id}
            transport={transport}
            labels={t}
            moves={moves}
            onOpen={open}
            contactsOpen={contactsOpen}
            refreshKey={refreshKey}
            startEditing={editContactId === top.id}
            onOpenJournalEntry={onOpenJournalEntry}
            onOpenLink={onOpenLink}
            back={backTarget}
          />
        )}
      {top?.kind === "compact" && fullscreen && summaryRoot && (
        <InlineContactRoot
          key={`${session}:${stack.length}:contact-summary:${top.contact.id}`}
          contact={top.contact}
          transport={transport}
          kindLabel={t.contact}
          labels={inlineLabels}
          onOpen={fullscreen}
        />
      )}
      {top?.kind === "compact" && !(fullscreen && summaryRoot) && (
        <ContactCard
          key={`${session}:${stack.length}:compact:${top.contact.id}`}
          contact={top.contact}
          transport={transport}
          labels={cards}
          showAddress={shortcuts}
          onOpen={() => openContact(top.contact.id, false)}
          onEdit={() => openContact(top.contact.id, true)}
        />
      )}
      {top?.kind === "card" && (
        <WorkCard
          state="ready"
          labels={cards}
          frame={top}
          onOpen={fullscreen}
          opening={opening}
          openingLabel={t.opening}
          // Fullscreen only: row titles open their Task or Project in this view's stack (back returns here).
          onOpenItem={shortcuts ? open : undefined}
          // Status segments only in fullscreen (shortcuts); the inline card is a compact list plus Open.
          writer={shortcuts ? transport : undefined}
          announce={onModelContext}
        />
      )}
      {top?.kind === "error" && (
        // The error frame holds no data and no tool name, so there is nothing to read again: no retry.
        <WorkCard
          state="error"
          labels={cards}
          appTitle={t.title}
          locale={t.dateLocale}
        />
      )}
      {top?.kind === "project" && fullscreen && summaryRoot && (
        <InlineRootSummary
          key={`${session}:${stack.length}:project-summary:${top.id}`}
          kind="project"
          id={top.id}
          initial={top.project ? projectInlineSummary(top.project) : undefined}
          transport={transport}
          labels={inlineLabels}
          onOpen={fullscreen}
        />
      )}
      {top?.kind === "project" && !summaryRoot && (
        <ProjectFrame
          key={`${session}:${stack.length}:project:${top.id}`}
          id={top.id}
          transport={transport}
          labels={t}
          moves={moves}
          onOpen={open}
          refreshKey={refreshKey}
          back={backTarget}
        />
      )}
      {top?.kind === "process" && (
        // A Process has no inline summary yet, so its page is drawn whole wherever it is the root.
        <ProcessFrame
          key={`${session}:${stack.length}:process:${top.id}`}
          id={top.id}
          transport={transport}
          labels={t}
          moves={moves}
          onOpen={open}
          refreshKey={refreshKey}
          back={backTarget}
        />
      )}
      {top?.kind === "board" && fullscreen && (
        // Inline: the host can open fullscreen, so the board is only summarised here.
        <BoardSummary
          key={`${session}:${stack.length}:board-summary`}
          page={top.page}
          labels={t}
          onOpen={fullscreen}
          onModelContext={onModelContext}
        />
      )}
      {top?.kind === "board" && !fullscreen && (
        <BoardView
          key={`${session}:${stack.length}:board`}
          frame={top}
          onChange={(next) => replaceFrame(top, next)}
          transport={transport}
          labels={t}
          moves={moves}
          onOpen={open}
          headingHidden={!chrome}
          stale={stale}
          onRead={() => setStale(false)}
          refreshKey={refreshKey}
        />
      )}
      {top?.kind === "contacts" && fullscreen && summaryRoot && (
        <ContactsRootSummary
          key={`${session}:${stack.length}:contacts-summary`}
          frame={top}
          transport={transport}
          labels={inlineLabels}
          onOpen={fullscreen}
        />
      )}
      {top?.kind === "contacts" && !summaryRoot && (
        <ContactsView
          key={`${session}:${stack.length}:contacts`}
          frame={top}
          onChange={replaceFrame}
          transport={transport}
          labels={t}
          moves={moves}
          onOpen={open}
          shortcuts={shortcuts}
          refreshKey={refreshKey}
          onRoute={onRoute}
        />
      )}
      {top?.kind === "agenda" && fullscreen && summaryRoot && (
        // Inline: the host can open fullscreen, so the agenda is only summarised here (rows open, nothing is written).
        <AgendaSummary
          key={`${session}:${stack.length}:agenda-summary`}
          page={top.page}
          filters={top.filters}
          labels={inlineLabels}
          onOpen={fullscreen}
          onOpenItem={(item) => {
            open(
              {
                kind: item.kind === "project" ? "project" : "task",
                id: item.id,
              },
              item.title,
            );
            fullscreen();
          }}
        />
      )}
      {top?.kind === "hierarchy" && (
        // The Projects list: a Project or Process opens as a page in this view's stack (or the shell's), Back returns.
        <HierarchyView
          key={`${session}:${stack.length}:hierarchy`}
          frame={top}
          transport={transport}
          onChange={(next) => replaceFrame(top, next)}
          stale={stale}
          onRead={() => setStale(false)}
          refreshKey={refreshKey}
          labels={t}
          shortcuts={shortcuts}
          headingHidden={!chrome}
          rowLimit={chrome ? HIERARCHY_MAX_ROWS : Infinity}
          query={hierarchyQuery}
          onOpen={open}
        />
      )}
      {top?.kind === "agenda" && !summaryRoot && (
        <AgendaView
          key={`${session}:${stack.length}:agenda`}
          frame={top}
          onChange={(next) => replaceFrame(top, next)}
          transport={transport}
          labels={t}
          moves={moves}
          onOpen={open}
          shortcuts={shortcuts}
          headingHidden={!chrome}
          stale={stale}
          onRead={() => setStale(false)}
          controls={agendaControls}
          refreshKey={refreshKey}
          boardAvailable={boardAvailable}
        />
      )}
    </section>
  );
}

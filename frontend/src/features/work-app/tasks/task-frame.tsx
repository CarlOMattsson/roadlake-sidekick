import { useCallback, useEffect, useId, useRef, useState } from "react";
import { relativeDue } from "../../mcp-apps/ui/due";
import { ErrorNotice } from "../../mcp-apps/ui/states";
import { ContactMenu } from "../contacts/contact-edit";
import { MoreIcon, TaskProps } from "./task-detail-controls";
import { useLinkUndo } from "./task-contacts";
import { TaskEditor } from "./task-edit";
import { TaskPlace } from "./task-place";
import { TaskReferences } from "./task-references";
import { TaskSteps } from "./task-steps";
import { TaskTrashed } from "./task-trashed";
import {
  isRecurringCycle,
  recurringDoneText,
  type RecurringCycle,
} from "../agenda/parts/agenda-helpers";
import { TaskCycleLine } from "./task-cycle";
import type {
  TaskStatusValue,
  WorkContact,
  WorkTask,
  WorkTaskChanges,
} from "../transport/transport";
import { DetailBar } from "../view/parts/detail-bar";
import { detailDate } from "../view/parts/detail-date";
import type { FrameProps } from "../view/parts/frame-types";
import { TaskContactsSection } from "./task-contacts-section";
import {
  useDetailFrame,
  useFrameRead,
  usePagedSection,
} from "../view/parts/use-detail-frame";
import { useTaskOffers } from "./use-task-offers";
import { useCutText } from "./use-cut-text";
import { WriteStatus } from "../view/parts/write-status";
import { TagField } from "../../mcp-apps/ui/tags";
import { useWorkTags } from "../shared/work-tags";

export function TaskFrame({
  id,
  transport,
  labels: t,
  moves,
  onOpen,
  contactsOpen,
  projectOpenable = true,
  refreshKey = 0,
  onSaved,
  back,
}: FrameProps & {
  id: string;
  onSaved: () => void;
  /** False when the host cannot answer get_project: the Project is then not offered as a link. */
  projectOpenable?: boolean;
}) {
  const frame = useDetailFrame({ moves });
  const { phase, write, editing, heading, banner } = frame;
  const [task, setTask] = useState<WorkTask>();
  // The ⋯ panel under the title; its one entry is "Redigera" (design system §3, Tillbakarad).
  const [menuOpen, setMenuOpen] = useState(false);
  const menuId = useId();
  const moreButton = useRef<HTMLButtonElement>(null);
  // The description shows two lines until "Show more" opens it; the view starts with it closed.
  const [descriptionOpen, setDescriptionOpen] = useState(false);
  const { ref: descriptionRef, cut: descriptionCut } =
    useCutText<HTMLParagraphElement>(task?.description);
  const contactsHeading = useRef<HTMLHeadingElement>(null);
  // Set when a contact link changed: the list is read again and focus returns to its heading.
  const contactsRefocus = useRef(false);
  const {
    offers,
    dueOffered,
    statusOffered,
    doneShown,
    editOffered,
    tagsOffered,
    trashOffered,
    contactsOn,
    unlinkOffered,
  } = useTaskOffers(transport, task);
  // "Markera klar" recorded a cycle of a recurring Task: the line under the button and the due date its Ångra puts back.
  const [cycle, setCycle] = useState<RecurringCycle>();
  const endCycle = useCallback(() => setCycle(undefined), []);
  // Set once "Ta bort uppgift" has moved the Task to the trash: the trash record's version, which Ångra needs.
  const [trashed, setTrashed] = useState<{ version: number }>();
  // Runs the last failed trash, Ångra or tag change again; the same action keeps its key, so the server replays it.
  const retryWrite = useRef<(() => void) | undefined>(undefined);
  // Which of them the failure line names.
  const [writeWhat, setWriteWhat] = useState<"trash" | "tags">("trash");
  const tags = useWorkTags(transport, "task");
  const menuOffered = editOffered || trashOffered;
  useFrameRead(
    frame,
    useCallback(() => transport.getTask(id), [transport, id]),
    (result) => setTask(result.task),
    refreshKey,
  );
  // The Contacts section loads and fails on its own; the Task itself stays visible.
  const contacts = usePagedSection<WorkContact>({
    list: useCallback(
      (...after: [] | [string]) => transport.listTaskContacts(id, ...after),
      [transport, id],
    ),
    enabled: contactsOn,
    refreshKey,
  });
  // "Ta bort koppling" in the Contact row's own menu: the row stays with its Ångra until the list is read again.
  const unlinks = useLinkUndo((contactId, link, key) =>
    link
      ? transport.linkContactToTask(id, contactId, key)
      : transport.unlinkContactFromTask(id, contactId, key),
  );
  // The detail's meta line under the title: "5 dagar försenad", only while the open Task is late.
  const late =
    task?.due_at && task.status !== "completed"
      ? relativeDue(
          task.due_at,
          new Date(),
          t.dateLocale.startsWith("sv") ? "sv" : "en",
        )
      : undefined;
  useEffect(() => {
    if (contacts.phase === "ready" && contactsRefocus.current) {
      contactsRefocus.current = false;
      contactsHeading.current?.focus();
    }
  }, [contacts.phase]);
  /** Reads the contact list again after a link or unlink; the list is replaced, not appended. */
  function reloadContacts() {
    contactsRefocus.current = true;
    contacts.retry();
  }
  function startEdit() {
    setMenuOpen(false);
    frame.setWrite({ kind: "idle" });
    frame.setEditing(true);
  }
  /**
   * Writes only the changed fields against the version the view holds; the key follows the action. Every write ends
   * the line of a recorded cycle; `then` sees the reply once it is shown.
   */
  function saveTask(changes: WorkTaskChanges, then?: (next: WorkTask) => void) {
    if (!task || frame.writing.current) return;
    if (Object.keys(changes).length === 0) {
      frame.stopEdit();
      return;
    }
    setCycle(undefined);
    frame.sendWrite(
      JSON.stringify([task.id, task.version, changes]),
      "save",
      (key) => transport.updateTask(task.id, task.version, changes, key),
      (result) => {
        setTask(result.task);
        then?.(result.task);
        frame.setEditing(false);
        onSaved();
        heading.current?.focus();
      },
    );
  }
  /**
   * Writes the Task's whole tag set (update_task changes.tags) in place: the focus stays in the tag field, and `done`
   * runs once it is stored. A failure keeps the typed tag and offers Försök igen.
   */
  function setTags(next: string[], done: () => void) {
    if (!task || frame.writing.current) return;
    retryWrite.current = () => setTags(next, done);
    setWriteWhat("tags");
    setCycle(undefined);
    frame.sendWrite(
      JSON.stringify(["tags", task.id, task.version, next]),
      "write",
      (key) => transport.updateTask(task.id, task.version, { tags: next }, key),
      (result) => {
        retryWrite.current = undefined;
        setTask(result.task);
        onSaved();
        tags.refresh();
        done();
      },
    );
  }
  /** Moves the Task to the trash at the version the view holds; no question first, since Ångra undoes it. */
  function trashTask() {
    if (!task || frame.writing.current) return;
    setMenuOpen(false);
    retryWrite.current = trashTask;
    setWriteWhat("trash");
    frame.sendWrite(
      JSON.stringify(["trash", task.id, task.version]),
      "write",
      (key) => transport.trashTask(task.id, task.version, key),
      (result) => {
        retryWrite.current = undefined;
        setTrashed({ version: result.version });
        onSaved();
        heading.current?.focus();
      },
    );
  }
  /** Takes the Task out of the trash and reads it again, so the view holds the version the restore left. */
  function restoreTask() {
    if (!trashed || frame.writing.current) return;
    retryWrite.current = restoreTask;
    setWriteWhat("trash");
    frame.sendWrite(
      JSON.stringify(["restore", id, trashed.version]),
      "write",
      (key) =>
        transport
          .restoreTask(id, trashed.version, key)
          .then(() => transport.getTask(id)),
      (result) => {
        retryWrite.current = undefined;
        setTask(result.task);
        setTrashed(undefined);
        onSaved();
        heading.current?.focus();
      },
    );
  }
  /** Fetches the latest Task; the open editor keeps the values the user typed. */
  function reloadTask() {
    frame.reload(
      () => transport.getTask(id),
      (result) => setTask(result.task),
    );
  }
  /** A quick status choice writes through saveTask, the same path as Spara. Off while the editor is open. */
  function chooseStatus(status: TaskStatusValue) {
    if (!task || task.status === status) return;
    // Done on a recurring Task: the reply is the Task open again with its next date (see isRecurringCycle).
    const before = task.due_at ?? null;
    const lastCompleted = task.last_completed_at ?? null;
    saveTask({ status }, (next) => {
      if (status === "completed" && isRecurringCycle(next, before))
        setCycle({ from: before, lastCompleted });
    });
  }
  // A deleted Task shows only its title, the line that it is in the trash and Ångra.
  if (trashed && task)
    return (
      <article className="work-task">
        <DetailBar back={back} kicker={t.task} />
        <h2 ref={heading} tabIndex={-1} className="work-detail-title">
          {task.title}
        </h2>
        <TaskTrashed
          labels={t}
          busy={write.kind === "busy"}
          failed={
            write.kind !== "idle" &&
            write.kind !== "busy" &&
            write.kind !== "saved"
          }
          onRestore={restoreTask}
        />
      </article>
    );
  return (
    <article className="work-task">
      {/* The Back row carries only ⋯, whose first entries are "Redigera" and "Ta bort uppgift"; a tap on the title edits too (§3). */}
      <DetailBar
        back={back}
        kicker={phase !== "gone" ? t.task : undefined}
        actions={
          phase === "ready" && task && menuOffered ? (
            <button
              ref={moreButton}
              type="button"
              className="sk-iconbtn work-detail-action"
              aria-label={t.moreActions}
              aria-expanded={menuOpen}
              aria-controls={menuOpen ? menuId : undefined}
              disabled={write.kind === "busy" || editing}
              onClick={() => setMenuOpen(!menuOpen)}
            >
              <MoreIcon />
            </button>
          ) : undefined
        }
      />
      {/* eslint-disable-next-line jsx-a11y/click-events-have-key-events -- a pointer shortcut for editing; the keyboard route to the same action is the Edit item in the header menu. */}
      <h2
        ref={heading}
        tabIndex={-1}
        className="work-detail-title"
        onClick={
          phase === "ready" &&
          task &&
          editOffered &&
          !editing &&
          write.kind !== "busy"
            ? startEdit
            : undefined
        }
      >
        {phase === "ready" && task ? task.title : t.task}
      </h2>
      {/* The Task's one meta line (§4 Detaljvy): "5 dagar försenad", under the title, only while the Task is late;
          its place stands as a chip in the control rows below. */}
      {late?.tone === "overdue" && (
        <p className="work-task-meta">
          <span className="work-task-late">{late.text}</span>
        </p>
      )}
      {phase === "ready" && task && menuOffered && menuOpen && (
        <ContactMenu
          id={menuId}
          busy={write.kind === "busy" || editing || unlinks.busy}
          edit={
            editOffered ? { label: t.edit, onChoose: startEdit } : undefined
          }
          remove={
            trashOffered
              ? { label: t.deleteTask, onChoose: trashTask }
              : undefined
          }
          onClose={() => {
            setMenuOpen(false);
            moreButton.current?.focus();
          }}
          labels={t}
        />
      )}
      {/* The date and status chips; both write through saveTask (update_task). */}
      {phase === "ready" &&
        task &&
        (dueOffered || statusOffered || doneShown) && (
          <TaskProps
            hasDue={Boolean(task.due_at)}
            busy={write.kind === "busy" || editing}
            status={task.status}
            labels={t}
            onDue={
              dueOffered ? (dueAt) => saveTask({ due_at: dueAt }) : undefined
            }
            onStatus={statusOffered ? chooseStatus : undefined}
            sentence={task.due_at ? detailDate(task.due_at, t) : undefined}
            done={
              doneShown && (
                // The screen's one primary: compact ink, last in the control row beside the
                // values it belongs with. A done Task shows "Återöppna" in the same place as a secondary, which sets it
                // back to "Att göra". Both go through chooseStatus.
                <button
                  type="button"
                  className={
                    task.status !== "completed"
                      ? "sk-btn--primary sk-btn--compact work-task-done"
                      : "sk-btn--secondary sk-btn--compact work-task-done"
                  }
                  disabled={write.kind === "busy" || editing}
                  onClick={() =>
                    chooseStatus(
                      task.status !== "completed" ? "completed" : "todo",
                    )
                  }
                >
                  {task.status !== "completed" ? t.markDone : t.reopenTask}
                </button>
              )
            }
          >
            {/* The chip carries only the value, "fre 30 okt"; how late it is stands on the line above. */}
            {task.due_at ? (
              <time dateTime={task.due_at}>{detailDate(task.due_at, t)}</time>
            ) : null}
          </TaskProps>
        )}
      {phase === "ready" && task && cycle && (
        <TaskCycleLine
          text={recurringDoneText(t, task.due_at, new Date())}
          labels={t}
          disabled={write.kind === "busy" || editing}
          onUndo={
            dueOffered
              ? () =>
                  saveTask({
                    due_at: cycle.from,
                    ...(cycle.lastCompleted !== undefined
                      ? { last_completed_at: cycle.lastCompleted }
                      : {}),
                  })
              : undefined
          }
          onExpire={endCycle}
        />
      )}
      {/* Where the Task belongs and how it repeats; a place choice is one update_task through saveTask. */}
      {phase === "ready" && task && (
        <TaskPlace
          task={task}
          transport={transport}
          labels={t}
          busy={write.kind === "busy" || editing}
          projectOpenable={projectOpenable}
          onChoose={saveTask}
          onOpen={onOpen}
        />
      )}
      {/* The tags under where the Task belongs, as on a Contact: the pills and one quiet button that edits them. */}
      {phase === "ready" && task && (
        <TagField
          tags={task.tags ?? []}
          suggestions={tags.suggestions}
          editable={tagsOffered}
          busy={write.kind === "busy" || editing}
          name={task.title}
          onChange={setTags}
          locale={t.dateLocale}
        />
      )}
      {phase === "loading" && <p role="status">{t.loading}</p>}
      {phase === "error" && (
        <section className="sk-card">
          <p className="sk-eyebrow">{t.title}</p>
          <ErrorNotice
            locale={t.dateLocale}
            cause={frame.readError}
            onRetry={frame.retry}
          />
        </section>
      )}
      {phase === "gone" && <p role="status">{t.goneTask}</p>}
      {phase === "ready" && task && (
        <>
          {task.description && (
            <>
              <p
                ref={descriptionRef}
                className={
                  descriptionOpen
                    ? "work-description"
                    : "work-description work-description-clamped"
                }
              >
                {task.description}
              </p>
              {/* Shown when the two drawn lines cut the text (measured; before that, from about two lines of text on),
                  and while it is open, so it can be closed again. */}
              {(descriptionOpen ||
                (descriptionCut ??
                  (task.description.length > 60 ||
                    task.description.split("\n").length > 2))) && (
                // A tertiary text button right after the text it opens, "Visa mer". No ›: › says
                // that a row opens a view (DR §4 "Klar"); this one opens the text in place.
                <button
                  type="button"
                  className="sk-btn--quiet sk-btn--compact work-more-link"
                  onClick={() => setDescriptionOpen((open) => !open)}
                >
                  {descriptionOpen ? t.descriptionLess : t.descriptionMore}
                </button>
              )}
            </>
          )}
          <WriteStatus
            write={write}
            conflict={t.conflict}
            onReload={reloadTask}
            banner={banner}
            labels={t}
          />
          {write.kind === "failed" && write.action === "write" && (
            <p role="alert">
              {writeWhat === "tags" ? t.saveFailed : t.taskTrashFailed}{" "}
              <button type="button" onClick={() => retryWrite.current?.()}>
                {t.retry}
              </button>
            </p>
          )}
          {editing && (
            <TaskEditor
              task={task}
              busy={write.kind === "busy"}
              saveFailed={write.kind === "failed" && write.action === "save"}
              onSave={saveTask}
              onCancel={frame.stopEdit}
              labels={t}
            />
          )}
          <TaskSteps taskId={task.id} transport={transport} labels={t} />
          <TaskReferences taskId={task.id} transport={transport} labels={t} />
          {contactsOn && (
            <TaskContactsSection
              taskId={task.id}
              transport={transport}
              labels={t}
              contacts={contacts}
              unlinks={unlinks}
              unlinkOffered={unlinkOffered}
              heading={contactsHeading}
              contactsOpen={contactsOpen}
              linkOffered={offers("link_contact_to_task")}
              createOffered={offers("create_contact")}
              onOpen={onOpen}
              onReloadContacts={reloadContacts}
            />
          )}
        </>
      )}
    </article>
  );
}

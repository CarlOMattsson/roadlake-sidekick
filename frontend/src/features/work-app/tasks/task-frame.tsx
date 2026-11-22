import { useCallback, useEffect, useId, useRef, useState } from "react";
import { relativeDue } from "../../mcp-apps/ui/due";
import { ReceiptBar, useReceipt } from "../../mcp-apps/ui/receipt";
import { ErrorNotice } from "../../mcp-apps/ui/states";
import { inlineSummaryLabelsFor } from "../inline/inline-summary-labels";
import { DetailMenu } from "../../mcp-apps/ui/detail-menu";
import { menuButtonKeys } from "../../mcp-apps/ui/menu";
import { MoreIcon, TaskProps } from "./task-detail-controls";
import { useLinkUndo } from "./task-contacts";
import { TaskEditor } from "./task-edit";
import { TaskPlace } from "./task-place";
import { TaskWaiting } from "./task-waiting";
import { TaskReferences } from "./task-references";
import { TaskSteps } from "./task-steps";
import { TaskTrashed } from "./task-trashed";
import {
  doneHandoff,
  TaskDoneControl,
  useDoneForm,
  useDoneReceipt,
} from "./task-cycle";
import type { DoneHandoff } from "../shared/done-handoff";
import type { WorkContact, WorkTask } from "../transport/transport";
import { DetailBar } from "../view/parts/detail-bar";
import { DetailTitle } from "../view/parts/detail-title";
import { detailDate } from "../view/parts/detail-date";
import type { FrameProps } from "../view/parts/frame-types";
import { TaskContactsSection } from "./task-contacts-section";
import {
  useDetailFrame,
  useFrameRead,
  usePagedSection,
} from "../view/parts/use-detail-frame";
import { useFocusRetry } from "./use-focus-retry";
import { useTaskOffers } from "./use-task-offers";
import { useCutText } from "./use-cut-text";
import { useTaskWrites } from "./use-task-writes";
import { WriteStatus } from "../view/parts/write-status";
import { TagField } from "../../mcp-apps/ui/tags";
import { useWorkTags } from "../shared/work-tags";
import { useQueuedRecords } from "../shared/use-queued-records";
import { WaitingLine } from "../shared/waiting-line";
import { aiLabelsFor } from "../ai/ai-labels";
import { AiPlanCard } from "../ai/ai-plan-card";
import { AiStepRun } from "../ai/ai-step-run";
import { AwaitingApproval } from "../ai/awaiting-approval";
import { useAiPlan } from "../ai/use-ai-plan";

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
  onDone,
}: FrameProps & {
  id: string;
  onSaved: () => void;
  /** False when the host cannot answer get_project: the Project is then not offered as a link. */
  projectOpenable?: boolean;
  /**
   * Given where the view goes back to the list it was opened from: a `markDone` that succeeded leaves the view with
   * what the list needs to offer its Ångra, instead of showing the Ångra here.
   */
  onDone?: (done: DoneHandoff) => void;
}) {
  // A write refused because the Task changed meanwhile reads it again, and the view shows what stands now.
  const frame = useDetailFrame({ moves, onConflict: () => reloadTask() });
  const { phase, write, editing, heading, banner } = frame;
  const [task, setTask] = useState<WorkTask>();
  // Counts the writes that changed the Task's Steps (completing it completes them); the Steps are read again for each.
  const [stepWrites, setStepWrites] = useState(0);
  // The ⋯ panel under the title; its one entry is `edit` (design system §3, Tillbakarad).
  const [menuOpen, setMenuOpen] = useState(false);
  const menuId = useId();
  const moreButton = useRef<HTMLButtonElement>(null);
  // The description shows two lines until "Show more" opens it; the view starts with it closed.
  const [descriptionOpen, setDescriptionOpen] = useState(false);
  const { ref: descriptionRef, cut: descriptionCut } =
    useCutText<HTMLParagraphElement>(task?.description);
  const doneForm = useDoneForm();
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
    aiMarkOffered,
    aiApproveOffered,
    contactsOn,
    unlinkOffered,
  } = useTaskOffers(transport, task);
  const ai = useAiPlan(transport, task);
  const aiWords = aiLabelsFor(t.dateLocale);
  const tags = useWorkTags(transport, "task");
  const waiting = useQueuedRecords(transport, task).has(id.toLowerCase());
  const menuOffered = editOffered || trashOffered || aiMarkOffered;
  // Every stored change is confirmed in the bar at the view's foot; the controls keep their place (designsystem §0.6).
  const bar = useReceipt(id);
  // After a `markDone` or its Ångra, focus returns to the done control once it is drawn with its new state.
  const doneButton = useRef<HTMLButtonElement>(null);
  const refocusDone = useRef(false);
  const {
    receipt: doneReceipt,
    endReceipt,
    trashed,
    writeWhat,
    retryLast,
    saveTask,
    setTags,
    trashTask,
    restoreTask,
    undoDone,
    chooseStatus,
  } = useTaskWrites({
    frame,
    transport,
    labels: t,
    bar,
    id,
    task,
    setTask,
    refreshTags: tags.refresh,
    onStepsChanged: () => setStepWrites((count) => count + 1),
    onSaved,
    onTrashStart: () => setMenuOpen(false),
    onDone: onDone && ((done) => onDone(doneHandoff(done, offers, t))),
    onDoneWritten: () => {
      refocusDone.current = true;
    },
  });
  useDoneReceipt({
    done: doneReceipt,
    task,
    offers,
    labels: t,
    bar,
    write: undoDone,
    onEnd: endReceipt,
  });
  useEffect(() => {
    if (!refocusDone.current || write.kind === "busy") return;
    refocusDone.current = false;
    const control = doneButton.current;
    (control && !control.disabled ? control : heading.current)?.focus();
  }, [write, task, heading]);
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
  // `removeLink` in the Contact row's own menu: the row stays with its Ångra until the list is read again.
  const unlinks = useLinkUndo((contactId, link, key) =>
    link
      ? transport.linkContactToTask(id, contactId, key)
      : transport.unlinkContactFromTask(id, contactId, key),
  );
  // The detail's meta line under the title: how late it is, only while the open Task is late.
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
  /** Fetches the latest Task; the open editor keeps the values the user typed. */
  function reloadTask() {
    frame.reload(
      () => transport.getTask(id),
      (result) => setTask(result.task),
    );
  }
  // A failed `markDone` puts focus on its `retry`, where the press was, not on the page.
  useFocusRetry(
    write.kind === "failed" &&
      write.action !== "reload" &&
      writeWhat === "done",
    heading,
  );
  // A deleted Task shows only its title, the line that it is in the trash and Ångra.
  if (trashed && task)
    return (
      <article className="work-task">
        <DetailBar back={back} kicker={t.task} />
        <DetailTitle heading={heading}>{task.title}</DetailTitle>
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
  // "Markera klar", or beside its list the ring before the title (useDoneForm).
  const doneControl = phase === "ready" && task && doneShown && (
    <TaskDoneControl
      task={task}
      labels={t}
      disabled={write.kind === "busy" || editing}
      onChoose={chooseStatus}
      buttonRef={doneButton}
      form={doneForm}
    />
  );
  return (
    <article className="work-task">
      {/* The Back row carries only ⋯, whose first entries are `edit` and `deleteTask`; a tap on the title edits too (§3). */}
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
              onKeyDown={menuButtonKeys(menuOpen, setMenuOpen)}
            >
              <MoreIcon />
            </button>
          ) : undefined
        }
      />
      <DetailTitle
        heading={heading}
        leading={doneForm === "ring" ? doneControl : undefined}
        onEdit={
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
      </DetailTitle>
      {/* The Task's one meta line (§4 Detaljvy): how late it is, under the title, only while the Task is late;
          its place stands as a chip in the control rows below. */}
      {late?.tone === "overdue" && (
        <p className="work-task-meta">
          <span className="work-task-late">{late.text}</span>
        </p>
      )}
      {/* A Task made or edited without a network waits in the phone's outbox: said under the title until it is sent. */}
      {phase === "ready" && task && waiting && (
        <WaitingLine text={t.queued} className="work-task-meta" />
      )}
      {phase === "ready" && task && menuOffered && menuOpen && (
        <DetailMenu
          id={menuId}
          anchor={moreButton}
          busy={write.kind === "busy" || editing || unlinks.busy}
          edit={
            editOffered ? { label: t.edit, onChoose: startEdit } : undefined
          }
          toggle={
            aiMarkOffered
              ? {
                  label: aiWords.possible,
                  pressed: Boolean(task.ai_possible),
                  onChoose: () => {
                    setMenuOpen(false);
                    saveTask({ ai_possible: !task.ai_possible });
                  },
                }
              : undefined
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
        />
      )}
      {/* The date and status chips; both write through saveTask (update_task). */}
      {phase === "ready" &&
        task &&
        (dueOffered || statusOffered || doneShown) && (
          <TaskProps
            hasDue={Boolean(task.due_at)}
            dueAt={task.due_at}
            busy={write.kind === "busy" || editing}
            status={task.status}
            labels={t}
            onDue={
              dueOffered ? (dueAt) => saveTask({ due_at: dueAt }) : undefined
            }
            onStatus={statusOffered ? chooseStatus : undefined}
            sentence={task.due_at ? detailDate(task.due_at, t) : undefined}
            done={doneForm === "button" && doneControl}
          >
            {/* The chip carries only the value (the date); how late it is stands on the line above. */}
            {task.due_at ? (
              <time dateTime={task.due_at}>{detailDate(task.due_at, t)}</time>
            ) : null}
          </TaskProps>
        )}
      {/* A failed change shows right under the controls it came from, in the family's write error row; the open editor
          shows its own. */}
      {phase === "ready" &&
        task &&
        write.kind === "failed" &&
        write.action !== "reload" &&
        !editing && (
          <ErrorNotice
            placement="row"
            locale={t.dateLocale}
            message={
              writeWhat === "trash"
                ? t.taskTrashFailed
                : writeWhat === "done"
                  ? inlineSummaryLabelsFor(t.dateLocale).doneFailed
                  : t.saveFailed
            }
            onRetry={retryLast}
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
      {/* Who the Task waits on, since when and when to follow up; each change is one update_task. */}
      {phase === "ready" && task && (
        <TaskWaiting
          task={task}
          labels={t}
          transport={transport}
          writable={offers("update_task")}
          busy={write.kind === "busy" || editing}
          onWrite={saveTask}
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
        <ErrorNotice
          locale={t.dateLocale}
          subject="work:task"
          cause={frame.readError}
          onRetry={frame.retry}
        />
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
                // A tertiary text button right after the text it opens, `descriptionMore`. No ›: › says
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
            savedLine={false}
          />
          {editing && (
            <TaskEditor
              task={task}
              busy={write.kind === "busy"}
              saveFailed={write.kind === "failed" && write.action === "save"}
              onSave={saveTask}
              onCancel={frame.stopEdit}
              labels={t}
              transport={transport}
            />
          )}
          {ai.shown && (
            <AiPlanCard
              ai={ai}
              title={task.title}
              locale={t.dateLocale}
              approveOffered={aiApproveOffered}
            />
          )}
          <AwaitingApproval plan={ai.plan}>
            <TaskSteps
              taskId={task.id}
              transport={transport}
              labels={t}
              receipt={bar}
              refreshKey={refreshKey + ai.stepsKey + stepWrites}
              stepExtra={(step) => {
                const entry = ai.byStep.get(step.id);
                return entry?.step.performer === "ai" ? (
                  <AiStepRun
                    entry={entry}
                    transport={transport}
                    server={ai.server}
                    labels={aiWords}
                    locale={t.dateLocale}
                    onReviewed={ai.reviewed}
                  />
                ) : null;
              }}
            />
          </AwaitingApproval>
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
      <ReceiptBar receipt={bar} />
    </article>
  );
}

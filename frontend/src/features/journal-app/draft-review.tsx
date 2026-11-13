import { useEffect, useId, useRef, useState } from "react";
import { ErrorNotice } from "../mcp-apps/ui/states";
import { TagField } from "../mcp-apps/ui/tags";
import {
  forgetTagVocabulary,
  useTagVocabulary,
} from "../mcp-apps/ui/tag-vocabulary";
import type { JournalLabels } from "./labels";
import type {
  JournalDraft,
  JournalDraftFields,
  JournalFinalizeResult,
  JournalSource,
  JournalTransport,
  JournalTaskProposal,
} from "./transport";
import { ApproveAllBar } from "./draft-review-parts/approve-all-bar";
import {
  FinalizeConfirm,
  RejectConfirm,
} from "./draft-review-parts/confirm-panels";
import { DecisionBar } from "./draft-review-parts/decision-bar";
import type { Plan, RelationKind } from "./draft-review-parts/decisions";
import { DraftNotices, type Notices } from "./draft-review-parts/draft-notices";
import { DraftReading } from "./draft-review-parts/draft-reading";
import type { DisclosureKey } from "./draft-review-parts/disclosure";
import {
  mergeFields,
  normalizeKeyPoints,
} from "./draft-review-parts/edit-values";
import { FieldsEditor } from "./draft-review-parts/fields-editor";
import { OriginalText } from "./draft-review-parts/original-text";
import { ProposalsSection } from "./draft-review-parts/proposals-section";
import { RelationsSection } from "./draft-review-parts/relations-section";
import {
  keptProposals,
  selection,
  summarizeReview,
} from "./draft-review-parts/review-plan";
import { useDraftChoices } from "./draft-review-parts/use-draft-choices";
import { useDraftConfirm } from "./draft-review-parts/use-draft-confirm";
import {
  useDraftLoader,
  type DraftRead,
} from "./draft-review-parts/use-draft-loader";
import { useDraftWrites } from "./draft-review-parts/use-draft-writes";

// The editing helpers and the editor live in draft-review-parts; other files import them from here.
export { changedFields, mergeFields } from "./draft-review-parts/edit-values";
export { FieldsEditor } from "./draft-review-parts/fields-editor";

export function DraftFrame({
  id,
  transport,
  labels: t,
  moves,
  onRejected,
  onFinalized,
}: {
  id: string;
  transport: JournalTransport;
  labels: JournalLabels;
  moves: number;
  /** The draft was rejected: the pending list should stop offering it. */
  onRejected: (draftId: string) => void;
  /** The draft became a journal entry: the view shows that entry next. */
  onFinalized: (draftId: string, result: JournalFinalizeResult) => void;
}) {
  const [draft, setDraft] = useState<JournalDraft>();
  const [source, setSource] = useState<JournalSource>();
  const [editing, setEditing] = useState(false);
  // The tags the owner sets on the entry the draft becomes; the draft itself carries none. Sent with the finalize.
  const [tags, setTags] = useState<string[]>([]);
  const vocabulary = useTagVocabulary(transport.listTags, "journal_entry");
  const editingRef = useRef(editing);
  const [notices, setNotices] = useState<Notices>({
    proposalChanged: false,
    editClosed: false,
    keyPointFixed: false,
  });
  // Inline, the sections start closed (CSS hides the bodies); fullscreen shows them all whatever this says.
  const baseId = useId();
  const [opened, setOpened] = useState<Record<DisclosureKey, boolean>>({
    keyPoints: false,
    relations: false,
    proposals: false,
  });
  const choices = useDraftChoices();
  const { picked, proposalPicks, declined } = choices;
  const writes = useDraftWrites();
  const { write, setWrite, busy } = writes;
  const confirmation = useDraftConfirm();
  const { confirm } = confirmation;
  const heading = useRef<HTMLHeadingElement>(null);
  const banner = useRef<HTMLDivElement>(null);
  // The status that replaces the summary after Godkänn alla takes focus: the button it came from is gone.
  const approvedNote = useRef<HTMLParagraphElement>(null);
  const focusApproved = useRef(false);

  // Async reads need the latest value; the ref is synced after each commit.
  useEffect(() => {
    editingRef.current = editing;
  });
  useEffect(() => {
    if (moves > 0) heading.current?.focus();
  }, [moves]);
  useEffect(() => {
    if (write.kind === "conflict") banner.current?.focus();
  }, [write.kind]);

  function applyRead(read: DraftRead) {
    const normalized = normalizeKeyPoints(read.draft);
    const fresh = normalized.draft;
    const hidden = fresh.task_proposal_count > fresh.task_proposals.length;
    setDraft(fresh);
    setSource(read.source);
    const dropped = choices.reconcile(fresh);
    setNotices({
      proposalChanged: dropped,
      // Editing is closed when permission now hides proposals: update would drop them.
      editClosed: hidden && editingRef.current,
      keyPointFixed: normalized.changed,
    });
    if (hidden) setEditing(false);
  }
  const { phase, retry } = useDraftLoader(transport, id, applyRead);

  function reload() {
    if (writes.isWriting()) return;
    writes.perform(
      "reload",
      () => transport.getDraft(id),
      (read) => {
        applyRead(read);
        confirmation.close();
        setWrite({ kind: "idle" });
        heading.current?.focus();
      },
    );
  }

  const pending = draft?.state === "pending_review";
  const hiddenProposals =
    draft !== undefined &&
    draft.task_proposal_count > draft.task_proposals.length;

  function saveEdits(changes: Partial<JournalDraftFields>) {
    // update_journal_draft replaces every proposal: never write a list permission has cut short.
    if (!draft || writes.isWriting() || hiddenProposals) return;
    if (Object.keys(changes).length === 0) {
      setEditing(false);
      setWrite({ kind: "idle" });
      heading.current?.focus();
      return;
    }
    const fields = mergeFields(draft, changes);
    const pendingKey = writes.keyedBy(
      JSON.stringify(["update", draft.id, draft.version, fields]),
    );
    writes.perform(
      "save",
      () =>
        transport.updateDraft(
          draft.id,
          draft.version,
          { ...fields, task_proposals: draft.task_proposals },
          pendingKey.key,
        ),
      (result) => {
        setDraft((held) =>
          held
            ? {
                ...held,
                ...fields,
                state: result.draft.state,
                version: result.draft.version,
              }
            : held,
        );
        setEditing(false);
        setWrite({ kind: "saved" });
        heading.current?.focus();
      },
    );
  }

  function rejectDraft() {
    if (!draft || writes.isWriting()) return;
    const pendingKey = writes.keyedBy(
      JSON.stringify(["reject", draft.id, draft.version]),
    );
    writes.perform(
      "reject",
      () => transport.rejectDraft(draft.id, draft.version, pendingKey.key),
      (result) => {
        setDraft((held) =>
          held
            ? {
                ...held,
                state: result.draft.state,
                version: result.draft.version,
              }
            : held,
        );
        confirmation.close();
        setWrite({ kind: "saved" });
        onRejected(draft.id);
        heading.current?.focus();
      },
    );
  }

  /** Saves the draft with the given choices. The plan is sent as given, never read back from the state. */
  function saveDraft(plan: Plan) {
    if (!draft || writes.isWriting()) return;
    const fields = mergeFields(draft, {});
    const input = {
      ...fields,
      relation_selection: selection(draft, plan.picked),
      task_proposals: keptProposals(draft, plan.picks),
      ...(tags.length > 0 ? { tags } : {}),
    };
    const pendingKey = writes.keyedBy(
      JSON.stringify(["finalize", draft.id, draft.version, input]),
    );
    writes.perform(
      "finalize",
      () =>
        transport.finalizeDraft(draft.id, draft.version, input, pendingKey.key),
      (result) => {
        // A tag that is new to the vocabulary is read again by the next view that lists it.
        if (tags.length > 0) forgetTagVocabulary(transport.listTags);
        onFinalized(draft.id, result);
      },
    );
  }

  /** Saves with what is chosen now; the undecided suggestions are left out, as the confirmation says. */
  function finalizeDraft() {
    saveDraft({ picked, picks: proposalPicks });
  }

  function askConfirm(kind: "reject" | "finalize") {
    if (busy) return;
    setWrite({ kind: "idle" });
    confirmation.ask(kind);
  }
  /** Godkänn on every known suggestion, as if each row were pressed. Returns the choices it made. */
  function approveEverything(current: JournalDraft): Plan {
    const plan = choices.approveEverything(current);
    setNotices((notes) => ({ ...notes, proposalChanged: false }));
    setWrite({ kind: "idle" });
    return plan;
  }
  function approveAllSuggestions() {
    if (!draft || busy || editing || confirm !== undefined) return;
    focusApproved.current = true;
    approveEverything(draft);
  }
  function approveAllAndSave() {
    if (!draft || writes.isWriting()) return;
    saveDraft(approveEverything(draft));
  }
  function toggleSection(key: DisclosureKey) {
    setOpened((current) => ({ ...current, [key]: !current[key] }));
  }
  /** Opens both sections, so the owner can decide each suggestion. */
  function openSuggestions() {
    setOpened((current) => ({ ...current, relations: true, proposals: true }));
  }
  /** Closes the confirmation and opens the suggestions. */
  function reviewThem() {
    confirmation.close();
    openSuggestions();
  }

  function togglePicked(kind: RelationKind, value: string, on: boolean) {
    setWrite({ kind: "idle" });
    choices.togglePicked(kind, value, on);
  }
  function toggleProposal(proposal: JournalTaskProposal, on: boolean) {
    setWrite({ kind: "idle" });
    setNotices((current) => ({ ...current, proposalChanged: false }));
    choices.toggleProposal(proposal, on);
  }
  function cancelEdit() {
    writes.discardKey();
    setEditing(false);
    setWrite({ kind: "idle" });
    heading.current?.focus();
  }

  const review = summarizeReview(draft, picked, proposalPicks, declined, t);
  const { allApprovedNow } = review;
  useEffect(() => {
    if (allApprovedNow && focusApproved.current) approvedNote.current?.focus();
    focusApproved.current = false;
  }, [allApprovedNow]);

  // The entry's tags, under the summary. Inline its heading is hidden (journal.css hides the section heads inline)
  // and the closed field, "+ Lägg till tagg", shares the row with "Läs mer", so the card still fits a phone screen.
  const tagField = draft ? (
    <div className="journal-draft-tags">
      <h3 className="journal-disclosure-head">{t.draftTags}</h3>
      <TagField
        tags={tags}
        suggestions={vocabulary.suggestions}
        editable
        busy={busy || confirm !== undefined}
        name={draft.title}
        onChange={(next, done) => {
          setWrite({ kind: "idle" });
          setTags(next);
          done();
        }}
        locale={t.dateLocale}
      />
    </div>
  ) : null;

  return (
    <article className="journal-draft">
      <h2 ref={heading} tabIndex={-1}>
        {phase === "ready" && draft ? draft.title : t.draft}
      </h2>
      {phase === "loading" && <p role="status">{t.loading}</p>}
      {phase === "forbidden" && <p>{t.forbidden}</p>}
      {phase === "error" && (
        <ErrorNotice locale={t.dateLocale} onRetry={retry} />
      )}
      {phase === "ready" && draft && (
        <>
          <p className="journal-draft-tag">
            <span className="journal-tag">{t.aiDraft}</span>
          </p>
          {pending ? (
            <p className="journal-muted journal-draft-note">{t.draftNote}</p>
          ) : (
            <p role="status">
              {draft.state === "rejected" && write.kind === "saved"
                ? t.rejected
                : t.terminalDraft}
            </p>
          )}
          <DraftNotices
            write={write}
            busy={busy}
            pending={pending}
            notices={notices}
            onReload={reload}
            bannerRef={banner}
            labels={t}
          />
          {pending && review.suggestionTotal > 0 && (
            <ApproveAllBar
              allApproved={allApprovedNow}
              linkCount={review.decidable.links.length}
              proposalCount={review.decidable.tasks.length}
              disabled={busy || editing || confirm !== undefined}
              onApproveAll={approveAllSuggestions}
              onChooseYourself={openSuggestions}
              approvedNoteRef={approvedNote}
              labels={t}
            />
          )}
          {editing && pending && !hiddenProposals ? (
            <>
              <FieldsEditor
                draft={draft}
                busy={busy}
                saveFailed={write.kind === "failed" && write.action === "save"}
                onSave={saveEdits}
                onCancel={cancelEdit}
                labels={t}
              />
              {tagField}
            </>
          ) : (
            <DraftReading
              draft={draft}
              tags={pending ? tagField : null}
              pending={pending}
              editDisabled={busy || hiddenProposals || confirm !== undefined}
              hiddenProposals={hiddenProposals}
              keyPointsId={`${baseId}-points`}
              keyPointsOpen={opened.keyPoints}
              onToggleKeyPoints={() => toggleSection("keyPoints")}
              onEdit={() => {
                setWrite({ kind: "idle" });
                setEditing(true);
              }}
              labels={t}
            />
          )}
          <OriginalText source={source} labels={t} />
          {pending && (
            <>
              <RelationsSection
                id={`${baseId}-relations`}
                draft={draft}
                count={review.suggestionCount}
                open={opened.relations}
                onToggle={() => toggleSection("relations")}
                picked={picked}
                declined={declined}
                locked={busy || confirm !== undefined}
                onPick={togglePicked}
                onDeclinedChange={choices.setDeclinedFor}
                labels={t}
              />
              <ProposalsSection
                id={`${baseId}-proposals`}
                draft={draft}
                open={opened.proposals}
                onToggle={() => toggleSection("proposals")}
                hidden={hiddenProposals}
                proposalPicks={proposalPicks}
                declined={declined}
                locked={busy || confirm !== undefined}
                taskLabel={review.taskLabel}
                onToggleProposal={toggleProposal}
                onDeclinedChange={choices.setDeclinedFor}
                labels={t}
              />
              <DecisionBar
                confirm={confirm}
                disabled={busy || editing}
                editing={editing}
                write={write}
                onFinalize={() => askConfirm("finalize")}
                onReject={() => askConfirm("reject")}
                finalizeRef={confirmation.finalizeButton}
                rejectRef={confirmation.rejectButton}
                labels={t}
              />
              {confirm === "finalize" && (
                <FinalizeConfirm
                  linkCount={review.linkCount}
                  createdCount={review.createdCount}
                  updatedCount={review.updatedCount}
                  undecidedLinks={review.undecidedLinks}
                  undecidedTasks={review.undecidedTasks}
                  chosenNames={review.chosenNames}
                  busy={busy}
                  write={write}
                  yesRef={confirmation.confirmYes}
                  onApproveAllAndSave={approveAllAndSave}
                  onFinalize={finalizeDraft}
                  onReview={reviewThem}
                  onCancel={confirmation.close}
                  labels={t}
                />
              )}
              {confirm === "reject" && (
                <RejectConfirm
                  busy={busy}
                  write={write}
                  yesRef={confirmation.confirmYes}
                  onReject={rejectDraft}
                  onCancel={confirmation.close}
                  labels={t}
                />
              )}
            </>
          )}
        </>
      )}
    </article>
  );
}

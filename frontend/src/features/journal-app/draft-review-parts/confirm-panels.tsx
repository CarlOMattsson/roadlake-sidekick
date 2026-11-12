import type { RefObject } from "react";
import type { JournalLabels } from "../labels";
import type { WriteState } from "./use-draft-writes";

const CONFIRM_LIST_MAX = 10;

/** What saving the draft will do, listed by name, with the way to decide the undecided suggestions first. */
export function FinalizeConfirm({
  linkCount,
  createdCount,
  updatedCount,
  undecidedLinks,
  undecidedTasks,
  chosenNames,
  busy,
  write,
  yesRef,
  onApproveAllAndSave,
  onFinalize,
  onReview,
  onCancel,
  labels: t,
}: {
  linkCount: number;
  createdCount: number;
  updatedCount: number;
  undecidedLinks: number;
  undecidedTasks: number;
  chosenNames: string[];
  busy: boolean;
  write: WriteState;
  yesRef: RefObject<HTMLButtonElement | null>;
  onApproveAllAndSave: () => void;
  onFinalize: () => void;
  onReview: () => void;
  onCancel: () => void;
  labels: JournalLabels;
}) {
  const undecidedCount = undecidedLinks + undecidedTasks;
  return (
    <div
      className="journal-confirm sk-card"
      role="group"
      aria-label={t.finalize}
    >
      <p>{t.finalizeConfirm(linkCount, createdCount, updatedCount)}</p>
      {undecidedCount > 0 && (
        <p>{t.undecidedNote(undecidedLinks, undecidedTasks)}</p>
      )}
      {chosenNames.length > 0 && (
        <ul className="journal-list">
          {chosenNames.slice(0, CONFIRM_LIST_MAX).map((name, i) => (
            <li key={i}>{name}</li>
          ))}
          {chosenNames.length > CONFIRM_LIST_MAX && (
            <li>{t.andMore(chosenNames.length - CONFIRM_LIST_MAX)}</li>
          )}
        </ul>
      )}
      {undecidedCount > 0 ? (
        <div className="journal-actions">
          <button
            type="button"
            className="sk-btn--primary"
            disabled={busy || write.kind === "conflict"}
            onClick={onApproveAllAndSave}
          >
            {t.approveAllAndSave}
          </button>
          <button
            type="button"
            disabled={busy || write.kind === "conflict"}
            onClick={onFinalize}
          >
            {t.saveWithoutThem}
          </button>
          <button
            type="button"
            className="sk-btn--quiet"
            ref={yesRef}
            disabled={busy}
            onClick={onReview}
          >
            {t.reviewThem}
          </button>
        </div>
      ) : (
        <div className="journal-actions">
          <button
            type="button"
            className="sk-btn--primary"
            ref={yesRef}
            disabled={busy || write.kind === "conflict"}
            onClick={onFinalize}
          >
            {t.finalizeYes}
          </button>
          <button
            type="button"
            className="sk-btn--quiet"
            disabled={busy}
            onClick={onCancel}
          >
            {t.cancel}
          </button>
        </div>
      )}
    </div>
  );
}

export function RejectConfirm({
  busy,
  write,
  yesRef,
  onReject,
  onCancel,
  labels: t,
}: {
  busy: boolean;
  write: WriteState;
  yesRef: RefObject<HTMLButtonElement | null>;
  onReject: () => void;
  onCancel: () => void;
  labels: JournalLabels;
}) {
  return (
    <div className="journal-confirm sk-card" role="group" aria-label={t.reject}>
      <p>{t.rejectConfirm}</p>
      <div className="journal-actions">
        <button
          type="button"
          className="sk-btn--danger"
          ref={yesRef}
          disabled={busy || write.kind === "conflict"}
          onClick={onReject}
        >
          {t.rejectYes}
        </button>
        <button
          type="button"
          className="sk-btn--quiet"
          disabled={busy}
          onClick={onCancel}
        >
          {t.keepDraft}
        </button>
      </div>
    </div>
  );
}

import type { RefObject } from "react";
import type { JournalLabels } from "../labels";

/**
 * "Approve all" on the AI's suggestions, or the status that replaces it once every suggestion is approved. The button
 * says how many it approves (`approveAll`); fullscreen the sentence over it (`suggestionSummary`) splits them,
 * inline the fold rows right under it do (`relationsFold` with a count), so the sentence is read
 * only by a screen reader there and the card still fits a phone screen. The button is secondary: approving saves
 * nothing, and the card's one primary is `finalize`.
 */
export function ApproveAllBar({
  allApproved,
  linkCount,
  proposalCount,
  disabled,
  onApproveAll,
  onChooseYourself,
  approvedNoteRef,
  labels: t,
}: {
  allApproved: boolean;
  linkCount: number;
  proposalCount: number;
  disabled: boolean;
  onApproveAll: () => void;
  onChooseYourself: () => void;
  approvedNoteRef: RefObject<HTMLParagraphElement | null>;
  labels: JournalLabels;
}) {
  if (allApproved)
    return (
      <p ref={approvedNoteRef} tabIndex={-1}>
        {t.allApproved}
      </p>
    );
  return (
    <>
      <p className="journal-suggestion-summary">
        {t.suggestionSummary(linkCount, proposalCount)}
      </p>
      <div className="journal-actions journal-approve-all">
        <button
          type="button"
          className="sk-btn--secondary"
          disabled={disabled}
          onClick={onApproveAll}
        >
          {t.approveAll(linkCount + proposalCount)}
        </button>
        <button
          type="button"
          className="sk-btn--quiet journal-choose-yourself"
          onClick={onChooseYourself}
        >
          {t.chooseYourself}
        </button>
      </div>
    </>
  );
}

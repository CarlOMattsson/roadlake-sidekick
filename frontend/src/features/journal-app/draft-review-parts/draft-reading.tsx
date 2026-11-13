import type { ReactNode } from "react";
import { labelFor, type JournalLabels } from "../labels";
import type { JournalDraft } from "../transport";
import { Disclosure } from "./disclosure";
import { DraftSummary } from "./draft-summary";

/** The draft as the owner reads it: summary, the tags for the entry (`tags`), key points, and the way into the editor. */
export function DraftReading({
  draft,
  tags,
  pending,
  editDisabled,
  hiddenProposals,
  keyPointsId,
  keyPointsOpen,
  onToggleKeyPoints,
  onEdit,
  labels: t,
}: {
  draft: JournalDraft;
  tags: ReactNode;
  pending: boolean;
  editDisabled: boolean;
  hiddenProposals: boolean;
  keyPointsId: string;
  keyPointsOpen: boolean;
  onToggleKeyPoints: () => void;
  onEdit: () => void;
  labels: JournalLabels;
}) {
  return (
    <>
      {draft.summary ? (
        <DraftSummary text={draft.summary} after={tags} labels={t} />
      ) : (
        <>
          <p className="journal-muted">{t.noDraftSummary}</p>
          {tags}
        </>
      )}
      {draft.key_points.length > 0 && (
        <Disclosure
          id={keyPointsId}
          title={t.keyPoints}
          count={draft.key_points.length}
          open={keyPointsOpen}
          onToggle={onToggleKeyPoints}
        >
          <ul className="journal-list">
            {draft.key_points.map((point, index) => (
              <li key={index}>
                <p>
                  {labelFor(t.keyPointKind, point.kind)}: {point.text}
                </p>
              </li>
            ))}
          </ul>
        </Disclosure>
      )}
      {pending && (
        <p className="journal-draft-action">
          <button type="button" disabled={editDisabled} onClick={onEdit}>
            {t.edit}
          </button>
        </p>
      )}
      {pending && hiddenProposals && (
        <p className="journal-muted">{t.editBlockedHidden}</p>
      )}
    </>
  );
}

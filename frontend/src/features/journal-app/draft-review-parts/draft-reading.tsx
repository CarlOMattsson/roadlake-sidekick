import type { ReactNode } from "react";
import { labelFor, type JournalLabels } from "../labels";
import type { JournalDraft } from "../transport";
import { Disclosure } from "./disclosure";
import { DraftSummary } from "./draft-summary";

/**
 * The draft as the owner reads it: summary, the tags for the entry (`tags`), the way into the editor beside the
 * original (`original`), then key points. Edit and the original sit under the summary they belong to, so the fold rows
 * (key points, links, task changes) follow each other with nothing between them.
 */
export function DraftReading({
  draft,
  tags,
  original,
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
  original: ReactNode;
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
      {pending && (
        <p className="journal-draft-action">
          <button
            type="button"
            className="sk-btn--quiet journal-toggle"
            disabled={editDisabled}
            onClick={onEdit}
          >
            {t.edit}
          </button>
        </p>
      )}
      {original}
      {pending && hiddenProposals && (
        <p className="journal-muted">{t.editBlockedHidden}</p>
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
    </>
  );
}

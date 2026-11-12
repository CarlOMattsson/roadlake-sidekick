import type { JournalLabels } from "../labels";
import type { JournalDraft, JournalTaskProposal } from "../transport";
import { proposalKey, proposalKnown } from "./decisions";
import { Disclosure } from "./disclosure";
import { ProposalCheck } from "./proposal-check";

/** The AI's task proposals as one disclosure, each with its Godkänn/Avslå pair. */
export function ProposalsSection({
  id,
  draft,
  open,
  onToggle,
  hidden,
  proposalPicks,
  declined,
  locked,
  taskLabel,
  onToggleProposal,
  onDeclinedChange,
  labels: t,
}: {
  id: string;
  draft: JournalDraft;
  open: boolean;
  onToggle: () => void;
  /** Permission hides some proposals from this view. */
  hidden: boolean;
  proposalPicks: Record<string, string>;
  declined: Record<string, boolean>;
  /** Busy or awaiting confirmation: no row can change. */
  locked: boolean;
  taskLabel: (taskId: string) => string;
  onToggleProposal: (proposal: JournalTaskProposal, on: boolean) => void;
  onDeclinedChange: (key: string, value: boolean) => void;
  labels: JournalLabels;
}) {
  return (
    <Disclosure
      id={id}
      title={t.proposals}
      count={draft.task_proposal_count}
      open={open}
      onToggle={onToggle}
    >
      {draft.task_proposals.length > 0 && (
        <p className="journal-muted">{t.proposalsNote}</p>
      )}
      {draft.task_proposals.length === 0 && !hidden && <p>{t.noProposals}</p>}
      {hidden && <p role="status">{t.hiddenProposals}</p>}
      {draft.task_proposals.length > 0 && (
        <fieldset className="journal-fieldset">
          <legend>{t.proposals}</legend>
          {draft.task_proposals.map((proposal) => (
            <ProposalCheck
              key={proposal.proposal_id}
              proposal={proposal}
              taskLabel={taskLabel}
              known={proposalKnown(proposal, draft)}
              checked={proposal.proposal_id in proposalPicks}
              declined={declined[proposalKey(proposal.proposal_id)] === true}
              onDeclinedChange={(value) =>
                onDeclinedChange(proposalKey(proposal.proposal_id), value)
              }
              disabled={locked}
              onChange={(on) => onToggleProposal(proposal, on)}
              labels={t}
            />
          ))}
        </fieldset>
      )}
    </Disclosure>
  );
}

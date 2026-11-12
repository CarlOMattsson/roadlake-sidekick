import type { JournalLabels } from "../labels";
import type {
  JournalDraft,
  JournalTaskProposal,
  RelationChoice,
  RelationSelection,
} from "../transport";
import {
  RELATION_KINDS,
  decidableOf,
  linkKey,
  optionsFor,
  pairValue,
  proposalKey,
  proposalKnown,
  proposalName,
  type Decision,
  type Picked,
  type RelationKind,
} from "./decisions";

/** The relation choices as they go to the server; unknown candidates are never sent. */
export function selection(
  current: JournalDraft,
  chosen: Picked,
): RelationSelection {
  const choose = (kind: RelationKind): RelationChoice[] =>
    optionsFor(current, kind, "")
      .filter((option) => option.known && chosen[kind].includes(option.id))
      .map((option) => ({
        id: option.id,
        origin: option.suggested ? "model_suggested" : "user_selected",
      }));
  return {
    project_ids: choose("projects"),
    task_ids: choose("tasks"),
    contact_ids: choose("contacts"),
  };
}

/** The proposals the owner kept that the app can act on. */
export function keptProposals(
  current: JournalDraft,
  picks: Record<string, string>,
): JournalTaskProposal[] {
  return current.task_proposals.filter(
    (proposal) =>
      proposal.proposal_id in picks && proposalKnown(proposal, current),
  );
}

/** Everything the review derives from the draft and the owner's choices, for rendering and the confirmation. */
export type ReviewSummary = {
  linkCount: number;
  suggestionCount: number;
  createdCount: number;
  updatedCount: number;
  taskLabel: (taskId: string) => string;
  chosenNames: string[];
  decidable: ReturnType<typeof decidableOf>;
  suggestionTotal: number;
  undecidedLinks: number;
  undecidedTasks: number;
  undecidedCount: number;
  allApprovedNow: boolean;
};

export function summarizeReview(
  draft: JournalDraft | undefined,
  picked: Picked,
  proposalPicks: Record<string, string>,
  declined: Record<string, boolean>,
  t: JournalLabels,
): ReviewSummary {
  const linkCount =
    picked.projects.length + picked.tasks.length + picked.contacts.length;
  // The AI's link suggestions, all kinds together: the count on the links disclosure row.
  const suggestionCount = draft
    ? RELATION_KINDS.reduce(
        (sum, kind) =>
          sum + optionsFor(draft, kind, "").filter((o) => o.suggested).length,
        0,
      )
    : 0;
  const keptList = draft ? keptProposals(draft, proposalPicks) : [];
  const createdCount = keptList.filter(
    (proposal) => proposal.type === "create_task",
  ).length;
  const updatedCount = keptList.length - createdCount;
  const taskLabel = (taskId: string) =>
    draft?.catalog.tasks.find((task) => task.id === taskId)?.label ??
    t.unknownTask;
  // What the confirmation lists: the chosen links and task changes by name.
  const chosenNames: string[] = draft
    ? [
        ...RELATION_KINDS.flatMap((kind) =>
          optionsFor(draft, kind, "")
            .filter(
              (option) => option.known && picked[kind].includes(option.id),
            )
            .map((option) => option.label),
        ),
        ...keptList.map((proposal) => proposalName(proposal, taskLabel, t)),
      ]
    : [];

  // Decided means Godkänn or Avslå: a row with neither is undecided, and a known suggestion is the only kind counted.
  const decisionOfLink = (kind: RelationKind, id: string): Decision | null =>
    pairValue(picked[kind].includes(id), declined[linkKey(kind, id)] === true);
  const decisionOfProposal = (proposalId: string): Decision | null =>
    pairValue(
      proposalId in proposalPicks,
      declined[proposalKey(proposalId)] === true,
    );
  const decidable: ReturnType<typeof decidableOf> = draft
    ? decidableOf(draft)
    : { links: [], tasks: [] };
  const suggestionTotal = decidable.links.length + decidable.tasks.length;
  const undecidedLinks = decidable.links.filter(
    (link) => decisionOfLink(link.kind, link.id) === null,
  ).length;
  const undecidedTasks = decidable.tasks.filter(
    (proposal) => decisionOfProposal(proposal.proposal_id) === null,
  ).length;
  const allApprovedNow =
    suggestionTotal > 0 &&
    [
      ...decidable.links.map((link) => decisionOfLink(link.kind, link.id)),
      ...decidable.tasks.map((proposal) =>
        decisionOfProposal(proposal.proposal_id),
      ),
    ].every((decision) => decision === "approve");
  return {
    linkCount,
    suggestionCount,
    createdCount,
    updatedCount,
    taskLabel,
    chosenNames,
    decidable,
    suggestionTotal,
    undecidedLinks,
    undecidedTasks,
    undecidedCount: undecidedLinks + undecidedTasks,
    allApprovedNow,
  };
}

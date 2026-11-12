import type { SegmentedOption } from "../../mcp-apps/ui/segmented";
import type { JournalLabels } from "../labels";
import type { JournalDraft, JournalTaskProposal } from "../transport";

export type RelationKind = "projects" | "tasks" | "contacts";
export const RELATION_KINDS: RelationKind[] = ["projects", "tasks", "contacts"];
/** The finalize schema allows at most 25 links of each kind. */
export const MAX_RELATIONS = 25;

export type Option = {
  id: string;
  label: string;
  context: string | null;
  suggested: boolean;
  rationale: string | null;
  /** False for a suggestion whose candidate is not in the catalogue: shown, never selectable. */
  known: boolean;
};

/** AI suggestions first, then the other catalogue candidates the owner may pick as their own. */
export function optionsFor(
  draft: JournalDraft,
  kind: RelationKind,
  unknownLabel: string,
): Option[] {
  const known = draft.catalog[kind];
  const options: Option[] = [];
  const seen = new Set<string>();
  for (const suggestion of draft.suggestions[kind]) {
    if (seen.has(suggestion.id)) continue;
    seen.add(suggestion.id);
    const candidate = known.find((item) => item.id === suggestion.id);
    options.push({
      id: suggestion.id,
      label: candidate?.label ?? unknownLabel,
      context: candidate?.context ?? null,
      suggested: true,
      rationale: suggestion.rationale,
      known: candidate !== undefined,
    });
  }
  for (const candidate of known) {
    if (seen.has(candidate.id)) continue;
    seen.add(candidate.id);
    options.push({
      id: candidate.id,
      label: candidate.label,
      context: candidate.context ?? null,
      suggested: false,
      rationale: null,
      known: true,
    });
  }
  return options;
}

export type Picked = Record<RelationKind, string[]>;
export const NONE_PICKED: Picked = { projects: [], tasks: [], contacts: [] };

/** JSON with sorted object keys, so equal proposals always give the same signature. */
export function stableJson(value: unknown): string {
  return JSON.stringify(value, (_key, item: unknown) =>
    item && typeof item === "object" && !Array.isArray(item)
      ? Object.fromEntries(
          Object.entries(item).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)),
        )
      : item,
  );
}

export function proposalName(
  proposal: JournalTaskProposal,
  taskLabel: (taskId: string) => string,
  t: JournalLabels,
): string {
  return proposal.type === "create_task"
    ? t.createTaskProposal(proposal.title)
    : t.updateTaskProposal(taskLabel(proposal.task_id));
}
/** An update can only be chosen for a Task the catalogue knows; a create needs nothing. */
export function proposalKnown(
  proposal: JournalTaskProposal,
  draft: JournalDraft,
) {
  return (
    proposal.type === "create_task" ||
    draft.catalog.tasks.some((task) => task.id === proposal.task_id)
  );
}

export type Decision = "approve" | "decline";
/**
 * Godkänn/Avslå for an AI suggestion or proposal. Nothing is included until the owner approves it,
 * and nothing is written before the draft is saved.
 */
export function decisionOptions(t: JournalLabels): SegmentedOption<Decision>[] {
  return [
    { value: "approve", label: t.approve },
    { value: "decline", label: t.decline },
  ];
}

/**
 * The pressed option of a Godkänn/Avslå pair. Nothing is pressed until the owner chooses: an
 * unchosen suggestion is not a declined one. `chosen` is the server-bound selection; `declined`
 * remembers an explicit Avslå, which has no selection of its own.
 */
export function pairValue(chosen: boolean, declined: boolean): Decision | null {
  if (chosen) return "approve";
  return declined ? "decline" : null;
}

/** The key of a link suggestion's Avslå in the frame: a declined suggestion has no selection of its own. */
export function linkKey(kind: RelationKind, id: string): string {
  return `${kind}:${id}`;
}
export function proposalKey(proposalId: string): string {
  return `proposal:${proposalId}`;
}

/** The suggestions the owner decides: known AI link suggestions, and the task proposals the app shows and can act on. */
export function decidableOf(draft: JournalDraft): {
  links: { kind: RelationKind; id: string }[];
  tasks: JournalTaskProposal[];
} {
  return {
    links: RELATION_KINDS.flatMap((kind) =>
      optionsFor(draft, kind, "")
        .filter((option) => option.suggested && option.known)
        .map((option) => ({ kind, id: option.id })),
    ),
    tasks: draft.task_proposals.filter((proposal) =>
      proposalKnown(proposal, draft),
    ),
  };
}

/** The owner's choices as they go to the server: chosen links and kept proposals with their signatures. */
export type Plan = { picked: Picked; picks: Record<string, string> };

/**
 * The choices after Godkänn on every known suggestion, which is what pressing each row's Godkänn gives. A
 * declined suggestion is approved too. Links stop at MAX_RELATIONS per kind, as the rows do.
 */
export function approvedSuggestions(draft: JournalDraft, base: Plan): Plan {
  const picked: Picked = {
    projects: [...base.picked.projects],
    tasks: [...base.picked.tasks],
    contacts: [...base.picked.contacts],
  };
  for (const link of decidableOf(draft).links) {
    if (picked[link.kind].includes(link.id)) continue;
    if (picked[link.kind].length >= MAX_RELATIONS) continue;
    picked[link.kind].push(link.id);
  }
  const picks = { ...base.picks };
  for (const proposal of decidableOf(draft).tasks)
    picks[proposal.proposal_id] = stableJson(proposal);
  return { picked, picks };
}

/** The chosen state in text, so it never relies on colour alone. */
export function decisionStatus(
  decision: Decision | null,
  t: JournalLabels,
): string {
  if (decision === "approve") return t.decisionApproved;
  if (decision === "decline") return t.decisionDeclined;
  return t.decisionOpen;
}

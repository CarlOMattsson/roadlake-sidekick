import { useEffect, useRef, useState } from "react";
import type { JournalDraft, JournalTaskProposal } from "../transport";
import {
  NONE_PICKED,
  RELATION_KINDS,
  approvedSuggestions,
  decidableOf,
  linkKey,
  optionsFor,
  proposalKey,
  proposalKnown,
  stableJson,
  type Picked,
  type Plan,
  type RelationKind,
} from "./decisions";

/**
 * The owner's link and proposal choices for one draft: chosen links, chosen proposals with the signature each
 * had when chosen (a changed proposal is not kept), and the explicit Avslå per suggestion. Nothing here is
 * written to the server; the frame sends a Plan when the draft is saved.
 */
export function useDraftChoices() {
  const [picked, setPicked] = useState<Picked>(NONE_PICKED);
  const [proposalPicks, setProposalPicks] = useState<Record<string, string>>(
    {},
  );
  const picksRef = useRef(proposalPicks);
  // Avslå per suggestion, keyed by linkKey/proposalKey: the frame counts undecided ones for the save confirmation.
  const [declined, setDeclined] = useState<Record<string, boolean>>({});
  // Async reads need the latest values; the ref is synced after each commit.
  useEffect(() => {
    picksRef.current = proposalPicks;
  });

  /** Choices survive a reload for as long as the option or proposal still exists. Returns whether a proposal was dropped. */
  function reconcile(fresh: JournalDraft): boolean {
    const kept: Record<string, string> = {};
    let dropped = false;
    for (const [proposalId, signature] of Object.entries(picksRef.current)) {
      const now = fresh.task_proposals.find(
        (proposal) => proposal.proposal_id === proposalId,
      );
      if (now && proposalKnown(now, fresh) && stableJson(now) === signature)
        kept[proposalId] = signature;
      else dropped = true;
    }
    setProposalPicks(kept);
    setPicked((current) => {
      const next: Picked = { projects: [], tasks: [], contacts: [] };
      for (const kind of RELATION_KINDS) {
        const valid = new Set(
          optionsFor(fresh, kind, "")
            .filter((option) => option.known)
            .map((option) => option.id),
        );
        next[kind] = current[kind].filter((value) => valid.has(value));
      }
      return next;
    });
    return dropped;
  }

  function togglePicked(kind: RelationKind, value: string, on: boolean) {
    setPicked((current) => ({
      ...current,
      [kind]: on
        ? [...current[kind], value]
        : current[kind].filter((item) => item !== value),
    }));
  }
  function toggleProposal(proposal: JournalTaskProposal, on: boolean) {
    setProposalPicks((current) => {
      const next = { ...current };
      if (on) next[proposal.proposal_id] = stableJson(proposal);
      else delete next[proposal.proposal_id];
      return next;
    });
  }
  function setDeclinedFor(key: string, value: boolean) {
    setDeclined((current) => ({ ...current, [key]: value }));
  }
  /** Godkänn on every known suggestion, as if each row were pressed. Returns the choices it made. */
  function approveEverything(current: JournalDraft): Plan {
    const plan = approvedSuggestions(current, { picked, picks: proposalPicks });
    setPicked(plan.picked);
    setProposalPicks(plan.picks);
    setDeclined((held) => {
      const next = { ...held };
      const decidable = decidableOf(current);
      for (const link of decidable.links)
        next[linkKey(link.kind, link.id)] = false;
      for (const proposal of decidable.tasks)
        next[proposalKey(proposal.proposal_id)] = false;
      return next;
    });
    return plan;
  }

  return {
    picked,
    proposalPicks,
    declined,
    reconcile,
    togglePicked,
    toggleProposal,
    setDeclinedFor,
    approveEverything,
  };
}

import { useCallback, useRef, useState } from "react";

import { HostToolError } from "../../mcp-apps/bridge";
import { keyFor, type PendingKey } from "../../mcp-apps/idempotency";
import type { RoomTarget } from "../../mcp-apps/room-types";
import {
  APPLY_ERRORS,
  type ApplyError,
} from "../../mcp-apps/ui/decision-codes";
import type { DecisionAnswer } from "../../mcp-apps/ui/decision-card";
import type { ReceiptState } from "../../mcp-apps/ui/receipt";
import type { SuggestionLabels } from "./labels";
import {
  addedLine,
  appliedTarget,
  MAX_PER_CONFIRMATION,
  suggestionValue,
  wholeGroup,
  type DecisionOutcome,
  type InboxGroup,
  type SuggestionItem,
} from "./model";
import type { SuggestionTransport } from "./transport";

/** What a card shows of a decision: the answer in flight, a failure, or its receipt. */
export type CardDecision = {
  busy?: DecisionAnswer;
  failed?: DecisionAnswer;
  applyError?: ApplyError;
  decided?: { message: string; target?: RoomTarget; hold: boolean };
};

/** What a safe group shows: its approval in flight, a failure (with a sentence of its own), or its receipt. */
export type GroupDecision = {
  busy?: boolean;
  failed?: boolean;
  note?: string;
  decided?: string;
};

/** A card as a decision needs it: its id, version, effect and line. */
type Decidable = Pick<SuggestionItem, "id" | "version" | "effect" | "summary">;

const applyErrorOf = (
  code: DecisionOutcome["error_code"],
): ApplyError | undefined => {
  const name = code?.startsWith("apply_error:")
    ? code.slice("apply_error:".length)
    : undefined;
  return (APPLY_ERRORS as readonly string[]).includes(name ?? "")
    ? (name as ApplyError)
    : undefined;
};

/**
 * The owner's decisions in the inbox: approve or dismiss one card, approve (part of) a safe group, and undo an approval.
 * Every write goes through the inbox's transport with an idempotency key, which a retry of the same action reuses. A
 * decided card holds its place as its receipt while the bar offers Ångra; when the receipt leaves, `onSettled` reads
 * the inbox again (in place), so the card goes and nothing moves while Ångra can still be pressed.
 *
 * At most three cards per confirmation (MAX_PER_CONFIRMATION). A group the owner approves whole is sent with the
 * server's digest (approve_suggestion_group); a part of it is decided card by card (decide_suggestions).
 * Dismissing has no Ångra: the server has no way back for a dismissal.
 */
export function useDecisions({
  api,
  t,
  receipt,
  onSettled,
  onOpen,
}: {
  api: SuggestionTransport;
  t: SuggestionLabels;
  receipt: ReceiptState;
  /** Something was decided or undone: read the inbox again. */
  onSettled: () => void;
  /** Opens an applied card's record ("Visa" in the receipt); absent: no such link. */
  onOpen?: (target: RoomTarget) => void;
}) {
  const [cards, setCards] = useState<Record<string, CardDecision>>({});
  const [groups, setGroups] = useState<Record<string, GroupDecision>>({});
  const keys = useRef(new Map<string, PendingKey>());
  const keyOf = (scope: string, signature: string) => {
    const next = keyFor(keys.current.get(scope), signature);
    keys.current.set(scope, next);
    return next.key;
  };
  const setCard = useCallback(
    (id: string, next: CardDecision | undefined) =>
      setCards((all) => {
        const copy = { ...all };
        if (next) copy[id] = next;
        else delete copy[id];
        return copy;
      }),
    [],
  );

  /** Undo the approvals in `outcomes` (one call each, at most three). */
  const undoAll = (taken: readonly DecisionOutcome[]) => {
    const undo = api.undo;
    if (!undo) return;
    void Promise.allSettled(
      taken.map((outcome) =>
        undo(
          outcome.suggestion_id,
          outcome.version,
          keyOf(
            `undo:${outcome.suggestion_id}`,
            `${outcome.suggestion_id}:${outcome.version}`,
          ),
        ),
      ),
    ).then((results) => {
      const done = results.filter((r) => r.status === "fulfilled").length;
      for (const outcome of taken)
        setCard(outcome.suggestion_id, {
          decided: { message: t.states.undone ?? t.undo, hold: false },
        });
      receipt.show({
        message: done === taken.length ? t.undone(done) : t.undoFailed,
      });
      onSettled();
    });
  };

  const settle = (ids: readonly string[]) => () => {
    setCards((all) => {
      const copy = { ...all };
      for (const id of ids) {
        const decided = copy[id]?.decided;
        if (decided) copy[id] = { decided: { ...decided, hold: false } };
      }
      return copy;
    });
    onSettled();
  };

  /** Approve or dismiss one card. `confirmed`: the owner saw the trust note (a flagged card). */
  const answer = (
    card: Decidable,
    decision: DecisionAnswer,
    confirmed = false,
  ) => {
    setCard(card.id, { busy: decision });
    const item = {
      suggestion_id: card.id,
      expected_version: card.version,
      decision,
      ...(confirmed && decision === "approve" ? { confirmed: true } : {}),
    };
    api
      .decide([item], keyOf(`card:${card.id}`, JSON.stringify(item)))
      .then((result) => {
        const outcome = result.items.find(
          (entry) => entry.suggestion_id === card.id,
        );
        if (!outcome || outcome.error_code) {
          setCard(card.id, {
            failed: decision,
            applyError: applyErrorOf(outcome?.error_code ?? null),
          });
          return;
        }
        const value = suggestionValue(card.effect, card.summary);
        if (decision === "dismiss") {
          setCard(card.id, {
            decided: { message: t.dismissedCard, hold: true },
          });
          receipt.show({
            message: t.dismissed(value),
            onEnd: settle([card.id]),
          });
          return;
        }
        const target = appliedTarget(outcome.applied, value);
        setCard(card.id, {
          decided: {
            message: addedLine(card.effect, card.summary, t),
            target,
            hold: true,
          },
        });
        receipt.show({
          message: t.approved(value),
          undo: api.undo
            ? { label: t.undo, onUndo: () => undoAll([outcome]) }
            : undefined,
          action:
            target && onOpen
              ? { label: t.show, onClick: () => onOpen(target) }
              : undefined,
          onEnd: settle([card.id]),
        });
      })
      .catch(() => setCard(card.id, { failed: decision }));
  };

  /** Approve `ids` of a safe group (the batch less the rows taken out; at most three). */
  const approveGroup = (inbox: InboxGroup, ids: readonly string[]) => {
    const digestKey = inbox.group.group_digest;
    const chosen = inbox.items
      .filter((item) => ids.includes(item.id))
      .slice(0, MAX_PER_CONFIRMATION);
    if (chosen.length === 0) return;
    const chosenIds = chosen.map((item) => item.id);
    setGroups((all) => ({ ...all, [digestKey]: { busy: true } }));
    // The server's group approved whole goes with its digest, so a group that changed since is refused as a whole. A
    // part of it (a row taken out, or the first three of a larger group) is decided card by card, each at its version.
    const whole = wholeGroup(inbox.group, chosenIds);
    const signature = `${whole ? digestKey : "cards"}:${chosen
      .map((item) => `${item.id}:${item.version}`)
      .join(",")}`;
    const key = keyOf(`group:${digestKey}`, signature);
    const send = () =>
      whole && api.approveGroup
        ? api.approveGroup(digestKey, chosenIds, key)
        : api.decide(
            chosen.map((item) => ({
              suggestion_id: item.id,
              expected_version: item.version,
              decision: "approve" as const,
            })),
            key,
          );
    send()
      .then((result) => {
        const taken = result.items.filter((item) => !item.error_code);
        setGroups((all) => ({
          ...all,
          [digestKey]: {
            decided: t.approvedMany(taken.length),
            note:
              taken.length < chosen.length
                ? t.groupPartly(taken.length, chosen.length)
                : undefined,
          },
        }));
        receipt.show({
          message: t.approvedMany(taken.length),
          undo:
            api.undo && taken.length > 0
              ? { label: t.undo, onUndo: () => undoAll(taken) }
              : undefined,
          onEnd: onSettled,
        });
      })
      .catch((cause: unknown) => {
        // The server refused the group as a whole (it changed since it was shown): read it again.
        const changed =
          cause instanceof HostToolError && /group/.test(cause.code ?? "");
        setGroups((all) => ({
          ...all,
          [digestKey]: changed ? {} : { failed: true },
        }));
        if (changed) {
          receipt.show({ message: t.groupChanged });
          onSettled();
        }
      });
  };

  return {
    card: (id: string): CardDecision => cards[id] ?? {},
    group: (digest: string): GroupDecision => groups[digest] ?? {},
    answer,
    approveGroup,
    /** Forgets the group's own state once a fresh read has replaced it. */
    forgetGroup: (digest: string) =>
      setGroups((all) => {
        if (!(digest in all)) return all;
        const copy = { ...all };
        delete copy[digest];
        return copy;
      }),
  };
}

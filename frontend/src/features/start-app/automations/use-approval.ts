import { useRef, useState } from "react";

import { HostToolError } from "../../mcp-apps/bridge";
import { keyFor, type PendingKey } from "../../mcp-apps/idempotency";
import type { ReceiptState } from "../../mcp-apps/ui/receipt";
import type { AutomationLabels } from "./labels";
import { approveArguments, type AutomationRecord } from "./model";
import type { AutomationTransport } from "./transport";

/** Where the approval of one automation stands in the view. */
export type ApprovalState = {
  /** `confirm`: the separate step of a spec that applies without a click is open. */
  step: "start" | "confirm";
  /** The owner ticked the confirmation in that step. */
  confirmed: boolean;
  busy: boolean;
  failed: boolean;
  /** Approve was pressed in the confirmation step before the box was ticked. */
  tickFirst: boolean;
};

const START: ApprovalState = {
  step: "start",
  confirmed: false,
  busy: false,
  failed: false,
  tickFirst: false,
};

/**
 * The owner's approval of one automation, exactly as shown. A spec that only proposes is approved at once with its
 * digest. A spec that applies suggestions without a click first opens its own confirmation step; only a ticked
 * confirmation sends `auto_apply_confirmed: true` (approveArguments), and nothing is sent before it. One key per
 * action: a retry of the same digest and confirmation reuses it, so the server replays instead of writing twice.
 */
export function useApproval({
  api,
  record,
  t,
  receipt,
  onApproved,
  onChanged,
}: {
  api: AutomationTransport;
  record: AutomationRecord;
  t: AutomationLabels;
  receipt: ReceiptState;
  /** The server's record after the approval. */
  onApproved: (record: AutomationRecord) => void;
  /** The server refused: the spec changed since it was shown. Read it again and say so. */
  onChanged: () => void;
}) {
  const [state, setState] = useState<ApprovalState>(START);
  const pending = useRef<PendingKey | undefined>(undefined);
  const auto = record.apply_mode === "auto_low_risk";

  const send = (confirmed: boolean) => {
    const approve = api.approve;
    if (!approve || state.busy) return;
    const signature = `${record.id}:${record.spec_digest}:${String(auto && confirmed)}`;
    pending.current = keyFor(pending.current, signature);
    const args = approveArguments(record, confirmed, pending.current.key);
    if (!args) {
      setState((now) => ({ ...now, tickFirst: true }));
      return;
    }
    setState((now) => ({
      ...now,
      busy: true,
      failed: false,
      tickFirst: false,
    }));
    approve(args).then(
      (approved) => {
        setState(START);
        onApproved(approved);
        receipt.show({ message: t.approvedReceipt(approved.title) });
      },
      (cause: unknown) => {
        const changed =
          cause instanceof HostToolError &&
          cause.reason === "automation_changed";
        // A changed spec is read again; the step starts over on the new digest (the view keys the card by it).
        setState((now) =>
          changed ? START : { ...now, busy: false, failed: true },
        );
        if (changed) onChanged();
      },
    );
  };

  return {
    state,
    auto,
    /** The first press: approves a spec that only proposes, or opens the confirmation step. */
    begin: () => {
      if (auto) setState({ ...START, step: "confirm" });
      else send(false);
    },
    setConfirmed: (confirmed: boolean) =>
      setState((now) => ({ ...now, confirmed, tickFirst: false })),
    cancel: () => setState(START),
    /** Approve in the confirmation step: sent only with the box ticked. */
    confirm: () => send(state.confirmed),
  };
}

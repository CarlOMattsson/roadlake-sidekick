import { Segmented } from "../../mcp-apps/ui/segmented";
import { labelFor, type JournalLabels } from "../labels";
import type { JournalTaskProposal } from "../transport";
import {
  decisionOptions,
  decisionStatus,
  pairValue,
  proposalName,
} from "./decisions";

function dueText(iso: string, locale: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString(locale, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

/** A task proposal: the Godkänn/Avslå pair is its only control, the details are shown as text. */
export function ProposalCheck({
  proposal,
  taskLabel,
  known,
  checked,
  declined,
  disabled,
  onChange,
  onDeclinedChange,
  labels: t,
}: {
  proposal: JournalTaskProposal;
  taskLabel: (taskId: string) => string;
  known: boolean;
  checked: boolean;
  declined: boolean;
  disabled: boolean;
  onChange: (on: boolean) => void;
  onDeclinedChange: (declined: boolean) => void;
  labels: JournalLabels;
}) {
  const decision = pairValue(checked && known, declined);
  const details: string[] = [];
  const name = proposalName(proposal, taskLabel, t);
  if (proposal.type === "create_task") {
    if (proposal.description)
      details.push(`${t.newDescription}: ${proposal.description}`);
    details.push(
      `${t.newPriority}: ${labelFor(t.priority, proposal.priority)}`,
    );
    if (proposal.due_at)
      details.push(`${t.newDue}: ${dueText(proposal.due_at, t.dateLocale)}`);
  } else {
    if (proposal.title) details.push(`${t.newTitle}: ${proposal.title}`);
    if (proposal.description)
      details.push(`${t.newDescription}: ${proposal.description}`);
    if (proposal.status)
      details.push(
        `${t.newStatus}: ${labelFor(t.taskStatus, proposal.status)}`,
      );
    if (proposal.priority)
      details.push(
        `${t.newPriority}: ${labelFor(t.priority, proposal.priority)}`,
      );
    if (proposal.due_at)
      details.push(`${t.newDue}: ${dueText(proposal.due_at, t.dateLocale)}`);
  }
  return (
    <div className="journal-check journal-check-flat">
      {/* Every row here is Claude's proposal (the section says so), so the row names no source. */}
      <p className="journal-choice">{name}</p>
      <Segmented
        label={t.decisionFor(name)}
        options={decisionOptions(t)}
        value={decision}
        onChange={(next) => {
          onDeclinedChange(next === "decline");
          onChange(next === "approve");
        }}
        disabled={disabled || !known}
      />
      {decision && (
        <p className="journal-muted">{decisionStatus(decision, t)}</p>
      )}
      {!known && <p className="journal-muted">{t.unknownItem}</p>}
      {details.length > 0 && (
        <p className="journal-muted">{details.join(" · ")}</p>
      )}
    </div>
  );
}

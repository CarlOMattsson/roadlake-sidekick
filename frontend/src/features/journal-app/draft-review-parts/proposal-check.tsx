import { ownerToday } from "../../mcp-apps/app-timezone";
import { Segmented } from "../../mcp-apps/ui/segmented";
import { formatShortDateWithYear } from "../dates";
import { labelFor, type JournalLabels } from "../labels";
import type { JournalTaskProposal } from "../transport";
import {
  decisionOptions,
  decisionStatus,
  pairValue,
  proposalName,
} from "./decisions";

/**
 * A due date as the rest of the journal shows dates: "5 nov", with the year only outside the owner's current year.
 * A bare calendar date is that day; an instant is the day it falls on in the owner's zone.
 */
function dueText(value: string, locale: string): string {
  if (/^\d{4}-\d{2}-\d{2}$/.test(value))
    return formatShortDateWithYear(value, locale, ownerToday());
  const instant = new Date(value);
  if (Number.isNaN(instant.getTime())) return value;
  return formatShortDateWithYear(
    ownerToday(undefined, instant),
    locale,
    ownerToday(),
  );
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

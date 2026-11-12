import { Row } from "../../mcp-apps/ui/row";
import type { WorkContactSummary } from "../transport/transport";
import { initialsOf } from "./contact-card";
import { contactMeta } from "./contacts-sections";

/**
 * One Contact in the list. A round grey avatar with the initials leads the row, hidden from assistive
 * tech because the name is read out. The name opens it; an archived Contact shows its label as a chip
 * in the same row, so the chip is part of the row's accessible name.
 */
export function ContactRow({
  contact,
  archivedLabel,
  onOpen,
}: {
  contact: WorkContactSummary;
  archivedLabel: string;
  onOpen: () => void;
}) {
  return (
    <Row
      leading={
        <span aria-hidden="true" className="work-contact-avatar">
          {initialsOf(contact.display_name)}
        </span>
      }
      primary={contact.display_name}
      secondary={contactMeta(contact) || undefined}
      trailing={
        contact.archived ? (
          <span className="work-chip">{archivedLabel}</span>
        ) : undefined
      }
      navigates
      onOpen={onOpen}
    />
  );
}

import { Row } from "../../mcp-apps/ui/row";
import { TagChips } from "../../mcp-apps/ui/tags";
import type { TagOption } from "../../mcp-apps/ui/tag-vocabulary";
import type { WorkContactSummary } from "../transport/transport";
import { initialsOf } from "../../mcp-apps/ui/initials";
import { contactMeta } from "./contacts-sections";

/**
 * One Contact in the list. A round grey avatar with the initials leads the row, hidden from assistive
 * tech because the name is read out. The name opens it; an archived Contact leads its muted meta line with its label
 * ("Arkiverad · Kund · Ek & Söner"), so no chip takes width from the organisation. Its tags follow the meta text, at
 * most two and "+N", so a row keeps its height.
 */
export function ContactRow({
  contact,
  archivedLabel,
  knownTags,
  locale,
  onOpen,
}: {
  contact: WorkContactSummary;
  archivedLabel: string;
  /** The tag vocabulary, for the tags' labels. */
  knownTags?: readonly TagOption[];
  locale: string;
  onOpen: () => void;
}) {
  const meta = [contact.archived ? archivedLabel : "", contactMeta(contact)]
    .filter(Boolean)
    .join(" · ");
  const tags = contact.tags ?? [];
  return (
    <Row
      leading={
        <span aria-hidden="true" className="work-contact-avatar">
          {initialsOf(contact.display_name)}
        </span>
      }
      primary={contact.display_name}
      secondary={
        meta || tags.length > 0 ? (
          <>
            {meta && <span className="sk-row-meta">{meta}</span>}
            <TagChips tags={tags} known={knownTags} max={2} locale={locale} />
          </>
        ) : undefined
      }
      navigates
      onOpen={onOpen}
    />
  );
}

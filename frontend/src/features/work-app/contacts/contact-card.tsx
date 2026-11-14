import { useCallback, useState, type CSSProperties } from "react";
import "../../mcp-apps/ui/tokens.css";
import { initialsOf } from "../../mcp-apps/ui/initials";
import { Fold } from "../../mcp-apps/ui/fold";
import { useRead } from "../../mcp-apps/ui/use-read";
import { CardFoot } from "../../mcp-apps/ui/card";
import { ChevronRightIcon } from "../../mcp-apps/ui/icons";
import { TagChips } from "../../mcp-apps/ui/tags";
import type { HierarchyDetailLabels } from "../hierarchy/hierarchy-detail-labels";
import type { CardLabels } from "../shared/card-labels";
import {
  writeFailure,
  type WorkContactRecord,
  type WorkTransport,
} from "../transport/transport";

export type ContactCardProps = {
  contact: WorkContactRecord;
  transport: WorkTransport;
  labels: CardLabels;
  /** The date locale, for the spoken sentence of the tags. */
  locale: string;
  onOpen: () => void;
  onEdit: () => void;
  /** Shows the address as a line under "role · organization". Only the fullscreen host passes true. */
  showAddress?: boolean;
};

/**
 * Compact card for one Contact: the kind as an eyebrow paragraph, initials, name, the relationship as a chip, role and organization on one line, the
 * address (fullscreen only), the note in two lines, the number of linked Tasks and two actions, `open` and `edit`. The initials are text on a CSS circle, never an image, and
 * are hidden from assistive tech because the name is already read out. The count comes from
 * get_contact_context; if that read fails the line is left out and the card keeps its other content.
 */
export function ContactCard({
  contact,
  transport,
  labels,
  locale,
  onOpen,
  onEdit,
  showAddress = false,
}: ContactCardProps) {
  // The count is kept with the Contact it belongs to, so a count for another Contact is never shown.
  const readCount = useCallback(
    () =>
      transport.getContactContext(contact.id).then((context) => ({
        id: contact.id,
        count: context.tasks.items.length,
        more: context.tasks.next_cursor !== null,
      })),
    [contact.id, transport],
  );
  const [read] = useRead(readCount);
  const linked =
    read.phase === "ready" && read.value.id === contact.id
      ? read.value
      : undefined;
  // Set when the read says the Contact no longer exists: the card then shows only that line, no actions.
  // The count is optional; the card still shows the Contact and its actions, unless it is gone.
  const gone =
    read.phase === "failed" && writeFailure(read.cause) === "not_found";

  if (gone) {
    return (
      <section className="work-compact-card sk-card">
        <p className="sk-eyebrow">{labels.kind.contact}</p>
        <p role="status" className="work-compact-status">
          {labels.goneContact}
        </p>
      </section>
    );
  }

  // Role and organization as one line. The address is shown only in fullscreen (showAddress), never inline.
  const roleAndOrganization = [contact.role, contact.organization]
    .filter(Boolean)
    .join(" · ");
  return (
    <section
      className="work-compact-card sk-card"
      aria-label={contact.display_name}
    >
      <p className="sk-eyebrow">{labels.kind.contact}</p>
      <div style={headStyle}>
        <span aria-hidden="true" style={initialsStyle}>
          {initialsOf(contact.display_name)}
        </span>
        <p className="work-compact-title" style={titleStyle}>
          {contact.display_name}
        </p>
      </div>
      {contact.relationship ? (
        <p>
          <span className="work-contact-relation">{contact.relationship}</span>
        </p>
      ) : null}
      {roleAndOrganization ? (
        <p className="work-compact-status">{roleAndOrganization}</p>
      ) : null}
      {showAddress && contact.address ? (
        <p className="work-compact-status">{contact.address}</p>
      ) : null}
      {contact.context_note ? (
        <p className="work-compact-note">{contact.context_note}</p>
      ) : null}
      {contact.tags?.length ? (
        <p>
          <TagChips tags={contact.tags} max={2} locale={locale} />
        </p>
      ) : null}
      {linked ? (
        <p className="work-compact-status">
          {`${labels.connections}: ${linked.count}${linked.more ? "+" : ""}`}
        </p>
      ) : null}
      <CardFoot>
        <button
          type="button"
          className="work-compact-action sk-btn--open"
          onClick={onOpen}
        >
          {labels.open}
          <ChevronRightIcon />
        </button>
      </CardFoot>
      <button type="button" className="work-compact-action" onClick={onEdit}>
        {labels.edit}
      </button>
    </section>
  );
}

const headStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "var(--sk-s2)",
  minWidth: 0,
};

const titleStyle: CSSProperties = {
  margin: 0,
  minWidth: 0,
};

const initialsStyle: CSSProperties = {
  flex: "0 0 auto",
  display: "grid",
  placeItems: "center",
  width: "2.25rem",
  height: "2.25rem",
  borderRadius: "50%",
  background: "var(--sk-surface)",
  border: "var(--sk-hairline) solid var(--sk-line)",
  color: "var(--sk-fg)",
  fontFamily: "var(--sk-font)",
  fontSize: "var(--sk-text-sm)",
  fontWeight: "var(--sk-weight-semibold)",
  lineHeight: 1,
  userSelect: "none",
};

/**
 * The `waysToReach` fold ⌄ after the `aboutContact` paragraph (design system §3, Contact view):
 * a foldable section, its label in the section heading style of `aboutContact` and `tasks` with ⌄ on the content edge
 * (as a row it read as a list item), and a meta line naming what is there (the `wayWords`). Closed by default. Open, the values are rows on the title's x with no labels;
 * e-mail and phone open through the host (`onOpenLink`, bridge ui/open-link), or as plain links without one.
 * Without any value the row is left out.
 */
export function ContactWays({
  contact,
  labels,
  onOpenLink,
}: {
  contact: WorkContactRecord;
  labels: HierarchyDetailLabels;
  onOpenLink?: (url: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const { email, phone, address } = contact;
  const values = [
    email && `mailto:${email}`,
    phone && `tel:${phone.replace(/[^\d+]/gu, "")}`,
    address,
  ];
  const kinds = labels.wayWords.filter((_, index) => values[index]);
  if (!kinds.length) return null;
  const meta = new Intl.ListFormat(labels.wayLocale).format(kinds);
  return (
    <section className="work-contact-ways">
      {/* The fold row: `waysToReach` ⌄ with what it holds (`wayWords`) as its meta line. */}
      <Fold
        text={labels.waysToReach}
        meta={meta.charAt(0).toUpperCase() + meta.slice(1)}
        open={open}
        onToggle={() => setOpen(!open)}
      />
      {open && (
        <ul className="work-list">
          {[email, phone, address].map((value, index) => {
            const href = values[index];
            if (!value || !href) return null;
            return (
              <li key={index}>
                {index < 2 ? (
                  <a
                    href={href}
                    onClick={
                      onOpenLink &&
                      ((event) => {
                        event.preventDefault();
                        onOpenLink(href);
                      })
                    }
                  >
                    {value}
                  </a>
                ) : (
                  value
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

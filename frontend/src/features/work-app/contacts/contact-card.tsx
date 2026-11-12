import { useEffect, useState, type CSSProperties } from "react";
import "../../mcp-apps/ui/tokens.css";
import { Fold } from "../../mcp-apps/ui/fold";
import { CardFoot } from "../../mcp-apps/ui/card";
import { ChevronRightIcon } from "../../mcp-apps/ui/icons";
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
  onOpen: () => void;
  onEdit: () => void;
  /** Shows the address as a line under "role · organization". Only the fullscreen host passes true. */
  showAddress?: boolean;
};

/**
 * Compact card for one Contact: the kind as an eyebrow paragraph, initials, name, the relationship as a chip, "role · organization", the
 * address (fullscreen only), the note in two lines, the number of linked Tasks and two actions, "Open" and "Edit". The initials are text on a CSS circle, never an image, and
 * are hidden from assistive tech because the name is already read out. The count comes from
 * get_contact_context; if that read fails the line is left out and the card keeps its other content.
 */
export function ContactCard({
  contact,
  transport,
  labels,
  onOpen,
  onEdit,
  showAddress = false,
}: ContactCardProps) {
  // The count is kept with the Contact it belongs to, so a count for another Contact is never shown.
  const [read, setRead] = useState<{
    id: string;
    count: number;
    more: boolean;
  }>();
  const linked = read?.id === contact.id ? read : undefined;
  // Set when the read says the Contact no longer exists: the card then shows only that line, no actions.
  const [gone, setGone] = useState(false);

  useEffect(() => {
    let live = true;
    transport
      .getContactContext(contact.id)
      .then((context) => {
        if (live)
          setRead({
            id: contact.id,
            count: context.tasks.items.length,
            more: context.tasks.next_cursor !== null,
          });
      })
      .catch((error: unknown) => {
        // The count is optional; the card still shows the Contact and its actions, unless it is gone.
        if (live && writeFailure(error) === "not_found") setGone(true);
      });
    return () => {
      live = false;
    };
  }, [contact.id, transport]);

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

/**
 * Up to two letters: the first letter of the first and the last word, or the first two letters of
 * a single word. Only letters and digits count, so punctuation never becomes an initial. Text in parentheses is a note,
 * not a name: "Kerstin Åberg (innebandylaget)" is "KÅ", unless the name is nothing else.
 */
export function initialsOf(name: string): string {
  const bare = name.replace(/\([^)]*\)?/gu, " ").trim();
  const words = (bare || name)
    .split(/\s+/u)
    .map((word) =>
      Array.from(word)
        .filter((ch) => /[\p{L}\p{N}]/u.test(ch))
        .join(""),
    )
    .filter((word) => word !== "");
  if (words.length === 0) return "?";
  const head = Array.from(words[0] ?? "");
  const tail = Array.from(words[words.length - 1] ?? "");
  const letters =
    words.length === 1 ? head.slice(0, 2) : [head[0] ?? "", tail[0] ?? ""];
  return letters.join("").toLocaleUpperCase();
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
 * "Kontaktvägar ⌄" (en "Ways to reach") after "Om Anna" (design system §3, Kontaktvyn):
 * a foldable section, its label in the section heading style of "Om Anna" and "Uppgifter" with ⌄ on the content edge
 * (as a row it read as a list item), and a meta line naming what is there ("E-post och telefon"). Closed by default. Open, the values are rows on the title's x with no labels;
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
      {/* The fold row: "Kontaktvägar ⌄" with what it holds ("E-post och telefon") as its meta line. */}
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

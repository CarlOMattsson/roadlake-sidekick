import type { ReactNode } from "react";

export type DisclosureKey = "keyPoints" | "relations" | "proposals";

/**
 * A section of the draft as a disclosure. Inline it is a closed row with its count ("Uppgiftsförslag (8)",
 * aria-expanded) and the heading is hidden; fullscreen shows the heading and the whole body, as before (the
 * CSS in journal.css decides which). The body stays mounted when closed, so each row keeps the owner's choices.
 */
export function Disclosure({
  id,
  title,
  count,
  open,
  onToggle,
  children,
}: {
  id: string;
  title: string;
  count: number;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  return (
    <section className="journal-disclosure" data-open={open ? "true" : "false"}>
      <h3 className="journal-disclosure-head">{title}</h3>
      <button
        type="button"
        className="sk-btn--quiet journal-disclosure-toggle"
        aria-expanded={open}
        aria-controls={id}
        onClick={onToggle}
      >
        <span>
          {title} ({count})
        </span>
        <span aria-hidden="true">{open ? "▴" : "▾"}</span>
      </button>
      <div id={id} className="journal-disclosure-body">
        {children}
      </div>
    </section>
  );
}

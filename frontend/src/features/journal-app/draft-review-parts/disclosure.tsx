import type { ReactNode } from "react";
import { Fold } from "../../mcp-apps/ui/fold";

export type DisclosureKey = "keyPoints" | "relations" | "proposals";

/**
 * A section of the draft as a disclosure. Inline it is the app's fold row with its count and ⌄
 * (aria-expanded), each on a line of its own, and the heading is hidden; fullscreen shows the heading and the
 * whole body, as before (the CSS in journal.css decides which). The body stays mounted when closed, so each row keeps
 * the owner's choices.
 */
export function Disclosure({
  id,
  title,
  foldTitle = title,
  count,
  open,
  onToggle,
  children,
}: {
  id: string;
  title: string;
  /** The fold row's name inline, when the heading's is too long for one line at 320 px. */
  foldTitle?: string;
  count: number;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  return (
    <section className="journal-disclosure" data-open={open ? "true" : "false"}>
      <h3 className="journal-disclosure-head">{title}</h3>
      <Fold
        className="journal-disclosure-toggle"
        text={`${foldTitle} (${count})`}
        open={open}
        onToggle={onToggle}
        controls={id}
      />
      <div id={id} className="journal-disclosure-body">
        {children}
      </div>
    </section>
  );
}

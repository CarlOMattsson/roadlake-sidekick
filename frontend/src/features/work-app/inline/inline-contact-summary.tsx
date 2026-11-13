import { CardFoot } from "../../mcp-apps/ui/card";
import { ChevronRightIcon } from "../../mcp-apps/ui/icons";
import { TagChips } from "../../mcp-apps/ui/tags";
import type { InlineSummaryLabels } from "./inline-summary-labels";
import "./inline-summary.css";

/** How many Projects and Tasks a Contact is linked to, counted on its context read; `more` marks a partial read. */
export type ContactLinkCounts = {
  projects: number;
  projectsMore: boolean;
  tasks: number;
  tasksMore: boolean;
};

/**
 * The inline Contact card: the kind label, the name, the relationship as a small chip (when set), one
 * meta line with "role · organization" (or the e-mail when neither is set) and the counts of its
 * Projects and Tasks (a count is shown only when there is one), and "Open", which asks the host for
 * fullscreen. The address is never shown inline. The card has no fields and no Edit: the Contact view
 * with its editor is shown in fullscreen only. `counts` is absent while the read runs or when it
 * failed; the card then shows what it has.
 */
export function ContactSummary({
  kindLabel,
  name,
  email,
  relationship,
  organization,
  role,
  tags,
  aliases,
  counts,
  labels,
  onOpen,
}: {
  kindLabel: string;
  name: string;
  email: string | null;
  relationship?: string | null;
  organization?: string | null;
  role?: string | null;
  /** The Contact's tags; the card shows two and "+N". */
  tags?: readonly string[];
  /** The Contact's nicknames, one line under the name. */
  aliases?: readonly string[];
  counts?: ContactLinkCounts;
  labels: InlineSummaryLabels;
  /** Asks the host for fullscreen; the caller passes it only when the host can show it. */
  onOpen: () => void;
}) {
  const meta: string[] = [];
  const roleAndOrganization = [role, organization].filter(Boolean).join(" · ");
  if (roleAndOrganization) meta.push(roleAndOrganization);
  else if (email) meta.push(email);
  if (counts && (counts.projects > 0 || counts.projectsMore))
    meta.push(
      `${labels.projectCount}: ${counts.projects}${counts.projectsMore ? "+" : ""}`,
    );
  if (counts && (counts.tasks > 0 || counts.tasksMore))
    meta.push(
      `${labels.taskCount}: ${counts.tasks}${counts.tasksMore ? "+" : ""}`,
    );
  return (
    <section
      className="work-compact-card sk-card work-compact-contact"
      aria-label={kindLabel}
    >
      <div className="work-compact-contact-text">
        <p className="work-compact-kind sk-eyebrow">{kindLabel}</p>
        <p className="work-compact-title sk-card__title">{name}</p>
        {relationship ? (
          <p>
            <span className="work-chip">{relationship}</span>
          </p>
        ) : null}
        {aliases && aliases.length > 0 ? (
          <p className="work-compact-status work-compact-aliases">
            {labels.alsoKnownAs(aliases.join(", "))}
          </p>
        ) : null}
        {meta.length > 0 ? (
          <p className="work-compact-status">{meta.join(" · ")}</p>
        ) : null}
        {tags && tags.length > 0 ? (
          <p>
            <TagChips tags={tags} max={2} locale={labels.dateLocale} />
          </p>
        ) : null}
      </div>
      <CardFoot>
        <button
          type="button"
          className="work-compact-action sk-btn--open"
          onClick={onOpen}
        >
          {labels.showContact}
          <ChevronRightIcon />
        </button>
      </CardFoot>
    </section>
  );
}

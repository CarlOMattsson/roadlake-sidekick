import { Card } from "../../mcp-apps/ui/card";
import { OpenLink } from "../../mcp-apps/ui/open-link";
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
 * The inline Contact card, in the family's `Card` (kicker: the app and the kind; title: the name): the relationship as a small chip (when set), one
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
    <Card
      className="work-compact-card work-compact-contact"
      aria-label={kindLabel}
      eyebrow={`${labels.appName} · ${kindLabel}`}
      title={name}
    >
      <div className="work-compact-contact-text">
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
      <OpenLink label={labels.showContact} onOpen={onOpen} />
    </Card>
  );
}

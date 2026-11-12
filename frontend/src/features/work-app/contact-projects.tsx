import { projectStatusLabel, type WorkLabels } from "./labels";
import { FolderIcon } from "../mcp-apps/ui/icons";
import { linksLabelsFor } from "./links-labels";
import { LinkedRow, LinkedRowTip, linkedRowHint } from "./linked-row";
import { OpenChevron, RowUndo } from "./task-detail-controls";
import type { WorkProjectSummary } from "./transport";

export type ContactProjectsProps = {
  /** The Projects the Contact is linked to, as get_contact_context returned them. */
  projects: WorkProjectSummary[];
  /** Projects whose link was removed from a row's menu ("gone"); their rows offer Ångra. */
  gone?: Record<string, string | undefined>;
  busy?: boolean;
  /** Removes a Project's link from the row's own menu; absent, the rows have no menu. */
  onRemove?: (projectId: string) => void;
  onUndo?: (projectId: string) => void;
  onExpire?: (projectId: string) => void;
  /** Opens a Project in the app. */
  onOpen: (projectId: string) => void;
  labels: WorkLabels;
};

/**
 * The Projects a Contact is linked to, under the heading "Projekt", in the shared row (design system §3, Listrad and
 * Kontaktvyn): FolderIcon in the leading column, the title on 52 that opens the Project, the status as the meta
 * line with no "Status:" label ("Aktivt"), and ›. The link is removed from the row's own menu (long press, right click,
 * Shift+F10: "Ta bort koppling"); the row then stays with "Kopplingen borttagen · Ångra". With no Project the section
 * is left out.
 */
export function ContactProjects({
  projects,
  gone = {},
  busy = false,
  onRemove,
  onUndo,
  onExpire,
  onOpen,
  labels: t,
}: ContactProjectsProps) {
  if (!projects.length) return null;
  return (
    <>
      <h3>{t.projects}</h3>
      <ul className="work-list">
        {projects.map((project) => (
          <LinkedRow
            key={project.id}
            title={project.title}
            gone={gone[project.id] === "gone"}
            busy={busy}
            onRemove={onRemove && (() => onRemove(project.id))}
            labels={t}
          >
            <div className="work-agenda-line">
              <span className="work-agenda-glyph" aria-hidden="true">
                <FolderIcon />
              </span>
              <div className="work-agenda-body">
                <button
                  type="button"
                  aria-keyshortcuts={
                    onRemove && !gone[project.id] ? "Shift+F10" : undefined
                  }
                  aria-description={
                    onRemove && !gone[project.id] ? linkedRowHint(t) : undefined
                  }
                  onClick={() => onOpen(project.id)}
                >
                  {project.title}
                </button>
                {gone[project.id] && onUndo ? (
                  <p role="status" className="work-card-meta">
                    {linksLabelsFor(t.dateLocale).linkRemoved}
                  </p>
                ) : (
                  <p className="work-card-meta">
                    {projectStatusLabel(t, project.status)}
                  </p>
                )}
              </div>
              {gone[project.id] && onUndo ? (
                <RowUndo
                  label={t.agendaUndo}
                  disabled={busy}
                  onUndo={() => onUndo(project.id)}
                  onExpire={() => onExpire?.(project.id)}
                />
              ) : (
                <OpenChevron />
              )}
            </div>
          </LinkedRow>
        ))}
      </ul>
      {onRemove && <LinkedRowTip labels={t} />}
    </>
  );
}

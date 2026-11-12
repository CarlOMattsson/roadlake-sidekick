import { CycleIcon, FolderIcon } from "../../mcp-apps/ui/icons";
import { type HierarchyDetailLabels } from "./hierarchy-detail-labels";
import type { GroupCounts } from "./hierarchy-tree";
import {
  hierarchyStatusLabel,
  workKindLabel,
  type WorkLabels,
} from "../shared/labels";
import { OpenChevron } from "../tasks/task-detail-controls";
import {
  domainAccentOf,
  type WorkFrame,
  type WorkHierarchyNode,
} from "../transport/transport";

/** The meta line of a Project or Process: what is not the default, the counts, and the overdue count in its tone. */
function GroupMeta({
  node,
  counts,
  domainTitle,
  t,
  dl,
}: {
  node: WorkHierarchyNode;
  counts: GroupCounts | undefined;
  /** In the completed group, the Domain the Project belonged to. */
  domainTitle?: string;
  t: WorkLabels;
  dl: HierarchyDetailLabels;
}) {
  const process = node.kind === "process";
  // "Aktivt" is the default and says nothing; a completed Project is in its own group, which says it.
  const status =
    node.status !== undefined &&
    node.status !== "active" &&
    node.status !== "completed"
      ? hierarchyStatusLabel(t, node.kind, node.status)
      : undefined;
  return (
    <p className="work-card-meta">
      {process ? <span>{workKindLabel(t, "process")}</span> : null}
      {status ? <span>{status}</span> : null}
      {domainTitle ? <span>{domainTitle}</span> : null}
      {counts &&
      !process &&
      !(node.status === "completed" && counts.total === 0) ? (
        <span>
          {counts.total > 0
            ? t.progressOf(counts.done, counts.total)
            : dl.noTasks}
        </span>
      ) : null}
      {counts && process ? (
        <span>{dl.openTasks(counts.total - counts.done)}</span>
      ) : null}
      {counts && counts.overdue > 0 ? (
        <span className="work-tree-overdue">{dl.overdue(counts.overdue)}</span>
      ) : null}
    </p>
  );
}

/** One Project or Process: its symbol, the title that opens its page, the meta line and ›. */
export function GroupRow({
  node,
  counts,
  domainTitle,
  t,
  dl,
  onOpen,
}: {
  node: WorkHierarchyNode;
  counts: GroupCounts | undefined;
  domainTitle?: string;
  t: WorkLabels;
  dl: HierarchyDetailLabels;
  onOpen?: (frame: WorkFrame, label?: string) => void;
}) {
  const process = node.kind === "process";
  const kind = workKindLabel(t, node.kind);
  return (
    <li className="work-tree-row" data-kind={node.kind}>
      <div className="work-agenda-line">
        <span className="work-agenda-glyph" aria-hidden="true">
          {process ? <CycleIcon /> : <FolderIcon />}
        </span>
        <div className="work-agenda-body">
          {onOpen ? (
            <button
              type="button"
              className="work-tree-open"
              onClick={() =>
                onOpen(
                  process
                    ? { kind: "process", id: node.id }
                    : { kind: "project", id: node.id },
                  node.title,
                )
              }
            >
              {node.title}
              {/* The symbol is decoration; the kind is said once, after the title. A Process says it in the meta. */}
              {process ? null : (
                <span className="work-visually-hidden">, {kind}</span>
              )}
            </button>
          ) : (
            <p className="work-tree-title">{node.title}</p>
          )}
          <GroupMeta
            node={node}
            counts={counts}
            domainTitle={domainTitle}
            t={t}
            dl={dl}
          />
        </div>
        {onOpen ? <OpenChevron /> : null}
      </div>
    </li>
  );
}

/** The Domain's colour dot before its name, when it has one; decoration only. */
export function DomainAccent({ node }: { node: WorkHierarchyNode }) {
  const accent = domainAccentOf(node.accent);
  return accent ? (
    <span
      className="work-accent hierarchy-accent"
      data-accent={accent}
      aria-hidden="true"
    >
      ●
    </span>
  ) : null;
}

import { vi } from "vitest";
import {
  type WorkHierarchyFrame,
  type WorkHierarchyNode,
  type WorkHierarchyTask,
  type WorkTransport,
} from "@/features/work-app/transport/transport";

export const domain: WorkHierarchyNode = {
  kind: "domain",
  id: "019f0000-0000-7000-8000-0000000000h1",
  parent_id: null,
  title: "Ekonomi",
  status: "active",
  version: 1,
};
export const project: WorkHierarchyNode = {
  kind: "project",
  id: "019f0000-0000-7000-8000-0000000000d1",
  parent_id: domain.id,
  title: "Offert till Anna",
  status: "active",
  version: 1,
};
export const processNode: WorkHierarchyNode = {
  kind: "process",
  id: "019f0000-0000-7000-8000-0000000000p1",
  parent_id: domain.id,
  title: "Fakturering",
  status: "active",
  version: 1,
};

export function frameOf(
  nodes: WorkHierarchyNode[],
  tasks?: WorkHierarchyTask[],
): WorkHierarchyFrame {
  return {
    kind: "hierarchy",
    nodes,
    truncated: false,
    ...(tasks ? { tasks } : {}),
  };
}

export function taskOf(
  id: string,
  parent: WorkHierarchyNode,
  fields: Partial<WorkHierarchyTask> = {},
): WorkHierarchyTask {
  return {
    id,
    parent_id: parent.id,
    title: `Uppgift ${id}`,
    status: "todo",
    version: 1,
    due_at: null,
    steps: [],
    ...fields,
  };
}

/** A transport whose only read is getWorkHierarchy; the list view calls nothing else. */
export function transport(
  getWorkHierarchy = vi.fn(),
  host: Partial<Pick<WorkTransport, "supportsTool" | "supportsCall">> = {},
): WorkTransport {
  return { getWorkHierarchy, ...host } as unknown as WorkTransport;
}

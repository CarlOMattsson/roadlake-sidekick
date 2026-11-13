import type { WorkFrame, WorkTransport } from "../transport/transport";

/** What Try again reads after a failed first result, and the notice subject that names that read. */
export type FirstRead = {
  /** The key of the heading in the shared read notice (ErrorNotice `subject`). */
  subject: string;
  read: (transport: WorkTransport) => Promise<WorkFrame>;
};

/**
 * The read behind Try again for an error result in the Work room. The result names no tool and no record, only the
 * view of the card it landed in, so the reads that need no argument are the ones that can be repeated: the Projects
 * for a hierarchy card, the agenda for everything else. The heading names that read, so it never claims more than
 * Try again will bring back.
 */
export function firstReadFor(view: string | undefined): FirstRead {
  if (view === "hierarchy")
    return { subject: "work:hierarchy", read: (t) => t.getWorkHierarchy() };
  return {
    subject: "work",
    read: (t) =>
      t
        .getWorkAgenda({})
        .then((page) => ({ kind: "agenda", filters: {}, page })),
  };
}

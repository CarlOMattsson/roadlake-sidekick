import type {
  WorkAgendaFrame,
  WorkBoardFrame,
  WorkFilters,
  WorkFrame,
  WorkHierarchyFrame,
  WorkTransport,
} from "../transport";
import type { WorkTab } from "../work-shell";

export const TABS: readonly WorkTab[] = ["agenda", "board", "hierarchy"];

/** One value per tab, filled in as the tabs are used. */
export type PerTab<T> = Partial<Record<WorkTab, T>>;

/** The frames the fullscreen tabs show. Other frame kinds stay inline in the view. */
export type WorkTabFrame =
  | WorkAgendaFrame
  | WorkBoardFrame
  | WorkHierarchyFrame;

/** The count of unsorted Tasks the To sort row shows: the first page read, and whether more follow it. */
export type UnsortedCount = { count: number; more: boolean };
/** The row counts with the server's maximum page, so most libraries fit in one read. */
export const UNSORTED_COUNT_LIMIT = 100;

export type TabEntry =
  | { status: "loading" }
  /** A failed read: why (for the notice's second line), and whether "Försök igen" is reading again now. */
  | { status: "error"; cause: unknown; retrying?: boolean }
  | { status: "ready"; frame: WorkTabFrame };
export type TabEntries = PerTab<TabEntry>;

/** The filters a tab shows now: an agenda or board frame that is ready carries them; otherwise none. */
export function filtersOf(entry: TabEntry | undefined): WorkFilters {
  if (entry?.status !== "ready") return {};
  const frame = entry.frame;
  return frame.kind === "agenda" || frame.kind === "board" ? frame.filters : {};
}

export function isTabFrame(frame: WorkFrame): frame is WorkTabFrame {
  return (
    frame.kind === "agenda" ||
    frame.kind === "board" ||
    frame.kind === "hierarchy"
  );
}

/** The calls of the transport that only read; every other call is taken for a write. */
const READS = /^(get|list|search|supports)/;

/**
 * The transport as one view uses it: when one of its writes has been answered, `onWrote` says so at once, so the
 * write is tied to the view that made it and not to the tab that happens to be shown when the answer comes.
 */
export function marking(
  transport: WorkTransport,
  onWrote: () => void,
): WorkTransport {
  return new Proxy(transport, {
    get(target, name, receiver) {
      const member: unknown = Reflect.get(target, name, receiver);
      if (
        typeof name !== "string" ||
        typeof member !== "function" ||
        READS.test(name)
      )
        return member;
      return (...args: unknown[]) => {
        const answer: unknown = member.apply(target, args);
        if (!(answer instanceof Promise)) return answer;
        return answer.then((value: unknown) => {
          onWrote();
          return value;
        });
      };
    },
  });
}

/** Reads the first page of one tab. */
export async function readTab(
  transport: WorkTransport,
  tab: WorkTab,
  withTasks: boolean,
): Promise<WorkTabFrame> {
  switch (tab) {
    case "agenda":
      return {
        kind: "agenda",
        filters: {},
        page: await transport.getWorkAgenda({}),
      };
    case "board":
      return {
        kind: "board",
        filters: {},
        page: await transport.getWorkBoard({}),
      };
    case "hierarchy":
      // The Projects tab counts each Project's Tasks, so it reads them along whenever the host can answer that.
      return transport.getWorkHierarchy({ includeTasks: withTasks });
  }
}

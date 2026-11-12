import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { vi } from "vitest";
import { BoardQuery, BoardView } from "@/features/work-app/board/board";
import { workEn } from "@/features/work-app/shared/labels";
import type {
  WorkBoardFrame,
  WorkBoardPage,
  WorkItemRecord,
  WorkTransport,
} from "@/features/work-app/transport/transport";

/*
 * The Work board on a phone (the "single" layout): the statuses as sections of one list, each with its
 * count in its heading, and Klar folded under a button. jsdom has no layout, so the layout is forced with
 * the `layout` prop; the measured "auto" mode is tested with a stubbed ResizeObserver. These are
 * simulated-host tests, not a test in a real Claude or Android host. The 44 px targets are sized in
 * work.css and are not measured here.
 */

export const KEY =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

export function task(n: number, status: string, title: string): WorkItemRecord {
  return {
    kind: "task",
    id: `019f0000-0000-7000-8000-00000000000${n}`,
    title,
    status,
    due_at: null,
    version: 1,
  };
}
export const a = task(1, "todo", "Ring Anna om offerten");
export const b = task(2, "todo", "Skicka faktura");
export const c = task(3, "in_progress", "Bygg webbplatsen");
export const d = task(4, "completed", "Boka revisorn");
export const project: WorkItemRecord = {
  kind: "project",
  id: "019f0000-0000-7000-8000-0000000000f1",
  title: "Renovering",
  status: "active",
  due_at: null,
  version: 1,
};
export const page: WorkBoardPage = {
  columns: {
    todo: [a, b],
    in_progress: [c],
    blocked: [],
    completed: [d],
    active: [project],
  },
  next_cursor: null,
};

export function transport(
  overrides: Partial<WorkTransport> = {},
): WorkTransport {
  return {
    updateTask: vi.fn(),
    getWorkBoard: vi.fn().mockResolvedValue(page),
    getTask: vi.fn(),
    reorderBoardColumn: vi.fn().mockResolvedValue({ items: [] }),
    ...overrides,
  } as unknown as WorkTransport;
}

/** The parent that owns the frame, as WorkView does: onChange replaces it. */
export function Harness({
  work,
  initial = { kind: "board", filters: {}, page },
  layout = "single",
  onChange,
  labels = workEn,
}: {
  work: WorkTransport;
  initial?: WorkBoardFrame;
  layout?: "auto" | "columns" | "single";
  onChange?: (next: WorkBoardFrame) => void;
  labels?: typeof workEn;
}) {
  const [frame, setFrame] = useState(initial);
  return (
    <BoardView
      frame={frame}
      onChange={(next) => {
        onChange?.(next);
        setFrame(next);
      }}
      transport={work}
      labels={labels}
      moves={0}
      onOpen={vi.fn()}
      layout={layout}
    />
  );
}

/** The board under a search text, as the fullscreen shell provides it around the Status tab. */
export function search(work: WorkTransport, query: string) {
  return (
    <BoardQuery.Provider value={query}>
      <Harness work={work} />
    </BoardQuery.Provider>
  );
}

/** The card's own list item, found by its title (the title is the button the keys open the group from). */
export function rowOf(title: string): HTMLElement {
  return screen
    .getByRole("button", { name: title })
    .closest("li") as HTMLElement;
}

/** Opens a card's quick choices from the keyboard: focus on its title, then Shift+F10. */
export async function openGroup(
  user: ReturnType<typeof userEvent.setup>,
  title: string,
) {
  act(() => screen.getByRole("button", { name: title }).focus());
  await user.keyboard("{Shift>}{F10}{/Shift}");
}

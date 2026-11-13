import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import { UNDO_MS } from "@/features/mcp-apps/ui/undo-hold";
import { BoardView } from "@/features/work-app/board/board";
import { InlineSummary } from "@/features/work-app/inline/inline-summary";
import { inlineSummaryLabelsSv } from "@/features/work-app/inline/inline-summary-labels";
import { workEn, workStatusLabel } from "@/features/work-app/shared/labels";
import {
  TASK_STATUSES,
  type WorkBoardPage,
  type WorkItemRecord,
} from "@/features/work-app/transport/transport";
import {
  taskA,
  transport,
  rootBoard,
  rect,
  handleOf,
} from "./helpers/board-kanban-fixtures";
import { readStylesheet } from "./helpers/stylesheet";

beforeAll(() => {
  // jsdom has no pointer capture; the board only asks for it, so a no-op is enough here.
  if (!("setPointerCapture" in HTMLElement.prototype))
    Object.defineProperty(HTMLElement.prototype, "setPointerCapture", {
      value: () => undefined,
    });
});

beforeEach(() => {
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(
    function (this: Element) {
      if (this.tagName === "ARTICLE") return rect(0, 0, 600, 400);
      const section = this.closest("[data-board-column]");
      if (!section) return rect(0, 0, 0, 0);
      const columns = Array.from(
        document.querySelectorAll("[data-board-column]"),
      );
      const left = columns.indexOf(section) * 100;
      if (this.hasAttribute("data-board-column"))
        return rect(left, 0, 100, 400);
      const cards = Array.from(section.querySelectorAll("[data-card-id]"));
      return rect(left + 8, 40 + cards.indexOf(this) * 60, 84, 40);
    },
  );
});

afterEach(() => {
  vi.restoreAllMocks();
});

const ROOM = { room: "sidekick-work" };

describe("fullscreen board: Undo in the card, quick choices and meta line", () => {
  // jsdom applies no CSS, so the layout rules are read from work.css and compared declaration by declaration.
  const workCss = readStylesheet("features/work-app/shell/work.css");

  it("the columns share the row from a 13.25rem minimum, the Projects column is a row of its own, and no column scrolls by itself", () => {
    expect(
      workCss.rule('.sk-shell[data-detail="closed"] .work-columns'),
    ).toMatchObject({
      "--work-column-min": "13.25rem",
      "grid-template-columns": "repeat(4, minmax(var(--work-column-min), 1fr))",
      "overflow-x": "auto",
    });
    expect(
      workCss.rule(
        '.sk-shell[data-detail="closed"] .work-columns > .work-column[data-board-column="project"]',
      )["grid-column"],
    ).toBe("1 / -1");
    // The page grows with the cards: a column has no height cap and no vertical scroll of its own.
    for (const rule of workCss.rules) {
      expect([undefined, "none"], rule.selector).toContain(
        rule.declarations["max-height"],
      );
      expect(rule.declarations["overflow-y"], rule.selector).not.toBe("auto");
    }
  });

  it("after an arrow move the Undo sits in the moved card's own line, with no foot under the columns", async () => {
    const user = userEvent.setup();
    render(rootBoard(transport()));
    act(() => handleOf(taskA.title).focus());

    await user.keyboard("{Shift>}{ArrowRight}{/Shift}");

    const undo = await screen.findByRole("button", {
      name: workEn.agendaUndo,
    });
    await waitFor(() => expect(undo).toBeEnabled());
    const wrap = undo.closest(".work-agenda-undo");
    const card = undo.closest("li");
    if (!wrap || !card) throw new Error("no Undo line in a card");
    const line = within(wrap as HTMLElement).getByRole("status");
    // The card stays in its new column, and its line says the new status beside the Undo button.
    expect(card).toHaveAttribute("data-card-id", taskA.id);
    expect(card).toContainElement(wrap as HTMLElement);
    expect(
      screen.getByRole("region", { name: workEn.taskStatus.in_progress }),
    ).toContainElement(card);
    expect(wrap).toHaveClass("work-agenda-undo");
    expect(line).toHaveTextContent(workEn.taskStatus.in_progress);
    expect(line).not.toContainElement(undo);
    expect(document.querySelectorAll(".work-agenda-undo")).toHaveLength(1);
    // The foot under the columns and the notice are gone: the Undo lives in the card.
    expect(document.querySelector(".work-board-undo")).toBeNull();
    expect(document.querySelector(".sk-notice")).toBeNull();
  });

  it("the move group sits inside the card, lists all four statuses with the current one pressed, and has no Cancel", async () => {
    const user = userEvent.setup();
    render(rootBoard(transport()));

    act(() => handleOf(taskA.title).focus());
    await user.keyboard("{Shift>}{F10}{/Shift}");

    const menu = screen.getByRole("group", {
      name: workEn.moveListFor(taskA.title),
    });
    // The group is part of the card's own flow, not a floating menu over the board.
    expect(handleOf(taskA.title).closest("li")).toContainElement(menu);
    for (const status of TASK_STATUSES) {
      expect(
        within(menu).getByRole("button", {
          name: workStatusLabel(workEn, status),
        }),
      ).toHaveAttribute(
        "aria-pressed",
        status === taskA.status ? "true" : "false",
      );
    }
    expect(
      within(menu).queryByRole("button", { name: workEn.cancel }),
    ).toBeNull();
  });

  it("the meta line of a board card carries its full text as a title, and is cut with an ellipsis on the board", () => {
    const withProject: WorkItemRecord = {
      ...taskA,
      project_title: "Bokslut och skatt",
      due_at: "2099-01-15T09:00:00Z",
    };
    render(
      <BoardView
        frame={{
          kind: "board",
          filters: {},
          page: {
            columns: {
              todo: [withProject],
              in_progress: [],
              completed: [],
              active: [],
              paused: [],
            },
            next_cursor: null,
          },
        }}
        onChange={() => undefined}
        transport={transport()}
        labels={workEn}
        moves={0}
        onOpen={() => undefined}
      />,
    );

    // The Project is the part that is cut: it carries the full name as its title (record-meta.tsx RecordMeta).
    const project = handleOf(taskA.title)
      .closest("li")
      ?.querySelector(".work-card-meta > .work-card-project");
    expect(project).toHaveAttribute("title", "Bokslut och skatt");
    const meta = project?.parentElement as HTMLElement;
    expect(workCss.styleOf(meta, ROOM)).toMatchObject({
      "white-space": "nowrap",
      // The due time is a plain part too: when it does not fit beside the Project it wraps onto its own row.
      "flex-wrap": "wrap",
    });
    expect(workCss.styleOf(project as Element, ROOM)).toMatchObject({
      flex: "1 1 6rem",
      overflow: "hidden",
      "text-overflow": "ellipsis",
    });
    // A priority or due part that does not fit is cut with an ellipsis too (200 % text), not clipped hard.
    const due = meta.querySelector("span:not(.work-card-project)");
    expect(due).not.toBeNull();
    expect(workCss.styleOf(due as Element, ROOM)).toMatchObject({
      "min-width": "0",
      "text-overflow": "ellipsis",
    });
    // The board has no pill rule for the kind any more: it is a plain part, cut by the span rule above.
    expect(
      workCss.rules.filter((rule) => rule.selector.includes("work-card-kind")),
    ).toEqual([]);
  });

  it("the parts come in one order, the time first, then the High marker and the Project last, with no separator text", () => {
    const withAll: WorkItemRecord = {
      ...taskA,
      project_title: "Bokslut och skatt",
      priority: "high",
      due_at: "2099-01-15T09:00:00Z",
    };
    render(
      <BoardView
        frame={{
          kind: "board",
          filters: {},
          page: {
            columns: {
              todo: [withAll],
              in_progress: [],
              completed: [],
              active: [],
              paused: [],
            },
            next_cursor: null,
          },
        }}
        onChange={() => undefined}
        transport={transport()}
        labels={workEn}
        moves={0}
        onOpen={() => undefined}
      />,
    );

    const parts = Array.from(
      handleOf(withAll.title).closest("li")?.querySelector(".work-card-meta")
        ?.children ?? [],
    );
    expect(parts).toHaveLength(3);
    // The time is the first part, then the High marker and the Project last. The "·" is drawn in CSS before
    // each part after the first (work.css), so no part's text carries a separator and no part ends with a dot.
    expect(parts[0]).toHaveClass("work-card-due");
    expect(parts[1]?.textContent).toBe(workEn.priorityLevel.high);
    expect(parts[2]?.textContent).toBe("Bokslut och skatt");
    for (const part of parts) {
      expect(part.textContent).not.toContain("·");
    }
    expect(
      workCss.rule(
        ".sidekick-work .work-column .work-card-meta > * + *::before",
      ).content,
    ).toBe('"· "');
    // The gap after each separator is set on the board's flex row, where a nowrap part keeps no trailing space.
    expect(
      workCss.rule(".sidekick-work .work-column .work-card-meta")["column-gap"],
    ).toBe("0.25em");
  });

  it("board titles get no automatic hyphens: every hyphen is manual, and words break only as a last resort", () => {
    // Chromium's Swedish patterns split compounds wrongly ("kalende-revent"), so no rule sets `hyphens: auto`.
    for (const rule of workCss.rules) {
      expect(rule.declarations.hyphens, rule.selector).not.toBe("auto");
      expect(rule.declarations, rule.selector).not.toHaveProperty(
        "hyphenate-limit-chars",
      );
    }
    expect(workCss.rule(".sidekick-work").hyphens).toBe("manual");
  });

  it("a status chip keeps its glyph on the label's line, with a gap before the label", () => {
    const { container } = render(
      <InlineSummary
        state="ready"
        labels={inlineSummaryLabelsSv}
        summary={{ kind: "task", title: "Ring Anna", status: "completed" }}
      />,
    );

    const chip = container.querySelector(".work-chip");
    // The glyph comes first and is hidden from assistive technology; the label follows it as text.
    expect(chip?.firstElementChild?.tagName.toLowerCase()).toBe("svg");
    expect(chip?.firstElementChild).toHaveAttribute("aria-hidden", "true");
    expect(chip?.lastChild?.textContent).toBe("Klar");
    // jsdom applies no CSS: the line and the gap are read from work.css.
    expect(workCss.styleOf(chip as Element, ROOM)).toMatchObject({
      display: "inline-flex",
      "align-items": "center",
      gap: "0.35rem",
    });
  });
});

describe("fullscreen board: Undo time", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("the Undo time starts once the move is answered, while the board is still being read in the background", async () => {
    vi.useFakeTimers();
    // The board read after the move stays open until the test answers it: the Undo does not wait for it.
    const getWorkBoard = vi.fn(
      () => new Promise<WorkBoardPage>(() => undefined),
    );
    render(rootBoard(transport({ getWorkBoard })));
    fireEvent.keyDown(handleOf(taskA.title), { key: "ArrowRight" });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(getWorkBoard).toHaveBeenCalledTimes(1);
    expect(
      screen.getByRole("button", { name: workEn.agendaUndo }),
    ).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(UNDO_MS - 1);
    });
    expect(
      screen.getByRole("button", { name: workEn.agendaUndo }),
    ).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(
      screen.queryByRole("button", { name: workEn.agendaUndo }),
    ).not.toBeInTheDocument();
  });

  it("the pointer over the Undo line pauses its time, and the line is still there after the pointer leaves until the time left runs out", async () => {
    vi.useFakeTimers();
    render(rootBoard(transport()));
    fireEvent.keyDown(handleOf(taskA.title), { key: "ArrowRight" });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    const undo = screen.getByRole("button", { name: workEn.agendaUndo });
    // The pause sits on the Undo line's wrapper, which holds both the status text and the button.
    const line = undo.closest(".work-agenda-undo");
    if (!line) throw new Error("no Undo line");
    act(() => {
      vi.advanceTimersByTime(10000);
    });
    fireEvent.pointerEnter(line);
    act(() => {
      vi.advanceTimersByTime(UNDO_MS * 2);
    });
    expect(undo).toBeInTheDocument();
    fireEvent.pointerLeave(line);
    act(() => {
      vi.advanceTimersByTime(UNDO_MS - 10000 - 1);
    });
    expect(undo).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(
      screen.queryByRole("button", { name: workEn.agendaUndo }),
    ).not.toBeInTheDocument();
  });
});

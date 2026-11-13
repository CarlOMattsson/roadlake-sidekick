import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { AgendaView } from "@/features/work-app/agenda/agenda";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import type {
  WorkAgendaFrame,
  WorkItemRecord,
} from "@/features/work-app/transport/transport";
import { elementWithText } from "./helpers/exact-text";
import { readStylesheet } from "./helpers/stylesheet";
import {
  TASK_ID,
  task,
  other,
  done,
  project,
  makeTransport,
  renderAgenda,
  glyphOf,
  rowOf,
  undoButton,
  openRow,
  resetAgendaEnvironment,
} from "./helpers/agenda-view-fixtures";

afterEach(resetAgendaEnvironment);

it("groups the Swedish agenda by due date from Wednesday 2026-10-28, with the day of Idag, and a count only on Försenade", () => {
  // The clock is fixed to Wednesday 28 October 2026, local time; the week runs Monday to Sunday.
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(2026, 9, 28, 12, 0));
  const { transport } = makeTransport();
  const record = (
    id: string,
    title: string,
    due_at: string | null,
    agenda_group: WorkItemRecord["agenda_group"],
  ): WorkItemRecord => ({
    kind: "task",
    id,
    title,
    status: "todo",
    due_at,
    version: 1,
    agenda_group,
  });
  const items = [
    record("t-1", "Ring banken", "2026-10-20T09:00:00", "overdue"),
    record("t-2", "Skicka offert", "2026-10-28T18:00:00", "today"),
    record("t-3", "Städa garaget", "2026-10-31T09:00:00", "upcoming"),
    record("t-4", "Boka tandläkare", "2026-11-03T09:00:00", "upcoming"),
    record("t-5", "Betala försäkringen", "2026-11-28T09:00:00", "upcoming"),
    record("t-6", "Fundera på semester", null, "scheduled_later"),
  ];
  const frame: WorkAgendaFrame = {
    kind: "agenda",
    filters: {},
    page: { items, next_cursor: null },
  };
  render(
    <AgendaView
      frame={frame}
      onChange={vi.fn()}
      transport={transport}
      labels={workSv}
      moves={0}
      onOpen={vi.fn()}
    />,
  );

  const headings = screen
    .getAllByRole("heading", { level: 3 })
    .map((heading) => heading.textContent);
  expect(headings).toEqual([
    "Idag, ons 28 okt",
    "Försenade (1)",
    "Denna vecka",
    "Nästa vecka",
    "Senare",
    "Utan datum",
  ]);
  // Each record sits under the heading of its group.
  const section = (name: string) => screen.getByRole("region", { name });
  expect(
    within(section("Försenade (1)")).getByText("Ring banken"),
  ).toBeInTheDocument();
  expect(
    within(section("Idag, ons 28 okt")).getByText("Skicka offert"),
  ).toBeInTheDocument();
  expect(
    within(section("Denna vecka")).getByText("Städa garaget"),
  ).toBeInTheDocument();
  expect(
    within(section("Nästa vecka")).getByText("Boka tandläkare"),
  ).toBeInTheDocument();
  expect(
    within(section("Senare")).getByText("Betala försäkringen"),
  ).toBeInTheDocument();
  expect(
    within(section("Utan datum")).getByText("Fundera på semester"),
  ).toBeInTheDocument();
});

it("without a Task due today the agenda starts with Försenade and shows no Idag heading", () => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(2026, 9, 28, 12, 0));
  const { transport } = makeTransport();
  const items: WorkItemRecord[] = [
    {
      kind: "task",
      id: "t-1",
      title: "Ring banken",
      status: "todo",
      due_at: "2026-10-20T09:00:00",
      version: 1,
      agenda_group: "overdue",
    },
    {
      kind: "task",
      id: "t-2",
      title: "Städa garaget",
      status: "todo",
      due_at: "2026-10-31T09:00:00",
      version: 1,
      agenda_group: "upcoming",
    },
  ];
  render(
    <AgendaView
      frame={{
        kind: "agenda",
        filters: {},
        page: { items, next_cursor: null },
      }}
      onChange={vi.fn()}
      transport={transport}
      labels={workSv}
      moves={0}
      onOpen={vi.fn()}
    />,
  );
  const headings = screen
    .getAllByRole("heading", { level: 3 })
    .map((heading) => heading.textContent);
  expect(headings).toEqual(["Försenade (1)", "Denna vecka"]);
  expect(screen.queryByText(/^Idag/)).not.toBeInTheDocument();
});

it("moves every open overdue Task to tomorrow with one reschedule_tasks call, and rows carry no triage buttons", async () => {
  const { transport, mock } = makeTransport();
  const reschedule = vi.fn(() => Promise.resolve({ count: 1, tasks: [] }));
  Object.assign(mock, {
    rescheduleTasks: reschedule,
    getWorkAgenda: vi.fn(() =>
      Promise.resolve({ items: [], next_cursor: null }),
    ),
  });
  renderAgenda([task, other], transport);
  // One open overdue Task: the button counts it, and reads "Move 1 overdue to tomorrow".
  await userEvent.click(
    screen.getByRole("button", { name: workEn.moveAllOverdue(1) }),
  );
  // The tap only asks; "Move" writes.
  expect(reschedule).not.toHaveBeenCalled();
  await userEvent.click(
    screen.getByRole("button", { name: workEn.moveAllConfirmYes }),
  );
  await waitFor(() => expect(reschedule).toHaveBeenCalledTimes(1));
  const [items] = reschedule.mock.calls[0] as unknown as [
    { taskId: string; version: number; when: string }[],
  ];
  expect(items).toEqual([{ taskId: TASK_ID, version: 1, when: "tomorrow" }]);
});

it("hides the move-all button while a search narrows the agenda, and shows it again when the search is cleared (ui-21)", async () => {
  const { transport } = makeTransport();
  renderAgenda([task, other], transport);
  const moveAll = () =>
    screen.queryByRole("button", { name: workEn.moveAllOverdue(1) });
  expect(moveAll()).toBeInTheDocument();
  const filter = screen.getByRole("searchbox", { name: workEn.agendaFilter });
  // The search still finds the overdue Task: its row shows, but the bulk move does not.
  await userEvent.type(filter, task.title.slice(0, 4));
  expect(rowOf(task.title)).toBeInTheDocument();
  expect(moveAll()).toBeNull();
  // Only spaces: no search, so the button is back.
  await userEvent.clear(filter);
  await userEvent.type(filter, "   ");
  expect(moveAll()).toBeInTheDocument();
});

it("puts the move button of Försenade after the group's last row, after the handled list, and never in the group's heading", () => {
  const now = new Date("2026-10-26T10:00:00Z");
  const { transport } = makeTransport();
  const second: WorkItemRecord = {
    ...task,
    id: "019f0000-0000-7000-8000-0000000000a6",
    title: "Betala hyran",
  };
  // Two open overdue Tasks and one done overdue Task (the handled list, which sinks to the group's end).
  renderAgenda([task, second, done], transport, false, now);
  const section = elementWithText(
    `${workEn.agendaGroup.overdue} (2)`,
    "h3",
  ).closest("section") as HTMLElement;
  const moveAll = within(section).getByRole("button", {
    name: workEn.moveAllOverdue(2),
  });
  expect(section.querySelector("ul.work-agenda-handled")).not.toBeNull();
  // Not in the heading row (the sticky head), but right after the group's last list.
  expect(moveAll.closest(".work-agenda-group-head")).toBeNull();
  expect(moveAll.previousElementSibling).toBe(
    section.querySelector("ul.work-agenda-handled"),
  );
  expect(moveAll.nextElementSibling).toBeNull();
});

it("the move-all button is an action row with the arrow glyph first and no quiet button class", () => {
  const { transport } = makeTransport();
  renderAgenda([task, other], transport);
  const moveAll = screen.getByRole("button", {
    name: workEn.moveAllOverdue(1),
  });
  expect(moveAll).toHaveClass("work-agenda-move-all", "sk-action-row");
  expect(moveAll).not.toHaveClass("sk-btn--quiet");
  expect(moveAll.firstElementChild?.tagName.toLowerCase()).toBe("svg");
  expect(moveAll.firstElementChild).toHaveAttribute("aria-hidden", "true");
});

it("a glyph tap that marks an overdue Task done drops it from the Försenade count at once, the same number the move button counts, while the row stands with Undo", async () => {
  const user = userEvent.setup();
  const { transport } = makeTransport();
  const second: WorkItemRecord = {
    ...task,
    id: "019f0000-0000-7000-8000-0000000000a5",
    title: "Betala hyran",
  };
  renderAgenda([task, second], transport);
  expect(
    elementWithText(`${workEn.agendaGroup.overdue} (2)`, "h3"),
  ).toBeInTheDocument();
  await user.click(glyphOf(task.title));
  await undoButton();
  // The heading counts open rows only, so it is the number the button moves.
  expect(
    elementWithText(`${workEn.agendaGroup.overdue} (1)`, "h3"),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: workEn.moveAllOverdue(1) }),
  ).toBeInTheDocument();
  const line = within(rowOf(task.title)).getByRole("status");
  expect(line.parentElement).toHaveClass("work-agenda-undo");
  expect(line).toHaveTextContent("Done · in Status");
  expect(
    within(line.parentElement as HTMLElement).getByRole("button", {
      name: workEn.agendaUndo,
    }),
  ).toBeInTheDocument();
  // The other overdue row is still open and has no Undo of its own.
  expect(
    within(rowOf(second.title)).queryByRole("status"),
  ).not.toBeInTheDocument();
});

it("the filter row carries the Refresh icon, and no row has a ⋯ button: its title names the quick choices", () => {
  const { transport } = makeTransport();
  renderAgenda([task, other], transport);
  const toolbar = screen
    .getByRole("searchbox", { name: workEn.agendaFilter })
    .closest(".work-agenda-toolbar");
  expect(toolbar).not.toBeNull();
  expect(
    within(toolbar as HTMLElement).getByRole("button", {
      name: workEn.refresh,
    }),
  ).toBeInTheDocument();
  expect(document.querySelector(".work-agenda-status")).toBeNull();
  expect(document.querySelector(".work-agenda-row .sk-iconbtn")).toBeNull();
  const title = screen.getByRole("button", { name: task.title });
  expect(title).toHaveAttribute("aria-keyshortcuts", "Shift+F10");
  expect(title).toHaveAttribute("aria-description", workEn.rowMenuHint);
});

it("a row's quick choices open with Shift+F10 from its title and close with the same keys or Escape, and only one row is open", async () => {
  const user = userEvent.setup();
  const { transport } = makeTransport();
  renderAgenda([task, other], transport);
  const title = screen.getByRole("button", { name: task.title });
  title.focus();
  await user.keyboard("{Shift>}{F10}{/Shift}");
  expect(
    within(rowOf(task.title)).getByRole("group", { name: workEn.status }),
  ).toBeInTheDocument();
  await user.keyboard("{Shift>}{F10}{/Shift}");
  expect(
    screen.queryByRole("group", { name: workEn.status }),
  ).not.toBeInTheDocument();
  // The ContextMenu key toggles them as well.
  fireEvent.keyDown(title, { key: "ContextMenu" });
  expect(
    screen.getByRole("group", { name: workEn.status }),
  ).toBeInTheDocument();
  await user.keyboard("{Escape}");
  expect(
    screen.queryByRole("group", { name: workEn.status }),
  ).not.toBeInTheDocument();
  // Escape hands focus back to the title, where the keys opened them.
  expect(title).toHaveFocus();
  // Opening another row's choices closes the first row's.
  openRow(task.title);
  openRow(other.title);
  expect(screen.getAllByRole("group", { name: workEn.status })).toHaveLength(1);
  expect(
    within(rowOf(other.title)).getByRole("group", { name: workEn.status }),
  ).toBeInTheDocument();
});

it("the filter field has a visible label above its input, in the view's language", () => {
  const { transport } = makeTransport();
  renderAgenda([task, other], transport);
  const label = screen.getByText(workEn.agendaFilter);
  expect(label).not.toHaveClass("work-visually-hidden");
  expect(label.closest("label")).toHaveClass("work-agenda-filter");
  expect(
    within(label.closest("label") as HTMLElement).getByRole("searchbox"),
  ).toBeInTheDocument();
  expect(workSv.agendaFilter).toBe("Filtrera uppgifter");
});

const ROOM = { room: "sidekick-work" };
const agendaCss = readStylesheet("features/work-app/agenda/agenda.css");
const workCss = readStylesheet("features/work-app/shell/work.css");
const tokens = readStylesheet("features/mcp-apps/ui/tokens.css");

/** A task whose meta line has every part: time, status, the High marker and a Project. */
const fullMeta: WorkItemRecord = {
  kind: "task",
  id: "t-meta",
  title: "Måla köket",
  status: "in_progress",
  due_at: "2026-10-20T09:00:00",
  version: 1,
  agenda_group: "overdue",
  priority: "high",
  project_title: "Renovering av köket",
};

// jsdom applies no CSS, so the phone-first rules are read from agenda.css and resolved against the rendered row.
// The rendered check is tests/e2e/meta-line-mcp-app.spec.ts (360 and 412 px, text 110, 150 and 200 %).
it("the meta line keeps its time and status whole, lets only the Project give way, and the filter row is a flex row", () => {
  const { transport } = makeTransport();
  const { container } = renderAgenda([fullMeta, project], transport);
  const meta = container.querySelector(".work-card-project")
    ?.parentElement as HTMLElement;
  const parts = Array.from(meta.children);

  // One meta line, at least one line high. A box fixed at one line that wrapped and clipped dropped "Pågår" and
  // the Project at 360 px and 200 %, so the box is a floor, not a height: a part that must stand moves whole to
  // a second line instead of vanishing.
  const style = agendaCss.styleOf(meta, ROOM);
  expect(style).toMatchObject({
    display: "flex",
    "flex-wrap": "wrap",
    "min-height": "var(--sk-type-meta-line)",
    "align-content": "flex-start",
    gap: "0 0.8em",
    "white-space": "nowrap",
    overflow: "clip",
    // The row's 6 of air under the meta line comes from the one row-template token, as a margin so the clip is
    // the line.
    margin: "0 0 var(--sk-row-pad)",
    padding: "0",
  });
  for (const forbidden of ["height", "row-gap", "column-gap"]) {
    expect(style[forbidden], forbidden).toBeUndefined();
  }
  // Every part keeps its own width; none is shrunk or cut except the Project.
  expect(parts.length).toBeGreaterThanOrEqual(3);
  for (const part of parts) {
    const partStyle = agendaCss.styleOf(part, ROOM);
    expect(partStyle, part.className).toMatchObject({
      position: "relative",
      "pointer-events": "none",
    });
    if (!part.matches(".work-card-project")) {
      expect(partStyle.flex, part.className).toBe("none");
    }
  }
  // Only the Project shrinks, to 4em with an ellipsis.
  expect(
    agendaCss.styleOf(
      meta.querySelector(".work-card-project") as Element,
      ROOM,
    ),
  ).toMatchObject({
    flex: "1 1 4em",
    "max-width": "max-content",
    "min-width": "0",
    overflow: "hidden",
    "text-overflow": "ellipsis",
  });
  // Hög and the Project after another part wrap to a 0-high line at the meta's edge, which the clip hides whole;
  // the part that opens the line is not pulled up.
  expect(
    agendaCss.styleOf(
      meta.querySelector(".work-card-priority") as Element,
      ROOM,
    )["margin-block-end"],
  ).toBe("calc(-1 * var(--sk-type-meta-line))");
  expect(
    agendaCss.styleOf(parts[0] as Element, ROOM)["margin-block-end"],
  ).toBeUndefined();
  // The separator hangs in the gap before its part, so a part that starts the second line has no leading "·".
  expect(
    agendaCss.styleOf(parts[1] as Element, { ...ROOM, pseudo: "::before" }),
  ).toMatchObject({
    content: '"·"',
    position: "absolute",
    right: "100%",
  });
  expect(
    agendaCss.styleOf(parts[0] as Element, { ...ROOM, pseudo: "::before" }),
  ).toEqual({});
  // The kind is plain text: the board's pill frame is gone.
  const kind = container.querySelector(".work-card-kind");
  expect(kind).not.toBeNull();
  expect(
    agendaCss.styleOf(kind as Element, ROOM)["border-radius"],
  ).toBeUndefined();
  for (const rule of agendaCss.rules) {
    expect(rule.declarations.height, rule.selector).not.toBe("0");
  }
  expect(
    agendaCss.styleOf(
      container.querySelector(".work-agenda-toolbar") as Element,
      ROOM,
    ).display,
  ).toBe("flex");
});

it("breaks a long agenda title word only as a last resort (no automatic hyphens, never anywhere), and keeps the row's glyph at 44 px at every width", () => {
  const { transport } = makeTransport();
  const { container } = renderAgenda([task], transport);
  const title = container.querySelector(
    ".work-agenda-body > button",
  ) as HTMLElement;
  const glyph = container.querySelector(".work-agenda-glyph") as HTMLElement;

  // The title moves to the next line whole; `anywhere` split words at the end of a line, and `hyphens: auto`
  // split "kalende-revent". It breaks inside a word only when the word alone is wider than the line.
  expect(agendaCss.styleOf(title, ROOM)["overflow-wrap"]).toBe("break-word");
  expect(workCss.styleOf(title, ROOM)).toMatchObject({
    "overflow-wrap": "break-word",
    hyphens: "manual",
  });
  for (const rule of [...agendaCss.rules, ...workCss.rules]) {
    expect(rule.declarations.hyphens, rule.selector).not.toBe("auto");
  }
  // The glyph keeps its 44 px target at every width. In a task row the ring starts at the page's 16 px margin:
  // the button is the leading column's width and hangs 10 px into the margin.
  expect(agendaCss.styleOf(glyph, ROOM)).toMatchObject({
    width: "var(--sk-lead-w)",
    "min-width": "var(--sk-lead-w)",
    "min-height": "var(--sk-lead-h)",
    margin: "0 2px 0 var(--sk-lead-hang)",
  });
  // The ring is 24 to 32 px; the leading column is the ring plus 20, and at least 44, and its height is two row
  // paddings plus one row line (the ring sits on the title line's middle).
  const root = tokens.rule(":root");
  expect(root["--sk-ring-glyph"]).toBe("clamp(24px, 1.5rem, 32px)");
  expect(root["--sk-lead-w"]).toBe(
    "max(44px, calc(var(--sk-ring-glyph) + 20px))",
  );
  expect(root["--sk-lead-h"]).toBe(
    "calc(2 * var(--sk-row-pad) + var(--sk-type-row-line))",
  );
  // No narrow-frame margin pulls the row's content outward at a narrow width.
  expect(
    agendaCss.rules.filter((rule) =>
      rule.conditions.includes("@container sk-frame (max-width: 360px)"),
    ),
  ).toEqual([]);
});

it("the row title is 16 on a 1.3 line and the meta line 14 on a 1.25 line, the agenda's row type", () => {
  const { transport } = makeTransport();
  const { container } = renderAgenda([task, fullMeta], transport);
  const root = tokens.rule(":root");
  // The line heights in tokens.css, as a ratio of the size: the title 1.3rem on 1rem, the meta 1.09375rem on 0.875rem.
  const rem = (name: string) => {
    const value = /^([\d.]+)rem$/.exec(root[`--${name}`] ?? "")?.[1];
    expect(value, name).toBeDefined();
    return Number(value);
  };
  expect(
    rem("sk-type-row-line") / rem("sk-type-row-size"),
  ).toBeGreaterThanOrEqual(1.3);
  expect(
    rem("sk-type-meta-line") / rem("sk-type-meta-size"),
  ).toBeGreaterThanOrEqual(1.25);
  // The title and the meta line use those types (the row's font shorthand).
  expect(
    agendaCss.styleOf(
      container.querySelector(".work-agenda-body > button") as Element,
      ROOM,
    ).font,
  ).toBe("var(--sk-type-row)");
  expect(
    agendaCss.styleOf(
      container.querySelector(".work-card-meta") as Element,
      ROOM,
    ).font,
  ).toBe("var(--sk-type-meta)");
});

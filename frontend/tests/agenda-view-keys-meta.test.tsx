import { agendaLabelsEn } from "@/features/work-app/agenda/agenda-labels";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { fillLabel } from "@/features/work-app/agenda/agenda-undo";
import { workEn } from "@/features/work-app/shared/labels";
import { elementWithText } from "./helpers/exact-text";
import { readStylesheet } from "./helpers/stylesheet";
import {
  TASK_ID,
  OTHER_ID,
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

const ROOM = { room: "sidekick-work" };
const agendaCss = readStylesheet("features/work-app/agenda/agenda.css");

afterEach(resetAgendaEnvironment);

it("j and k step through the records, x completes the selected Task and 3 sets Blocked", async () => {
  const { transport, mock } = makeTransport();
  renderAgenda([task, other, project], transport, true);
  // "Idag" comes before "Försenade": j steps over "Boka målare" and "Kök" to the overdue Task.
  fireEvent.keyDown(document.body, { key: "j" });
  fireEvent.keyDown(document.body, { key: "j" });
  fireEvent.keyDown(document.body, { key: "j" });
  expect(rowOf(task.title)).toHaveFocus();
  fireEvent.keyDown(document.body, { key: "x" });
  await waitFor(() =>
    expect(mock.updateTask).toHaveBeenCalledWith(
      TASK_ID,
      1,
      { status: "completed" },
      expect.any(String),
    ),
  );
  await undoButton();
  fireEvent.keyDown(document.body, { key: "k" });
  fireEvent.keyDown(document.body, { key: "k" });
  fireEvent.keyDown(document.body, { key: "k" });
  expect(rowOf(other.title)).toHaveFocus();
  fireEvent.keyDown(document.body, { key: "3" });
  await waitFor(() =>
    expect(mock.updateTask).toHaveBeenCalledWith(
      OTHER_ID,
      4,
      { status: "blocked" },
      expect.any(String),
    ),
  );
});

it("the window keys do nothing when shortcuts are off, as in an inline card", () => {
  const { transport, mock } = makeTransport();
  renderAgenda([task, other, project], transport);
  fireEvent.keyDown(document.body, { key: "j" });
  expect(rowOf(task.title)).not.toHaveFocus();
  fireEvent.keyDown(document.body, { key: "x" });
  fireEvent.keyDown(document.body, { key: "3" });
  expect(mock.updateTask).not.toHaveBeenCalled();
});

it("the filter narrows the list by title and says when nothing matches", async () => {
  const user = userEvent.setup();
  const { transport } = makeTransport();
  renderAgenda([task, other], transport);
  const search = screen.getByRole("searchbox", { name: agendaLabelsEn.filter });
  await user.type(search, "målare");
  expect(
    screen.queryByRole("button", { name: task.title }),
  ).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: other.title })).toBeInTheDocument();
  await user.clear(search);
  await user.type(search, "zzz");
  expect(
    screen.getByText(fillLabel(agendaLabelsEn.noMatch, { q: "zzz" })),
  ).toBeInTheDocument();
  // The text button under the sentence empties the search and brings the rows back.
  await user.click(
    screen.getByRole("button", { name: agendaLabelsEn.clearSearch }),
  );
  expect(search).toHaveValue("");
  expect(screen.getByRole("button", { name: task.title })).toBeInTheDocument();
});

it("group headings stick to the top, and a Project has a glyph but no quick action", () => {
  const { transport } = makeTransport();
  renderAgenda([task, other, project], transport);
  // The heading row sticks as one: the heading and the overdue button stay together.
  expect(
    elementWithText(`${agendaLabelsEn.group.overdue} (1)`, "h3").closest(
      ".work-agenda-group-head",
    ),
  ).toHaveStyle({ position: "sticky" });
  expect(
    screen.getByRole("button", { name: project.title }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", {
      name: fillLabel(workEn.agendaComplete, { title: project.title }),
    }),
  ).not.toBeInTheDocument();
});

it("a due date reads relative to now, with the board's wording and tone", () => {
  const now = new Date("2026-10-26T10:00:00Z");
  const { transport } = makeTransport();
  renderAgenda(
    [
      { ...task, due_at: "2026-10-24" },
      { ...other, due_at: "2026-10-26" },
      {
        kind: "task",
        id: "019f0000-0000-7000-8000-0000000000a4",
        title: "Boka tid",
        status: "todo",
        due_at: "2026-10-27",
        version: 1,
      },
    ],
    transport,
    false,
    now,
  );
  // Under "Overdue" too the meta line says "2 days overdue", so a row reads on its own.
  const overdue = screen.getByText("2 days overdue", { selector: "time" });
  expect(overdue).toHaveAttribute("data-tone", "overdue");
  expect(overdue).toHaveAttribute("datetime", "2026-10-24");
  // The row under "Idag" names no date: its group heading already says the day.
  expect(rowOf(other.title).querySelector("time")).toBeNull();
  // At the start of a meta line the next day reads with a capital, as on the board.
  const tomorrow = screen.getByText("Tomorrow", { selector: "time" });
  expect(tomorrow).toHaveAttribute("data-tone", "soon");
  expect(tomorrow).toHaveAttribute("datetime", "2026-10-27");
  // The exact "Due: date" form is replaced by the relative one.
  expect(screen.queryByText(/Due:/)).not.toBeInTheDocument();
});

it("the agenda meta line has one element per part and no separator text", () => {
  const now = new Date("2026-10-26T10:00:00Z");
  const { transport } = makeTransport();
  renderAgenda(
    [
      {
        ...task,
        due_at: "2026-10-24",
        priority: "high",
        project_title: "Webbplats",
      },
    ],
    transport,
    false,
    now,
  );
  const meta = rowOf(task.title).querySelector(
    ".work-agenda-body > .work-card-meta",
  );
  expect(meta).not.toBeNull();
  // The time comes first, then the High marker and the Project last. A Task's kind is not shown in
  // the agenda, and a To do Task names no status.
  expect(Array.from(meta?.children ?? [], (part) => part.className)).toEqual([
    "work-card-due",
    "work-card-priority",
    "work-card-project",
  ]);
  expect(meta?.textContent).toContain("Webbplats");
  // The "·" comes from agenda.css (::before), never from text, so a wrapped line cannot end on it.
  expect(meta?.textContent).not.toContain("·");
});

it("the agenda shows the Project last, after the time, the status and the High marker, with its full name as the title", () => {
  const now = new Date("2026-10-26T10:00:00Z");
  const { transport } = makeTransport();
  renderAgenda(
    [
      {
        ...other,
        agenda_group: "overdue",
        due_at: "2026-10-24",
        priority: "high",
        project_title: "Webbplats",
      },
    ],
    transport,
    false,
    now,
  );
  const meta = rowOf(other.title).querySelector(
    ".work-agenda-body > .work-card-meta",
  );
  const parts = Array.from(meta?.children ?? []);
  expect(parts.map((part) => part.className)).toEqual([
    "work-card-due",
    "work-card-status",
    "work-card-priority",
    "work-card-project",
  ]);
  // The Project is the part CSS may cut; it carries the full name as its text and its title.
  expect(parts[3]).toHaveTextContent("Webbplats");
  expect(parts[3]).toHaveAttribute("title", "Webbplats");
});

it("a done Task keeps its check glyph, and the agenda CSS dims its row", () => {
  const now = new Date("2026-10-26T10:00:00Z");
  const { transport } = makeTransport();
  renderAgenda([done, task], transport, false, now);
  expect(
    rowOf(done.title).querySelector('[data-glyph$="-check"]'),
  ).not.toBeNull();
  expect(rowOf(task.title).querySelector('[data-glyph$="-check"]')).toBeNull();
  // jsdom applies no CSS, so the dimming rule is read from agenda.css and resolved against the rendered rows: it
  // keys on the check glyph.
  const body = (title: string) =>
    rowOf(title).querySelector(".work-agenda-body") as Element;
  expect(agendaCss.styleOf(body(done.title), ROOM).color).toBe(
    "var(--sk-muted)",
  );
  expect(agendaCss.styleOf(body(task.title), ROOM).color).toBeUndefined();
});

it("the Undo line is the changed row's own meta line, as a polite status line, and no list item or notice is added", async () => {
  const user = userEvent.setup();
  const { transport } = makeTransport();
  renderAgenda([task, other], transport);
  await user.click(glyphOf(task.title));
  const undo = await undoButton();
  // The wrapper sits inside its row, so it covers no other row and adds no list item of its own.
  const wrap = undo.closest(".work-agenda-undo");
  if (!wrap) throw new Error("no Undo line");
  expect(rowOf(task.title)).toContainElement(wrap as HTMLElement);
  expect(document.querySelector("li.work-agenda-undo")).toBeNull();
  expect(wrap.tagName).toBe("DIV");
  const line = within(wrap as HTMLElement).getByRole("status");
  expect(line.tagName).toBe("P");
  expect(line).toHaveTextContent("Done");
  expect(line).not.toHaveClass("sk-notice");
  // jsdom applies no CSS: no rule that names the line gives it a sticky position in agenda.css.
  const undoRules = agendaCss.rules.filter((rule) =>
    rule.selector.includes("work-agenda-undo"),
  );
  expect(undoRules.length).toBeGreaterThan(0);
  for (const rule of undoRules) {
    expect(rule.declarations.position, rule.selector).not.toBe("sticky");
  }
  expect(agendaCss.styleOf(wrap, ROOM).position).not.toBe("sticky");
});

it("opening a row's quick choices scrolls them into view, so they are not hidden under the host's reply field", () => {
  const { transport } = makeTransport();
  // jsdom has no scrollIntoView: the test supplies one and records the element it was called on.
  const scrolled: Element[] = [];
  const scrollIntoView = vi.fn(function (this: Element) {
    scrolled.push(this);
  });
  Object.defineProperty(Element.prototype, "scrollIntoView", {
    configurable: true,
    writable: true,
    value: scrollIntoView,
  });
  try {
    renderAgenda([task], transport);
    expect(scrollIntoView).not.toHaveBeenCalled();
    openRow(task.title);
    // The menu (its two rows, Status and Datum) is what scrolls in, not the group inside it.
    const menu = screen
      .getByRole("group", { name: workEn.status })
      .closest(".work-agenda-menu");
    expect(menu).not.toBeNull();
    expect(scrollIntoView).toHaveBeenCalledTimes(1);
    expect(scrollIntoView).toHaveBeenCalledWith({
      block: "nearest",
      inline: "nearest",
    });
    expect(scrolled[0]).toBe(menu);
  } finally {
    Reflect.deleteProperty(Element.prototype, "scrollIntoView");
  }
});

it("the Undo line scrolls itself into view with nearest when it shows, so its Ångra is not hidden under the reply field", async () => {
  const user = userEvent.setup();
  const { transport } = makeTransport();
  // jsdom has no scrollIntoView: the test supplies one and records the element it was called on.
  const scrolled: Element[] = [];
  const scrollIntoView = vi.fn(function (this: Element) {
    scrolled.push(this);
  });
  Object.defineProperty(Element.prototype, "scrollIntoView", {
    configurable: true,
    writable: true,
    value: scrollIntoView,
  });
  try {
    renderAgenda([task, other], transport);
    await user.click(glyphOf(task.title));
    const undo = await undoButton();
    const line = undo
      .closest(".work-agenda-undo")
      ?.querySelector('p[role="status"]');
    expect(line).not.toBeNull();
    expect(scrollIntoView).toHaveBeenCalledWith({
      block: "nearest",
      inline: "nearest",
    });
    expect(scrolled).toContain(line);
  } finally {
    Reflect.deleteProperty(Element.prototype, "scrollIntoView");
  }
});

it("the Datum choices are chips that wrap, the date input lies invisibly over its chip, and the open row and its menu are one surface with a --sk-border edge", () => {
  const { transport } = makeTransport();
  renderAgenda([task], transport);
  openRow(task.title);
  const choices = screen
    .getAllByRole("group")
    .find((group) => group.classList.contains("work-agenda-choices"));
  expect(choices).toBeDefined();

  // jsdom applies no CSS: the rules are read from agenda.css and resolved against the rendered row.
  const style = agendaCss.styleOf(choices as Element, ROOM);
  expect(style).toMatchObject({ display: "flex", "flex-wrap": "wrap" });
  // No field is drawn. The input lies invisible over the chip's 48 target (the chip is 40 drawn, so 4 over
  // on each side), and a pointer anywhere on it reaches the platform's picker.
  expect(
    agendaCss.rule(".sidekick-work .work-agenda-date-input"),
  ).toMatchObject({
    position: "absolute",
    // 4 past the chip's 1 px edge, placed from its padding box: the chip's 48.
    inset: "calc(-4px - var(--sk-hairline))",
    opacity: "0",
  });
  expect(agendaCss.has(".work-agenda-menu-row:last-child input")).toBe(false);
  // The surface is the open row's own box, with the card radius; the menu inside it has no background of its own.
  // The edge is the secondary button's --sk-border, drawn inside; --sk-panel-line is gone.
  const row = agendaCss.styleOf(rowOf(task.title), ROOM);
  expect(row).toMatchObject({
    background: "var(--sk-surface)",
    "border-radius": "var(--sk-radius-card)",
    "box-shadow": "inset 0 0 0 var(--sk-hairline) var(--sk-border)",
  });
  expect(Object.values(row).join(" ")).not.toMatch(/tonal|--sk-panel-line/);
  const menu = document.querySelector(".work-agenda-menu") as Element;
  expect(agendaCss.styleOf(menu, ROOM).background).toBeUndefined();
});

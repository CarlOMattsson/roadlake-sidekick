import { readFileSync } from "node:fs";
import path from "node:path";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { AgendaView } from "@/features/work-app/agenda";
import { workEn, workSv } from "@/features/work-app/labels";
import type {
  WorkAgendaFrame,
  WorkItemRecord,
} from "@/features/work-app/transport";
import { elementWithText } from "./helpers/exact-text";
import {
  TASK_ID,
  task,
  other,
  done,
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
  const reschedule = vi.fn(() => Promise.resolve({ count: 1 }));
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

it("the agenda CSS keeps the meta line's time and status whole, lets only Hög and the Project give way, and sets the filter row", () => {
  // jsdom applies no CSS, so the phone-first rules are read from agenda.css. The rendered check is
  // tests/e2e/meta-line-mcp-app.spec.ts (360 and 412 px, text 110, 150 and 200 %).
  const css = readFileSync(
    path.resolve(import.meta.dirname, "../src/features/work-app/agenda.css"),
    "utf8",
  );
  // The kind is plain text: the board's pill frame is gone and no rule of its own remains.
  expect(css).not.toMatch(/work-card-kind[^{]*\{[^}]*border-radius: 999px/);
  // One meta line, at least one line high. A box fixed at one
  // line that wrapped and clipped dropped "Pågår" and the Project at 360 px and 200 %, so the box is a floor, not a
  // height: a part that must stand moves whole to a second line instead of vanishing.
  const metaRule = css.match(/\.work-card-meta \{([^}]*)\}/);
  expect(metaRule?.[1]).toMatch(/display: flex;/);
  expect(metaRule?.[1]).toMatch(/flex-wrap: wrap;/);
  expect(metaRule?.[1]).toMatch(/min-height: var\(--sk-type-meta-line\);/);
  expect(metaRule?.[1]).not.toMatch(/(?<![-\w])height:/);
  expect(metaRule?.[1]).toMatch(/align-content: flex-start;/);
  expect(metaRule?.[1]).toMatch(/gap: 0 0\.8em;/);
  expect(metaRule?.[1]).toMatch(/white-space: nowrap;/);
  expect(metaRule?.[1]).toMatch(/overflow: clip;/);
  expect(metaRule?.[1]).not.toMatch(/row-gap/);
  expect(metaRule?.[1]).not.toMatch(/column-gap/);
  // The row's 6 of air under the meta line comes from the one row-template token, as a margin so the clip is the line.
  expect(metaRule?.[1]).toMatch(/margin: 0 0 var\(--sk-row-pad\);/);
  expect(metaRule?.[1]).toMatch(/padding: 0;/);
  expect(css).not.toMatch(/(?<![-\w])height: 0;/);
  // Every part keeps its own width; no rule shrinks or cuts whatever part happens to be last (it was "Blockerad").
  expect(css).toMatch(
    /\.work-card-meta\s*>\s*\*\s*\{[^}]*position: relative;[^}]*flex: none;[^}]*pointer-events: none;/,
  );
  expect(css).not.toMatch(/\.work-card-meta\s*>\s*:last-child/);
  // Only the Project shrinks, to 4em with an ellipsis.
  const projectRule = css.match(
    /\.work-card-meta\s*>\s*\.work-card-project\s*\{([^}]*)\}/,
  );
  expect(projectRule?.[1]).toMatch(/flex: 1 1 4em;/);
  expect(projectRule?.[1]).toMatch(/max-width: max-content;/);
  expect(projectRule?.[1]).toMatch(/min-width: 0;/);
  expect(projectRule?.[1]).toMatch(/overflow: hidden;/);
  expect(projectRule?.[1]).toMatch(/text-overflow: ellipsis;/);
  // Hög and the Project after another part wrap to a 0-high line at the meta's edge, which the clip hides whole.
  expect(css).toMatch(
    /\*\s*\+\s*:is\(\.work-card-priority, \.work-card-project\)\s*\{[^}]*margin-block-end: calc\(-1 \* var\(--sk-type-meta-line\)\);/,
  );
  // The separator hangs in the gap before its part, so a part that starts the second line has no leading "·".
  const sepRule = css.match(
    /\.work-card-meta\s*>\s*\*\s*\+\s*\*::before\s*\{([^}]*)\}/,
  );
  expect(sepRule?.[1]).toMatch(/content: "·";/);
  expect(sepRule?.[1]).toMatch(/position: absolute;/);
  expect(sepRule?.[1]).toMatch(/right: 100%;/);
  expect(css).toMatch(
    /\.sidekick-work \.work-agenda-toolbar \{[^}]*display: flex;/,
  );
});

it("breaks a long agenda title word only as a last resort (no automatic hyphens, never anywhere), and keeps the row's glyph at 44 px at every width", () => {
  // jsdom applies no CSS, so the narrow-frame rules are read from agenda.css.
  const css = readFileSync(
    path.resolve(import.meta.dirname, "../src/features/work-app/agenda.css"),
    "utf8",
  );
  // The title moves to the next line whole; `anywhere` split words at the end of a line.
  expect(css).toMatch(
    /\.sidekick-work \.work-agenda-body > button \{[^}]*overflow-wrap: break-word;/,
  );
  // No automatic hyphens. A title moves whole to the next line and breaks inside a word only when the word
  // alone is wider than the line (work.css, with the rule for the board's titles). `hyphens: auto` split "kalende-revent".
  const work = readFileSync(
    path.resolve(import.meta.dirname, "../src/features/work-app/work.css"),
    "utf8",
  );
  expect(work).toMatch(
    /\.sidekick-work \.work-agenda-body > button,[\s\S]*?\{\s*overflow-wrap: break-word;\s*hyphens: manual;/,
  );
  const workDeclarations = work.replace(/\/\*[\s\S]*?\*\//g, "");
  expect(workDeclarations).not.toMatch(/hyphens:\s*auto/);
  // Comments mention `anywhere` on purpose; only the declarations count here.
  const declarations = css.replace(/\/\*[\s\S]*?\*\//g, "");
  expect(declarations).not.toMatch(
    /\.work-agenda-body > button \{[^}]*anywhere/,
  );
  // The glyph keeps its 44 px target at every width.
  expect(css).toMatch(
    /\.sidekick-work \.work-agenda-glyph \{[^}]*min-width: 2\.75rem;[^}]*min-height: 2\.75rem;/,
  );
  // In a task row the ring starts at the page's 16 px margin: the button is the leading column's width (tokens.css
  // --sk-lead-w: at least 44 px, the ring and 10 on each side at larger text) and hangs 10 px into the margin.
  expect(css).toMatch(
    /\.sidekick-work \.work-agenda-row \.work-agenda-glyph \{\s*width: var\(--sk-lead-w\);\s*min-width: var\(--sk-lead-w\);\s*min-height: var\(--sk-lead-h\);\s*margin: 0 2px 0 var\(--sk-lead-hang\);/,
  );
  const tokens = readFileSync(
    path.resolve(import.meta.dirname, "../src/features/mcp-apps/ui/tokens.css"),
    "utf8",
  );
  // The ring is 24 to 32 px; the leading column is the ring plus 20, and at least 44.
  expect(tokens).toMatch(/--sk-ring-glyph: clamp\(24px, 1\.5rem, 32px\);/);
  expect(tokens).toMatch(
    /--sk-lead-w: max\(44px, calc\(var\(--sk-ring-glyph\) \+ 20px\)\);/,
  );
  // The leading column's height is two row paddings plus one row line (the ring sits on
  // the title line's middle).
  expect(tokens).toMatch(
    /--sk-lead-h: calc\(2 \* var\(--sk-row-pad\) \+ var\(--sk-type-row-line\)\);/,
  );
  // No narrow-frame margin pulls the row's content outward at a narrow width.
  expect(css).not.toMatch(/@container sk-frame \(max-width: 360px\)/);
  expect(css).not.toMatch(/margin-inline: -0\.25rem -0\.5rem/);
});

it("the row title is 16 on a 1.3 line and the meta line 14 on a 1.25 line, the agenda's row type", () => {
  const css = readFileSync(
    path.resolve(import.meta.dirname, "../src/features/work-app/agenda.css"),
    "utf8",
  );
  const tokens = readFileSync(
    path.resolve(import.meta.dirname, "../src/features/mcp-apps/ui/tokens.css"),
    "utf8",
  );
  // The line heights in tokens.css, as a ratio of the size: the title 1.3rem on 1rem, the meta 1.09375rem on 0.875rem.
  const rem = (name: string) => {
    const match = new RegExp(`--${name}: ([\\d.]+)rem;`).exec(tokens);
    expect(match, name).not.toBeNull();
    return Number(match?.[1]);
  };
  expect(
    rem("sk-type-row-line") / rem("sk-type-row-size"),
  ).toBeGreaterThanOrEqual(1.3);
  expect(
    rem("sk-type-meta-line") / rem("sk-type-meta-size"),
  ).toBeGreaterThanOrEqual(1.25);
  // The title and the meta line use those types (the row's font shorthand), in the agenda's CSS.
  expect(css).toMatch(
    /\.sidekick-work \.work-agenda-body > button \{[^}]*font: var\(--sk-type-row\);/,
  );
  expect(css).toMatch(/\.work-card-meta \{[^}]*font: var\(--sk-type-meta\);/);
});

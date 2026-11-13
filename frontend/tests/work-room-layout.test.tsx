import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { workEn } from "@/features/work-app/shared/labels";
import {
  projectA,
  rootProject,
  rootTask,
  taskA,
  transport,
} from "./helpers/work-app-fixtures";
import { readStylesheet } from "./helpers/stylesheet";

const ROOM = { room: "sidekick-work" };

/** Builds `html` into the document and returns the element `selector` names in it. */
function markup(html: string, selector: string): Element {
  const host = document.createElement("div");
  host.innerHTML = html;
  document.body.append(host);
  const element = host.querySelector(selector);
  if (!element) throw new Error(`no ${selector}`);
  return element;
}

afterEach(() => {
  document.body.innerHTML = "";
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("shows the Project's editor in place of its values, not under them", async () => {
  const user = userEvent.setup();
  render(rootProject(transport({})));
  expect(await screen.findByText(projectA.description!)).toBeInTheDocument();
  // Edit sits in the ⋯ menu of the header row now.
  await user.click(
    await screen.findByRole("button", { name: workEn.moreActions }),
  );
  await user.click(screen.getByRole("button", { name: workEn.edit }));
  // The description is a field of the editor now, not a paragraph above it as well.
  expect(screen.getByLabelText(workEn.description)).toHaveValue(
    projectA.description,
  );
  expect(
    screen.queryByText(projectA.description!, { selector: "p" }),
  ).toBeNull();
  await user.click(screen.getByRole("button", { name: workEn.cancel }));
  expect(
    screen.getByText(projectA.description!, { selector: "p" }),
  ).toBeInTheDocument();
});

it("offers Show more only when the two drawn lines cut the description", async () => {
  // A wide box: the measured paragraph shows the whole text in its two lines. The observer reports once it observes,
  // as a browser's does.
  vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(40);
  vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockReturnValue(40);
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(private readonly report: () => void) {}
      observe() {
        queueMicrotask(this.report);
      }
      disconnect() {}
    },
  );
  const description =
    "Fakturan ska innehålla timmar för oktober, uppdelade per kund och med momsen angiven för varje rad.";
  const work = transport({
    getTask: vi.fn().mockResolvedValue({ task: { ...taskA, description } }),
  });
  render(rootTask(work));
  expect(await screen.findByText(description)).toBeInTheDocument();
  await waitFor(() =>
    expect(
      screen.queryByRole("button", { name: workEn.descriptionMore }),
    ).toBeNull(),
  );
});

it("wraps a long place inside its chip, with the ⌄ at its end and 44 to tap", () => {
  const css = readStylesheet(
    "features/mcp-apps/ui/family.css",
    "features/work-app/tasks/task-detail.css",
  );
  const chip = markup(
    `<div class="work-task-props work-task-place"><button class="sk-chip work-prop-chip"><span>Plats: Fastighetsförvaltningsprojektet för Bergströms Byggnadsentreprenad AB 2026</span><svg></svg></button></div>`,
    "button",
  );
  expect(css.styleOf(chip, ROOM)).toMatchObject({
    "white-space": "normal",
    "flex-wrap": "nowrap",
    "max-width": "100%",
    "min-width": "0",
    "min-height": "var(--sk-tap)",
  });
  expect(css.styleOf(chip.querySelector("span")!, ROOM)).toMatchObject({
    "min-width": "0",
    "overflow-wrap": "anywhere",
  });
  expect(css.styleOf(chip.querySelector("svg")!, ROOM)).toMatchObject({
    flex: "none",
  });
});

it("draws the Task's Markera klar 44 high beside its chips", () => {
  const css = readStylesheet(
    "features/mcp-apps/ui/family.css",
    "features/work-app/tasks/task-detail.css",
  );
  const done = markup(
    `<div class="work-task-props"><button class="sk-btn--primary sk-btn--compact work-task-done">Markera klar</button></div>`,
    "button",
  );
  expect(css.styleOf(done, ROOM)).toMatchObject({
    "min-height": "var(--sk-tap)",
  });
});

it("keeps the dot before Hög on Status's phone layout, as in the Agenda", () => {
  const css = readStylesheet(
    "features/work-app/shell/work.css",
    "features/work-app/agenda/agenda.css",
  );
  const priority = markup(
    `<div class="work-board" data-layout="single"><section class="work-column"><ul class="work-list"><li class="work-card"><p class="work-card-meta"><span><time>imorgon</time></span><span class="work-card-priority">Hög</span></p></li></ul></section></div>`,
    ".work-card-priority",
  );
  // Status's columns cut every part; the phone layout hangs each part's dot outside its box, so the part must not clip.
  expect(css.styleOf(priority, ROOM)).toMatchObject({ overflow: "visible" });
  expect(css.styleOf(priority, { ...ROOM, pseudo: "::before" })).toMatchObject({
    content: '"·"',
    position: "absolute",
  });
});

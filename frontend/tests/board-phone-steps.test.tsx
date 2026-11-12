import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { fillLabel } from "@/features/work-app/agenda-undo";
import { workEn, workSv } from "@/features/work-app/labels";
import type { WorkItemRecord } from "@/features/work-app/transport";
import {
  KEY,
  a,
  b,
  c,
  d,
  page,
  transport,
  Harness,
} from "./helpers/board-phone-fixtures";

afterEach(() => vi.unstubAllGlobals());

it("a Step right after its Task in the same section is indented and has no meta line at all", async () => {
  const user = userEvent.setup();
  const step: WorkItemRecord = {
    kind: "step",
    id: "019f0000-0000-7000-8000-0000000000f5",
    task_id: a.id,
    title: "Ring receptionen",
    status: "todo",
    due_at: null,
    version: 3,
  };
  const completeTaskStep = vi.fn().mockResolvedValue({
    step: { ...step, status: "completed", version: 4 },
  });
  const work = transport({ completeTaskStep });
  render(
    <Harness
      work={work}
      labels={workSv}
      initial={{
        kind: "board",
        filters: {},
        page: { ...page, columns: { ...page.columns, todo: [a, step, b] } },
      }}
    />,
  );
  const check = screen.getByRole("button", {
    name: fillLabel(workSv.agendaComplete, { title: step.title }),
  });
  const card = check.closest("li") as HTMLElement;
  expect(card).toHaveAttribute("data-kind", "step");
  // The Task stands in the same section, so the Step follows it there (data-nested). The indent
  // says whose Step it is, so a nested Step renders no "Steg" meta line.
  expect(card).toHaveAttribute("data-nested", "true");
  expect(card.querySelector(".work-card-step-of")).toBeNull();
  expect(card.querySelector(".work-card-meta")).toBeNull();
  expect(
    Array.from(
      screen
        .getByRole("region", { name: workSv.taskStatus.todo })
        .querySelectorAll("li[data-card-id]"),
      (item) => item.getAttribute("data-card-id"),
    ),
  ).toEqual([a.id, step.id, b.id]);
  expect(check).toHaveClass("work-card-done");
  expect(check.querySelector(".sk-status-glyph")).not.toBeNull();
  await user.click(check);
  await waitFor(() =>
    expect(completeTaskStep).toHaveBeenCalledWith(
      step.id,
      3,
      expect.stringMatching(KEY),
    ),
  );
});

it("a Step whose Task stands in another section keeps its place there and says Steg i: <titel>", () => {
  const step: WorkItemRecord = {
    kind: "step",
    id: "019f0000-0000-7000-8000-0000000000f7",
    task_id: a.id,
    title: "Ring receptionen",
    status: "todo",
    due_at: null,
    version: 1,
  };
  render(
    <Harness
      work={transport()}
      initial={{
        kind: "board",
        filters: {},
        page: {
          ...page,
          columns: { ...page.columns, in_progress: [c, step] },
        },
      }}
    />,
  );
  const card = screen
    .getByRole("button", {
      name: fillLabel(workEn.agendaComplete, { title: step.title }),
    })
    .closest("li") as HTMLElement;
  expect(card).not.toHaveAttribute("data-nested");
  expect(card.querySelector(".work-card-step-of")).toHaveTextContent(
    fillLabel(workEn.stepOf, { title: a.title }),
  );
  expect(
    Array.from(
      screen
        .getByRole("region", { name: workEn.taskStatus.in_progress })
        .querySelectorAll("li[data-card-id]"),
      (item) => item.getAttribute("data-card-id"),
    ),
  ).toEqual([c.id, step.id]);
});

it("a Step whose Task is not on the page says only Steg", () => {
  const step: WorkItemRecord = {
    kind: "step",
    id: "019f0000-0000-7000-8000-0000000000f6",
    task_id: "019f0000-0000-7000-8000-0000000000f9",
    title: "Skicka kvittot",
    status: "todo",
    due_at: null,
    version: 1,
  };
  render(
    <Harness
      work={transport()}
      labels={workSv}
      initial={{
        kind: "board",
        filters: {},
        page: { ...page, columns: { todo: [step], completed: [] } },
      }}
    />,
  );
  const card = screen
    .getByRole("button", {
      name: fillLabel(workSv.agendaComplete, { title: step.title }),
    })
    .closest("li") as HTMLElement;
  expect(card.querySelector(".work-card-step-of")).toHaveTextContent(/^Steg$/);
});

it("a second tap on a Step, queued behind its own write, keeps the state it had at the tap: it does not reopen the Step", async () => {
  const user = userEvent.setup();
  const step: WorkItemRecord = {
    kind: "step",
    id: "019f0000-0000-7000-8000-0000000000f7",
    task_id: a.id,
    title: "Ring receptionen",
    status: "todo",
    due_at: null,
    version: 3,
  };
  const doneStep: WorkItemRecord = { ...step, status: "completed", version: 4 };
  let answer!: (value: unknown) => void;
  const completeTaskStep = vi.fn().mockImplementation(
    () =>
      new Promise((resolve) => {
        answer = resolve;
      }),
  );
  const updateTaskStep = vi.fn().mockResolvedValue({
    step: { ...step, status: "todo", version: 5 },
  });
  const getWorkBoard = vi.fn().mockResolvedValue({
    ...page,
    columns: { ...page.columns, todo: [a, b], completed: [d, doneStep] },
  });
  const work = transport({ completeTaskStep, updateTaskStep, getWorkBoard });
  render(
    <Harness
      work={work}
      labels={workSv}
      initial={{
        kind: "board",
        filters: {},
        page: { ...page, columns: { ...page.columns, todo: [a, step, b] } },
      }}
    />,
  );
  const check = () =>
    screen.getByRole("button", {
      name: fillLabel(workSv.agendaComplete, { title: step.title }),
    });
  await user.click(check());
  await waitFor(() => expect(completeTaskStep).toHaveBeenCalledTimes(1));
  // The second tap comes while the first write runs: it is queued, and it asked for Klar, as the first did.
  await user.click(check());
  act(() => {
    answer({ step: doneStep });
  });
  await waitFor(() => expect(getWorkBoard).toHaveBeenCalled());
  // The Step is done already: the queued tap writes nothing, and does not reopen it.
  expect(completeTaskStep).toHaveBeenCalledTimes(1);
  expect(updateTaskStep).not.toHaveBeenCalled();
});

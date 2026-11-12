import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { HostToolError } from "@/features/mcp-apps/bridge";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import { WorkView } from "@/features/work-app/view/work-view";
import {
  KEY,
  keyOf,
  rootTask,
  taskA,
  transport,
} from "./helpers/work-app-fixtures";

/*
 * "Ta bort uppgift" in the Task's ⋯: move_to_trash at the Task's version, then the line with Ångra
 * (restore_from_trash at the trash version). The views run in jsdom with a simulated host; this is not a real
 * Claude or Android host.
 */

async function openMenu(
  user: ReturnType<typeof userEvent.setup>,
  name: string = workEn.moreActions,
) {
  await user.click(await screen.findByRole("button", { name }));
}

it("deletes the Task to the trash at its version, with a key, and shows the line with Undo", async () => {
  const user = userEvent.setup();
  const trashTask = vi.fn().mockResolvedValue({ version: 7 });
  const work = transport({ trashTask });
  render(rootTask(work));
  await openMenu(user);
  await user.click(screen.getByRole("button", { name: workEn.deleteTask }));
  expect(await screen.findByText(workEn.taskTrashed)).toBeInTheDocument();
  expect(trashTask).toHaveBeenCalledWith(
    taskA.id,
    expect.any(Number),
    expect.stringMatching(KEY),
  );
  expect(screen.getByRole("button", { name: workEn.undo })).toBeEnabled();
  // The Task body and its menu are gone while it is in the trash.
  expect(screen.queryByRole("button", { name: workEn.moreActions })).toBeNull();
});

it("puts the delete entry last-but-archive in the danger style and closes the menu when chosen", async () => {
  const user = userEvent.setup();
  render(rootTask(transport()));
  await openMenu(user);
  const entry = screen.getByRole("button", { name: workEn.deleteTask });
  expect(entry).toHaveAttribute("data-danger");
  expect(screen.getByRole("button", { name: workEn.edit })).toBeInTheDocument();
  await user.click(entry);
  await screen.findByText(workEn.taskTrashed);
  expect(screen.queryByRole("button", { name: workEn.edit })).toBeNull();
});

it("Undo restores the Task at the trash version and reads it again", async () => {
  const user = userEvent.setup();
  const trashTask = vi.fn().mockResolvedValue({ version: 7 });
  const restoreTask = vi.fn().mockResolvedValue({});
  const work = transport({ trashTask, restoreTask });
  render(rootTask(work));
  await openMenu(user);
  await user.click(screen.getByRole("button", { name: workEn.deleteTask }));
  await user.click(await screen.findByRole("button", { name: workEn.undo }));
  expect(
    await screen.findByRole("heading", { name: taskA.title }),
  ).toBeInTheDocument();
  expect(restoreTask).toHaveBeenCalledWith(
    taskA.id,
    7,
    expect.stringMatching(KEY),
  );
  expect(screen.queryByText(workEn.taskTrashed)).toBeNull();
  expect(
    screen.getByRole("button", { name: workEn.moreActions }),
  ).toBeInTheDocument();
});

it("retries a failed delete with the same key and says nothing from the backend", async () => {
  const user = userEvent.setup();
  const trashTask = vi
    .fn()
    .mockRejectedValueOnce(new Error("PRIVATE_BACKEND_MESSAGE"))
    .mockResolvedValue({ version: 7 });
  render(rootTask(transport({ trashTask })));
  await openMenu(user);
  await user.click(screen.getByRole("button", { name: workEn.deleteTask }));
  expect(await screen.findByText(workEn.taskTrashFailed)).toBeInTheDocument();
  expect(screen.queryByText("PRIVATE_BACKEND_MESSAGE")).toBeNull();
  await user.click(screen.getByRole("button", { name: workEn.retry }));
  expect(await screen.findByText(workEn.taskTrashed)).toBeInTheDocument();
  expect(trashTask).toHaveBeenCalledTimes(2);
  expect(keyOf(trashTask, 1)).toBe(keyOf(trashTask, 0));
});

it("says the Task changed elsewhere when the delete meets a stale version", async () => {
  const user = userEvent.setup();
  const trashTask = vi.fn().mockRejectedValue(new HostToolError("conflict"));
  render(rootTask(transport({ trashTask })));
  await openMenu(user);
  await user.click(screen.getByRole("button", { name: workEn.deleteTask }));
  expect(await screen.findByText(workEn.conflict)).toBeInTheDocument();
  expect(screen.queryByText(workEn.taskTrashed)).toBeNull();
});

it("shows a failed Undo and tries again with the same key", async () => {
  const user = userEvent.setup();
  const restoreTask = vi
    .fn()
    .mockRejectedValueOnce(new Error("down"))
    .mockResolvedValue({});
  render(rootTask(transport({ restoreTask })));
  await openMenu(user);
  await user.click(screen.getByRole("button", { name: workEn.deleteTask }));
  await user.click(await screen.findByRole("button", { name: workEn.undo }));
  expect(await screen.findByText(workEn.taskRestoreFailed)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: workEn.undo }));
  await waitFor(() => expect(restoreTask).toHaveBeenCalledTimes(2));
  expect(keyOf(restoreTask, 1)).toBe(keyOf(restoreTask, 0));
  expect(
    await screen.findByRole("heading", { name: taskA.title }),
  ).toBeVisible();
});

it("offers the delete only when the host answers both trash tools", async () => {
  const user = userEvent.setup();
  const work = transport({
    supportsTool: (name: string) => name !== "restore_from_trash",
  });
  render(rootTask(work));
  await openMenu(user);
  expect(screen.getByRole("button", { name: workEn.edit })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: workEn.deleteTask })).toBeNull();
});

it("names the delete and Undo in Swedish", async () => {
  const user = userEvent.setup();
  render(
    <WorkView
      transport={transport()}
      initial={{ kind: "task", id: taskA.id }}
      labels={workSv}
    />,
  );
  await openMenu(user, workSv.moreActions);
  await user.click(screen.getByRole("button", { name: "Ta bort uppgift" }));
  expect(
    await screen.findByText("Uppgiften är borttagen."),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Ångra" })).toBeInTheDocument();
});

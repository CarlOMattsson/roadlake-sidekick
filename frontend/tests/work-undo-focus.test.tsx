import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { workSv } from "@/features/work-app/labels";
import { linksLabelsSv } from "@/features/work-app/links-labels";
import { manageLabelsSv } from "@/features/work-app/manage-labels";
import { StepActions } from "@/features/work-app/step-actions";
import { TaskReferences } from "@/features/work-app/task-references";
import { TaskSteps } from "@/features/work-app/task-steps";
import type {
  WorkAction,
  WorkExternalReference,
  WorkStep,
  WorkTransport,
} from "@/features/work-app/transport";

// jsdom has no CSS global; the row controls select their buttons with CSS.escape, as the browser does.
if (!("CSS" in globalThis)) {
  vi.stubGlobal("CSS", { escape: (value: string) => value });
}

/*
 * The focus rule every list follows: an archive or an unlink puts focus on its Undo line; Undo puts
 * it back on the restored row, or on the row now standing in its place when that row is gone.
 */

const TASK = "019f0000-0000-7000-8000-0000000000a1";
const STEP_ID = "019f0000-0000-7000-8000-0000000000s1";
const sv = manageLabelsSv;

function step(id: string, title: string, version: number): WorkStep {
  return { id, title, status: "todo", due_at: null, version, position: 0 };
}
const stepA = step("019f0000-0000-7000-8000-0000000000b1", "Ring Anna", 1);
const stepB = step("019f0000-0000-7000-8000-0000000000b2", "Skriv offert", 2);
const stepC = step("019f0000-0000-7000-8000-0000000000b3", "Skicka faktura", 3);
const page = (items: WorkStep[]) => ({ items, next_cursor: null });

/** Opens a Step's menu with a right click on its row. */
async function openStepMenu(title: string): Promise<void> {
  const check = await screen.findByRole("checkbox", { name: title });
  fireEvent.contextMenu(check.closest("li") as HTMLElement);
}

const ring: WorkAction = {
  id: "019f0000-0000-7000-8000-0000000000f1",
  step_id: STEP_ID,
  title: "Ring receptionen",
  status: "todo",
  due_at: null,
  version: 1,
  position: 0,
};
const mailAction: WorkAction = {
  id: "019f0000-0000-7000-8000-0000000000f2",
  step_id: STEP_ID,
  title: "Skicka mejlet",
  status: "todo",
  due_at: null,
  version: 1,
  position: 1,
};

const mail: WorkExternalReference = {
  id: "019f0000-0000-7000-8000-0000000000e1",
  kind: "mail",
  provider: "google_gmail",
  account_ref: "acc-1",
  external_id: "msg-1",
  instance_ref: null,
  title: "Offert på tak",
  url: "https://mail.example.test/msg-1",
  occurs_at: null,
};
const doc: WorkExternalReference = {
  id: "019f0000-0000-7000-8000-0000000000e2",
  kind: "document",
  provider: "google_drive",
  account_ref: "acc-1",
  external_id: "doc-1",
  instance_ref: null,
  title: "Avtal",
  url: null,
  occurs_at: null,
};

function removeReference(reference: WorkExternalReference) {
  return screen.getByRole("button", {
    name: linksLabelsSv.removeReferenceFor(reference.title),
  });
}

describe("focus after an archive or an unlink, and after Undo", () => {
  it("TaskSteps: archive focuses Ångra, and Ångra focuses the restored Step", async () => {
    const user = userEvent.setup();
    const transport = {
      listTaskSteps: vi
        .fn()
        .mockResolvedValueOnce(page([stepA, stepB, stepC]))
        .mockResolvedValue(page([stepA, { ...stepB, version: 4 }, stepC])),
      archiveTaskStep: vi
        .fn()
        .mockResolvedValue({ step: { ...stepB, version: 3 } }),
      restoreTaskStep: vi
        .fn()
        .mockResolvedValue({ step: { ...stepB, version: 4 } }),
    } as unknown as WorkTransport;
    render(<TaskSteps taskId={TASK} transport={transport} labels={workSv} />);

    await openStepMenu(stepB.title);
    await user.click(
      screen.getByRole("button", { name: sv.archiveFor(stepB.title) }),
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: sv.undo })).toHaveFocus(),
    );
    await user.click(screen.getByRole("button", { name: sv.undo }));
    await waitFor(() =>
      expect(screen.getByRole("checkbox", { name: stepB.title })).toHaveFocus(),
    );
  });

  it("TaskSteps: when the restored Step is gone from the fresh list, the Step now at its place takes the focus", async () => {
    const user = userEvent.setup();
    const transport = {
      listTaskSteps: vi
        .fn()
        .mockResolvedValueOnce(page([stepA, stepB, stepC]))
        .mockResolvedValue(page([stepA, stepC])),
      archiveTaskStep: vi
        .fn()
        .mockResolvedValue({ step: { ...stepB, version: 3 } }),
      restoreTaskStep: vi
        .fn()
        .mockResolvedValue({ step: { ...stepB, version: 4 } }),
    } as unknown as WorkTransport;
    render(<TaskSteps taskId={TASK} transport={transport} labels={workSv} />);

    await openStepMenu(stepB.title);
    await user.click(
      screen.getByRole("button", { name: sv.archiveFor(stepB.title) }),
    );
    await user.click(await screen.findByRole("button", { name: sv.undo }));
    await waitFor(() =>
      expect(screen.getByRole("checkbox", { name: stepC.title })).toHaveFocus(),
    );
  });

  it("StepActions: archive focuses Ångra, and Ångra focuses the restored Action", async () => {
    const user = userEvent.setup();
    const transport = {
      listStepActions: vi
        .fn()
        .mockResolvedValue({ items: [ring, mailAction], next_cursor: null }),
      archiveStepAction: vi.fn().mockResolvedValue({
        action: { ...ring, version: 2, archived_at: "2026-11-02T08:00:00Z" },
      }),
      restoreStepAction: vi
        .fn()
        .mockResolvedValue({ action: { ...ring, version: 3 } }),
    } as unknown as WorkTransport;
    render(
      <StepActions
        step={{ ...stepA, id: STEP_ID }}
        transport={transport}
        labels={workSv}
        open
      />,
    );

    await user.click(
      await screen.findByRole("button", { name: "Arkivera: Ring receptionen" }),
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: sv.undo })).toHaveFocus(),
    );
    await user.click(screen.getByRole("button", { name: sv.undo }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Arkivera: Ring receptionen" }),
      ).toHaveFocus(),
    );
  });

  it("TaskReferences: remove focuses Ångra, and Ångra focuses the restored pointer by its title", async () => {
    const user = userEvent.setup();
    const transport = {
      listTaskExternalReferences: vi
        .fn()
        .mockResolvedValueOnce({ items: [mail, doc], next_cursor: null })
        .mockResolvedValue({
          items: [{ ...mail, id: "019f0000-0000-7000-8000-0000000000e9" }, doc],
          next_cursor: null,
        }),
      unlinkExternalReferenceFromTask: vi
        .fn()
        .mockResolvedValue({ linked: false, reference_removed: true }),
      linkExternalReferenceToTask: vi.fn().mockResolvedValue({ linked: true }),
    } as unknown as WorkTransport;
    render(
      <TaskReferences taskId={TASK} transport={transport} labels={workSv} />,
    );

    await user.click(
      await screen.findByRole("button", {
        name: linksLabelsSv.removeReferenceFor(mail.title),
      }),
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: sv.undo })).toHaveFocus(),
    );
    await user.click(screen.getByRole("button", { name: sv.undo }));
    await waitFor(() => expect(removeReference(mail)).toHaveFocus());
  });

  it("TaskReferences: when the restored pointer is gone from the fresh list, the row now at its place takes the focus", async () => {
    const user = userEvent.setup();
    const transport = {
      listTaskExternalReferences: vi
        .fn()
        .mockResolvedValueOnce({ items: [mail, doc], next_cursor: null })
        .mockResolvedValue({ items: [doc], next_cursor: null }),
      unlinkExternalReferenceFromTask: vi
        .fn()
        .mockResolvedValue({ linked: false, reference_removed: true }),
      linkExternalReferenceToTask: vi.fn().mockResolvedValue({ linked: true }),
    } as unknown as WorkTransport;
    render(
      <TaskReferences taskId={TASK} transport={transport} labels={workSv} />,
    );

    await user.click(
      await screen.findByRole("button", {
        name: linksLabelsSv.removeReferenceFor(mail.title),
      }),
    );
    await user.click(await screen.findByRole("button", { name: sv.undo }));
    await waitFor(() => expect(removeReference(doc)).toHaveFocus());
  });
});

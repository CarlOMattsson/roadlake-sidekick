import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import {
  processFrameLabelsEn,
  processFrameLabelsSv,
} from "@/features/work-app/hierarchy/process-frame-labels";
import type {
  WorkProcessRecord,
  WorkTransport,
} from "@/features/work-app/transport/transport";
import { WorkView } from "@/features/work-app/view/work-view";
import { transport as fakeTransport } from "@tests/helpers/work-app-fixtures";

/*
 * The Process page: kicker, name, the "Hem · Varje vecka" line, the status only when it is not active, the description
 * and the Process's Tasks with "+ Ny uppgift". A simulated host only: the phone's closed list of routes is stood in for
 * by supportsTool/supportsCall stubs, not a real device.
 */

const PROCESS_ID = "019f0000-0000-7000-8000-0000000000e1";
const DOMAIN_ID = "019f0000-0000-7000-8000-0000000000f1";

const processRecord: WorkProcessRecord = {
  id: PROCESS_ID,
  domain_id: DOMAIN_ID,
  name: "Fakturering",
  description: "Skicka och följ upp fakturor.",
  status: "active",
  cadence: "Varje vecka",
  tags: [],
  version: 1,
};
const taskRow = {
  id: "019f0000-0000-7000-8000-0000000000a9",
  title: "Skicka veckofaktura",
  status: "todo",
  due_at: null,
};

function transportWith(overrides: Partial<WorkTransport> = {}): WorkTransport {
  return fakeTransport({
    getProcess: vi.fn().mockResolvedValue({ process: processRecord }),
    getDomain: vi
      .fn()
      .mockResolvedValue({ domain: { id: DOMAIN_ID, name: "Hem" } }),
    listProcessTasks: vi
      .fn()
      .mockResolvedValue({ items: [taskRow], next_cursor: null }),
    createTask: vi.fn().mockResolvedValue({
      task: { ...taskRow, id: "new-1", title: "Ny faktura", version: 1 },
    }),
    ...overrides,
  });
}

function renderProcess(transport: WorkTransport, labels = workSv) {
  return render(
    <WorkView
      transport={transport}
      initial={{ kind: "process", id: PROCESS_ID }}
      labels={labels}
    />,
  );
}

describe("the Process page", () => {
  it("shows the kicker, the name, the Area and cadence line, the description and the Tasks", async () => {
    const transport = transportWith();
    renderProcess(transport);

    expect(
      await screen.findByRole("heading", { name: "Fakturering" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Process", { selector: ".sk-eyebrow" }),
    ).toBeVisible();
    await waitFor(() => expect(screen.getByText("Hem")).toBeInTheDocument());
    const line = screen.getByText("Varje vecka").closest("p");
    expect(line).toHaveTextContent("Hem");
    expect(screen.getByText("Skicka och följ upp fakturor.")).toBeVisible();
    expect(await screen.findByText("Skicka veckofaktura")).toBeInTheDocument();
    expect(transport.listProcessTasks).toHaveBeenCalledWith(PROCESS_ID);
    expect(screen.queryByText(new RegExp(`^${workSv.status}:`))).toBeNull();
  });

  it("names the status only when the Process is not active", async () => {
    renderProcess(
      transportWith({
        getProcess: vi.fn().mockResolvedValue({
          process: { ...processRecord, status: "paused" },
        }),
      }),
    );
    expect(
      await screen.findByText(new RegExp(`^${workSv.status}:`)),
    ).toBeInTheDocument();
  });

  it("goes without the Area name, and without an error, when the Area cannot be read", async () => {
    const getDomain = vi.fn().mockRejectedValue(new Error("nope"));
    renderProcess(transportWith({ getDomain }));
    expect(
      await screen.findByRole("heading", { name: "Fakturering" }),
    ).toBeInTheDocument();
    await waitFor(() => expect(getDomain).toHaveBeenCalledWith(DOMAIN_ID));
    expect(screen.getByText("Varje vecka")).toBeVisible();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("creates a Task in the Process with process_id and puts it at the top", async () => {
    const user = userEvent.setup();
    const transport = transportWith();
    renderProcess(transport);

    await user.click(await screen.findByRole("button", { name: /Ny uppgift/ }));
    await user.type(screen.getByLabelText(workSv.newTaskTitle), "Ny faktura");
    await user.click(screen.getByRole("button", { name: workSv.createTask }));

    await waitFor(() => expect(transport.createTask).toHaveBeenCalled());
    const body = vi.mocked(transport.createTask).mock.calls[0]?.[0];
    expect(body).toMatchObject({ title: "Ny faktura", process_id: PROCESS_ID });
    expect(body).not.toHaveProperty("project_id");
    const list = screen.getByRole("list");
    expect(within(list).getAllByRole("listitem")[0]).toHaveTextContent(
      "Ny faktura",
    );
  });

  it("shows a calm line, and reads no Tasks, on a host that lists Project Tasks only", async () => {
    const transport = transportWith({
      supportsTool: () => true,
      supportsCall: (name: string) => name !== "list_tasks",
    });
    renderProcess(transport);

    expect(
      await screen.findByText(processFrameLabelsSv.tasksUnavailable),
    ).toBeVisible();
    expect(transport.listProcessTasks).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /Ny uppgift/ })).toBeNull();
  });

  it("offers Try again when the Tasks cannot be read, with the Process itself still shown", async () => {
    const user = userEvent.setup();
    const listProcessTasks = vi
      .fn()
      .mockRejectedValueOnce(new Error("down"))
      .mockResolvedValue({ items: [taskRow], next_cursor: null });
    renderProcess(transportWith({ listProcessTasks }));

    expect(
      await screen.findByRole("heading", { name: "Fakturering" }),
    ).toBeVisible();
    await user.click(await screen.findByRole("button", { name: workSv.retry }));
    expect(await screen.findByText("Skicka veckofaktura")).toBeInTheDocument();
  });

  it("says the Process is gone, with no retry, when the server no longer has it", async () => {
    renderProcess(
      transportWith({
        getProcess: vi.fn().mockRejectedValue(
          Object.assign(new Error("gone"), {
            name: "HostToolError",
            code: "not_found",
          }),
        ),
      }),
    );
    expect(
      await screen.findByText(processFrameLabelsSv.gone),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: workSv.retry })).toBeNull();
  });

  it("reads in English with the English words", async () => {
    renderProcess(
      transportWith({
        getProcess: vi.fn().mockResolvedValue({
          process: { ...processRecord, status: "paused" },
        }),
        listProcessTasks: vi
          .fn()
          .mockResolvedValue({ items: [], next_cursor: null }),
      }),
      workEn,
    );
    expect(
      await screen.findByText(processFrameLabelsEn.noTasks),
    ).toBeInTheDocument();
  });

  it.each([
    ["sv", workSv, processFrameLabelsSv],
    ["en", workEn, processFrameLabelsEn],
  ])(
    "says the Task list is cut short when the server truncated it and has no cursor (%s)",
    async (_name, labels, words) => {
      renderProcess(
        transportWith({
          listProcessTasks: vi.fn().mockResolvedValue({
            items: [taskRow],
            next_cursor: null,
            truncated: true,
          }),
        }),
        labels,
      );
      expect(await screen.findByText(taskRow.title)).toBeInTheDocument();
      expect(screen.getByText(words.tasksTruncated)).toBeInTheDocument();
    },
  );

  it("shows no truncation line for a complete Task list", async () => {
    renderProcess(transportWith());
    await screen.findByText(taskRow.title);
    expect(
      screen.queryByText(processFrameLabelsSv.tasksTruncated),
    ).not.toBeInTheDocument();
  });

  it("has the same word keys in Swedish and English", () => {
    expect(Object.keys(processFrameLabelsEn).sort()).toEqual(
      Object.keys(processFrameLabelsSv).sort(),
    );
  });
});

import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { HostToolError } from "@/features/mcp-apps/bridge";
import { workEn, workSv } from "@/features/work-app/labels";
import {
  linksLabelsEn,
  linksLabelsFor,
  linksLabelsSv,
} from "@/features/work-app/links-labels";
import { manageLabelsSv } from "@/features/work-app/manage-labels";
import { TaskReferences } from "@/features/work-app/task-references";
import type {
  WorkExternalReference,
  WorkTransport,
} from "@/features/work-app/transport";

const TASK = "019f0000-0000-7000-8000-0000000000a1";
const KEY =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const mail: WorkExternalReference = {
  id: "019f0000-0000-7000-8000-0000000000e1",
  kind: "mail",
  provider: "google_gmail",
  account_ref: "acc-1",
  external_id: "msg-1",
  instance_ref: null,
  title: "Offert på tak",
  url: "https://mail.example.test/msg-1",
  occurs_at: "2026-11-02T09:00:00Z",
};
const doc: WorkExternalReference = {
  id: "019f0000-0000-7000-8000-0000000000e2",
  kind: "document",
  provider: "google_drive",
  account_ref: "acc-1",
  external_id: "doc-1",
  instance_ref: null,
  title: "<b>x</b> Avtal",
  url: null,
  occurs_at: null,
};
// The pointer is dated the day before the test clock (2026-11-03 in Stockholm): "igår".
const mailDate = "igår";

function transport(overrides: Partial<WorkTransport>): WorkTransport {
  return {
    listTaskExternalReferences: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
    unlinkExternalReferenceFromTask: vi
      .fn()
      .mockResolvedValue({ linked: false, reference_removed: true }),
    linkExternalReferenceToTask: vi.fn().mockResolvedValue({ linked: true }),
    ...overrides,
  } as unknown as WorkTransport;
}

function removeButton(reference: WorkExternalReference) {
  return screen.getByRole("button", {
    name: linksLabelsSv.removeReferenceFor(reference.title),
  });
}

describe("TaskReferences", () => {
  it("renders nothing when the Task has no pointers", async () => {
    const list = vi.fn().mockResolvedValue({ items: [], next_cursor: null });
    const { container } = render(
      <TaskReferences
        taskId={TASK}
        transport={transport({ listTaskExternalReferences: list })}
        labels={workSv}
      />,
    );
    await waitFor(() => expect(list).toHaveBeenCalledWith(TASK));
    await act(async () => {});
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when the list is forbidden", async () => {
    const list = vi.fn().mockRejectedValue(new HostToolError("forbidden"));
    const { container } = render(
      <TaskReferences
        taskId={TASK}
        transport={transport({ listTaskExternalReferences: list })}
        labels={workSv}
      />,
    );
    await waitFor(() => expect(list).toHaveBeenCalledTimes(1));
    await act(async () => {});
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when the list cannot be read", async () => {
    const list = vi
      .fn()
      .mockRejectedValue(new Error("PRIVATE_BACKEND_MESSAGE"));
    const { container } = render(
      <TaskReferences
        taskId={TASK}
        transport={transport({ listTaskExternalReferences: list })}
        labels={workSv}
      />,
    );
    await waitFor(() => expect(list).toHaveBeenCalledTimes(1));
    await act(async () => {});
    expect(container).toBeEmptyDOMElement();
  });

  it("shows titles as plain text with kind, date and a remove button, and no link", async () => {
    // Only Date is faked, so the relative date of the pointer is stable.
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-11-03T12:00:00Z"));
    const list = vi
      .fn()
      .mockResolvedValue({ items: [mail, doc], next_cursor: null });
    const { container } = render(
      <TaskReferences
        taskId={TASK}
        transport={transport({ listTaskExternalReferences: list })}
        labels={workSv}
      />,
    );
    expect(
      await screen.findByRole("heading", { name: linksLabelsSv.references }),
    ).toBeInTheDocument();
    expect(screen.getByText(mail.title)).toBeInTheDocument();
    expect(screen.getByText("<b>x</b> Avtal")).toBeInTheDocument();
    expect(container.querySelector("b")).toBeNull();
    expect(container.querySelector("a")).toBeNull();
    expect(
      screen.getByText(`${linksLabelsSv.kind.mail} · ${mailDate}`),
    ).toBeInTheDocument();
    expect(screen.getByText(linksLabelsSv.kind.document)).toBeInTheDocument();
    expect(screen.getByText(linksLabelsSv.keptNote)).toBeInTheDocument();
    expect(removeButton(mail)).toHaveTextContent(manageLabelsSv.removeLink);
    expect(removeButton(doc)).toBeInTheDocument();
    vi.useRealTimers();
  });

  it("removes only the pointer, offers Undo, then links it back and reads the list again", async () => {
    const user = userEvent.setup();
    const list = vi
      .fn()
      .mockResolvedValueOnce({ items: [mail], next_cursor: null })
      .mockResolvedValue({
        items: [{ ...mail, id: "019f0000-0000-7000-8000-0000000000e9" }],
        next_cursor: null,
      });
    const unlink = vi
      .fn()
      .mockResolvedValue({ linked: false, reference_removed: true });
    const link = vi.fn().mockResolvedValue({ linked: true });
    render(
      <TaskReferences
        taskId={TASK}
        transport={transport({
          listTaskExternalReferences: list,
          unlinkExternalReferenceFromTask: unlink,
          linkExternalReferenceToTask: link,
        })}
        labels={workSv}
      />,
    );
    await user.click(
      await screen.findByRole("button", {
        name: linksLabelsSv.removeReferenceFor(mail.title),
      }),
    );
    expect(unlink).toHaveBeenCalledWith(
      TASK,
      mail.id,
      expect.stringMatching(KEY),
    );
    expect(
      await screen.findByText(linksLabelsSv.referenceUnlinked(mail.title)),
    ).toBeInTheDocument();
    expect(screen.queryByText(mail.title)).not.toBeInTheDocument();
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: manageLabelsSv.undo }),
      ).toHaveFocus(),
    );
    await user.click(screen.getByRole("button", { name: manageLabelsSv.undo }));
    await waitFor(() => expect(list).toHaveBeenCalledTimes(2));
    expect(link).toHaveBeenCalledWith(TASK, mail, expect.stringMatching(KEY));
    expect(await screen.findByText(mail.title)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: manageLabelsSv.undo }),
    ).not.toBeInTheDocument();
    // The pointer came back under a new id, so its row is found by title and takes the focus.
    await waitFor(() => expect(removeButton(mail)).toHaveFocus());
  });

  it("sends the same idempotency key when a failed removal is tried again", async () => {
    const user = userEvent.setup();
    const unlink = vi
      .fn()
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValueOnce({ linked: false, reference_removed: true });
    render(
      <TaskReferences
        taskId={TASK}
        transport={transport({
          listTaskExternalReferences: vi
            .fn()
            .mockResolvedValue({ items: [mail], next_cursor: null }),
          unlinkExternalReferenceFromTask: unlink,
        })}
        labels={workSv}
      />,
    );
    await user.click(
      await screen.findByRole("button", {
        name: linksLabelsSv.removeReferenceFor(mail.title),
      }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      manageLabelsSv.failed,
    );
    await user.click(
      screen.getByRole("button", { name: manageLabelsSv.retry }),
    );
    await waitFor(() => expect(unlink).toHaveBeenCalledTimes(2));
    const firstKey: unknown = unlink.mock.calls[0]?.[2];
    expect(firstKey).toMatch(KEY);
    expect(unlink.mock.calls[1]?.[2]).toBe(firstKey);
    expect(
      await screen.findByText(linksLabelsSv.referenceUnlinked(mail.title)),
    ).toBeInTheDocument();
  });

  it("explains a conflict on Undo and reads the list again on request", async () => {
    const user = userEvent.setup();
    const list = vi
      .fn()
      .mockResolvedValue({ items: [mail], next_cursor: null });
    const unlink = vi
      .fn()
      .mockResolvedValue({ linked: false, reference_removed: true });
    const link = vi.fn().mockRejectedValue(new HostToolError("conflict"));
    render(
      <TaskReferences
        taskId={TASK}
        transport={transport({
          listTaskExternalReferences: list,
          unlinkExternalReferenceFromTask: unlink,
          linkExternalReferenceToTask: link,
        })}
        labels={workSv}
      />,
    );
    await user.click(
      await screen.findByRole("button", {
        name: linksLabelsSv.removeReferenceFor(mail.title),
      }),
    );
    await user.click(
      await screen.findByRole("button", { name: manageLabelsSv.undo }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      manageLabelsSv.conflict,
    );
    await user.click(
      screen.getByRole("button", { name: manageLabelsSv.reload }),
    );
    await waitFor(() => expect(list).toHaveBeenCalledTimes(2));
  });

  it("shows the next page on Show more and keeps the first one", async () => {
    const user = userEvent.setup();
    const list = vi
      .fn()
      .mockResolvedValueOnce({ items: [mail], next_cursor: "page-2" })
      .mockResolvedValueOnce({ items: [doc], next_cursor: null });
    render(
      <TaskReferences
        taskId={TASK}
        transport={transport({ listTaskExternalReferences: list })}
        labels={workSv}
      />,
    );
    await user.click(
      await screen.findByRole("button", { name: linksLabelsSv.more }),
    );
    expect(await screen.findByText("<b>x</b> Avtal")).toBeInTheDocument();
    expect(screen.getByText(mail.title)).toBeInTheDocument();
    expect(list).toHaveBeenLastCalledWith(TASK, "page-2");
    expect(
      screen.queryByRole("button", { name: linksLabelsSv.more }),
    ).not.toBeInTheDocument();
  });

  it("has the same keys in Swedish and English and picks the locale", () => {
    expect(Object.keys(linksLabelsSv).sort()).toEqual(
      Object.keys(linksLabelsEn).sort(),
    );
    expect(Object.keys(linksLabelsSv.kind).sort()).toEqual(
      Object.keys(linksLabelsEn.kind).sort(),
    );
    expect(linksLabelsFor(workSv.dateLocale)).toBe(linksLabelsSv);
    expect(linksLabelsFor(workEn.dateLocale)).toBe(linksLabelsEn);
  });
});

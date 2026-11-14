import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { tagEn, tagSv } from "@/features/mcp-apps/ui/tag-labels";
import type { TagRecord } from "@/features/mcp-apps/ui/tag-vocabulary";
import { WorkView } from "@/features/work-app/view/work-view";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import {
  filterTags,
  withFilterTags,
} from "@/features/work-app/shared/work-tags";
import {
  agendaTask,
  projectA,
  projectTask,
  rootBoard,
  rootProject,
  rootTask,
  taskA,
  transport,
  boardPage,
  boardTask,
} from "@tests/helpers/work-app-fixtures";

function tag(slug: string, task: number, project = 0, label = slug): TagRecord {
  return {
    id: `019f0000-0000-7000-8000-${String(task * 10 + project).padStart(12, "0")}`,
    slug,
    archived_at: null,
    label,
    created_at: "2026-11-01T10:00:00Z",
    updated_at: "2026-11-01T10:00:00Z",
    version: 1,
    usage: {
      contact: 4,
      domain: null,
      journal_entry: null,
      process: null,
      project,
      task,
    },
  };
}

// "kund" marks a Project only, "familj" no Task or Project: the Work filter offers Task and Project tags.
const vocabulary = [
  tag("viktig", 5),
  tag("kund", 0, 2),
  tag("familj", 0),
  tag("bygg", 1, 0, "Bygg Göteborg"),
];

afterEach(() => vi.restoreAllMocks());

describe("the tag filter of Agenda and Status", () => {
  it("keeps the other filters and drops both tag keys when no tag is chosen", () => {
    const filters = { status: "todo", tags: ["a"], tag_match: "any" };
    expect(withFilterTags(filters, ["a", "b"])).toEqual({
      status: "todo",
      tags: ["a", "b"],
      tag_match: "all",
    });
    expect(withFilterTags(filters, [])).toEqual({ status: "todo" });
    expect(filterTags(filters)).toEqual(["a"]);
    expect(filterTags({ tags: "solo" })).toEqual(["solo"]);
    expect(filterTags({})).toEqual([]);
  });

  it("Agenda reads again with every chosen tag and says when nothing carries them", async () => {
    const user = userEvent.setup();
    const getWorkAgenda = vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null });
    const work = transport({
      getWorkAgenda,
      listTags: vi.fn().mockResolvedValue(vocabulary),
    });
    render(
      <WorkView
        transport={work}
        initial={{
          kind: "agenda",
          filters: { status: "todo" },
          page: {
            items: [{ ...agendaTask, tags: ["viktig", "bygg", "kund"] }],
            next_cursor: null,
          },
        }}
        labels={workSv}
      />,
    );
    // The row reads its tags by the vocabulary's labels: two and "+1".
    await waitFor(() =>
      expect(
        screen.getByText(`${tagSv.tags}: viktig, Bygg Göteborg och 1 till`),
      ).toBeInTheDocument(),
    );
    const group = screen.getByRole("group", { name: tagSv.filter });
    // In use on Tasks or Projects, most used first; "familj" marks neither.
    expect(
      within(group)
        .getAllByRole("button")
        .map((button) => button.textContent),
    ).toEqual(["viktig", "kund", "Bygg Göteborg"]);
    await user.click(within(group).getByRole("button", { name: "kund" }));
    expect(within(group).getByRole("button", { name: "kund" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await waitFor(() =>
      expect(getWorkAgenda).toHaveBeenLastCalledWith({
        status: "todo",
        tags: ["kund"],
        tag_match: "all",
      }),
    );
    expect(await screen.findByText(workSv.agendaNoMatches)).toBeInTheDocument();
    expect(screen.getByText(tagSv.filtered(["kund"]))).toBeInTheDocument();
    await user.click(
      within(group).getByRole("button", { name: tagSv.clear(1) }),
    );
    await waitFor(() =>
      expect(getWorkAgenda).toHaveBeenLastCalledWith({ status: "todo" }),
    );
  });

  it("Status reads the board again with the chosen tags", async () => {
    const user = userEvent.setup();
    const getWorkBoard = vi.fn().mockResolvedValue(boardPage);
    const work = transport({
      getWorkBoard,
      listTags: vi.fn().mockResolvedValue(vocabulary),
    });
    render(
      rootBoard(work, {
        ...boardPage,
        columns: {
          ...boardPage.columns,
          todo: [{ ...boardTask, tags: ["viktig"] }],
        },
      }),
    );
    const group = await screen.findByRole("group", { name: tagEn.filter });
    await user.click(within(group).getByRole("button", { name: "viktig" }));
    await waitFor(() =>
      expect(getWorkBoard).toHaveBeenLastCalledWith({
        tags: ["viktig"],
        tag_match: "all",
      }),
    );
  });

  it("draws no filter row where the host has no list_tags", async () => {
    const listTags = vi.fn().mockResolvedValue(vocabulary);
    const work = transport({
      listTags,
      supportsTool: (name: string) => name !== "list_tags",
    });
    render(rootBoard(work));
    await screen.findByRole("heading", { name: workEn.board });
    expect(listTags).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("group", { name: tagEn.filter }),
    ).not.toBeInTheDocument();
  });
});

describe("tags in a Task's and a Project's room", () => {
  it("adds a tag to a Task as one update_task of the whole set, with the focus kept in the field", async () => {
    const user = userEvent.setup();
    const tagged = { ...taskA, tags: ["viktig"] };
    const updateTask = vi.fn().mockResolvedValue({
      task: { ...tagged, tags: ["viktig", "kund"], version: 2 },
    });
    const listTags = vi.fn().mockResolvedValue(vocabulary);
    const work = transport({
      getTask: vi.fn().mockResolvedValue({ task: tagged }),
      updateTask,
      listTags,
    });
    render(rootTask(work));
    await user.click(
      await screen.findByRole("button", { name: tagEn.editFor(taskA.title) }),
    );
    await user.click(
      await screen.findByRole("button", { name: tagEn.suggest("kund") }),
    );
    await waitFor(() =>
      expect(updateTask).toHaveBeenCalledWith(
        taskA.id,
        1,
        { tags: ["viktig", "kund"] },
        expect.any(String),
      ),
    );
    expect(
      await screen.findByRole("button", { name: tagEn.remove("kund") }),
    ).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: tagEn.input })).toHaveFocus();
    // The write made the vocabulary stale: it is read again.
    await waitFor(() => expect(listTags).toHaveBeenCalledTimes(2));
  });

  it("names a failed tag write and writes it again with the same key", async () => {
    const user = userEvent.setup();
    const updateTask = vi
      .fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue({ task: { ...taskA, tags: ["bygg"], version: 2 } });
    const work = transport({ updateTask, listTags: undefined });
    render(rootTask(work));
    await user.click(await screen.findByRole("button", { name: tagEn.add }));
    await user.type(
      screen.getByRole("textbox", { name: tagEn.input }),
      "bygg{Enter}",
    );
    expect(
      await screen.findByText(workEn.saveFailed, { exact: false }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: workEn.retry }));
    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(2));
    expect(updateTask.mock.calls[1]?.[3]).toBe(updateTask.mock.calls[0]?.[3]);
  });

  it("shows a Task's tags without editing where the host cannot write them (the phone)", async () => {
    const work = transport({
      getTask: vi
        .fn()
        .mockResolvedValue({ task: { ...taskA, tags: ["viktig"] } }),
      supportsCall: (name: string, args: unknown) =>
        name !== "update_task" || !JSON.stringify(args).includes('"tags"'),
    });
    render(rootTask(work));
    expect(
      await screen.findByText(`${tagEn.tags}: viktig`),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: tagEn.editFor(taskA.title) }),
    ).not.toBeInTheDocument();
  });

  it("edits a Project's tags with update_project and shows its Tasks' tags", async () => {
    const user = userEvent.setup();
    const updateProject = vi.fn().mockResolvedValue({
      project: { ...projectA, tags: ["kund"], version: 2 },
    });
    const work = transport({
      updateProject,
      listTags: vi.fn().mockResolvedValue(vocabulary),
      listProjectTasks: vi.fn().mockResolvedValue({
        items: [
          {
            id: projectTask.id,
            title: projectTask.title,
            status: "todo",
            due_at: null,
            tags: ["bygg"],
          },
        ],
        next_cursor: null,
      }),
    });
    render(rootProject(work));
    expect(
      await screen.findByText(`${tagEn.tags}: Bygg Göteborg`),
    ).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: tagEn.add }));
    await user.click(
      await screen.findByRole("button", { name: tagEn.suggest("kund") }),
    );
    await waitFor(() =>
      expect(updateProject).toHaveBeenCalledWith(
        projectA.id,
        projectA.version,
        { tags: ["kund"] },
        expect.any(String),
      ),
    );
  });
});

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { workEn } from "@/features/work-app/labels";
import { savedViewsLabelsEn } from "@/features/work-app/saved-views-labels";
import { WorkFullscreen } from "@/features/work-app/work-fullscreen";
import type {
  WorkAgendaPage,
  WorkBoardPage,
  WorkFrame,
  WorkItemRecord,
  WorkSavedView,
  WorkTransport,
} from "@/features/work-app/transport";
import { workShellLabelsEn } from "@/features/work-app/work-shell-labels";
import { fakeTransport } from "./helpers/saved-views-fixtures";

describe("WorkFullscreen with saved views", () => {
  const agendaItem: WorkItemRecord = {
    kind: "task",
    id: "019f0000-0000-7000-8000-0000000000a1",
    title: "Agenda item",
    status: "todo",
    due_at: null,
    version: 1,
    project_id: null,
    agenda_group: "today",
  };
  const blockedItem: WorkItemRecord = {
    kind: "task",
    id: "019f0000-0000-7000-8000-0000000000a2",
    title: "Blocked item",
    status: "blocked",
    due_at: null,
    version: 1,
    project_id: null,
    agenda_group: "today",
  };
  const boardItem: WorkItemRecord = {
    kind: "task",
    id: "019f0000-0000-7000-8000-0000000000b1",
    title: "Board item",
    status: "todo",
    due_at: null,
    version: 1,
    project_id: null,
  };
  const highItem: WorkItemRecord = {
    ...boardItem,
    id: "019f0000-0000-7000-8000-0000000000b2",
    title: "High item",
    priority: "high",
  };
  const agendaPage: WorkAgendaPage = { items: [agendaItem], next_cursor: null };
  const boardPage: WorkBoardPage = {
    columns: { todo: [boardItem] },
    next_cursor: null,
  };
  const englishAgenda: WorkSavedView = {
    id: "019f0000-0000-7000-8000-0000000000v4",
    name: "Blocked",
    definition: { view: "agenda", context: "all", status: "blocked" },
    version: 1,
    archived_at: null,
  };
  const englishBoard: WorkSavedView = {
    id: "019f0000-0000-7000-8000-0000000000v5",
    name: "High",
    definition: { view: "board", context: "all", priorities: ["high"] },
    version: 1,
    archived_at: null,
  };
  const severalPrioritiesBoard: WorkSavedView = {
    id: "019f0000-0000-7000-8000-0000000000v6",
    name: "Several",
    definition: {
      view: "board",
      context: "all",
      priorities: ["high", "urgent"],
    },
    version: 1,
    archived_at: null,
  };

  /** A fullscreen transport: the reads of the tabs and the saved-view methods. */
  function fullTransport(
    views: WorkSavedView[] = [englishAgenda, englishBoard],
  ) {
    const fake = fakeTransport(views);
    const getWorkAgenda = vi.fn().mockResolvedValue(agendaPage);
    const getWorkBoard = vi.fn().mockResolvedValue(boardPage);
    const listUnsortedTasks = vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null });
    const listDomains = vi.fn().mockResolvedValue([]);
    const transport = {
      ...fake.transport,
      getWorkAgenda,
      getWorkBoard,
      listUnsortedTasks,
      listDomains,
    } as unknown as WorkTransport;
    return { ...fake, transport, getWorkAgenda, getWorkBoard };
  }

  function mount(initial: WorkFrame, transport: WorkTransport) {
    return render(
      <WorkFullscreen
        transport={transport}
        initial={initial}
        labels={workEn}
        shellLabels={workShellLabelsEn}
      />,
    );
  }

  it("reads no saved view until the bar is opened", async () => {
    const fake = fullTransport();
    mount({ kind: "agenda", filters: {}, page: agendaPage }, fake.transport);

    expect(await screen.findByText("Agenda item")).toBeInTheDocument();
    // In the agenda the bar sits in the "⋯" panel, which is closed until it is pressed.
    expect(
      screen.queryByRole("button", { name: savedViewsLabelsEn.button }),
    ).not.toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: workEn.moreActions }));
    expect(
      screen.getByRole("button", { name: savedViewsLabelsEn.button }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: workEn.refresh }),
    ).toBeInTheDocument();
    expect(fake.listSavedWorkViews).not.toHaveBeenCalled();
  });

  it('keeps the "⋯" panel open, the bar\'s status and the focus when a saved view remounts the agenda, and clears the filter text', async () => {
    const fake = fullTransport();
    fake.getWorkAgenda.mockResolvedValueOnce({
      items: [blockedItem],
      next_cursor: null,
    });
    const user = userEvent.setup();
    mount({ kind: "agenda", filters: {}, page: agendaPage }, fake.transport);

    // The search field is folded behind the search icon until it is pressed.
    await user.click(
      await screen.findByRole("button", { name: "Search tasks" }),
    );
    await user.type(
      await screen.findByRole("searchbox", { name: "Search tasks" }),
      "Agenda",
    );
    expect(screen.getByText("Agenda item")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: workEn.moreActions }));
    await user.click(
      await screen.findByRole("button", { name: "Saved views" }),
    );
    await user.click(
      await screen.findByRole("button", { name: "Open: Blocked" }),
    );

    expect(await screen.findByText("Blocked item")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: workEn.moreActions }),
    ).toHaveAttribute("aria-expanded", "true");
    expect(
      screen.getByText(savedViewsLabelsEn.openedView("Blocked")),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Saved views" })).toHaveFocus();
    expect(screen.getByRole("searchbox", { name: "Search tasks" })).toHaveValue(
      "",
    );
  });

  it('reads the agenda again from Refresh in the "⋯" panel and closes the panel', async () => {
    const fake = fullTransport();
    const user = userEvent.setup();
    mount({ kind: "agenda", filters: {}, page: agendaPage }, fake.transport);

    await screen.findByText("Agenda item");
    expect(fake.getWorkAgenda).not.toHaveBeenCalled();
    const more = screen.getByRole("button", { name: workEn.moreActions });
    await user.click(more);
    await user.click(screen.getByRole("button", { name: workEn.refresh }));

    await vi.waitFor(() => expect(fake.getWorkAgenda).toHaveBeenCalledTimes(1));
    expect(more).toHaveAttribute("aria-expanded", "false");
    expect(more).toHaveFocus();
  });

  it("opens a saved agenda view: it reads the view's filters, shows its items and focuses the bar", async () => {
    const fake = fullTransport();
    fake.getWorkAgenda.mockResolvedValueOnce({
      items: [blockedItem],
      next_cursor: null,
    });
    const user = userEvent.setup();
    mount({ kind: "agenda", filters: {}, page: agendaPage }, fake.transport);

    await user.click(
      await screen.findByRole("button", { name: workEn.moreActions }),
    );
    await user.click(
      await screen.findByRole("button", { name: "Saved views" }),
    );
    await user.click(
      await screen.findByRole("button", { name: "Open: Blocked" }),
    );

    expect(fake.getWorkAgenda).toHaveBeenLastCalledWith({ status: "blocked" });
    expect(await screen.findByText("Blocked item")).toBeInTheDocument();
    expect(screen.queryByText("Agenda item")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Saved views" })).toHaveFocus();
  });

  it("opens a saved board view with its one priority as the board's filter", async () => {
    const fake = fullTransport();
    fake.getWorkBoard.mockResolvedValueOnce({
      columns: { todo: [highItem] },
      next_cursor: null,
    });
    const user = userEvent.setup();
    mount({ kind: "board", filters: {}, page: boardPage }, fake.transport);

    // On the Status tab the saved views sit in its own "More actions" menu.
    await user.click(screen.getByRole("button", { name: workEn.moreActions }));
    await user.click(
      await screen.findByRole("button", { name: "Saved views" }),
    );
    await user.click(await screen.findByRole("button", { name: "Open: High" }));

    expect(fake.getWorkBoard).toHaveBeenLastCalledWith({ priority: "high" });
    expect(await screen.findByText("High item")).toBeInTheDocument();
    expect(screen.queryByText("Board item")).not.toBeInTheDocument();
    expect(
      screen.queryByText(savedViewsLabelsEn.severalPriorities),
    ).not.toBeInTheDocument();
  });

  it("opens a saved board view with several priorities unfiltered, says so, and drops the note on the next view", async () => {
    const fake = fullTransport([severalPrioritiesBoard, englishBoard]);
    const user = userEvent.setup();
    mount({ kind: "board", filters: {}, page: boardPage }, fake.transport);

    await user.click(screen.getByRole("button", { name: workEn.moreActions }));
    await user.click(
      await screen.findByRole("button", { name: "Saved views" }),
    );
    await user.click(
      await screen.findByRole("button", { name: "Open: Several" }),
    );

    expect(fake.getWorkBoard).toHaveBeenLastCalledWith({});
    expect(
      await screen.findByText(savedViewsLabelsEn.severalPriorities),
    ).toBeInTheDocument();

    await user.click(await screen.findByRole("button", { name: "Open: High" }));
    expect(fake.getWorkBoard).toHaveBeenLastCalledWith({ priority: "high" });
    expect(
      screen.queryByText(savedViewsLabelsEn.severalPriorities),
    ).not.toBeInTheDocument();
  });

  it("keeps the tab's view when the saved view cannot be read", async () => {
    const fake = fullTransport();
    fake.getWorkAgenda.mockRejectedValueOnce(new Error("network"));
    const user = userEvent.setup();
    mount({ kind: "agenda", filters: {}, page: agendaPage }, fake.transport);

    await user.click(
      await screen.findByRole("button", { name: workEn.moreActions }),
    );
    await user.click(
      await screen.findByRole("button", { name: "Saved views" }),
    );
    await user.click(
      await screen.findByRole("button", { name: "Open: Blocked" }),
    );

    expect(
      await screen.findByText(savedViewsLabelsEn.openFailed),
    ).toBeInTheDocument();
    expect(screen.getByText("Agenda item")).toBeInTheDocument();
    expect(screen.queryByText("Öppen")).not.toBeInTheDocument();
  });

  it("saves the agenda's current filters as a view of this tab", async () => {
    const fake = fullTransport([]);
    fake.createSavedWorkView.mockResolvedValue({
      saved_view: englishAgenda,
    });
    const user = userEvent.setup();
    mount(
      { kind: "agenda", filters: { status: "todo" }, page: agendaPage },
      fake.transport,
    );

    await user.click(
      await screen.findByRole("button", { name: workEn.moreActions }),
    );
    await user.click(
      await screen.findByRole("button", { name: "Saved views" }),
    );
    await user.type(
      await screen.findByLabelText(savedViewsLabelsEn.nameLabel),
      "Mine",
    );
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(fake.createSavedWorkView).toHaveBeenCalledWith(
      "Mine",
      { view: "agenda", context: "all", status: "todo" },
      expect.any(String),
    );
  });
});

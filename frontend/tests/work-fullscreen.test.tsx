import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi, type Mock } from "vitest";
import { workEn } from "@/features/work-app/labels";
import { WorkFullscreen } from "@/features/work-app/work-fullscreen";
import { WorkView } from "@/features/work-app/work-view";
import type {
  WorkAgendaPage,
  WorkBoardPage,
  WorkFrame,
  WorkHierarchyFrame,
  WorkItemRecord,
  WorkTask,
  WorkTransport,
  WorkUnsortedPage,
} from "@/features/work-app/transport";
import { workShellLabelsEn } from "@/features/work-app/work-shell-labels";

const agendaItem: WorkItemRecord = {
  kind: "task",
  id: "019f0000-0000-7000-8000-0000000000a1",
  title: "Agenda-uppgift",
  status: "todo",
  due_at: null,
  version: 1,
  project_id: null,
  agenda_group: "today",
};
const boardItem: WorkItemRecord = {
  kind: "task",
  id: "019f0000-0000-7000-8000-0000000000b1",
  title: "Board-uppgift",
  status: "todo",
  due_at: null,
  version: 1,
  project_id: null,
};
const agendaPage: WorkAgendaPage = { items: [agendaItem], next_cursor: null };
const boardPage: WorkBoardPage = {
  columns: { todo: [boardItem] },
  next_cursor: null,
};
const hierarchy: WorkHierarchyFrame = {
  kind: "hierarchy",
  nodes: [
    {
      kind: "domain",
      id: "019f0000-0000-7000-8000-0000000000h1",
      parent_id: null,
      title: "Ekonomi",
      status: "active",
      version: 1,
    },
  ],
  truncated: false,
  // The server answers with the Tasks array when include_tasks is sent, so the tab need not read it again.
  tasks: [],
};

const unsortedTask: WorkTask = {
  id: "019f0000-0000-7000-8000-0000000000c1",
  title: "Köp ny dammsugare",
  status: "todo",
  due_at: null,
  version: 1,
  domain_id: null,
};

type Fake = {
  transport: WorkTransport;
  getWorkAgenda: Mock;
  getWorkBoard: Mock;
  getWorkHierarchy: Mock;
  listContacts: Mock;
  listUnsortedTasks: Mock;
  listDomains: Mock;
};

/**
 * Only the reads the fullscreen tabs make are faked; every other method is absent on purpose. The
 * unsorted reads answer with `unsorted` (empty by default), for the To sort row and its view.
 */
function fakeTransport(
  unsorted: WorkUnsortedPage = { items: [], next_cursor: null },
): Fake {
  const getWorkAgenda = vi.fn().mockResolvedValue(agendaPage);
  const getWorkBoard = vi.fn().mockResolvedValue(boardPage);
  const getWorkHierarchy = vi.fn().mockResolvedValue(hierarchy);
  const listContacts = vi.fn().mockResolvedValue({
    items: [],
    next_cursor: null,
  });
  const listUnsortedTasks = vi.fn().mockResolvedValue(unsorted);
  const listDomains = vi.fn().mockResolvedValue([]);
  return {
    transport: {
      getWorkAgenda,
      getWorkBoard,
      getWorkHierarchy,
      listContacts,
      listUnsortedTasks,
      listDomains,
    } as unknown as WorkTransport,
    getWorkAgenda,
    getWorkBoard,
    getWorkHierarchy,
    listContacts,
    listUnsortedTasks,
    listDomains,
  };
}

/** Lets the unsorted count read settle; its answer lands in a microtask or two. */
async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

const agendaFrame: WorkFrame = {
  kind: "agenda",
  filters: {},
  page: agendaPage,
};

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

describe("WorkFullscreen", () => {
  it("keeps the app name only as a visually hidden heading, since the tab strip names the view", async () => {
    mount(agendaFrame, fakeTransport().transport);

    const name = await screen.findByRole("heading", {
      level: 1,
      name: workEn.title,
    });
    expect(name).toHaveClass("work-visually-hidden");
    expect(name.closest("header")).toBeNull();
  });

  it("hides the board heading visually in the shell, since the tab strip names the board", async () => {
    mount(
      { kind: "board", filters: {}, page: boardPage },
      fakeTransport().transport,
    );

    const board = await screen.findByRole("heading", {
      level: 2,
      name: workEn.board,
    });
    expect(board).toHaveClass("work-visually-hidden");
    expect(board).toHaveAttribute("tabindex", "-1");
  });

  it("keeps the agenda heading in the shell, hidden visually and still named for assistive technology", async () => {
    mount(agendaFrame, fakeTransport().transport);

    const agenda = await screen.findByRole("heading", {
      level: 2,
      name: workEn.agenda,
    });
    expect(agenda).toHaveClass("work-visually-hidden");
  });

  it("shows the board heading outside the shell, where no tab strip names the view", async () => {
    const fake = fakeTransport();
    render(
      <WorkView
        transport={fake.transport}
        initial={{ kind: "board", filters: {}, page: boardPage }}
        labels={workEn}
      />,
    );

    const board = await screen.findByRole("heading", {
      level: 2,
      name: workEn.board,
    });
    expect(board).not.toHaveClass("work-visually-hidden");
    expect(board).toBeVisible();
  });

  it("starts on the tab of the first frame and reads nothing for it", async () => {
    const fake = fakeTransport();
    mount({ kind: "board", filters: {}, page: boardPage }, fake.transport);

    expect(screen.getByRole("button", { name: "Status" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(await screen.findByText("Board-uppgift")).toBeInTheDocument();
    expect(fake.getWorkBoard).not.toHaveBeenCalled();
    expect(fake.getWorkAgenda).not.toHaveBeenCalled();
  });

  it("draws the tab strip inside the Work frame, so it takes the app's font and colours", () => {
    const fake = fakeTransport();
    const { container } = mount(agendaFrame, fake.transport);

    const frame = container.querySelector(".sidekick-work");
    expect(frame).not.toBeNull();
    expect(frame).toContainElement(
      screen.getByRole("button", { name: "Status" }),
    );
  });

  it("reads the board once, shows only the active tab, and keeps the board when returning", async () => {
    const fake = fakeTransport();
    const user = userEvent.setup();
    mount(agendaFrame, fake.transport);

    expect(await screen.findByText("Agenda-uppgift")).toBeInTheDocument();
    expect(fake.getWorkBoard).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Status" }));
    expect(await screen.findByText("Board-uppgift")).toBeInTheDocument();
    expect(screen.getByText("Agenda-uppgift")).not.toBeVisible();
    expect(fake.getWorkBoard).toHaveBeenCalledTimes(1);
    expect(fake.getWorkBoard).toHaveBeenCalledWith({});

    await user.click(screen.getByRole("button", { name: "Agenda" }));
    expect(await screen.findByText("Agenda-uppgift")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Status" }));
    expect(await screen.findByText("Board-uppgift")).toBeInTheDocument();
    expect(fake.getWorkBoard).toHaveBeenCalledTimes(1);
  });

  it("shows an error notice when a tab fails, and Try again reads it again", async () => {
    const fake = fakeTransport();
    fake.getWorkBoard
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce(boardPage);
    const user = userEvent.setup();
    mount(agendaFrame, fake.transport);

    await user.click(screen.getByRole("button", { name: "Status" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(fake.getWorkBoard).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Board-uppgift")).toBeInTheDocument();
    expect(fake.getWorkBoard).toHaveBeenCalledTimes(2);
  });

  it("keeps the notice while Try again reads, its button saying Trying again…, with the line of what failed", async () => {
    const fake = fakeTransport();
    let answer: (page: WorkBoardPage) => void = () => {};
    fake.getWorkBoard
      .mockRejectedValueOnce(new Error("Host request failed"))
      .mockReturnValueOnce(
        new Promise<WorkBoardPage>((resolve) => {
          answer = resolve;
        }),
      );
    const user = userEvent.setup();
    mount(agendaFrame, fake.transport);

    await user.click(screen.getByRole("button", { name: "Status" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    // No "Try again in a moment." sentence: the line says only what the failure knows.
    expect(screen.queryByText("Try again in a moment.")).toBeNull();
    expect(document.querySelector(".sk-error-hint")).toHaveTextContent(
      "Sidekick didn’t respond. Check your connection.",
    );
    // + and search are off while the tab has no list.
    expect(
      screen.getByRole("button", { name: "Search tasks" }),
    ).toHaveAttribute("aria-disabled", "true");
    await user.click(screen.getByRole("button", { name: "Try again" }));
    const busy = screen.getByRole("button", { name: "Trying again…" });
    expect(busy).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("alert")).toBeInTheDocument();
    act(() => answer(boardPage));
    expect(await screen.findByText("Board-uppgift")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("keeps the list when a refresh after a good read fails", async () => {
    const fake = fakeTransport();
    const user = userEvent.setup();
    const { container } = mount(agendaFrame, fake.transport);
    expect(await screen.findByText("Agenda-uppgift")).toBeInTheDocument();
    await settle();
    const rows = container.querySelectorAll("li").length;
    expect(rows).toBeGreaterThan(0);

    fake.getWorkAgenda.mockRejectedValue(new Error("Host request failed"));
    const more = screen
      .getAllByRole("button", { name: workEn.moreActions })
      .find(
        (button) => button.offsetParent !== null || !button.closest("[hidden]"),
      )!;
    await user.click(more);
    await user.click(
      screen
        .getAllByRole("button", { name: workEn.refresh })
        .find((button) => !button.closest("[hidden]"))!,
    );
    await settle();
    expect(fake.getWorkAgenda).toHaveBeenCalled();
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("Agenda-uppgift")).toBeInTheDocument();
    expect(container.querySelectorAll("li")).toHaveLength(rows);
  });

  it("reads the hierarchy through getWorkHierarchy when its tab opens", async () => {
    const fake = fakeTransport();
    const user = userEvent.setup();
    mount(agendaFrame, fake.transport);

    await user.click(screen.getByRole("button", { name: "Projects" }));
    expect(await screen.findByText("Ekonomi")).toBeInTheDocument();
    expect(fake.getWorkHierarchy).toHaveBeenCalledTimes(1);
    expect(fake.getWorkHierarchy).toHaveBeenCalledWith({ includeTasks: true });
  });

  it("shows no Contacts tab, since Contacts is a room of its own", () => {
    const fake = fakeTransport();
    mount(agendaFrame, fake.transport);

    expect(
      screen.getByRole("button", { name: "Projects" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Contacts" }),
    ).not.toBeInTheDocument();
    expect(fake.listContacts).not.toHaveBeenCalled();
  });

  it("folds the agenda's search field behind the search icon, and Escape closes it, clears the text and focuses the icon", async () => {
    const fake = fakeTransport();
    const user = userEvent.setup();
    mount(agendaFrame, fake.transport);

    const toggle = await screen.findByRole("button", { name: "Search tasks" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const field = screen.getByRole("searchbox", { name: "Search tasks" });
    expect(field).toHaveFocus();
    await user.type(field, "Agenda");
    expect(screen.getByText("Agenda-uppgift")).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveFocus();
    expect(screen.getByText("Agenda-uppgift")).toBeVisible();
  });

  it("a hidden agenda ignores j while Status is shown, and j works again when Agenda returns", async () => {
    const fake = fakeTransport();
    const user = userEvent.setup();
    mount(agendaFrame, fake.transport);
    // The row is taken before Board is shown, while Agenda is still visible.
    const row = screen
      .getByRole("button", { name: "Agenda-uppgift" })
      .closest("li");
    if (!row) throw new Error("no agenda row");

    await user.click(screen.getByRole("button", { name: "Status" }));
    expect(await screen.findByText("Board-uppgift")).toBeInTheDocument();
    fireEvent.keyDown(document.body, { key: "j" });
    expect(row).not.toHaveFocus();

    await user.click(screen.getByRole("button", { name: "Agenda" }));
    fireEvent.keyDown(document.body, { key: "j" });
    expect(row).toHaveFocus();
  });
});

describe("the To sort row above the agenda and its view", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    Object.defineProperty(window, "scrollY", { configurable: true, value: 0 });
  });

  it("shows no row when no Task is unsorted", async () => {
    const fake = fakeTransport();
    mount(agendaFrame, fake.transport);

    expect(await screen.findByText("Agenda-uppgift")).toBeInTheDocument();
    await settle();
    expect(fake.listUnsortedTasks).toHaveBeenCalledWith(null, 100);
    expect(
      screen.queryByRole("button", { name: /^Unsorted/ }),
    ).not.toBeInTheDocument();
  });

  it("hides the row when the count read fails", async () => {
    const fake = fakeTransport({ items: [unsortedTask], next_cursor: null });
    fake.listUnsortedTasks.mockRejectedValueOnce(new Error("network"));
    mount(agendaFrame, fake.transport);

    expect(await screen.findByText("Agenda-uppgift")).toBeInTheDocument();
    await settle();
    expect(
      screen.queryByRole("button", { name: /^Unsorted/ }),
    ).not.toBeInTheDocument();
  });

  it("reads the count as N+ when the first page has more Tasks after it", async () => {
    const fake = fakeTransport({
      items: [unsortedTask],
      next_cursor: "cursor-2",
    });
    mount(agendaFrame, fake.transport);

    expect(
      await screen.findByRole("button", { name: "Unsorted (1+)" }),
    ).toBeInTheDocument();
  });

  it("shows the count after the agenda, opens the view, and Back returns without reading the agenda again", async () => {
    vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
    const fake = fakeTransport({ items: [unsortedTask], next_cursor: null });
    const user = userEvent.setup();
    mount(agendaFrame, fake.transport);

    const row = await screen.findByRole("button", { name: "Unsorted (1)" });
    expect(
      row.compareDocumentPosition(screen.getByText("Agenda-uppgift")) &
        Node.DOCUMENT_POSITION_PRECEDING,
    ).toBeTruthy();

    await user.click(row);

    expect(
      await screen.findByRole("heading", { level: 2, name: "Unsorted" }),
    ).toBeVisible();
    expect(await screen.findByText("Köp ny dammsugare")).toBeVisible();
    expect(screen.getByText("Agenda-uppgift")).not.toBeVisible();

    await user.click(screen.getByRole("button", { name: "Back" }));

    expect(screen.getByText("Agenda-uppgift")).toBeVisible();
    expect(
      screen.queryByRole("heading", { level: 2, name: "Unsorted" }),
    ).not.toBeInTheDocument();
    expect(fake.getWorkAgenda).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(fake.listUnsortedTasks).toHaveBeenLastCalledWith(null, 100),
    );
  });

  it("opens the view at the top, and puts the agenda's scroll back when Back returns to it", async () => {
    const scrollTo = vi
      .spyOn(window, "scrollTo")
      .mockImplementation(() => undefined);
    Object.defineProperty(window, "scrollY", {
      configurable: true,
      value: 420,
    });
    const fake = fakeTransport({ items: [unsortedTask], next_cursor: null });
    const user = userEvent.setup();
    mount(agendaFrame, fake.transport);

    await user.click(
      await screen.findByRole("button", { name: "Unsorted (1)" }),
    );
    expect(scrollTo).toHaveBeenLastCalledWith(0, 0);

    await user.click(screen.getByRole("button", { name: "Back" }));
    expect(scrollTo).toHaveBeenLastCalledWith(0, 420);
  });
});

describe("a Task opened over the agenda", () => {
  it("hides the search icon, the More options button and the To sort row, so Back is the first control", async () => {
    const fake = fakeTransport({ items: [unsortedTask], next_cursor: null });
    // The Task view reads several things; any read the fake does not know stays pending. `offline` is the phone's
    // optional support, not a read, so it stays absent as in Claude.
    const transport = new Proxy(fake.transport, {
      get: (target, key): unknown =>
        key in target || key === "offline"
          ? (Reflect.get(target, key) as unknown)
          : () => new Promise(() => undefined),
    });
    const user = userEvent.setup();
    mount(agendaFrame, transport);

    await user.click(
      await screen.findByRole("button", { name: "Search tasks" }),
    );
    expect(
      await screen.findByRole("searchbox", { name: "Search tasks" }),
    ).toBeVisible();
    expect(
      await screen.findByRole("button", { name: "Unsorted (1)" }),
    ).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Agenda-uppgift" }));

    const back = await screen.findByRole("button", { name: /^Tillbaka till / });
    // The search icon and the "⋯" are replaced while the Task is open; the search field is folded away.
    expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Search tasks" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: workEn.moreActions }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^Unsorted/ }),
    ).not.toBeInTheDocument();
    // Back comes before every other visible control of the agenda tab's panel.
    const panel = back.closest("section.sk-shell-list") as HTMLElement;
    expect(within(panel).getAllByRole("button")[0]).toBe(back);

    await user.click(back);
    // Back brings the search icon and the open field back; the field stayed open over the Task.
    expect(
      await screen.findByRole("searchbox", { name: "Search tasks" }),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Unsorted (1)" })).toBeVisible();
  });
});

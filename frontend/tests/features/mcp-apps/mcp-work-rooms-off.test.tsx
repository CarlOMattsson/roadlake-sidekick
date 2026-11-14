// SIDEKICK_ENABLED_ROOMS in the Work app: a room that is off leaves no link, chip, menu entry or button that leads to
// it, and its tools are not called. The instance declares its rooms in <meta name="sidekick-rooms">; without the meta
// every room is on. The hosts here are simulated, not a real Claude or Android host.
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { RoomProps } from "@/features/mcp-apps/room-types";
import { ContactsRoom } from "@/features/work-app/contacts/contacts-room";
import { ContactsView } from "@/features/work-app/contacts/contacts-list";
import { workEn } from "@/features/work-app/shared/labels";
import type {
  WorkContactRecord,
  WorkFrame,
  WorkTask,
  WorkTransport,
} from "@/features/work-app/transport/transport";
import { WorkFullscreen } from "@/features/work-app/fullscreen/work-fullscreen";
import { workShellLabelsEn } from "@/features/work-app/shell/work-shell-labels";
import { WorkView } from "@/features/work-app/view/work-view";

const TASK_ID = "019f0000-0000-7000-8000-0000000000a1";
const ANNA_ID = "019f0000-0000-7000-8000-0000000000c1";

const anna: WorkContactRecord = {
  id: ANNA_ID,
  display_name: "Anna Andersson",
  email: null,
  phone: null,
  context_note: null,
  relationship: null,
  organization: null,
  role: null,
  address: null,
  aliases: [],
  archived: false,
  archived_at: null,
  version: 1,
};

const task: WorkTask = {
  id: TASK_ID,
  title: "Ring Anna om flytten",
  status: "todo",
  due_at: null,
  version: 1,
};

const entry = {
  id: "019f0000-0000-7000-8000-0000000000e1",
  journal_date: "2026-11-03",
  title: "Möte om offerten",
};

/** The instance's rooms, as the backend writes them into the app document; undefined removes the meta. */
function declareRooms(rooms?: string) {
  document.head.innerHTML =
    rooms === undefined
      ? ""
      : `<meta name="sidekick-rooms" content="${rooms}">`;
}

afterEach(() => {
  cleanup();
  document.head.innerHTML = "";
});

const empty = { items: [], next_cursor: null };

function taskTransport() {
  const listTaskContacts = vi
    .fn()
    .mockResolvedValue({ items: [anna], next_cursor: null });
  const transport = {
    getTask: vi.fn().mockResolvedValue({ task }),
    listTaskContacts,
    listTaskSteps: vi.fn().mockResolvedValue(empty),
    listStepActions: vi.fn().mockResolvedValue(empty),
    listTaskExternalReferences: vi.fn().mockResolvedValue(empty),
  } as unknown as WorkTransport;
  return { transport, listTaskContacts };
}

function renderTask(transport: WorkTransport) {
  return render(
    <WorkView
      transport={transport}
      initial={{ kind: "task", id: TASK_ID }}
      labels={workEn}
    />,
  );
}

describe("the Task detail with the contacts room off", () => {
  it("draws no Contacts section, link control or All contacts link, and reads no Contacts", async () => {
    declareRooms("work");
    const { transport, listTaskContacts } = taskTransport();
    renderTask(transport);

    await screen.findByRole("heading", { name: task.title });

    expect(
      screen.queryByRole("heading", { name: workEn.contacts }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(anna.display_name)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: workEn.linkContact }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: workEn.allContacts }),
    ).not.toBeInTheDocument();
    expect(listTaskContacts).not.toHaveBeenCalled();
  });

  it("draws the Contacts section, the linked Contact and the link control without the meta", async () => {
    declareRooms();
    const { transport, listTaskContacts } = taskTransport();
    renderTask(transport);

    expect(
      await screen.findByRole("heading", { name: workEn.contacts }),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("button", { name: anna.display_name }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: workEn.linkContact }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: workEn.allContacts }),
    ).toBeInTheDocument();
    expect(listTaskContacts).toHaveBeenCalled();
  });

  it("offers the Contact row's menu (hidden button) only with the room on", async () => {
    declareRooms("work");
    const off = taskTransport();
    renderTask(off.transport);
    await screen.findByRole("heading", { name: task.title });
    expect(screen.queryByText(anna.display_name)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /More options for .*Anna/ }),
    ).not.toBeInTheDocument();
    cleanup();

    declareRooms();
    const on = taskTransport();
    renderTask(on.transport);
    await screen.findByRole("button", { name: anna.display_name });
    expect(
      screen.getByRole("button", { name: /More options for .*Anna/ }),
    ).toBeInTheDocument();
  });

  it("draws a linked Contact as a row with only a › that opens it and no ⋯ button", async () => {
    declareRooms();
    renderTask(taskTransport().transport);

    const open = await screen.findByRole("button", {
      name: anna.display_name,
    });
    const row = open.closest("li");
    expect(row).not.toBeNull();
    expect(row?.textContent).not.toContain("⋯");
    expect(row?.querySelector(".work-row-actions")).toBeNull();
    expect(row?.querySelector(".work-open-chevron")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
  });
});

describe("the Contact view with the contacts room off", () => {
  function renderContact() {
    const getContactContext = vi.fn().mockResolvedValue({
      contact: anna,
      projects: empty,
      tasks: empty,
    });
    render(
      <WorkView
        transport={{ getContactContext } as unknown as WorkTransport}
        initial={{ kind: "contact", id: ANNA_ID }}
        labels={workEn}
      />,
    );
  }

  it("offers no All contacts link", async () => {
    declareRooms("work,journal");
    renderContact();
    await screen.findByRole("heading", { name: anna.display_name });
    expect(
      screen.queryByRole("button", { name: workEn.allContacts }),
    ).not.toBeInTheDocument();
  });

  it("offers the All contacts link without the meta", async () => {
    declareRooms();
    renderContact();
    await screen.findByRole("heading", { name: anna.display_name });
    expect(
      screen.getByRole("button", { name: workEn.allContacts }),
    ).toBeInTheDocument();
  });
});

describe("the Journal entries under a Contact with the journal room off", () => {
  const context = {
    contact: anna,
    projects: empty,
    tasks: empty,
    journal_entries: { items: [entry], has_more: false, readable: true },
  };
  const host = () =>
    ({
      // The Contact reads the tag vocabulary too; every other call answers with the Contact's context.
      call: vi.fn((name: string) =>
        Promise.resolve(
          name === "list_tags" ? { tags: [], next_cursor: null } : context,
        ),
      ),
      requestDisplayMode: vi.fn().mockResolvedValue("fullscreen"),
      updateModelContext: vi.fn().mockResolvedValue(undefined),
    }) as unknown as RoomProps["transport"];
  const mountContact = () =>
    render(
      <ContactsRoom
        mode="full"
        transport={host()}
        resultId={1}
        initial={context}
        onNavigate={vi.fn()}
      />,
    );

  it("draws no entry link", async () => {
    declareRooms("work,contacts");
    mountContact();
    await screen.findByRole("heading", { name: anna.display_name });
    expect(
      screen.queryByRole("heading", { name: workEn.journalEntries }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: entry.title }),
    ).not.toBeInTheDocument();
  });

  it("draws the entry link with the journal room on", async () => {
    declareRooms("work,contacts,journal");
    mountContact();
    expect(
      await screen.findByRole("button", { name: entry.title }),
    ).toBeInTheDocument();
  });
});

describe("the Minne och kontroll menu entry with the control room off", () => {
  const agendaFrame = {
    kind: "agenda",
    filters: {},
    page: { items: [], next_cursor: null, truncated: false },
  } as unknown as WorkFrame;

  async function openAgendaMenu() {
    const transport = {
      listUnsortedTasks: vi.fn().mockResolvedValue(empty),
      listDomains: vi.fn().mockResolvedValue([]),
    } as unknown as WorkTransport;
    const user = userEvent.setup();
    render(
      <WorkFullscreen
        transport={transport}
        initial={agendaFrame}
        labels={workEn}
        shellLabels={workShellLabelsEn}
        onRoute={vi.fn()}
      />,
    );
    await user.click(
      await screen.findByRole("button", { name: workEn.moreActions }),
    );
  }

  it("leaves it out of the Work menu", async () => {
    declareRooms("work,journal");
    await openAgendaMenu();
    expect(
      screen.queryByText(/Minne och kontroll|Memory and control/),
    ).not.toBeInTheDocument();
  });

  it("keeps it in the Work menu without the meta", async () => {
    declareRooms();
    await openAgendaMenu();
    expect(
      (await screen.findAllByText(/Minne och kontroll|Memory and control/))
        .length,
    ).toBeGreaterThan(0);
  });

  function contactsList() {
    render(
      <ContactsView
        frame={{ kind: "contacts", q: "", includeArchived: false }}
        onChange={vi.fn()}
        transport={
          {
            listContacts: vi.fn().mockResolvedValue(empty),
          } as unknown as WorkTransport
        }
        labels={workEn}
        moves={0}
        onOpen={vi.fn()}
        onRoute={vi.fn()}
      />,
    );
  }

  it("leaves it out of the Contacts menu", async () => {
    declareRooms("work,contacts");
    contactsList();
    await screen.findByRole("heading", { name: workEn.contacts });
    expect(
      screen.queryByText(/Minne och kontroll|Memory and control/),
    ).not.toBeInTheDocument();
  });

  it("keeps it in the Contacts menu without the meta", async () => {
    declareRooms();
    contactsList();
    expect(
      await screen.findByText(/Minne och kontroll|Memory and control/),
    ).toBeInTheDocument();
  });
});

// One read-error presentation for a whole room. Journal, Shopping and Contacts show the shared notice under the
// room's own chrome (no card with an eyebrow), always with the cause line and "Try again"; the place picker uses the
// notice's row variant. Work keeps its tab row around the notice; Control names the failed view. The heading names what
// Try again reads (an error result names no tool and no record), and every Contacts card has that Try again. These are
// simulated-host tests (the room components with a plain transport), not a real Claude host.
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { JournalRoom } from "@/features/journal-app/room";
import { ShoppingRoom } from "@/features/shopping-app/room";
import { ContactsRoom } from "@/features/work-app/contacts/contacts-room";
import { ControlRoom } from "@/features/control-app/room";
import { WorkRoom } from "@/features/work-app/room";
import { GroupSelect } from "@/features/work-app/hierarchy/group-select";
import {
  groupSelectLabelsEn,
  groupSelectLabelsFor,
  groupSelectLabelsSv,
} from "@/features/work-app/hierarchy/group-select-labels";
import type { RoomProps } from "@/features/mcp-apps/room-types";
import { toolResultCause } from "@/features/mcp-apps/ui/states";

const transport = {
  call: vi.fn(() => new Promise(() => undefined)),
  requestDisplayMode: vi.fn().mockResolvedValue("inline"),
  updateModelContext: vi.fn().mockResolvedValue(undefined),
} as unknown as RoomProps["transport"];

beforeEach(() => {
  document.head.innerHTML = '<meta name="sidekick-app-locale" content="en">';
});

/** The failed first result a host hands a room: an error result that names no Sidekick code. */
const failedResult = { initial: undefined, initialError: true, resultId: 1 };

describe("toolResultCause", () => {
  it("shapes an error result as the bridge throws it, keeping Sidekick's closed code", () => {
    const cause = toolResultCause({ code: "not_found" });
    expect(cause).toBeInstanceOf(Error);
    expect(cause.name).toBe("HostToolError");
    expect((cause as Error & { code?: string }).code).toBe("not_found");
    expect(toolResultCause(undefined).name).toBe("HostToolError");
  });
});

describe.each([
  ["Journal", JournalRoom],
  ["Shopping", ShoppingRoom],
  ["Contacts", ContactsRoom],
] as const)("%s room, full view, first result is an error", (_name, Room) => {
  it("shows the notice with the cause line and Try again, without a card or eyebrow around it", async () => {
    render(<Room mode="full" transport={transport} {...failedResult} />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveClass("sk-error--card");
    expect(alert.querySelector(".sk-error-hint")).toHaveTextContent(
      "Sidekick didn’t respond.",
    );
    expect(
      screen.getByRole("button", { name: "Try again" }),
    ).toBeInTheDocument();
    // Under the room's chrome: no card box and no room-name eyebrow of its own.
    expect(alert.closest(".sk-card")).toBeNull();
    expect(document.querySelector(".sk-eyebrow")).toBeNull();
  });
});

describe("Work room, first result is an error", () => {
  it("keeps the tab row in the full view and shows the notice with the cause line and Try again, which reads the tab", async () => {
    const call = vi.fn((name: string) =>
      name === "get_work_agenda"
        ? Promise.resolve({ items: [], next_cursor: null })
        : new Promise(() => undefined),
    );
    render(
      <WorkRoom
        mode="full"
        transport={{ ...transport, call } as unknown as RoomProps["transport"]}
        {...failedResult}
      />,
    );
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveClass("sk-error--card");
    expect(alert).toHaveTextContent("Couldn’t load your tasks");
    expect(alert.querySelector(".sk-error-hint")).toHaveTextContent(
      "Sidekick didn’t respond.",
    );
    // The tabs stay, so another view is one press away, and the notice has no card of its own around it.
    expect(
      screen.getByRole("button", { name: "Projects" }),
    ).toBeInTheDocument();
    expect(alert.closest(".sk-card")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(call).toHaveBeenCalledWith("get_work_agenda", expect.anything());
  });

  it("shows the same notice inline, and Try again reads the agenda", async () => {
    const call = vi.fn((name: string) =>
      name === "get_work_agenda"
        ? Promise.resolve({ items: [], next_cursor: null })
        : new Promise(() => undefined),
    );
    render(
      <WorkRoom
        mode="inline"
        transport={{ ...transport, call } as unknown as RoomProps["transport"]}
        {...failedResult}
      />,
    );
    const alert = await screen.findByRole("alert");
    // Try again reads the agenda, so that is what the heading names, whichever tool failed.
    expect(alert).toHaveTextContent("Couldn’t load your tasks");
    expect(alert.querySelector(".sk-error-hint")).toHaveTextContent(
      "Sidekick didn’t respond.",
    );
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(call).toHaveBeenCalledWith("get_work_agenda", expect.anything());
  });
});

describe("Work room, an error result in a card of the Projects view", () => {
  it.each([
    ["en", "Couldn’t load your projects", "Try again"],
    ["sv", "Projekten kunde inte hämtas", "Försök igen"],
  ])(
    "names the Projects, and Try again reads them (%s)",
    async (lang, heading, retryName) => {
      document.head.innerHTML = `<meta name="sidekick-app-locale" content="${lang}">`;
      const call = vi.fn((name: string) =>
        name === "get_work_hierarchy"
          ? Promise.resolve({ nodes: [], truncated: false })
          : new Promise(() => undefined),
      );
      render(
        <WorkRoom
          mode="inline"
          transport={
            { ...transport, call } as unknown as RoomProps["transport"]
          }
          view="hierarchy"
          {...failedResult}
        />,
      );
      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent(heading);
      await userEvent.click(screen.getByRole("button", { name: retryName }));
      await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
      expect(call).toHaveBeenCalledWith(
        "get_work_hierarchy",
        expect.anything(),
      );
      expect(call).not.toHaveBeenCalledWith(
        "get_work_agenda",
        expect.anything(),
      );
    },
  );

  it.each(["task", "project", "agenda"])(
    "falls back to the agenda for the %s view, which has no argument to read again, and says so",
    async (view) => {
      const call = vi.fn((name: string) =>
        name === "get_work_agenda"
          ? Promise.resolve({ items: [], next_cursor: null })
          : new Promise(() => undefined),
      );
      render(
        <WorkRoom
          mode="inline"
          transport={
            { ...transport, call } as unknown as RoomProps["transport"]
          }
          view={view}
          {...failedResult}
        />,
      );
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Couldn’t load your tasks",
      );
      await userEvent.click(screen.getByRole("button", { name: "Try again" }));
      await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
      expect(call).toHaveBeenCalledWith("get_work_agenda", expect.anything());
    },
  );
});

describe("Contacts room, inline card, first result is an error", () => {
  it.each([
    [
      "en",
      "Couldn’t load your contacts",
      "Sidekick didn’t respond.",
      "Try again",
    ],
    [
      "sv",
      "Kontakterna kunde inte hämtas",
      "Sidekick svarade inte.",
      "Försök igen",
    ],
  ])(
    "names the contacts, gives the cause line and a Try again that reads the list (%s)",
    async (lang, heading, hint, retryName) => {
      document.head.innerHTML = `<meta name="sidekick-app-locale" content="${lang}">`;
      const call = vi.fn((name: string) =>
        name === "list_contacts"
          ? Promise.resolve({ contacts: [], next_cursor: null })
          : new Promise(() => undefined),
      );
      render(
        <ContactsRoom
          mode="inline"
          transport={
            { ...transport, call } as unknown as RoomProps["transport"]
          }
          view="contact"
          {...failedResult}
        />,
      );
      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent(heading);
      expect(alert).not.toHaveTextContent(/tasks|Uppgift/);
      expect(alert.querySelector(".sk-error-hint")).toHaveTextContent(hint);
      expect(alert.closest(".sk-card")).not.toBeNull();
      await userEvent.click(screen.getByRole("button", { name: retryName }));
      await waitFor(() =>
        expect(call).toHaveBeenCalledWith("list_contacts", expect.anything()),
      );
      await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    },
  );
});

describe("Control room, first result is an error", () => {
  it.each([
    ["list_trash", "trash", "Couldn’t load deleted items"],
    ["list_recent_changes", "changes", "Couldn’t load the history"],
    ["list_assistant_activity", "activity", "Couldn’t load the history"],
    ["get_memory_status", "memory", "Couldn’t load the memory settings"],
  ])(
    "names what %s could not read, with the cause line and Try again",
    async (_tool, view, heading) => {
      render(
        <ControlRoom
          mode="full"
          transport={transport}
          view={view}
          {...failedResult}
        />,
      );
      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent(heading);
      expect(alert.querySelector(".sk-error-hint")).toHaveTextContent(
        "Sidekick didn’t respond.",
      );
      expect(
        screen.getByRole("button", { name: "Try again" }),
      ).toBeInTheDocument();
    },
  );
});

describe("Journal and Shopping inline", () => {
  it("keep the card that names the room around the same notice", async () => {
    render(
      <JournalRoom mode="inline" transport={transport} {...failedResult} />,
    );
    const alert = await screen.findByRole("alert");
    expect(alert.closest(".sk-card")).not.toBeNull();
    expect(document.querySelector(".sk-eyebrow")).toHaveTextContent("Journal");
    expect(alert.querySelector(".sk-error-hint")).not.toBeNull();
  });
});

describe("the place picker's failed read", () => {
  it.each([
    ["en", groupSelectLabelsEn, "Try again"],
    ["sv", groupSelectLabelsSv, "Försök igen"],
  ] as const)(
    "is the notice's row variant with a retry button (%s)",
    async (_lang, labels, retryName) => {
      const retry = vi.fn();
      render(
        <GroupSelect
          label="Place"
          value={null}
          choices={{ phase: "error", retry }}
          labels={labels}
          onChange={vi.fn()}
        />,
      );
      const alert = screen.getByRole("alert");
      expect(alert).toHaveClass("sk-error--row");
      expect(alert).toHaveTextContent(labels.failed);
      await userEvent.click(screen.getByRole("button", { name: retryName }));
      expect(retry).toHaveBeenCalledTimes(1);
    },
  );

  it("keeps the same keys in both languages and resolves them by locale", () => {
    expect(Object.keys(groupSelectLabelsSv).sort()).toEqual(
      Object.keys(groupSelectLabelsEn).sort(),
    );
    expect(groupSelectLabelsFor("sv-SE")).toBe(groupSelectLabelsSv);
    expect(groupSelectLabelsFor("en-GB")).toBe(groupSelectLabelsEn);
  });
});

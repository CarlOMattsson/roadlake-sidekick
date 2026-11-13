// An error result carries no data, but the host reports which tool failed and which record it read. The Work and
// Contacts rooms name that record in the heading and Try again reads that very record again; with no known tool they
// fall back to the first list, and the heading says so. Simulated-host tests (the room components with a plain
// transport), not a real Claude host.
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ContactsRoom } from "@/features/work-app/contacts/contacts-room";
import { WorkRoom } from "@/features/work-app/room";
import type { RoomProps, ToolArgs } from "@/features/mcp-apps/room-types";
import { toolArgsOf } from "@/features/mcp-apps/room-types";
import { anna, projectA, taskA } from "./helpers/work-app-fixtures";

/** The failed first result a host hands a room: an error result with the tool and record id of its call. */
function failed(toolArgs?: ToolArgs) {
  return { initial: undefined, initialError: true, resultId: 1, toolArgs };
}

/** A transport that answers the given tools and leaves every other call pending. */
function transportOf(answers: Record<string, unknown>) {
  const call = vi.fn((name: string) =>
    name in answers
      ? Promise.resolve(answers[name])
      : new Promise(() => undefined),
  );
  const transport = {
    call,
    requestDisplayMode: vi.fn().mockResolvedValue("inline"),
    updateModelContext: vi.fn().mockResolvedValue(undefined),
  } as unknown as RoomProps["transport"];
  return { call, transport };
}

const locales = [
  ["en", "Try again"],
  ["sv", "Försök igen"],
] as const;

beforeEach(() => {
  document.head.innerHTML = '<meta name="sidekick-app-locale" content="en">';
});

function setLocale(lang: string) {
  document.head.innerHTML = `<meta name="sidekick-app-locale" content="${lang}">`;
}

describe("toolArgsOf", () => {
  it("keeps the tool and the record id of a tool of ours, and nothing else of the arguments", () => {
    expect(
      toolArgsOf("get_task", { task_id: taskA.id, secret: "x" }),
    ).toStrictEqual({ tool: "get_task", id: taskA.id });
    expect(toolArgsOf("sidekick__get_project", { project_id: "p1" })).toEqual({
      tool: "get_project",
      id: "p1",
    });
    expect(toolArgsOf("get_contact_context", { contact_id: "c1" })).toEqual({
      tool: "get_contact_context",
      id: "c1",
    });
  });

  it("gives the tool alone when the input is missing or names no id, and nothing for an unknown tool", () => {
    expect(toolArgsOf("get_task", undefined)).toStrictEqual({
      tool: "get_task",
    });
    expect(toolArgsOf("get_task", { task_id: 7 })).toStrictEqual({
      tool: "get_task",
    });
    expect(toolArgsOf("not_ours", { task_id: "x" })).toBeUndefined();
    expect(toolArgsOf(undefined, { task_id: "x" })).toBeUndefined();
  });
});

describe.each(locales)(
  "Work room, an error result with a known record (%s)",
  (lang, retryName) => {
    const headings = {
      en: {
        task: "Couldn’t load the task",
        project: "Couldn’t load the project",
      },
      sv: {
        task: "Uppgiften kunde inte hämtas",
        project: "Projektet kunde inte hämtas",
      },
    }[lang];

    beforeEach(() => setLocale(lang));

    it("names the Task, and Try again reads it by its id", async () => {
      const { call, transport } = transportOf({ get_task: { task: taskA } });
      render(
        <WorkRoom
          mode="inline"
          transport={transport}
          view="task"
          {...failed({ tool: "get_task", id: taskA.id })}
        />,
      );
      expect(await screen.findByRole("alert")).toHaveTextContent(headings.task);
      await userEvent.click(screen.getByRole("button", { name: retryName }));
      await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
      expect(call).toHaveBeenCalledWith("get_task", { task_id: taskA.id });
      expect(call).not.toHaveBeenCalledWith(
        "get_work_agenda",
        expect.anything(),
      );
    });

    it("names the Project, and Try again reads it by its id", async () => {
      const { call, transport } = transportOf({
        get_project: { project: projectA },
      });
      render(
        <WorkRoom
          mode="inline"
          transport={transport}
          view="project"
          {...failed({ tool: "get_project", id: projectA.id })}
        />,
      );
      expect(await screen.findByRole("alert")).toHaveTextContent(
        headings.project,
      );
      await userEvent.click(screen.getByRole("button", { name: retryName }));
      await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
      expect(call).toHaveBeenCalledWith("get_project", {
        project_id: projectA.id,
      });
      expect(call).not.toHaveBeenCalledWith(
        "get_work_agenda",
        expect.anything(),
      );
    });

    it("keeps the named error when the read fails again", async () => {
      const call = vi.fn(() => Promise.reject(new Error("down")));
      render(
        <WorkRoom
          mode="inline"
          transport={
            { ...transportOf({}).transport, call } as RoomProps["transport"]
          }
          view="task"
          {...failed({ tool: "get_task", id: taskA.id })}
        />,
      );
      await userEvent.click(
        await screen.findByRole("button", { name: retryName }),
      );
      await waitFor(() => expect(call).toHaveBeenCalledTimes(1));
      expect(await screen.findByRole("alert")).toHaveTextContent(headings.task);
    });
  },
);

describe.each(locales)(
  "Contacts room, an error result with a known Contact (%s)",
  (lang, retryName) => {
    beforeEach(() => setLocale(lang));

    it("names the Contact, and Try again reads that Contact, not the list", async () => {
      const { call, transport } = transportOf({
        get_contact_context: {
          contact: anna,
          projects: { items: [], next_cursor: null },
          tasks: { items: [], next_cursor: null },
        },
      });
      render(
        <ContactsRoom
          mode="inline"
          transport={transport}
          view="contact"
          {...failed({ tool: "get_contact_context", id: anna.id })}
        />,
      );
      expect(await screen.findByRole("alert")).toHaveTextContent(
        lang === "en"
          ? "Couldn’t load the contact"
          : "Kontakten kunde inte hämtas",
      );
      await userEvent.click(screen.getByRole("button", { name: retryName }));
      await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
      expect(call).toHaveBeenCalledWith(
        "get_contact_context",
        expect.objectContaining({ contact_id: anna.id }),
      );
      expect(call).not.toHaveBeenCalledWith("list_contacts", expect.anything());
    });
  },
);

describe("an error result with no known tool", () => {
  it.each(locales)(
    "reads the agenda in the Work room and says so (%s)",
    async (lang, retryName) => {
      setLocale(lang);
      const { call, transport } = transportOf({
        get_work_agenda: { items: [], next_cursor: null },
      });
      render(<WorkRoom mode="inline" transport={transport} {...failed()} />);
      expect(await screen.findByRole("alert")).toHaveTextContent(
        lang === "en"
          ? "Couldn’t load your tasks"
          : "Uppgifterna kunde inte hämtas",
      );
      await userEvent.click(screen.getByRole("button", { name: retryName }));
      await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
      expect(call).toHaveBeenCalledWith("get_work_agenda", expect.anything());
    },
  );

  it("falls back to the agenda for a Task whose id the host did not report", async () => {
    const { call, transport } = transportOf({
      get_work_agenda: { items: [], next_cursor: null },
    });
    render(
      <WorkRoom
        mode="inline"
        transport={transport}
        view="task"
        {...failed({ tool: "get_task" })}
      />,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn’t load your tasks",
    );
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(call).toHaveBeenCalledWith("get_work_agenda", expect.anything());
    expect(call).not.toHaveBeenCalledWith("get_task", expect.anything());
  });

  it.each(locales)(
    "reads the list in the Contacts room (%s)",
    async (lang, retryName) => {
      setLocale(lang);
      const { call, transport } = transportOf({
        list_contacts: { contacts: [], next_cursor: null },
      });
      render(
        <ContactsRoom mode="inline" transport={transport} {...failed()} />,
      );
      expect(await screen.findByRole("alert")).toHaveTextContent(
        lang === "en"
          ? "Couldn’t load your contacts"
          : "Kontakterna kunde inte hämtas",
      );
      await userEvent.click(screen.getByRole("button", { name: retryName }));
      await waitFor(() =>
        expect(call).toHaveBeenCalledWith("list_contacts", expect.anything()),
      );
      await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    },
  );
});

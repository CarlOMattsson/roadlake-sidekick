import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CompanionRoomTransport } from "@/mobile/companion-transport";
import { MobileApp } from "@/mobile/mobile-app";
import type { MobilePlatform } from "@/mobile/platform";
import { fakeNative, ok, type FakeNative } from "./helpers/fake-native";
import type { NativeRequest } from "@/mobile/sidekick-native";

const TODAY_ID = "019f0000-0000-7000-8000-0000000000a2";
const LATE_ID = "019f0000-0000-7000-8000-0000000000a1";
const DOMAIN_ID = "019f0000-0000-7000-8000-0000000000d1";
const PROJECT_ID = "019f0000-0000-7000-8000-0000000000b1";
const STEP_ID = "019f0000-0000-7000-8000-0000000000e1";

/** structuredContent of get_work_agenda (the MCP tool's output, which the companion route returns unchanged). */
const AGENDA = {
  items: [
    {
      kind: "task",
      id: LATE_ID,
      title: "Skicka offert",
      status: "todo",
      due_at: null,
      version: 1,
      agenda_group: "overdue",
    },
    {
      kind: "task",
      id: TODAY_ID,
      title: "Boka målare",
      status: "in_progress",
      due_at: null,
      version: 4,
      agenda_group: "today",
    },
  ],
  filters: {},
  next_cursor: null,
};

/** structuredContent of get_task. */
const TASK = {
  task: {
    id: TODAY_ID,
    title: "Boka målare",
    status: "in_progress",
    due_at: null,
    description: null,
    priority: "normal",
    version: 4,
    project_id: null,
    project_title: null,
    steps_done: 0,
    steps_total: 0,
  },
};

/** structuredContent of get_work_hierarchy with include_tasks: one Domain with one Project under it, and two of the Project's Tasks (one done). */
const HIERARCHY = {
  nodes: [
    {
      kind: "domain",
      id: DOMAIN_ID,
      parent_id: null,
      title: "Hemmet",
      accent: null,
    },
    {
      kind: "project",
      id: PROJECT_ID,
      parent_id: DOMAIN_ID,
      title: "Flytten",
      status: "active",
      version: 2,
    },
  ],
  tasks: [
    {
      id: "019f0000-0000-7000-8000-0000000000a3",
      parent_id: PROJECT_ID,
      title: "Packa kartonger",
      status: "in_progress",
      version: 1,
      due_at: null,
      steps: [],
    },
    {
      id: "019f0000-0000-7000-8000-0000000000a4",
      parent_id: PROJECT_ID,
      title: "Boka flyttbil",
      status: "completed",
      version: 3,
      due_at: null,
      steps: [],
    },
  ],
  truncated: false,
};

/** The same Domain with a Process under it (a Project-less Domain), as the hierarchy answers with include_tasks. */
const PROCESS_ID = "019f0000-0000-7000-8000-0000000000a9";
const PROCESS_HIERARCHY = {
  nodes: [
    {
      kind: "domain",
      id: DOMAIN_ID,
      parent_id: null,
      title: "Hemmet",
      accent: null,
    },
    {
      kind: "process",
      id: PROCESS_ID,
      parent_id: DOMAIN_ID,
      title: "Veckostäd",
      status: "active",
      version: 1,
    },
  ],
  tasks: [
    {
      id: "019f0000-0000-7000-8000-0000000000b5",
      parent_id: PROCESS_ID,
      title: "Dammsuga",
      status: "todo",
      version: 1,
      due_at: null,
      steps: [],
    },
  ],
  truncated: false,
};

/** structuredContent of get_process. */
const PROCESS = {
  process: {
    id: PROCESS_ID,
    name: "Veckostäd",
    status: "active",
    description: null,
    cadence: null,
    domain_id: DOMAIN_ID,
    version: 1,
  },
};

/** structuredContent of get_project. */
const PROJECT = {
  project: {
    id: PROJECT_ID,
    title: "Flytten",
    status: "active",
    description: null,
    start_date: null,
    target_date: null,
    version: 2,
    tasks_done: 0,
    tasks_total: 1,
    tasks_overdue: 0,
  },
};

/** A Step of the Task, as the steps route and the step routes return it. */
const STEP = {
  id: STEP_ID,
  title: "Boka flyttbil",
  status: "todo",
  due_at: null,
  version: 1,
};

function answer(request: NativeRequest) {
  if (request.path === "/companion/v1/work/agenda") return ok(AGENDA);
  if (request.path === "/companion/v1/work/hierarchy") return ok(HIERARCHY);
  if (request.path === `/companion/v1/projects/${PROJECT_ID}`)
    return ok(PROJECT);
  if (request.path === `/companion/v1/projects/${PROJECT_ID}/tasks`)
    return ok({
      tasks: [
        {
          id: "019f0000-0000-7000-8000-0000000000a3",
          title: "Packa kartonger",
          status: "in_progress",
          due_at: null,
        },
      ],
      next_cursor: null,
    });
  if (request.path === `/companion/v1/tasks/${TODAY_ID}`) return ok(TASK);
  if (request.path === `/companion/v1/tasks/${TODAY_ID}/complete`)
    return ok({ task: { ...TASK.task, status: "completed", version: 5 } });
  return { status: 404, body: { code: "not_found" } };
}

type TestPlatform = MobilePlatform & {
  pressBack: () => boolean;
  launch: (search: string) => void;
  resume: () => void;
};

function platformFor(search = ""): TestPlatform {
  let back: (() => boolean) | undefined;
  let launched: ((search: string) => void) | undefined;
  let resumed: (() => void) | undefined;
  return {
    onBack: (handler) => {
      back = handler;
      return () => {
        back = undefined;
      };
    },
    launchSearch: () => search,
    onLaunchSearch: (listener) => {
      launched = listener;
      return () => {
        launched = undefined;
      };
    },
    onResume: (listener) => {
      resumed = listener;
      return () => {
        resumed = undefined;
      };
    },
    safeAreaInsets: () => ({ top: 24, right: 0, bottom: 16, left: 0 }),
    pressBack: () => back?.() ?? false,
    launch: (next) => launched?.(next),
    resume: () => resumed?.(),
  };
}

function mount(native: FakeNative, platform: TestPlatform) {
  return render(
    <MobileApp
      transport={new CompanionRoomTransport(native)}
      platform={platform}
      locale="sv"
    />,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  cleanup();
  document.documentElement.removeAttribute("style");
});

describe("MobileApp", () => {
  it("opens Today (the Agenda) over the companion transport, with the view tabs and the strip of the three rooms the app serves", async () => {
    const native = fakeNative(answer);
    mount(native, platformFor());

    expect(await screen.findByText("Skicka offert")).toBeInTheDocument();
    expect(screen.getByText("Boka målare")).toBeInTheDocument();
    expect(native.requests[0]).toEqual({
      method: "GET",
      path: "/companion/v1/work/agenda",
      query: { limit: "25" },
    });
    // The strip names the rooms the companion serves, and leaves out Contacts (no route yet) and Kontroll.
    const strip = screen.getByRole("navigation", { name: "Rum" });
    expect(
      Array.from(strip.querySelectorAll("button")).map((b) => b.textContent),
    ).toEqual(["Arbete", "Dagbok", "Inköp"]);
    expect(screen.getByRole("button", { name: "Arbete" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    // Two views are offered, so the tab strip names the place (no separate room heading); Agenda is the one open.
    expect(
      screen.getByRole("button", { name: "Agenda", pressed: true }),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Projekt", pressed: false }),
    ).toBeVisible();
    expect(
      screen.queryByRole("heading", { name: "Arbete", level: 2 }),
    ).toBeNull();
    // The platform's insets reach the frame.
    expect(
      document.documentElement.style.getPropertyValue("--host-safe-top"),
    ).toBe("24px");
  });

  it("falls back to the CSS env() insets when the platform gives none", async () => {
    const platform = { ...platformFor(), safeAreaInsets: () => undefined };
    mount(fakeNative(answer), platform);

    await screen.findByText("Skicka offert");
    expect(
      document.documentElement.style.getPropertyValue("--host-safe-bottom"),
    ).toBe(
      "max(env(safe-area-inset-bottom, 0px), var(--safe-area-inset-bottom, 0px))",
    );
  });

  it("completes a task through the complete route with the expected version and one idempotency key", async () => {
    const user = userEvent.setup();
    const native = fakeNative(answer);
    mount(native, platformFor());

    await user.click(
      await screen.findByRole("button", {
        name: "Markera Boka målare som klar",
      }),
    );

    await waitFor(() =>
      expect(
        native.requests.find((request) => request.method === "POST"),
      ).toMatchObject({
        method: "POST",
        path: `/companion/v1/tasks/${TODAY_ID}/complete`,
        body: { version: 4 },
      }),
    );
    const posts = native.requests.filter(
      (request) => request.method === "POST",
    );
    expect(posts).toHaveLength(1);
    expect(posts[0]?.idempotencyKey).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("shows the room's own failure state when a write is refused, and sends nothing else", async () => {
    const user = userEvent.setup();
    const native = fakeNative((request) =>
      request.method === "POST"
        ? { status: 409, body: { code: "conflict" } }
        : answer(request),
    );
    mount(native, platformFor());

    await user.click(
      await screen.findByRole("button", {
        name: "Markera Boka målare som klar",
      }),
    );

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(native.requests.filter((r) => r.method === "POST")).toHaveLength(1);
  });

  it("opens a task from a valid hint, and Android Back leads to Today and then leaves", async () => {
    const native = fakeNative(answer);
    const platform = platformFor(`?view=task&id=${TODAY_ID}`);
    mount(native, platform);

    expect(
      await screen.findByRole("heading", { name: "Boka målare" }),
    ).toBeInTheDocument();
    expect(
      native.requests.some((r) => r.path === `/companion/v1/tasks/${TODAY_ID}`),
    ).toBe(true);

    // First Back: one layer, to Today.
    act(() => {
      expect(platform.pressBack()).toBe(true);
    });
    expect(await screen.findByText("Skicka offert")).toBeVisible();
    // At the root Back is the platform's: it leaves the app.
    expect(platform.pressBack()).toBe(false);
  });

  it.each([
    ["an unknown view", "?view=contacts"],
    ["a task id that is not a uuid", "?view=task&id=../../x"],
  ])("opens Today for %s and never asks for a task", async (_label, search) => {
    const native = fakeNative(answer);
    mount(native, platformFor(search));

    expect(await screen.findByText("Skicka offert")).toBeInTheDocument();
    expect(
      native.requests.some((r) => r.path.startsWith("/companion/v1/tasks/")),
    ).toBe(false);
  });

  it("re-roots on a hint that arrives while the app runs", async () => {
    const native = fakeNative(answer);
    const platform = platformFor();
    mount(native, platform);
    await screen.findByText("Skicka offert");

    act(() => platform.launch(`?view=task&id=${TODAY_ID}`));

    expect(
      await screen.findByRole("heading", { name: "Boka målare" }),
    ).toBeInTheDocument();
  });
});

describe("MobileApp views", () => {
  it("offers Agenda and Projekt as tabs: no Status tab to fail, and Projekt is not read before it is opened", async () => {
    const native = fakeNative(answer);
    mount(native, platformFor());

    await screen.findByText("Skicka offert");
    expect(screen.getByRole("button", { name: "Agenda" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Projekt" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Status" })).toBeNull();
    expect(
      native.requests.some(
        (r) => r.path.includes("/work/board") || r.path.includes("hierarchy"),
      ),
    ).toBe(false);
  });

  describe("coming back to the foreground", () => {
    const agendaReads = (native: FakeNative) =>
      native.requests.filter((r) => r.path === "/companion/v1/work/agenda");

    it("reads Today again in place when the last read is older than 30 seconds, once per return", async () => {
      const native = fakeNative(answer);
      const platform = platformFor();
      mount(native, platform);
      await screen.findByText("Skicka offert");
      expect(agendaReads(native)).toHaveLength(1);

      const later = Date.now() + 31_000;
      vi.spyOn(Date, "now").mockReturnValue(later);
      act(() => {
        platform.resume();
        // A second event before the read has started adds no second read.
        platform.resume();
      });

      await waitFor(() => expect(agendaReads(native)).toHaveLength(2));
      // The list stays on screen: no skeleton, no remount.
      expect(screen.getByText("Skicka offert")).toBeInTheDocument();
      await act(async () => {
        await Promise.resolve();
      });
      expect(agendaReads(native)).toHaveLength(2);
    });

    it("does nothing when the last read is younger than 30 seconds", async () => {
      const native = fakeNative(answer);
      const platform = platformFor();
      mount(native, platform);
      await screen.findByText("Skicka offert");

      vi.spyOn(Date, "now").mockReturnValue(Date.now() + 10_000);
      act(() => platform.resume());
      await act(async () => {
        await Promise.resolve();
      });

      expect(agendaReads(native)).toHaveLength(1);
    });
  });

  describe("the widget's language", () => {
    it("tells the native side the app language at start and when it changes", async () => {
      const native = fakeNative(answer);
      const platform = platformFor();
      const transport = new CompanionRoomTransport(native);
      const { rerender } = render(
        <MobileApp
          transport={transport}
          platform={platform}
          locale="sv"
          native={native}
        />,
      );
      await screen.findByText("Skicka offert");
      rerender(
        <MobileApp
          transport={transport}
          platform={platform}
          locale="en"
          native={native}
        />,
      );

      await waitFor(() =>
        expect(native.setLocale.mock.calls.map(([o]) => o)).toEqual([
          { tag: "sv" },
          { tag: "en" },
        ]),
      );
    });

    it("keeps working when the native side refuses the language", async () => {
      const native = fakeNative(answer);
      native.setLocale.mockRejectedValue(new Error("bad_request"));
      render(
        <MobileApp
          transport={new CompanionRoomTransport(native)}
          platform={platformFor()}
          locale="sv"
          native={native}
        />,
      );
      expect(await screen.findByText("Skicka offert")).toBeInTheDocument();
    });
  });

  it("offers only the menu items whose tools the companion has: Uppdatera, not Sparade vyer or Kontroll", async () => {
    const user = userEvent.setup();
    const native = fakeNative(answer);
    mount(native, platformFor());
    await screen.findByText("Skicka offert");

    await user.click(screen.getByRole("button", { name: "Fler val" }));

    expect(screen.getByRole("button", { name: "Uppdatera" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Sparade vyer" })).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Minne och kontroll" }),
    ).toBeNull();
    // The hidden bar never read the saved views, so no read of a route the companion lacks was sent.
    expect(
      native.requests.every((r) => r.path.startsWith("/companion/v1/")),
    ).toBe(true);
    expect(native.requests.some((r) => /saved|views/.test(r.path))).toBe(false);
  });

  it("keeps every menu item on a host without a tool list (the Claude behaviour)", async () => {
    const user = userEvent.setup();
    const closed = new CompanionRoomTransport(fakeNative(answer));
    const open = {
      call: closed.call,
      requestDisplayMode: closed.requestDisplayMode,
      updateModelContext: closed.updateModelContext,
    };
    render(<MobileApp transport={open} platform={platformFor()} locale="sv" />);
    await screen.findByText("Skicka offert");

    await user.click(screen.getByRole("button", { name: "Fler val" }));

    expect(screen.getByRole("button", { name: "Sparade vyer" })).toBeDefined();
    expect(
      screen.getByRole("button", { name: "Minne och kontroll" }),
    ).toBeVisible();
  });
  it("shows the Task detail with 'Markera klar' and the Step checks to write, and no other control that would be refused", async () => {
    const native = fakeNative((request) => {
      if (request.path === `/companion/v1/tasks/${TODAY_ID}/steps`)
        return ok({ items: [STEP], next_cursor: null });
      if (
        request.path === `/companion/v1/tasks/${TODAY_ID}/contacts` ||
        request.path === `/companion/v1/tasks/${TODAY_ID}/external-references`
      )
        return ok({ items: [], next_cursor: null });
      return answer(request);
    });
    mount(native, platformFor(`?view=task&id=${TODAY_ID}`));

    expect(await screen.findByText("Boka flyttbil")).toBeVisible();
    expect(screen.getByRole("button", { name: "Markera klar" })).toBeVisible();
    // The Step check is offered: complete_task_step and update_task_step (uncheck) both have a route.
    expect(
      screen.getByRole("checkbox", { name: "Boka flyttbil" }),
    ).toBeVisible();
    expect(screen.getAllByRole("checkbox")).toHaveLength(1);
    // Everything else that writes has no route and is not drawn.
    for (const name of [
      /^Lägg till datum|^Ändra datum/,
      /^Ändra status/,
      "Fler val",
      "Lägg till steg",
      "Koppla kontakt",
    ])
      expect(screen.queryByRole("button", { name })).toBeNull();
    // Nothing is written until the owner asks.
    expect(native.requests.filter((r) => r.method !== "GET")).toHaveLength(0);
  });

  it("offers Today without +, and its rows only the tick and 'Klar' in the quick choices", async () => {
    mount(fakeNative(answer), platformFor());
    await screen.findByText("Skicka offert");

    expect(screen.queryByRole("button", { name: "Ny uppgift" })).toBeNull();
    expect(screen.queryByText(/^Flytta \d+ försenade/)).toBeNull();
    expect(
      screen.getByRole("button", { name: "Markera Boka målare som klar" }),
    ).toBeVisible();
  });
});

describe("MobileApp Projekt", () => {
  it("reads the hierarchy only when Projekt is opened, and a tap on a Project reads that Project", async () => {
    const user = userEvent.setup();
    const native = fakeNative(answer);
    mount(native, platformFor());
    await screen.findByText("Skicka offert");

    await user.click(screen.getByRole("button", { name: "Projekt" }));

    // The Project row is on the screen, under its Domain.
    expect(await screen.findByText("Flytten")).toBeVisible();
    const reads = native.requests.filter((r) =>
      r.path.includes("/work/hierarchy"),
    );
    expect(reads).toHaveLength(1);
    expect(reads[0]).toMatchObject({
      method: "GET",
      path: "/companion/v1/work/hierarchy",
    });
    // The hierarchy is read with its Tasks, so each Project row counts them (one of two done).
    expect(reads[0]?.query).toEqual({ include_tasks: "true" });
    expect(screen.getByText("1 av 2 klara")).toBeVisible();

    await user.click(screen.getByRole("button", { name: /Flytten/ }));

    await waitFor(() =>
      expect(native.requests).toContainEqual({
        method: "GET",
        path: `/companion/v1/projects/${PROJECT_ID}`,
      }),
    );
    // Reading never writes.
    expect(native.requests.filter((r) => r.method !== "GET")).toHaveLength(0);
  });

  it("shows a Process's open Tasks in the list and lists them on its page, read through the hierarchy", async () => {
    const user = userEvent.setup();
    const native = fakeNative((request) => {
      if (request.path === "/companion/v1/work/hierarchy") {
        // A Process's Tasks are the hierarchy asked for that Process alone; the list asks the whole page.
        return ok(
          request.query?.process_id === PROCESS_ID
            ? {
                nodes: [],
                tasks: PROCESS_HIERARCHY.tasks,
                truncated: false,
                next_cursor: null,
              }
            : PROCESS_HIERARCHY,
        );
      }
      if (request.path === `/companion/v1/processes/${PROCESS_ID}`)
        return ok(PROCESS);
      return answer(request);
    });
    mount(native, platformFor());
    await screen.findByText("Skicka offert");
    await user.click(screen.getByRole("button", { name: "Projekt" }));
    expect(await screen.findByText("Veckostäd")).toBeVisible();

    await user.click(screen.getByRole("button", { name: /Veckostäd/ }));

    expect(await screen.findByText("Dammsuga")).toBeVisible();
    expect(native.requests).toContainEqual({
      method: "GET",
      path: "/companion/v1/work/hierarchy",
      query: { limit: "1", include_tasks: "true", process_id: PROCESS_ID },
    });
    // The phone has no route that lists a Process's Tasks, and none is asked for.
    expect(
      native.requests.filter((r) => r.path.endsWith("/tasks")),
    ).toHaveLength(0);
    expect(native.requests.filter((r) => r.method !== "GET")).toHaveLength(0);
  });

  it("opens a Project from its Task as the Project page: it reads the Project and its Tasks, and offers neither 'Redigera' nor 'Ny uppgift'", async () => {
    const user = userEvent.setup();
    const native = fakeNative((request) => {
      if (request.path === `/companion/v1/tasks/${TODAY_ID}`)
        return ok({
          task: {
            ...TASK.task,
            project_id: PROJECT_ID,
            project_title: "Flytten",
          },
        });
      if (
        request.path.startsWith(`/companion/v1/tasks/${TODAY_ID}/`) &&
        request.method === "GET"
      )
        return ok({ items: [], next_cursor: null });
      return answer(request);
    });
    mount(native, platformFor(`?view=task&id=${TODAY_ID}`));

    // The place chip opens a panel; on the phone it holds only the link to the Project (the place is not written there).
    await user.click(
      await screen.findByRole("button", { name: "Ändra plats: Flytten" }),
    );
    expect(screen.queryByRole("combobox")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Öppna Flytten" }));

    expect(
      await screen.findByRole("heading", { name: "Flytten", level: 2 }),
    ).toBeVisible();
    await waitFor(() =>
      expect(native.requests).toContainEqual({
        method: "GET",
        path: `/companion/v1/projects/${PROJECT_ID}/tasks`,
        query: { limit: "20" },
      }),
    );
    expect(native.requests).toContainEqual({
      method: "GET",
      path: `/companion/v1/projects/${PROJECT_ID}`,
    });
    // The Tasks are listed (the Project page is ready) ...
    expect(await screen.findByText("Packa kartonger")).toBeVisible();
    // ... and the two controls the phone cannot write are not drawn.
    expect(screen.queryByRole("button", { name: "Redigera" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Ny uppgift" })).toBeNull();
    expect(native.requests.filter((r) => r.method !== "GET")).toHaveLength(0);
  });
});

describe("MobileApp Step checks", () => {
  /** A fake server with one Step: complete and reopen answer the Step as stored, with the next version. */
  function stepServer() {
    return fakeNative((request) => {
      if (request.path === `/companion/v1/tasks/${TODAY_ID}/steps`)
        return ok({ items: [STEP], next_cursor: null });
      if (request.path.startsWith(`/companion/v1/tasks/${TODAY_ID}/`))
        return ok({ items: [], next_cursor: null });
      if (request.path === `/companion/v1/steps/${STEP_ID}/complete`)
        return ok({ step: { ...STEP, status: "completed", version: 2 } });
      if (request.path === `/companion/v1/steps/${STEP_ID}/reopen`)
        return ok({ step: { ...STEP, status: "todo", version: 3 } });
      return answer(request);
    });
  }

  const posts = (native: FakeNative) =>
    native.requests.filter((request) => request.method === "POST");

  it("ticks a Step through the Step complete route with its version and one idempotency key", async () => {
    const user = userEvent.setup();
    const native = stepServer();
    mount(native, platformFor(`?view=task&id=${TODAY_ID}`));

    await user.click(
      await screen.findByRole("checkbox", { name: "Boka flyttbil" }),
    );

    await waitFor(() => expect(posts(native)).toHaveLength(1));
    const [complete] = posts(native);
    expect(complete).toMatchObject({
      method: "POST",
      path: `/companion/v1/steps/${STEP_ID}/complete`,
      body: { version: 1 },
    });
    expect(typeof complete?.idempotencyKey).toBe("string");
    expect(complete?.idempotencyKey?.length).toBeGreaterThanOrEqual(8);
    // The check shows its result in its own row: "Klar" and Ångra beside the title.
    expect(await screen.findByRole("button", { name: /^Ångra/ })).toBeVisible();
  });

  it("takes the tick back with Ångra through the Step reopen route, against the version the tick left", async () => {
    const user = userEvent.setup();
    const native = stepServer();
    mount(native, platformFor(`?view=task&id=${TODAY_ID}`));
    await user.click(
      await screen.findByRole("checkbox", { name: "Boka flyttbil" }),
    );

    await user.click(await screen.findByRole("button", { name: /^Ångra/ }));

    await waitFor(() => expect(posts(native)).toHaveLength(2));
    const [complete, reopen] = posts(native);
    expect(reopen).toMatchObject({
      method: "POST",
      path: `/companion/v1/steps/${STEP_ID}/reopen`,
      body: { version: 2 },
    });
    expect(typeof reopen?.idempotencyKey).toBe("string");
    expect(reopen?.idempotencyKey?.length).toBeGreaterThanOrEqual(8);
    // Another action, another key.
    expect(reopen?.idempotencyKey).not.toBe(complete?.idempotencyKey);
  });

  it("unchecks a completed Step through the reopen route", async () => {
    const user = userEvent.setup();
    const native = fakeNative((request) => {
      if (request.path === `/companion/v1/tasks/${TODAY_ID}/steps`)
        return ok({
          items: [{ ...STEP, status: "completed", version: 5 }],
          next_cursor: null,
        });
      if (request.path === `/companion/v1/steps/${STEP_ID}/reopen`)
        return ok({ step: { ...STEP, status: "todo", version: 6 } });
      if (request.path.startsWith(`/companion/v1/tasks/${TODAY_ID}/`))
        return ok({ items: [], next_cursor: null });
      return answer(request);
    });
    mount(native, platformFor(`?view=task&id=${TODAY_ID}`));

    await user.click(
      await screen.findByRole("checkbox", { name: "Boka flyttbil" }),
    );

    await waitFor(() => expect(posts(native)).toHaveLength(1));
    expect(posts(native)[0]).toMatchObject({
      method: "POST",
      path: `/companion/v1/steps/${STEP_ID}/reopen`,
      body: { version: 5 },
    });
    expect(posts(native)[0]?.idempotencyKey).toMatch(/^.{8,}$/);
  });
});

describe("MobileApp rooms: Inköp and Dagbok", () => {
  const LIST_ID = "019f0000-0000-7000-8000-0000000000b1";
  const LIST = {
    id: LIST_ID,
    name: "Veckohandel",
    version: 1,
    archived: false,
    created_at: "2026-11-01T12:00:00Z",
    updated_at: "2026-11-01T12:00:00Z",
  };
  const DAY = {
    journal_date: "2026-11-09",
    entries: [],
    next_cursor: null,
    summary: {
      journal_date: "2026-11-09",
      exists: false,
      status: null,
      content: null,
    },
  };

  function roomAnswer(request: NativeRequest) {
    if (request.path === "/companion/v1/shopping/lists")
      return ok({ lists: [LIST], next_offset: null });
    if (request.path === `/companion/v1/shopping/lists/${LIST_ID}`)
      return ok({
        shopping_list: LIST,
        evaluated_on: "2026-11-09",
        next_offset: null,
        items: [],
      });
    if (request.path.startsWith("/companion/v1/journal/days/")) return ok(DAY);
    return answer(request);
  }

  it("switching to Inköp reads the lists through the transport", async () => {
    const user = userEvent.setup();
    const native = fakeNative(roomAnswer);
    mount(native, platformFor());
    await screen.findByText("Skicka offert");

    await user.click(screen.getByRole("button", { name: "Inköp" }));

    expect(
      await screen.findByRole("heading", { name: "Veckohandel" }),
    ).toBeInTheDocument();
    const paths = native.requests.map((r) => r.path);
    expect(paths).toContain("/companion/v1/shopping/lists");
    expect(paths).toContain(`/companion/v1/shopping/lists/${LIST_ID}`);
  });

  it.each([
    ["Inköp", "Veckohandel"],
    ["Dagbok", undefined],
  ] as const)(
    "opens Inställningar from %s's ⋯ and goes back to that room (ua-8)",
    async (room, heading) => {
      const user = userEvent.setup();
      const native = fakeNative(roomAnswer);
      render(
        <MobileApp
          transport={new CompanionRoomTransport(native)}
          platform={platformFor()}
          locale="sv"
          native={native}
        />,
      );
      await screen.findByText("Skicka offert");
      await user.click(screen.getByRole("button", { name: room }));
      if (heading) await screen.findByRole("heading", { name: heading });
      const more = await screen.findAllByRole("button", { name: "Fler val" });
      await user.click(more[0]!);
      await user.click(
        await screen.findByRole("button", { name: "Inställningar" }),
      );
      await screen.findByRole("heading", { name: "Inställningar" });
      await user.click(
        screen.getByRole("button", { name: `Tillbaka till ${room}` }),
      );
      await waitFor(() =>
        expect(
          screen.queryByRole("heading", { name: "Inställningar" }),
        ).toBeNull(),
      );
    },
  );

  it("switching to Dagbok reads today's day through the transport and asks for no draft or original", async () => {
    const user = userEvent.setup();
    const native = fakeNative(roomAnswer);
    mount(native, platformFor());
    await screen.findByText("Skicka offert");

    await user.click(screen.getByRole("button", { name: "Dagbok" }));

    await waitFor(() =>
      expect(
        native.requests.some((r) =>
          r.path.startsWith("/companion/v1/journal/days/"),
        ),
      ).toBe(true),
    );
    expect(
      native.requests.some((r) => /pending|draft|source/.test(r.path)),
    ).toBe(false);
  });
});

import { readFileSync } from "node:fs";
import { withAppLocale } from "./mcp-host-fixture";
import { test, expect } from "@playwright/test";

test("sandboxed Work App navigates Task and Contact through the host on a mobile viewport", async ({
  page,
}) => {
  const html = withAppLocale(
    readFileSync("../backend/src/sidekick/mcp/apps/sidekick.html", "utf8"),
    "en",
  );
  const failures: string[] = [];
  page.on("pageerror", (error) => failures.push(error.message));
  let networkRequests = 0;
  await page.route("**/*", async (route) => {
    networkRequests++;
    await route.abort();
  });
  await page.setContent(
    '<iframe title="Sidekick work" sandbox="allow-scripts" style="width:360px;height:750px;border:0"></iframe>',
  );
  await page.evaluate((resource) => {
    const frame = document.querySelector("iframe")!;
    const task = {
      id: "019f0000-0000-7000-8000-000000000001",
      project_id: null,
      domain_id: null,
      process_id: null,
      derived_domain_id: null,
      title: "Ring Anna om offerten",
      description: null,
      status: "todo",
      priority: "normal",
      due_at: "2026-10-30T09:00:00Z",
      completed_at: null,
      created_at: "2026-10-24T12:00:00Z",
      updated_at: "2026-10-24T12:00:00Z",
      version: 1,
    };
    // Injected markup in a title must render as text, never as an element.
    const followUp = {
      id: "019f0000-0000-7000-8000-000000000002",
      title:
        'Faktura <img src="https://example.org/tracker" onerror="alert(1)">',
      status: "doing",
      priority: "normal",
      due_at: null,
      project_id: null,
      updated_at: "2026-10-24T12:00:00Z",
      version: 1,
    };
    const contact = {
      id: "019f0000-0000-7000-8000-000000000003",
      display_name: "Anna Andersson",
      context_note: null,
      email: null,
      phone: null,
      aliases: [],
      archived: false,
      archived_at: null,
      created_at: "2026-10-24T12:00:00Z",
      updated_at: "2026-10-24T12:00:00Z",
      version: 1,
    };
    const state = {
      calls: [] as { name: string; arguments: Record<string, unknown> }[],
      initialized: false,
    };
    Object.assign(window, { workTest: state });
    window.addEventListener("message", (event) => {
      if (event.source !== frame.contentWindow) return;
      const message = event.data as {
        id?: number;
        method: string;
        params: { name: string; arguments: Record<string, unknown> };
      };
      const reply = (result: object) =>
        frame.contentWindow!.postMessage(
          { jsonrpc: "2.0", id: message.id, result },
          "*",
        );
      if (message.method === "ui/initialize")
        reply({
          protocolVersion: "2026-01-26",
          hostCapabilities: {},
          hostInfo: { name: "Test host", version: "1" },
          hostContext: { locale: "en", theme: "light" },
        });
      else if (message.method === "ui/notifications/initialized") {
        state.initialized = true;
        frame.contentWindow!.postMessage(
          {
            jsonrpc: "2.0",
            method: "ui/notifications/tool-result",
            params: { structuredContent: { task } },
          },
          "*",
        );
      } else if (message.method === "tools/call") {
        state.calls.push(message.params);
        const { name } = message.params;
        if (name === "get_task")
          reply({
            structuredContent: {
              task:
                message.params.arguments.task_id === followUp.id
                  ? followUp
                  : task,
            },
          });
        else if (name === "list_task_contacts")
          reply({
            structuredContent: { items: [contact], next_cursor: null },
          });
        else if (name === "get_contact_context")
          reply({
            structuredContent: {
              contact,
              projects: { items: [], next_cursor: null },
              tasks: { items: [followUp], next_cursor: null },
            },
          });
        else if (name === "list_task_steps")
          reply({ structuredContent: { items: [], next_cursor: null } });
        else reply({ isError: true });
      }
    });
    frame.srcdoc = resource;
  }, html);
  const app = page.frameLocator("iframe");
  // Inline the Task is a summary; this host offers no fullscreen, so Show more expands the full view inline.
  await app.getByRole("button", { name: "Show more", exact: true }).click();
  await expect(
    app.getByRole("heading", { level: 2, name: "Ring Anna om offerten" }),
  ).toBeVisible();
  await app
    .getByRole("button", { name: "Anna Andersson", exact: true })
    .click();
  const contactHeading = app.getByRole("heading", {
    level: 2,
    name: "Anna Andersson",
  });
  await expect(contactHeading).toBeVisible();
  await expect(contactHeading).toBeFocused();
  // The Task row's name is its literal title (which carries an <img> string); the row's "More options for
  // Faktura …" button also contains "Faktura", so anchor the match at the start.
  await app.getByRole("button", { name: /^Faktura/ }).click();
  await expect(
    app.getByRole("heading", { level: 2, name: "Faktura" }),
  ).toBeVisible();
  await expect(app.locator("img")).toHaveCount(0);
  await app.getByRole("button", { name: "Back" }).click();
  await expect(contactHeading).toBeVisible();
  await app.getByRole("button", { name: "Back" }).click();
  await expect(
    app.getByRole("heading", { level: 2, name: "Ring Anna om offerten" }),
  ).toBeVisible();
  await expect(app.getByRole("button", { name: "Back" })).toHaveCount(0);
  const state = await page.evaluate(
    () =>
      (
        window as unknown as {
          workTest: {
            initialized: boolean;
            calls: { name: string; arguments: Record<string, unknown> }[];
          };
        }
      ).workTest,
  );
  expect(state.initialized).toBe(true);
  const names = state.calls.map((call) => call.name);
  expect(names).toContain("get_task");
  expect(names).toContain("list_task_contacts");
  expect(names).toContain("get_contact_context");
  const context = state.calls.find(
    (call) => call.name === "get_contact_context",
  )!;
  expect(context.arguments).toMatchObject({
    project_limit: 10,
    task_limit: 20,
  });
  // The inlined stylesheet must reach the App: the shell frame pads 8px above the strip.
  await expect(
    app
      .locator(".sk-frame__body")
      .evaluate((element) => getComputedStyle(element).paddingTop),
  ).resolves.toBe("8px");
  const dimensions = await app.locator("body").evaluate((body) => ({
    width: body.scrollWidth,
    viewport: window.innerWidth,
  }));
  expect(dimensions.width).toBeLessThanOrEqual(dimensions.viewport);
  expect(failures).toEqual([]);
  expect(networkRequests).toBe(0);
});

test("sandboxed Work App resets its stack on a new root and shows an error frame for an error result", async ({
  page,
}) => {
  const html = withAppLocale(
    readFileSync("../backend/src/sidekick/mcp/apps/sidekick.html", "utf8"),
    "en",
  );
  const failures: string[] = [];
  page.on("pageerror", (error) => failures.push(error.message));
  let networkRequests = 0;
  await page.route("**/*", async (route) => {
    networkRequests++;
    await route.abort();
  });
  await page.setContent(
    '<iframe title="Sidekick work" sandbox="allow-scripts" style="width:360px;height:750px;border:0"></iframe>',
  );
  await page.evaluate((resource) => {
    const frame = document.querySelector("iframe")!;
    const task = {
      id: "019f0000-0000-7000-8000-000000000001",
      title: "Ring Anna om offerten",
      status: "todo",
      due_at: null,
    };
    const followUp = {
      id: "019f0000-0000-7000-8000-000000000002",
      title: "Faktura",
      status: "doing",
      due_at: null,
    };
    // Full ContactRecord fields: get_contact_context returns the whole contact.
    const anna = {
      id: "019f0000-0000-7000-8000-000000000003",
      display_name: "Anna Andersson",
      email: null,
      phone: null,
      context_note: null,
      aliases: [],
      archived: false,
      archived_at: null,
      version: 1,
    };
    const bo = {
      id: "019f0000-0000-7000-8000-000000000004",
      display_name: "Bo Berg",
      email: null,
      phone: null,
      context_note: null,
      aliases: [],
      archived: false,
      archived_at: null,
      version: 1,
    };
    window.addEventListener("message", (event) => {
      if (event.source !== frame.contentWindow) return;
      const message = event.data as {
        id?: number;
        method: string;
        params: { name: string; arguments: Record<string, unknown> };
      };
      const reply = (result: object) =>
        frame.contentWindow!.postMessage(
          { jsonrpc: "2.0", id: message.id, result },
          "*",
        );
      if (message.method === "ui/initialize")
        reply({
          protocolVersion: "2026-01-26",
          hostCapabilities: {},
          hostInfo: { name: "Test host", version: "1" },
          hostContext: { locale: "en", theme: "light" },
        });
      else if (message.method === "ui/notifications/initialized")
        frame.contentWindow!.postMessage(
          {
            jsonrpc: "2.0",
            method: "ui/notifications/tool-result",
            params: { structuredContent: { task } },
          },
          "*",
        );
      else if (message.method === "tools/call") {
        const { name, arguments: args } = message.params;
        if (name === "get_task") reply({ structuredContent: { task } });
        else if (name === "list_task_contacts")
          reply({
            structuredContent: { items: [anna], next_cursor: null },
          });
        else if (name === "get_contact_context")
          reply({
            structuredContent: {
              contact: args.contact_id === bo.id ? bo : anna,
              projects: { items: [], next_cursor: null },
              tasks: { items: [followUp], next_cursor: null },
            },
          });
        else if (name === "list_task_steps")
          reply({ structuredContent: { items: [], next_cursor: null } });
        else reply({ isError: true });
      }
    });
    Object.assign(window, {
      pushToolResult: (params: object) =>
        frame.contentWindow!.postMessage(
          { jsonrpc: "2.0", method: "ui/notifications/tool-result", params },
          "*",
        ),
    });
    frame.srcdoc = resource;
  }, html);
  const push = (params: object) =>
    page.evaluate(
      (value) =>
        (
          window as unknown as {
            pushToolResult: (params: object) => void;
          }
        ).pushToolResult(value),
      params,
    );
  const app = page.frameLocator("iframe");
  // A full ContactRecord, as contact results carry it: a partial one has no context, so no summary.
  const bo = {
    id: "019f0000-0000-7000-8000-000000000004",
    display_name: "Bo Berg",
    email: null,
    phone: null,
    context_note: null,
    aliases: [],
    archived: false,
    archived_at: null,
    version: 1,
  };
  const contactResult = (contact: { id: string; display_name: string }) => ({
    structuredContent: {
      contact,
      projects: { items: [], next_cursor: null },
      tasks: { items: [], next_cursor: null },
    },
  });
  await app.getByRole("button", { name: "Show task", exact: true }).click();
  await expect(
    app.getByRole("heading", { level: 2, name: "Ring Anna om offerten" }),
  ).toBeVisible();
  await app
    .getByRole("button", { name: "Anna Andersson", exact: true })
    .click();
  await expect(
    app.getByRole("heading", { level: 2, name: "Anna Andersson" }),
  ).toBeVisible();
  await expect(app.getByRole("button", { name: "Back" })).toBeVisible();
  // A result flagged as an error opens the error frame (inline-kort-och-kanban-design): it
  // replaces the stack, says what failed and keeps no Contact data. It has no "Try again": the
  // frame holds no tool name, so a retry would have nothing to read again.
  await push({ ...contactResult(bo), isError: true });
  // The heading names what could not be read: the room the error replaces (the task). A heading has no full stop
  // (designsystem §1.6). A failure without Sidekick's own error code may be the connection, so the card adds one muted
  // line only when the frame knows it is offline; online it is the heading alone ("Try again in a moment."
  // repeated the button and is gone). The card holds no retry (see below).
  await expect(
    app.getByRole("alert").getByText("Couldn’t load the task", { exact: true }),
  ).toBeVisible();
  await expect(app.getByRole("alert").locator("p")).toHaveText([
    "Couldn’t load the task",
  ]);
  await expect(app.getByRole("button", { name: "Try again" })).toHaveCount(0);
  await expect(
    app.getByRole("heading", { level: 2, name: "Anna Andersson" }),
  ).toHaveCount(0);
  await expect(app.getByRole("button", { name: "Back" })).toHaveCount(0);
  // A new root result for another contact replaces the whole stack. Inline it is a summary again.
  await push(contactResult(bo));
  await app.getByRole("button", { name: "Open", exact: true }).click();
  await expect(
    app.getByRole("heading", { level: 2, name: "Bo Berg" }),
  ).toBeVisible();
  await expect(
    app.getByRole("heading", { level: 2, name: "Anna Andersson" }),
  ).toHaveCount(0);
  await expect(app.getByRole("button", { name: "Back" })).toHaveCount(0);
  expect(failures).toEqual([]);
  expect(networkRequests).toBe(0);
});

test("sandboxed Work App recovers from a stale Task version by reloading and saving again", async ({
  page,
}) => {
  const html = withAppLocale(
    readFileSync("../backend/src/sidekick/mcp/apps/sidekick.html", "utf8"),
    "en",
  );
  const failures: string[] = [];
  page.on("pageerror", (error) => failures.push(error.message));
  let networkRequests = 0;
  await page.route("**/*", async (route) => {
    networkRequests++;
    await route.abort();
  });
  await page.setContent(
    '<iframe title="Sidekick work" sandbox="allow-scripts" style="width:360px;height:750px;border:0"></iframe>',
  );
  await page.evaluate((resource) => {
    const frame = document.querySelector("iframe")!;
    const task = {
      id: "019f0000-0000-7000-8000-000000000001",
      title: "Ring Anna om offerten",
      status: "todo",
      due_at: null,
      version: 1,
    };
    const state = {
      calls: [] as { name: string; arguments: Record<string, unknown> }[],
      initialized: false,
    };
    Object.assign(window, { workTest: state });
    // Another writer changes the Task after the view loaded it: the server now holds version 2.
    let current = task;
    let updates = 0;
    window.addEventListener("message", (event) => {
      if (event.source !== frame.contentWindow) return;
      const message = event.data as {
        id?: number;
        method: string;
        params: { name: string; arguments: Record<string, unknown> };
      };
      const reply = (result: object) =>
        frame.contentWindow!.postMessage(
          { jsonrpc: "2.0", id: message.id, result },
          "*",
        );
      if (message.method === "ui/initialize")
        reply({
          protocolVersion: "2026-01-26",
          hostCapabilities: {},
          hostInfo: { name: "Test host", version: "1" },
          hostContext: { locale: "en", theme: "light" },
        });
      else if (message.method === "ui/notifications/initialized") {
        state.initialized = true;
        frame.contentWindow!.postMessage(
          {
            jsonrpc: "2.0",
            method: "ui/notifications/tool-result",
            params: { structuredContent: { task } },
          },
          "*",
        );
      } else if (message.method === "tools/call") {
        state.calls.push(message.params);
        const { name, arguments: args } = message.params;
        if (name === "get_task")
          reply({ structuredContent: { task: current } });
        else if (name === "list_task_contacts")
          reply({ structuredContent: { items: [], next_cursor: null } });
        else if (name === "list_task_steps")
          reply({ structuredContent: { items: [], next_cursor: null } });
        else if (name === "update_task") {
          updates++;
          if (updates === 1) {
            current = {
              ...task,
              title: "Ring Anna (annan)",
              version: 2,
            };
            reply({
              isError: true,
              structuredContent: {
                code: "conflict",
                message: "Conflict.",
                correlation_id: "e2e-conflict",
              },
            });
          } else {
            const changes = args.changes as { title: string };
            current = {
              ...current,
              title: changes.title,
              version: (args.version as number) + 1,
            };
            reply({ structuredContent: { task: current } });
          }
        } else reply({ isError: true });
      }
    });
    frame.srcdoc = resource;
  }, html);
  const app = page.frameLocator("iframe");
  await app.getByRole("button", { name: "Show more", exact: true }).click();
  await expect(
    app.getByRole("heading", { level: 2, name: "Ring Anna om offerten" }),
  ).toBeVisible();
  // Redigera sits in the ⋯ menu of the Back row: it is no longer a pen beside the title.
  await app.getByRole("button", { name: "More options", exact: true }).click();
  await app.getByRole("button", { name: "Edit", exact: true }).click();
  await app.getByLabel("Title").fill("Ring Anna idag");
  await app.getByRole("button", { name: "Save" }).click();
  const banner = app.getByRole("alert");
  await expect(banner).toContainText("This task was changed elsewhere");
  await expect(banner).toBeFocused();
  await banner.getByRole("button", { name: "Reload" }).click();
  await expect(
    app.getByRole("heading", { level: 2, name: "Ring Anna (annan)" }),
  ).toBeVisible();
  await expect(app.getByLabel("Title")).toHaveValue("Ring Anna idag");
  await expect(app.getByRole("alert")).toHaveCount(0);
  await app.getByRole("button", { name: "Save" }).click();
  await expect(app.getByText("Saved", { exact: true })).toBeVisible();
  const calls = await page.evaluate(
    () =>
      (
        window as unknown as {
          workTest: {
            calls: { name: string; arguments: Record<string, unknown> }[];
          };
        }
      ).workTest.calls,
  );
  const writes = calls.filter((call) => call.name === "update_task");
  expect(writes).toHaveLength(2);
  const [first, second] = writes;
  expect(first?.arguments).toMatchObject({
    task_id: "019f0000-0000-7000-8000-000000000001",
    version: 1,
    changes: { title: "Ring Anna idag" },
  });
  expect(second?.arguments).toMatchObject({
    version: 2,
    changes: { title: "Ring Anna idag" },
  });
  expect(second?.arguments.idempotency_key).not.toBe(
    first?.arguments.idempotency_key,
  );
  expect(calls.map((call) => call.name)).toContain("get_task");
  expect(failures).toEqual([]);
  expect(networkRequests).toBe(0);
});

test("sandboxed Work App opens a Task's Project, recovers from a stale Project version and goes back", async ({
  page,
}) => {
  const html = withAppLocale(
    readFileSync("../backend/src/sidekick/mcp/apps/sidekick.html", "utf8"),
    "en",
  );
  const failures: string[] = [];
  page.on("pageerror", (error) => failures.push(error.message));
  let networkRequests = 0;
  await page.route("**/*", async (route) => {
    networkRequests++;
    await route.abort();
  });
  await page.setContent(
    '<iframe title="Sidekick work" sandbox="allow-scripts" style="width:360px;height:750px;border:0"></iframe>',
  );
  await page.evaluate((resource) => {
    const frame = document.querySelector("iframe")!;
    const projectId = "019f0000-0000-7000-8000-0000000000d1";
    const task = {
      id: "019f0000-0000-7000-8000-000000000001",
      title: "Ring Anna om offerten",
      status: "todo",
      due_at: null,
      project_id: projectId,
      project_title: "Offert till Anna",
      version: 1,
    };
    const projectTask = {
      id: "019f0000-0000-7000-8000-0000000000a4",
      title: "Skriv offertutkast",
      status: "in_progress",
      due_at: null,
    };
    const state = {
      calls: [] as { name: string; arguments: Record<string, unknown> }[],
      initialized: false,
    };
    Object.assign(window, { workTest: state });
    // Another writer renames the Project after the view loaded it: the server now holds version 2.
    let current = {
      id: projectId,
      title: "Offert till Anna",
      status: "active",
      description: null,
      start_date: null,
      target_date: null,
      version: 1,
    };
    let updates = 0;
    window.addEventListener("message", (event) => {
      if (event.source !== frame.contentWindow) return;
      const message = event.data as {
        id?: number;
        method: string;
        params: { name: string; arguments: Record<string, unknown> };
      };
      const reply = (result: object) =>
        frame.contentWindow!.postMessage(
          { jsonrpc: "2.0", id: message.id, result },
          "*",
        );
      if (message.method === "ui/initialize")
        reply({
          protocolVersion: "2026-01-26",
          hostCapabilities: {},
          hostInfo: { name: "Test host", version: "1" },
          hostContext: { locale: "en", theme: "light" },
        });
      else if (message.method === "ui/notifications/initialized") {
        state.initialized = true;
        frame.contentWindow!.postMessage(
          {
            jsonrpc: "2.0",
            method: "ui/notifications/tool-result",
            params: { structuredContent: { task } },
          },
          "*",
        );
      } else if (message.method === "tools/call") {
        state.calls.push(message.params);
        const { name, arguments: args } = message.params;
        if (name === "get_task") reply({ structuredContent: { task } });
        else if (name === "get_project")
          reply({ structuredContent: { project: current } });
        else if (name === "list_tasks")
          reply({
            structuredContent: { tasks: [projectTask], next_cursor: null },
          });
        else if (name === "list_task_contacts")
          reply({ structuredContent: { items: [], next_cursor: null } });
        else if (name === "list_task_steps")
          reply({ structuredContent: { items: [], next_cursor: null } });
        else if (name === "update_project") {
          updates++;
          if (updates === 1) {
            current = { ...current, title: "Offert (annan)", version: 2 };
            reply({
              isError: true,
              structuredContent: {
                code: "conflict",
                message: "Conflict.",
                correlation_id: "e2e-project-conflict",
              },
            });
          } else {
            const changes = args.changes as { title: string };
            current = {
              ...current,
              title: changes.title,
              version: (args.version as number) + 1,
            };
            reply({ structuredContent: { project: current } });
          }
        } else reply({ isError: true });
      }
    });
    frame.srcdoc = resource;
  }, html);
  const app = page.frameLocator("iframe");
  await app.getByRole("button", { name: "Show more", exact: true }).click();
  await expect(
    app.getByRole("heading", { level: 2, name: "Ring Anna om offerten" }),
  ).toBeVisible();
  // The Project link lives in the place chip's panel: open the chip, then the link.
  await app.getByRole("button", { name: /^Change place/ }).click();
  await app.getByRole("button", { name: /^Open Offert till Anna/ }).click();
  await expect(
    app.getByRole("heading", { level: 2, name: "Offert till Anna" }),
  ).toBeVisible();
  await app.getByRole("button", { name: "Edit" }).click();
  await app.getByLabel("Title").fill("Offert idag");
  await app.getByRole("button", { name: "Save" }).click();
  const banner = app.getByRole("alert");
  await expect(banner).toContainText("This project was changed elsewhere");
  await expect(banner).toBeFocused();
  await banner.getByRole("button", { name: "Reload" }).click();
  await expect(
    app.getByRole("heading", { level: 2, name: "Offert (annan)" }),
  ).toBeVisible();
  await expect(app.getByLabel("Title")).toHaveValue("Offert idag");
  await expect(app.getByRole("alert")).toHaveCount(0);
  await app.getByRole("button", { name: "Save" }).click();
  await expect(app.getByText("Saved", { exact: true })).toBeVisible();
  await app.getByRole("button", { name: "Back" }).click();
  await expect(
    app.getByRole("heading", { level: 2, name: "Ring Anna om offerten" }),
  ).toBeVisible();
  const calls = await page.evaluate(
    () =>
      (
        window as unknown as {
          workTest: {
            calls: { name: string; arguments: Record<string, unknown> }[];
          };
        }
      ).workTest.calls,
  );
  const names = calls.map((call) => call.name);
  expect(names).toContain("get_project");
  expect(names).toContain("list_tasks");
  const writes = calls.filter((call) => call.name === "update_project");
  expect(writes).toHaveLength(2);
  const [first, second] = writes;
  expect(first?.arguments).toMatchObject({
    project_id: "019f0000-0000-7000-8000-0000000000d1",
    version: 1,
    changes: { title: "Offert idag" },
  });
  expect(second?.arguments).toMatchObject({
    version: 2,
    changes: { title: "Offert idag" },
  });
  expect(second?.arguments.idempotency_key).not.toBe(
    first?.arguments.idempotency_key,
  );
  expect(failures).toEqual([]);
  expect(networkRequests).toBe(0);
});

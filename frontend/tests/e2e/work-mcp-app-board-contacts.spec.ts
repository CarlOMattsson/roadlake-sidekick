// Playwright runs this file outside Vitest: it reads the bundled app HTML (and font files) from disk to serve them to the simulated host.
import { readFileSync } from "node:fs";
import { withAppLocale } from "./mcp-host-fixture";
import { test, expect } from "@playwright/test";

test("sandboxed Work App adds a Step and links a searched Contact to the Task without network access", async ({
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
    const createdStep = {
      id: "019f0000-0000-7000-8000-000000000004",
      task_id: task.id,
      title: "Boka tid",
      status: "todo",
      position: 1,
      due_at: null,
      version: 1,
    };
    const state = {
      calls: [] as { name: string; arguments: Record<string, unknown> }[],
      initialized: false,
    };
    // The Task's steps and links change only through the writes the view makes.
    let steps: object[] = [];
    let linked = false;
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
        if (name === "get_task") reply({ structuredContent: { task } });
        else if (name === "list_task_steps")
          reply({ structuredContent: { items: steps, next_cursor: null } });
        else if (name === "create_task_step") {
          steps = [...steps, createdStep];
          reply({ structuredContent: { step: createdStep } });
        } else if (name === "list_task_contacts")
          reply({
            structuredContent: {
              items: linked ? [contact] : [],
              next_cursor: null,
            },
          });
        else if (name === "list_contacts")
          reply({
            structuredContent: { contacts: [contact], next_cursor: null },
          });
        else if (name === "link_contact_to_task") {
          linked = true;
          reply({
            structuredContent: {
              contact_id: contact.id,
              task_id: task.id,
              linked: true,
            },
          });
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
  // The add form is closed until "Add step" opens it; the opener is then replaced by the form's own button.
  await app.getByRole("button", { name: "Add step", exact: true }).click();
  await app.getByLabel("Step name").fill("Boka tid");
  await app.getByRole("button", { name: "Add step" }).click();
  await expect(app.getByRole("checkbox", { name: "Boka tid" })).toBeVisible();
  await expect(app.getByText("Step added.", { exact: true })).toBeVisible();
  await expect(
    app.getByText("No contacts linked to this task.", { exact: true }),
  ).toBeVisible();
  // The link field is closed until its opener is pressed, as the Add step form is.
  await app.getByRole("button", { name: "Link contact", exact: true }).click();
  await app.getByLabel("Link contact").fill("Anna");
  await app
    .getByRole("button", { name: "Anna Andersson", exact: true })
    .click();
  await expect(
    app.getByRole("button", { name: "Anna Andersson", exact: true }),
  ).toHaveCount(1);
  await expect(
    app.getByRole("heading", { level: 3, name: "Contacts" }),
  ).toBeFocused();
  // The link is removed from the Contact row's own menu (a right click, as a long press; Shift+F10): "Remove link". The row has no ⋯.
  await app
    .getByRole("button", { name: "Anna Andersson", exact: true })
    .click({ button: "right" });
  await expect(
    app.getByRole("button", { name: "Remove link", exact: true }),
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
  expect(names).toContain("get_task");
  const create = calls.find((call) => call.name === "create_task_step");
  expect(create?.arguments).toMatchObject({
    task_id: "019f0000-0000-7000-8000-000000000001",
    title: "Boka tid",
  });
  expect(
    calls.find((call) => call.name === "list_contacts")?.arguments,
  ).toMatchObject({ q: "Anna" });
  const link = calls.find((call) => call.name === "link_contact_to_task");
  expect(link?.arguments).toMatchObject({
    task_id: "019f0000-0000-7000-8000-000000000001",
    contact_id: "019f0000-0000-7000-8000-000000000003",
  });
  const dimensions = await app.locator("body").evaluate((body) => ({
    width: body.scrollWidth,
    viewport: window.innerWidth,
  }));
  expect(dimensions.width).toBeLessThanOrEqual(dimensions.viewport);
  expect(failures).toEqual([]);
  expect(networkRequests).toBe(0);
});

test("sandboxed Work board opens from get_work_board, moves a card to In progress after the host answers, without network access", async ({
  page,
}) => {
  const html = readFileSync(
    "../backend/src/sidekick/mcp/apps/sidekick.html",
    "utf8",
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
    const card = (
      id: string,
      title: string,
      status: string,
      version: number,
    ) => ({
      kind: "task",
      id,
      parent_id: null,
      title,
      status,
      priority: "normal",
      due_at: null,
      project_id: null,
      version,
      tags: [],
    });
    const first = card(
      "019f0000-0000-7000-8000-000000000001",
      "Ring Anna om offerten",
      "todo",
      1,
    );
    const second = card(
      "019f0000-0000-7000-8000-000000000002",
      "Skicka faktura",
      "todo",
      1,
    );
    const board: { columns: Record<string, object[]>; next_cursor: null } = {
      columns: {
        todo: [first, second],
        in_progress: [],
        blocked: [],
        completed: [],
      },
      next_cursor: null,
    };
    const movedBoard = {
      columns: {
        todo: [second],
        in_progress: [{ ...first, status: "in_progress", version: 2 }],
        blocked: [],
        completed: [],
      },
      next_cursor: null,
    };
    let current = board;
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
          hostContext: { locale: "sv", theme: "light" },
        });
      else if (message.method === "ui/notifications/initialized") {
        state.initialized = true;
        frame.contentWindow!.postMessage(
          {
            jsonrpc: "2.0",
            method: "ui/notifications/tool-result",
            params: { structuredContent: board },
          },
          "*",
        );
      } else if (message.method === "tools/call") {
        state.calls.push(message.params);
        const { name } = message.params;
        if (name === "update_task") {
          current = movedBoard;
          reply({
            structuredContent: {
              task: { ...first, status: "in_progress", version: 2 },
            },
          });
        } else if (name === "get_work_board")
          reply({ structuredContent: current });
        else reply({ isError: true });
      }
    });
    frame.srcdoc = resource;
  }, html);
  const app = page.frameLocator("iframe");
  // Inline the board is a summary; this host offers no fullscreen, so "Öppna Status" expands it inline.
  await app.getByRole("button", { name: /^Öppna Status/ }).click();
  const todo = app.getByRole("region", { name: "Att göra" });
  await expect(
    todo.getByRole("heading", { level: 3, name: "Att göra (2)" }),
  ).toBeVisible();
  // The card's quick choices open with a long press on its title: the row has no ⋯ or "Flytta" button.
  await todo
    .getByRole("button", { name: "Ring Anna om offerten", exact: true })
    .dispatchEvent("contextmenu");
  await app
    .getByRole("group", { name: "Välj status för Ring Anna om offerten" })
    .getByRole("button", { name: "Pågår", exact: true })
    .click();
  // The card keeps its place in its section while its Undo lasts: the row's meta line says "Pågår", and "Ångra"
  // is a compact secondary button in the row's trailing slot. `.work-agenda-undo` is display: contents, so the button is
  // checked, not the wrapper's box.
  const undoLine = todo.locator(".work-agenda-undo");
  await expect(undoLine.getByRole("status")).toHaveText("Pågår");
  await expect(
    undoLine.getByRole("button", { name: "Ångra", exact: true }),
  ).toBeVisible();
  // The section count says where the card is now: it left "Att göra" at once, while its row stands here
  // for its Ångra.
  await expect(
    todo.getByRole("heading", { level: 3, name: "Att göra (1)" }),
  ).toBeVisible();
  // When the Undo time (UNDO_MS, 15 s) has run out the card leaves the shown list and lands in Pågår.
  await expect(undoLine).toHaveCount(0, { timeout: 20000 });
  await expect(
    todo.getByRole("heading", { level: 3, name: "Att göra (1)" }),
  ).toBeVisible();
  await expect(
    todo.getByRole("button", { name: "Ring Anna om offerten", exact: true }),
  ).toHaveCount(0);
  // The Status view has no chip row any more: every status is a section of its own, so Pågår is in view.
  const doing = app.getByRole("region", { name: "Pågår" });
  await expect(
    doing.getByRole("heading", { level: 3, name: "Pågår (1)" }),
  ).toBeVisible();
  await expect(
    doing.getByRole("button", { name: "Ring Anna om offerten", exact: true }),
  ).toBeVisible();
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
  // The expanded view is the full view: the board reads the tag vocabulary for its filter row, and its To sort row
  // counts the unsorted Tasks.
  expect(state.calls.map((call) => call.name)).toEqual([
    "list_tags",
    "list_tasks",
    "update_task",
    "get_work_board",
  ]);
  expect(state.calls[2]?.arguments).toMatchObject({
    task_id: "019f0000-0000-7000-8000-000000000001",
    version: 1,
    changes: { status: "in_progress" },
  });
  expect(failures).toEqual([]);
  expect(networkRequests).toBe(0);
});

test("sandboxed Work App edits a Contact's note with a stale version first, adds an alias and makes no network request", async ({
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
    const contactId = "019f0000-0000-7000-8000-000000000003";
    const contact = {
      id: contactId,
      display_name: "Anna Andersson",
      context_note: "Vill ha offerten före fredag.",
      email: "anna@example.test",
      phone: null,
      aliases: [] as { id: string; value: string; created_at: string }[],
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
    // Another writer changes the note after the view opened: the server now holds version 2.
    let current: typeof contact = contact;
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
            params: {
              structuredContent: {
                contact,
                projects: { items: [], next_cursor: null },
                tasks: { items: [], next_cursor: null },
              },
            },
          },
          "*",
        );
      } else if (message.method === "tools/call") {
        state.calls.push(message.params);
        const { name, arguments: args } = message.params;
        if (name === "get_contact_context")
          reply({
            structuredContent: {
              contact: current,
              projects: { items: [], next_cursor: null },
              tasks: { items: [], next_cursor: null },
            },
          });
        else if (name === "update_contact") {
          updates++;
          const changes = args.changes as { context_note: string };
          if (updates === 1) {
            current = {
              ...contact,
              context_note: "Annan anteckning",
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
            current = {
              ...current,
              context_note: changes.context_note,
              version: (args.expected_version as number) + 1,
            };
            reply({ structuredContent: { contact: current } });
          }
        } else if (name === "add_contact_alias") {
          current = {
            ...current,
            aliases: [
              {
                id: "019f0000-0000-7000-8000-0000000000f1",
                value: args.value as string,
                created_at: "2026-10-25T10:00:00Z",
              },
            ],
            version: (args.expected_version as number) + 1,
          };
          reply({ structuredContent: { contact: current } });
        } else reply({ isError: true });
      }
    });
    frame.srcdoc = resource;
  }, html);
  const app = page.frameLocator("iframe");
  await app.getByRole("button", { name: "Open", exact: true }).click();
  await expect(
    app.getByRole("heading", { level: 2, name: "Anna Andersson" }),
  ).toBeVisible();
  // Redigera sits in the ⋯ menu of the Back row: the Contact has no pen beside its name.
  await app.getByRole("button", { name: "More options", exact: true }).click();
  await app.getByRole("button", { name: "Edit", exact: true }).click();
  await app.getByLabel("Note", { exact: true }).fill("Ny anteckning");
  await app.getByRole("button", { name: "Save" }).click();
  const banner = app.getByRole("alert");
  await expect(banner).toContainText("This contact was changed elsewhere");
  await expect(banner).toBeFocused();
  await banner.getByRole("button", { name: "Reload" }).click();
  await expect(app.getByRole("alert")).toHaveCount(0);
  await expect(app.getByLabel("Note", { exact: true })).toHaveValue(
    "Ny anteckning",
  );
  await app.getByRole("button", { name: "Save" }).click();
  await expect(app.getByText("Saved", { exact: true })).toBeVisible();
  await expect(app.getByText("Ny anteckning", { exact: true })).toBeVisible();
  // Without nicknames there is no "Nickname:" line. Nicknames are edited in the editor ("More options" > "Edit"),
  // in the "Nicknames" group: the "New nickname" field and its own "Add nickname" button.
  await expect(app.locator("p.work-alias-line")).toHaveCount(0);
  await app.getByRole("button", { name: "More options", exact: true }).click();
  await app.getByRole("button", { name: "Edit", exact: true }).click();
  const aliasPanel = app.getByRole("group", { name: "Nicknames" });
  await aliasPanel.getByLabel("New nickname", { exact: true }).fill("Annan A");
  await aliasPanel
    .getByRole("button", { name: "Add nickname", exact: true })
    .click();
  await expect(app.locator("p.work-alias-line")).toHaveText(
    "Nickname: Annan A",
  );
  await expect(
    aliasPanel.getByRole("button", {
      name: "Remove nickname Annan A",
      exact: true,
    }),
  ).toBeVisible();
  await expect(app.locator("a")).toHaveCount(0);
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
  const writes = calls.filter((call) => call.name === "update_contact");
  expect(writes).toHaveLength(2);
  const [first, second] = writes;
  expect(first?.arguments).toMatchObject({
    contact_id: "019f0000-0000-7000-8000-000000000003",
    expected_version: 1,
    changes: { context_note: "Ny anteckning" },
  });
  expect(second?.arguments).toMatchObject({
    expected_version: 2,
    changes: { context_note: "Ny anteckning" },
  });
  expect(second?.arguments.idempotency_key).not.toBe(
    first?.arguments.idempotency_key,
  );
  expect(calls.map((call) => call.name)).toContain("get_contact_context");
  const alias = calls.find((call) => call.name === "add_contact_alias");
  expect(alias?.arguments).toMatchObject({
    contact_id: "019f0000-0000-7000-8000-000000000003",
    expected_version: 3,
    value: "Annan A",
  });
  expect(failures).toEqual([]);
  expect(networkRequests).toBe(0);
});

test("sandboxed Work App opens the Contact list from list_contacts, searches, opens a Contact and goes back without network access", async ({
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
    const summary = (id: string, display_name: string) => ({
      id,
      display_name,
      archived: false,
      updated_at: "2026-10-24T12:00:00Z",
      version: 1,
    });
    const anna = summary(
      "019f0000-0000-7000-8000-000000000003",
      "Anna Andersson",
    );
    const bo = summary("019f0000-0000-7000-8000-000000000004", "Bo Berg");
    const record = (item: typeof anna) => ({
      ...item,
      email: null,
      phone: null,
      context_note: null,
      aliases: [],
      archived_at: null,
      created_at: "2026-10-24T12:00:00Z",
    });
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
            params: {
              structuredContent: { contacts: [anna, bo], next_cursor: null },
            },
          },
          "*",
        );
      } else if (message.method === "tools/call") {
        state.calls.push(message.params);
        const { name, arguments: args } = message.params;
        if (name === "list_contacts")
          reply({
            structuredContent: {
              contacts: args.q === "Bo" ? [bo] : [anna, bo],
              next_cursor: null,
            },
          });
        else if (name === "get_contact_context")
          reply({
            structuredContent: {
              contact: record(args.contact_id === bo.id ? bo : anna),
              projects: { items: [], next_cursor: null },
              tasks: { items: [], next_cursor: null },
            },
          });
        else reply({ isError: true });
      }
    });
    frame.srcdoc = resource;
  }, html);
  const app = page.frameLocator("iframe");
  await app.getByRole("button", { name: "Show all", exact: true }).click();
  await expect(
    app.getByRole("heading", { level: 2, name: "Contacts" }),
  ).toBeVisible();
  const list = app.getByRole("list", { name: "Contacts" });
  await expect(list.getByRole("listitem")).toHaveCount(2);
  await app.getByLabel("Search contacts").fill("Bo");
  await expect(list.getByRole("listitem")).toHaveCount(1);
  await list.getByRole("button", { name: "Bo Berg", exact: true }).click();
  const contactHeading = app.getByRole("heading", {
    level: 2,
    name: "Bo Berg",
  });
  await expect(contactHeading).toBeVisible();
  await expect(contactHeading).toBeFocused();
  await app.getByRole("button", { name: "Back" }).click();
  await expect(app.getByLabel("Search contacts")).toHaveValue("Bo");
  await expect(list.getByRole("listitem")).toHaveCount(1);
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
  // The tag filter's vocabulary (list_tags) is read once beside the list; it is not navigation.
  const calls = state.calls.filter((call) => call.name !== "list_tags");
  expect(calls.map((call) => call.name)).toEqual([
    "list_contacts",
    "get_contact_context",
  ]);
  expect(calls[0]?.arguments).toMatchObject({
    q: "Bo",
    include_archived: false,
    limit: 25,
    cursor: null,
  });
  expect(calls[1]?.arguments).toMatchObject({
    contact_id: "019f0000-0000-7000-8000-000000000004",
  });
  // The inlined stylesheet must reach the App: the row is a flex navigation row and the frame is padded.
  await expect(
    app
      .locator(".sk-frame__body")
      .evaluate((element) => getComputedStyle(element).paddingTop),
  ).resolves.toBe("8px");
  await expect(
    list
      .getByRole("button", { name: "Bo Berg", exact: true })
      .evaluate((element) => getComputedStyle(element).display),
  ).resolves.toBe("flex");
  // The archive switch sits in the "More options" panel of the Contact list.
  await app.getByRole("button", { name: "More options", exact: true }).click();
  await expect(
    app
      .getByRole("checkbox", { name: "Show archived" })
      .evaluate((element) => getComputedStyle(element).width),
  ).resolves.toBe("20px");
  const dimensions = await app.locator("body").evaluate((body) => ({
    width: body.scrollWidth,
    viewport: window.innerWidth,
  }));
  expect(dimensions.width).toBeLessThanOrEqual(dimensions.viewport);
  expect(failures).toEqual([]);
  expect(networkRequests).toBe(0);
});

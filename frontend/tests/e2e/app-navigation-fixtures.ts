import { expect, type FrameLocator, type Page } from "@playwright/test";
import {
  anna,
  contactContext,
  domainReplies,
  ids,
  ok,
  task,
} from "./sidekick-domain-fixtures";
import {
  deliverToolResult,
  openSimulatedApp,
  readBuiltApp,
  setHostReply,
  simulatedHostState,
  waitForAppInitialized,
} from "./mcp-host-fixture";

// What the app-navigation specs share: how the Sidekick app is opened on the simulated host (see
// mcp-host-fixture.ts, not a real Claude or Android host), the room strip, and the helpers that move between rooms.
// Every spec runs at 375 and 320 px, light and dark.

export const widths = [375, 320] as const;
export const themes = ["light", "dark"] as const;

export type Options = {
  width: number;
  theme: "light" | "dark";
  tool: string;
  result: unknown;
  displayMode?: "inline" | "fullscreen";
  availableDisplayModes?: string[];
  replies?: Record<string, unknown>;
  capabilities?: Record<string, unknown>;
  safeAreaInsets?: { top: number; right: number; bottom: number; left: number };
};

export async function openSidekick(page: Page, options: Options) {
  await page.emulateMedia({ colorScheme: options.theme });
  const opened = await openSimulatedApp(page, {
    resource: readBuiltApp("sidekick", "sv"),
    width: options.width,
    height: 780,
    hostContext: {
      locale: "sv",
      theme: options.theme,
      displayMode: options.displayMode ?? "fullscreen",
      availableDisplayModes: options.availableDisplayModes ?? [
        "inline",
        "fullscreen",
      ],
      toolInfo: { id: 1, tool: { name: options.tool } },
      ...(options.safeAreaInsets
        ? { safeAreaInsets: options.safeAreaInsets }
        : {}),
    },
    hostCapabilities: options.capabilities ?? { serverTools: {}, message: {} },
    replies: { ...domainReplies(), ...options.replies },
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, options.result);
  return opened;
}

export const strip = (app: FrameLocator) =>
  app.getByRole("navigation", { name: "Rum" });
export const room = (app: FrameLocator, name: string) =>
  strip(app).getByRole("button", { name });
export const back = (app: FrameLocator) =>
  app.getByRole("button", { name: /^Tillbaka/ });
export const h2 = (app: FrameLocator, name: string) =>
  app.getByRole("heading", { level: 2, name });

// When the four labels do not fit one row (measured, not by breakpoint) the strip shows the picker
// "Arbete ⌄" instead of its tabs (ui/view-picker.tsx). The tabs then carry data-narrow and are hidden; the picker
// is the strip's only button and its menu holds the four rooms as menuitemradio.
export const narrowTabs = (app: FrameLocator) =>
  strip(app).locator(".sk-rooms__tabs[data-narrow]");
export const picker = (app: FrameLocator) => strip(app).locator(".sk-pick");
export async function isNarrow(app: FrameLocator) {
  await expect(strip(app)).toBeVisible();
  return (await narrowTabs(app).count()) > 0;
}
/** Goes to a room from the strip, as its tab or, in the picker form, through the menu. */
export async function goRoom(app: FrameLocator, name: string) {
  if (await isNarrow(app)) {
    await picker(app).click();
    await app.getByRole("menuitemradio", { name, exact: true }).click();
    return;
  }
  await room(app, name).click();
}
/** The room that is active: aria-current on its tab, or the picker's name when the picker stands in. */
export async function expectCurrentRoom(app: FrameLocator, name: string) {
  if (await isNarrow(app)) {
    await expect(picker(app)).toHaveText(name);
    return;
  }
  await expect(room(app, name)).toHaveAttribute("aria-current", "page");
}
/** Every room is offered: as the four tabs, or in the picker's menu (the menu is closed again). */
export async function expectRoomNames(app: FrameLocator, names: string[]) {
  if (!(await isNarrow(app))) {
    await expect(strip(app).getByRole("button")).toHaveText(names);
    return;
  }
  await picker(app).click();
  await expect(app.getByRole("menuitemradio")).toHaveText(names);
  await app.getByRole("menuitemradio").first().press("Escape");
}

export const doneTask = {
  ...task,
  status: "completed",
  completed_at: "2026-10-24T13:00:00Z",
  version: 2,
};

/** The server remembers that the task is done: every read after this one says so. */
export async function serverRemembersDone(page: Page) {
  await setHostReply(page, "get_task", ok({ task: doneTask }));
  await setHostReply(
    page,
    "get_work_agenda",
    ok({ items: [], filters: {}, next_cursor: null }),
  );
  await setHostReply(page, "get_contact_context", {
    __byArgument: {
      key: "contact_id",
      answers: { [ids.anna]: contactContext(anna, doneTask) },
    },
  });
}

export async function callNames(p: Page) {
  return (await simulatedHostState(p)).calls.map((call) => call.name);
}

export const openTask = (app: FrameLocator) =>
  app.getByRole("button", { name: "Ring Anna om offerten", exact: true });
// A task has no pen. Redigera is the first entry of the ⋯ menu in the Back row (a tap on the title edits too).
export async function editTask(app: FrameLocator) {
  await app.getByRole("button", { name: "Fler val", exact: true }).click();
  await app.getByRole("button", { name: "Redigera" }).click();
}
// The Status view shows every status as a section; the column chip row is gone. Status is a tab of the view tabs.
// When the tabs do not fit (320 px, text at 200 %) the row is hidden and the view picker "Agenda ⌄" stands in
// its place; the views are then menuitemradio in that menu. At 375 px the tab is clicked as before.
export async function chooseView(
  app: FrameLocator,
  name: "Agenda" | "Status" | "Projekt",
  width: number,
) {
  if (width > 340) {
    await app
      .getByRole("group", { name: "Vyer" })
      .getByRole("button", { name })
      .click();
    return;
  }
  await app.locator(".work-view-pick").click();
  await app.getByRole("menuitemradio", { name }).click();
}

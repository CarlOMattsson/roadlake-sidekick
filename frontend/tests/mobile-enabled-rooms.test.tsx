// SIDEKICK_ENABLED_ROOMS on the phone: the server is the one place the rooms are chosen. The app reads `enabledRooms`
// from the pairing (the stored copy) and from the server at the start and on each return, and draws no room that is
// off. The native plugin and the platform here are simulated; this is not a real Android run.
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  declareEnabledRooms,
  enabledRooms,
} from "@/features/mcp-apps/enabled-rooms";
import { CompanionRoomTransport } from "@/mobile/companion-transport";
import { MobileApp } from "@/mobile/mobile-app";
import type { MobilePlatform } from "@/mobile/platform";
import { fakeNative, ok, type FakeNative } from "./helpers/fake-native";

const AGENDA = { items: [], filters: {}, next_cursor: null };

function platformFor(): MobilePlatform & { resume: () => void } {
  let resumed: (() => void) | undefined;
  return {
    onBack: () => () => undefined,
    launchSearch: () => "",
    onLaunchSearch: () => () => undefined,
    onResume: (listener) => {
      resumed = listener;
      return () => {
        resumed = undefined;
      };
    },
    safeAreaInsets: () => ({ top: 0, right: 0, bottom: 0, left: 0 }),
    resume: () => resumed?.(),
  };
}

function phone(stored?: string[], fresh: string[] | "offline" = stored ?? []) {
  const native = fakeNative((request) =>
    request.path === "/companion/v1/work/agenda"
      ? ok(AGENDA)
      : { status: 404, body: { code: "not_found" } },
  );
  native.status.mockResolvedValue({
    paired: true,
    serverHost: "sidekick.example",
    ...(stored ? { enabledRooms: stored } : {}),
  });
  native.deviceStatus.mockImplementation(() =>
    fresh === "offline"
      ? Promise.reject(new Error("offline"))
      : Promise.resolve({
          paired: true,
          ...(fresh.length > 0 ? { enabledRooms: fresh } : {}),
        }),
  );
  return native;
}

function mount(native: FakeNative, platform: MobilePlatform) {
  return render(
    <MobileApp
      transport={new CompanionRoomTransport(native)}
      platform={platform}
      locale="sv"
      native={native}
    />,
  );
}

function stripLabels(): string[] | undefined {
  const strip = screen.queryByRole("navigation", { name: "Rum" });
  return strip
    ? Array.from(strip.querySelectorAll("button")).map((b) => b.textContent)
    : undefined;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  document.documentElement.removeAttribute("style");
});

describe("declareEnabledRooms", () => {
  it("writes, updates and removes the meta the rooms read", () => {
    const doc = document.implementation.createHTMLDocument("");
    declareEnabledRooms(["work", "journal"], doc);
    expect(enabledRooms(doc)).toEqual(["work", "journal"]);
    declareEnabledRooms(["work"], doc);
    expect(doc.querySelectorAll('meta[name="sidekick-rooms"]')).toHaveLength(1);
    expect(enabledRooms(doc)).toEqual(["work"]);
    declareEnabledRooms(undefined, doc);
    expect(enabledRooms(doc)).toHaveLength(5);
  });
});

describe("the rooms of the server in the mobile app", () => {
  it("keeps today's strip when the server does not say (an older server)", async () => {
    mount(phone(undefined, []), platformFor());

    await waitFor(() =>
      expect(stripLabels()).toEqual(["Arbete", "Dagbok", "Inköp"]),
    );
  });

  it("never draws Kontroll: the phone has no routes for it, whatever the server lists", async () => {
    mount(phone(["work", "journal", "control"]), platformFor());

    await waitFor(() => expect(stripLabels()).toEqual(["Arbete", "Dagbok"]));
    expect(enabledRooms()).toEqual(["work", "journal"]);
  });

  it("leaves Kontroll out for an older server that lists no rooms", async () => {
    mount(phone(undefined, []), platformFor());

    await waitFor(() =>
      expect(enabledRooms()).toEqual([
        "work",
        "journal",
        "contacts",
        "shopping",
      ]),
    );
  });

  it("leaves out a room the server switched off, from the stored copy before the server answers", async () => {
    const native = phone(["work", "journal", "contacts", "control"]);
    native.deviceStatus.mockImplementation(() => new Promise(() => undefined));
    mount(native, platformFor());

    await waitFor(() => expect(stripLabels()).toEqual(["Arbete", "Dagbok"]));
  });

  it("draws no strip at all when Arbete is the only room", async () => {
    mount(phone(["work"]), platformFor());

    await screen.findByRole("button", { name: "Agenda" });
    expect(stripLabels()).toBeUndefined();
    expect(screen.queryByRole("button", { name: "Inköp" })).toBeNull();
  });

  it("uses the stored copy when the server cannot be reached", async () => {
    mount(phone(["work", "shopping"], "offline"), platformFor());

    await waitFor(() => expect(stripLabels()).toEqual(["Arbete", "Inköp"]));
  });

  it("picks up a change of the setting from the server", async () => {
    // The phone stored all three; the server now says Inköp is off.
    const native = phone(["work", "journal", "shopping"], ["work", "journal"]);
    mount(native, platformFor());

    await waitFor(() => expect(stripLabels()).toEqual(["Arbete", "Dagbok"]));
    expect(native.deviceStatus).toHaveBeenCalled();
  });

  it("falls back to Arbete, without an error, when the open room is switched off", async () => {
    const user = userEvent.setup();
    const native = phone(["work", "journal", "shopping"]);
    const platform = platformFor();
    mount(native, platform);
    await user.click(await screen.findByRole("button", { name: "Inköp" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Inköp" })).toHaveAttribute(
        "aria-current",
        "page",
      ),
    );

    // Back in the foreground the server says Inköp is off.
    native.deviceStatus.mockResolvedValue({
      paired: true,
      enabledRooms: ["work", "journal"],
    });
    act(() => platform.resume());

    await waitFor(() => expect(stripLabels()).toEqual(["Arbete", "Dagbok"]));
    expect(screen.getByRole("button", { name: "Arbete" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SidekickNativeWeb } from "@/mobile/sidekick-native-web";
import type { PushStatus } from "@/mobile/sidekick-native";
import { CompanionRoomTransport } from "@/mobile/companion-transport";
import { MobileApp } from "@/mobile/mobile-app";
import {
  PUSH_NOTICE_DISMISSED_KEY,
  pushNoticeLabelsEn,
  pushNoticeLabelsSv,
} from "@/mobile/push-notice";
import type { MobilePlatform } from "@/mobile/platform";
import { fakeNative, ok, type FakeNative } from "./helpers/fake-native";

const NO_DISTRIBUTOR: PushStatus = {
  distributor: false,
  registered: false,
  permission: "prompt",
};

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

const AGENDA = { items: [], filters: {}, next_cursor: null };

/** The pairing of a server that sends notifications: only then is the note drawn. */
const PUSH_ON = { pushEnabled: true };

function mount(
  native: FakeNative,
  platform: MobilePlatform,
  locale: "sv" | "en" = "sv",
) {
  return render(
    <MobileApp
      transport={new CompanionRoomTransport(native)}
      platform={platform}
      locale={locale}
      native={native}
    />,
  );
}

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.restoreAllMocks();
  document.documentElement.removeAttribute("style");
});

describe("SidekickNative.pushStatus", () => {
  it("the fake reports a phone where push works", async () => {
    const native = fakeNative(() => ok({}));
    await expect(native.pushStatus()).resolves.toEqual({
      distributor: true,
      registered: true,
      permission: "granted",
    });
  });

  it("the web implementation reports no distributor and nothing registered", async () => {
    await expect(new SidekickNativeWeb().pushStatus()).resolves.toEqual(
      NO_DISTRIBUTOR,
    );
  });
});

describe("the push note in the mobile app", () => {
  it("is not drawn when a distributor is installed", async () => {
    const native = fakeNative(() => ok(AGENDA), PUSH_ON);
    mount(native, platformFor());
    await waitFor(() => expect(native.pushStatus).toHaveBeenCalled());
    expect(screen.queryByText(pushNoticeLabelsSv.missing)).toBeNull();
  });

  it("tells in Swedish to install ntfy when there is no distributor", async () => {
    const native = fakeNative(() => ok(AGENDA), PUSH_ON);
    native.pushStatus.mockResolvedValue(NO_DISTRIBUTOR);
    mount(native, platformFor());
    expect(
      await screen.findByText(
        "Aviseringar levereras av den gratis appen ntfy. Installera den för att få dem.",
      ),
    ).toBeVisible();
  });

  it("has an English text of its own", async () => {
    const native = fakeNative(() => ok(AGENDA), PUSH_ON);
    native.pushStatus.mockResolvedValue(NO_DISTRIBUTOR);
    mount(native, platformFor(), "en");
    expect(await screen.findByText(pushNoticeLabelsEn.missing)).toBeVisible();
    expect(screen.queryByText(pushNoticeLabelsSv.missing)).toBeNull();
  });

  it("draws nothing when the status cannot be read, and the app keeps working", async () => {
    const native = fakeNative(() => ok(AGENDA), PUSH_ON);
    native.pushStatus.mockRejectedValue(new Error("unavailable"));
    mount(native, platformFor());
    await waitFor(() => expect(native.pushStatus).toHaveBeenCalled());
    expect(screen.queryByText(pushNoticeLabelsSv.missing)).toBeNull();
    expect(native.requests.length).toBeGreaterThan(0);
  });

  it("reads again when the app comes back, so the note goes once ntfy is installed", async () => {
    const native = fakeNative(() => ok(AGENDA), PUSH_ON);
    native.pushStatus.mockResolvedValueOnce(NO_DISTRIBUTOR);
    const platform = platformFor();
    mount(native, platform);
    expect(await screen.findByText(pushNoticeLabelsSv.missing)).toBeVisible();

    act(() => platform.resume());
    await waitFor(() =>
      expect(screen.queryByText(pushNoticeLabelsSv.missing)).toBeNull(),
    );
    expect(native.pushStatus).toHaveBeenCalledTimes(2);
  });

  it("offers ntfy's store page with a button, in both languages", async () => {
    const user = userEvent.setup();
    const native = fakeNative(() => ok(AGENDA), PUSH_ON);
    native.pushStatus.mockResolvedValue(NO_DISTRIBUTOR);
    mount(native, platformFor());
    await user.click(await screen.findByRole("button", { name: "Hämta ntfy" }));
    expect(native.openNtfyInstall).toHaveBeenCalledTimes(1);
    cleanup();

    const english = fakeNative(() => ok(AGENDA), PUSH_ON);
    english.pushStatus.mockResolvedValue(NO_DISTRIBUTOR);
    mount(english, platformFor(), "en");
    expect(
      await screen.findByRole("button", { name: "Get ntfy" }),
    ).toBeVisible();
  });

  it("does not break when the store cannot open", async () => {
    const user = userEvent.setup();
    const native = fakeNative(() => ok(AGENDA), PUSH_ON);
    native.pushStatus.mockResolvedValue(NO_DISTRIBUTOR);
    native.openNtfyInstall.mockRejectedValue(new Error("unavailable"));
    mount(native, platformFor());
    await user.click(await screen.findByRole("button", { name: "Hämta ntfy" }));
    expect(screen.getByText(pushNoticeLabelsSv.missing)).toBeVisible();
  });

  it("is not drawn when the server sends no notifications, or has not said", async () => {
    for (const pushEnabled of [false, undefined]) {
      const native = fakeNative(
        () => ok(AGENDA),
        pushEnabled === undefined ? {} : { pushEnabled },
      );
      native.pushStatus.mockResolvedValue(NO_DISTRIBUTOR);
      mount(native, platformFor());
      await waitFor(() => expect(native.deviceStatus).toHaveBeenCalled());
      expect(screen.queryByText(pushNoticeLabelsSv.missing)).toBeNull();
      cleanup();
    }
  });

  it("goes away for good with Dölj", async () => {
    const user = userEvent.setup();
    const native = fakeNative(() => ok(AGENDA), PUSH_ON);
    native.pushStatus.mockResolvedValue(NO_DISTRIBUTOR);
    mount(native, platformFor());
    await user.click(await screen.findByRole("button", { name: "Dölj" }));
    expect(screen.queryByText(pushNoticeLabelsSv.missing)).toBeNull();
    expect(localStorage.getItem(PUSH_NOTICE_DISMISSED_KEY)).toBe("1");
    cleanup();

    const again = fakeNative(() => ok(AGENDA), PUSH_ON);
    again.pushStatus.mockResolvedValue(NO_DISTRIBUTOR);
    mount(again, platformFor());
    await waitFor(() => expect(again.requests.length).toBeGreaterThan(0));
    expect(screen.queryByText(pushNoticeLabelsSv.missing)).toBeNull();
  });

  it("keeps the Swedish and English texts in step", () => {
    expect(Object.keys(pushNoticeLabelsEn)).toEqual(
      Object.keys(pushNoticeLabelsSv),
    );
  });
});

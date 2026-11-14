// The owner's time zone on the phone: the server says it with the device answers, the native side keeps it in the
// pairing, and the app declares it as the backend declares it in the app document, so every date the phone draws is
// in the owner's zone (never Stockholm's default, never the phone's own). The native plugin and the platform here are
// simulated; this is not a real Android run.
import { cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  appTimeZone,
  declareOwnerTimeZone,
  DEFAULT_OWNER_TIMEZONE,
} from "@/features/mcp-apps/app-timezone";
import { CompanionRoomTransport } from "@/mobile/companion-transport";
import { MobileApp } from "@/mobile/mobile-app";
import type { MobilePlatform } from "@/mobile/platform";
import { fakeNative, ok } from "@tests/helpers/fake-native";

const platform: MobilePlatform = {
  onBack: () => () => undefined,
  launchSearch: () => "",
  onLaunchSearch: () => () => undefined,
  onResume: () => () => undefined,
  safeAreaInsets: () => ({ top: 0, right: 0, bottom: 0, left: 0 }),
};

function phone(stored: string | undefined, fresh: string | undefined) {
  const native = fakeNative((request) =>
    request.path === "/companion/v1/work/agenda"
      ? ok({ items: [], filters: {}, next_cursor: null })
      : { status: 404, body: { code: "not_found" } },
  );
  native.status.mockResolvedValue({
    paired: true,
    serverHost: "sidekick.example",
    ...(stored ? { ownerTimeZone: stored } : {}),
  });
  native.deviceStatus.mockResolvedValue({
    paired: true,
    ...(fresh ? { ownerTimeZone: fresh } : {}),
  });
  return native;
}

function mount(native: ReturnType<typeof phone>) {
  return render(
    <MobileApp
      transport={new CompanionRoomTransport(native)}
      platform={platform}
      locale="sv"
      native={native}
    />,
  );
}

afterEach(() => {
  cleanup();
  declareOwnerTimeZone(undefined);
  vi.restoreAllMocks();
});

describe("declareOwnerTimeZone", () => {
  it("writes, updates and removes the meta appTimeZone reads", () => {
    const doc = document.implementation.createHTMLDocument("");
    expect(appTimeZone(doc)).toBe(DEFAULT_OWNER_TIMEZONE);
    declareOwnerTimeZone("America/New_York", doc);
    expect(appTimeZone(doc)).toBe("America/New_York");
    declareOwnerTimeZone("Asia/Tokyo", doc);
    expect(
      doc.querySelectorAll('meta[name="sidekick-owner-timezone"]'),
    ).toHaveLength(1);
    expect(appTimeZone(doc)).toBe("Asia/Tokyo");
    declareOwnerTimeZone(undefined, doc);
    expect(appTimeZone(doc)).toBe(DEFAULT_OWNER_TIMEZONE);
  });
});

describe("the owner's zone in the mobile app", () => {
  it("declares the stored zone first and the server's fresh one after it", async () => {
    mount(phone("America/New_York", "Asia/Tokyo"));
    await waitFor(() => expect(appTimeZone()).toBe("Asia/Tokyo"));
  });

  it("keeps the stored zone for a phone without network", async () => {
    const native = phone("America/New_York", undefined);
    native.deviceStatus.mockRejectedValue(new Error("offline"));
    mount(native);
    await waitFor(() => expect(appTimeZone()).toBe("America/New_York"));
  });

  it("falls back to the default when the server never said a zone", async () => {
    const native = phone(undefined, undefined);
    mount(native);
    await waitFor(() => expect(native.deviceStatus).toHaveBeenCalled());
    expect(appTimeZone()).toBe(DEFAULT_OWNER_TIMEZONE);
  });

  it("removes the declaration with the app", async () => {
    const { unmount } = mount(phone("America/New_York", "America/New_York"));
    await waitFor(() => expect(appTimeZone()).toBe("America/New_York"));
    unmount();
    expect(appTimeZone()).toBe(DEFAULT_OWNER_TIMEZONE);
  });
});

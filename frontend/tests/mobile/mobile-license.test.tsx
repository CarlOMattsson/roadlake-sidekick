import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { licenseLabelsSv } from "@/features/mcp-apps/license-labels";
import { readLicense } from "@/features/mcp-apps/license-state";
import type { NativeRequest, NativeResponse } from "@/mobile/sidekick-native";
import { CompanionRoomTransport } from "@/mobile/companion-transport";
import { MobileApp } from "@/mobile/mobile-app";
import type { MobilePlatform } from "@/mobile/platform";
import { fakeNative, ok } from "@tests/helpers/fake-native";

// The phone has no app document: it reads the license display state from GET /companion/v1/license and saves a key
// with PUT /companion/v1/license (the backend's contract, see docs/decisions/log.md D-083). Fixtures only; no server.
const AGENDA = {
  items: [
    {
      kind: "task",
      id: "019f0000-0000-7000-8000-0000000000a1",
      title: "Skicka offert",
      status: "todo",
      due_at: null,
      version: 1,
      agenda_group: "overdue",
    },
  ],
  filters: {},
  next_cursor: null,
};

function platform(): MobilePlatform {
  return {
    onBack: () => () => undefined,
    launchSearch: () => "",
    onLaunchSearch: () => () => undefined,
    onResume: () => () => undefined,
    safeAreaInsets: () => undefined,
  };
}

afterEach(() => {
  cleanup();
  document.head.innerHTML = "";
});

describe("the companion transport", () => {
  it("sends set_license_key as PUT /companion/v1/license with the key in the body only", async () => {
    const native = fakeNative(() =>
      ok({ state: "licensed", licensee: "Alex", accepted: true }),
    );
    const transport = new CompanionRoomTransport(native);
    expect(transport.supportsTool("set_license_key")).toBe(true);
    await expect(
      transport.call("set_license_key", { key: " KEY-1 " }),
    ).resolves.toEqual({ state: "licensed", licensee: "Alex", accepted: true });
    expect(native.requests).toEqual([
      { method: "PUT", path: "/companion/v1/license", body: { key: "KEY-1" } },
    ]);
  });

  it("refuses an empty key or another argument before anything is sent", async () => {
    const native = fakeNative(() => ok({}));
    const transport = new CompanionRoomTransport(native);
    await expect(
      transport.call("set_license_key", { key: "  " }),
    ).rejects.toMatchObject({ code: "validation_error" });
    await expect(
      transport.call("set_license_key", { key: "k", other: 1 }),
    ).rejects.toMatchObject({ code: "validation_error" });
    expect(native.requests).toEqual([]);
  });
});

function app(handler: (request: NativeRequest) => NativeResponse) {
  const native = fakeNative(handler);
  render(
    <MobileApp
      transport={new CompanionRoomTransport(native)}
      platform={platform()}
      locale="sv"
      native={native}
    />,
  );
  return native;
}

describe("the phone", () => {
  it("declares the state the server answers, so the coin stands; a tap opens Inställningar with the row last, focused", async () => {
    const user = userEvent.setup();
    const native = app((request) => {
      if (request.path === "/companion/v1/work/agenda") return ok(AGENDA);
      if (request.path === "/companion/v1/license")
        return ok({ state: "unlicensed" });
      return { status: 404, body: { code: "not_found" } };
    });
    await screen.findByText("Skicka offert");
    expect(
      native.requests.some(
        (request) =>
          request.method === "GET" && request.path === "/companion/v1/license",
      ),
    ).toBe(true);
    const coin = await screen.findByRole("button", {
      name: licenseLabelsSv.mark,
    });
    await user.click(coin);
    const lead = await screen.findByText(licenseLabelsSv.unlicensedNoShop);
    const settings = lead.closest(".mobile-settings");
    expect(settings).not.toBeNull();
    // Last in the settings, after "Den här telefonen".
    expect(settings?.lastElementChild?.contains(lead)).toBe(true);
    await waitFor(() => expect(document.activeElement).toBe(lead));
    // The key goes through the companion transport: the field is offered.
    expect(
      screen.getByRole("button", { name: licenseLabelsSv.enterKey }),
    ).toBeTruthy();
  });

  it("draws nothing when the server has no license route (older server)", async () => {
    app((request) =>
      request.path === "/companion/v1/work/agenda"
        ? ok(AGENDA)
        : { status: 404, body: { code: "not_found" } },
    );
    await screen.findByText("Skicka offert");
    await waitFor(() => expect(readLicense()).toBeUndefined());
    expect(
      screen.queryByRole("button", { name: licenseLabelsSv.mark }),
    ).toBeNull();
  });

  it("draws no coin when licensed", async () => {
    app((request) => {
      if (request.path === "/companion/v1/work/agenda") return ok(AGENDA);
      return ok({
        state: "licensed",
        licensee: "Alex Exempel",
        expires: "2099-01-01",
      });
    });
    await screen.findByText("Skicka offert");
    await waitFor(() => expect(readLicense()?.state).toBe("licensed"));
    expect(
      screen.queryByRole("button", { name: licenseLabelsSv.mark }),
    ).toBeNull();
  });
});

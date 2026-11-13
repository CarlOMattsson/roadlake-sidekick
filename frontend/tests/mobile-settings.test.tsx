import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { TestPushResult } from "@/mobile/sidekick-native";
import { CompanionRoomTransport } from "@/mobile/companion-transport";
import { MobileApp } from "@/mobile/mobile-app";
import { PairingGate } from "@/mobile/pairing-gate";
import type { MobilePlatform } from "@/mobile/platform";
import { SettingsPanel } from "@/mobile/settings-panel";
import { settingsLabelsEn, settingsLabelsSv } from "@/mobile/settings-labels";
import { fakeNative, ok, type FakeNative } from "./helpers/fake-native";
import type { NativeRequest } from "@/mobile/sidekick-native";

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

function answer(request: NativeRequest) {
  if (request.path === "/companion/v1/work/agenda") return ok(AGENDA);
  return { status: 404, body: { code: "not_found" } };
}

/** 8 Nov 2026, noon in Stockholm: the fake's pairedAt is 1 Nov, its expiresAt 15 Nov. */
const NOW = new Date("2026-11-08T11:00:00Z");

function platformFor(): MobilePlatform & { pressBack: () => boolean } {
  let back: (() => boolean) | undefined;
  return {
    onBack: (handler) => {
      back = handler;
      return () => {
        back = undefined;
      };
    },
    launchSearch: () => "",
    onLaunchSearch: () => () => undefined,
    onResume: () => () => undefined,
    safeAreaInsets: () => undefined,
    pressBack: () => back?.() ?? false,
  };
}

function panel(
  native: FakeNative,
  options: {
    locale?: "sv" | "en";
    from?: "work" | "journal" | "shopping";
    onUnpaired?: (revoked: boolean) => void;
  } = {},
) {
  const onBack = vi.fn();
  const onUnpaired = options.onUnpaired ?? vi.fn();
  render(
    <SettingsPanel
      native={native}
      locale={options.locale ?? "sv"}
      from={options.from ?? "work"}
      refreshKey={0}
      onBack={onBack}
      onUnpaired={onUnpaired}
      now={NOW}
    />,
  );
  return { onBack, onUnpaired };
}

afterEach(() => {
  cleanup();
  document.documentElement.removeAttribute("style");
});

describe("SettingsPanel: Aviseringar", () => {
  it.each([
    [
      { distributor: true, registered: true, permission: "granted" },
      "Aviseringar är på.",
    ],
    [
      { distributor: false, registered: false, permission: "prompt" },
      "Aviseringar levereras av den gratis appen ntfy. Installera den för att få dem.",
    ],
    [
      { distributor: true, registered: true, permission: "denied" },
      "Aviseringar är avstängda för Sidekick. Slå på dem i telefonens inställningar.",
    ],
    [
      { distributor: true, registered: false, permission: "granted" },
      "Aviseringar kopplas in…",
    ],
    [
      { distributor: true, registered: true, permission: "prompt" },
      "Aviseringar kopplas in…",
    ],
  ] as const)("says the push state %o in plain words", async (state, text) => {
    const native = fakeNative(answer);
    native.pushStatus.mockResolvedValue(state);
    panel(native);
    expect(await screen.findByText(text)).toBeVisible();
  });

  it("explains the lock screen in one sentence (D-079)", async () => {
    panel(fakeNative(answer));
    expect(
      await screen.findByText(
        "Låsskärmen visar titlar bara om telefonen tillåter känsligt innehåll där.",
      ),
    ).toBeVisible();
  });

  it.each([
    [
      "notifications are not allowed",
      { distributor: true, registered: true, permission: "denied" },
      undefined,
    ],
    [
      "ntfy is missing",
      { distributor: false, registered: false, permission: "prompt" },
      undefined,
    ],
    [
      "the server sends none",
      { distributor: true, registered: true, permission: "granted" },
      false,
    ],
  ] as const)(
    "leaves the lock screen sentence out when %s",
    async (_case, state, pushEnabled) => {
      const native = fakeNative(answer, { pushEnabled });
      native.pushStatus.mockResolvedValue(state);
      panel(native);
      await screen.findByText("Den här telefonen");
      await waitFor(() => expect(native.pushStatus).toHaveBeenCalled());
      await screen.findByRole("button", { name: "Skicka testavisering" });
      expect(screen.queryByText(/Låsskärmen visar titlar/)).toBeNull();
    },
  );

  it("shows a failed read with a retry that reads again", async () => {
    const user = userEvent.setup();
    const native = fakeNative(answer);
    native.pushStatus.mockRejectedValueOnce(new Error("unknown"));
    panel(native);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Aviseringarnas status kunde inte läsas.",
    );
    await user.click(screen.getByRole("button", { name: "Försök igen" }));
    expect(await screen.findByText("Aviseringar är på.")).toBeVisible();
    expect(native.pushStatus).toHaveBeenCalledTimes(2);
  });

  it.each<[TestPushResult, string]>([
    [{ outcome: "queued" }, "Testavisering skickad."],
    [
      { outcome: "rate_limited", retryAfterSeconds: 1500 },
      "Högst 5 testaviseringar i timmen. Försök igen om 25 min.",
    ],
    [
      { outcome: "rate_limited", retryAfterSeconds: 20 },
      "Högst 5 testaviseringar i timmen. Försök igen om 1 min.",
    ],
    [
      { outcome: "rate_limited" },
      "Högst 5 testaviseringar i timmen. Försök igen senare.",
    ],
    [{ outcome: "no_subscription" }, "Aviseringar är inte kopplade än."],
    [{ outcome: "disabled" }, "Aviseringar är avstängda på servern."],
    [{ outcome: "unpaired" }, "Telefonen är inte kopplad längre."],
  ])("answers the test push %o calmly", async (result, text) => {
    const user = userEvent.setup();
    const native = fakeNative(answer);
    native.sendTestPush.mockResolvedValue(result);
    panel(native);

    await user.click(
      await screen.findByRole("button", { name: "Skicka testavisering" }),
    );

    expect(await screen.findByText(text)).toBeVisible();
    // A calm line, never an alert.
    expect(screen.getByText(text).closest("[role=status]")).not.toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(native.sendTestPush).toHaveBeenCalledTimes(1);
  });

  it("says when no answer came (offline) as a failure line", async () => {
    const user = userEvent.setup();
    const native = fakeNative(answer);
    native.sendTestPush.mockResolvedValue({ outcome: "offline" });
    panel(native);

    await user.click(
      await screen.findByRole("button", { name: "Skicka testavisering" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Servern kunde inte nås. Försök igen när telefonen har nät.",
    );
  });

  it("says the test could not be sent when the plugin call fails", async () => {
    const user = userEvent.setup();
    const native = fakeNative(answer);
    native.sendTestPush.mockRejectedValue(new Error("unknown"));
    panel(native);

    await user.click(
      await screen.findByRole("button", { name: "Skicka testavisering" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Testaviseringen kunde inte skickas.",
    );
  });

  it("sends once while a test is under way", async () => {
    const user = userEvent.setup();
    const native = fakeNative(answer);
    let finish: (result: TestPushResult) => void = () => undefined;
    native.sendTestPush.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    panel(native);

    await user.click(
      await screen.findByRole("button", { name: "Skicka testavisering" }),
    );
    const busy = screen.getByRole("button", { name: "Skickar…" });
    expect(busy).toHaveAttribute("aria-disabled", "true");
    await user.click(busy);
    expect(native.sendTestPush).toHaveBeenCalledTimes(1);

    finish({ outcome: "queued" });
    expect(await screen.findByText("Testavisering skickad.")).toBeVisible();
  });
});

describe("SettingsPanel: Aviseringar, one button for each fixable state", () => {
  it("offers ntfy's store page when no distributor is installed, then reads again", async () => {
    const user = userEvent.setup();
    const native = fakeNative(answer);
    native.pushStatus.mockResolvedValueOnce({
      distributor: false,
      registered: false,
      permission: "prompt",
    });
    panel(native);

    await user.click(await screen.findByRole("button", { name: "Hämta ntfy" }));

    expect(native.openNtfyInstall).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(native.pushStatus).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("Aviseringar är på.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Hämta ntfy" })).toBeNull();
  });

  it("opens the phone's notification settings when the permission was refused", async () => {
    const user = userEvent.setup();
    const native = fakeNative(answer);
    native.pushStatus.mockResolvedValue({
      distributor: true,
      registered: true,
      permission: "denied",
    });
    panel(native);

    await user.click(
      await screen.findByRole("button", {
        name: "Öppna aviseringsinställningar",
      }),
    );

    expect(native.openNotificationSettings).toHaveBeenCalledTimes(1);
  });

  it("asks for the permission again while the question is still open", async () => {
    const user = userEvent.setup();
    const native = fakeNative(answer);
    native.pushStatus.mockResolvedValue({
      distributor: true,
      registered: false,
      permission: "prompt",
    });
    panel(native, { locale: "en" });

    await user.click(
      await screen.findByRole("button", { name: "Allow notifications" }),
    );

    expect(native.requestNotificationPermission).toHaveBeenCalledTimes(1);
  });

  it("offers nothing when push works, or while it is being set up with the permission given", async () => {
    const native = fakeNative(answer);
    native.pushStatus.mockResolvedValue({
      distributor: true,
      registered: false,
      permission: "granted",
    });
    panel(native);
    expect(await screen.findByText("Aviseringar kopplas in…")).toBeVisible();
    for (const name of [
      labelOf("getNtfy"),
      labelOf("openSettings"),
      labelOf("allow"),
    ]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
  });

  it("reads the buttons in both languages from the same set", () => {
    expect(Object.keys(settingsLabelsEn.push)).toEqual(
      Object.keys(settingsLabelsSv.push),
    );
    expect(settingsLabelsEn.push.getNtfy).toBe("Get ntfy");
  });

  it("still reads again when the screen could not open", async () => {
    const user = userEvent.setup();
    const native = fakeNative(answer);
    native.pushStatus.mockResolvedValueOnce({
      distributor: false,
      registered: false,
      permission: "prompt",
    });
    native.openNtfyInstall.mockRejectedValue(new Error("unavailable"));
    panel(native);

    await user.click(await screen.findByRole("button", { name: "Hämta ntfy" }));

    await waitFor(() => expect(native.pushStatus).toHaveBeenCalledTimes(2));
  });
});

function labelOf(key: "getNtfy" | "openSettings" | "allow") {
  return settingsLabelsSv.push[key];
}

describe("SettingsPanel: Den här telefonen", () => {
  it("shows the name, when it was paired and that the sign-in renews before it expires", async () => {
    panel(fakeNative(answer));

    expect(await screen.findByText("Samsung")).toBeVisible();
    expect(screen.getByText("Server: sidekick.example")).toBeVisible();
    expect(screen.getByText("Kopplad sedan sön 1 nov")).toBeVisible();
    expect(
      screen.getByText("Kopplingen förnyas automatiskt innan den går ut."),
    ).toBeVisible();
    expect(screen.queryByText(/Giltig till/)).toBeNull();
  });

  it("reads in English with the same parts", async () => {
    panel(fakeNative(answer), { locale: "en" });

    expect(await screen.findByText("Connected since Sun 1 Nov")).toBeVisible();
    expect(screen.getByText("Server: sidekick.example")).toBeVisible();
    expect(
      screen.getByText(
        "The connection renews automatically before it expires.",
      ),
    ).toBeVisible();
    expect(screen.queryByText(/Valid until/)).toBeNull();
    expect(
      screen.getByRole("button", { name: "Disconnect this phone" }),
    ).toBeVisible();
  });

  it("names an unnamed phone and leaves out dates it does not have", async () => {
    const native = fakeNative(answer);
    native.deviceStatus.mockResolvedValue({ paired: true });
    panel(native);

    expect(await screen.findByText("Telefon utan namn")).toBeVisible();
    expect(screen.queryByText(/^Kopplad sedan/)).toBeNull();
    expect(
      screen.getByText("Kopplingen förnyas automatiskt innan den går ut."),
    ).toBeVisible();
  });

  it("shows a failed read with a retry", async () => {
    const user = userEvent.setup();
    const native = fakeNative(answer);
    native.deviceStatus.mockRejectedValueOnce(new Error("unknown"));
    panel(native);

    expect(
      await screen.findByText("Telefonens koppling kunde inte läsas."),
    ).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Försök igen" }));
    expect(await screen.findByText("Samsung")).toBeVisible();
  });

  it("asks before it disconnects: the first press sends nothing, Avbryt gives the focus back", async () => {
    const user = userEvent.setup();
    const native = fakeNative(answer);
    const { onUnpaired } = panel(native);

    const first = await screen.findByRole("button", {
      name: "Koppla från den här telefonen",
    });
    await user.click(first);

    expect(native.unpair).not.toHaveBeenCalled();
    expect(
      screen.getByText(
        "Sidekick töms på telefonen. För att koppla igen behövs en ny kopplingskod.",
      ),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Koppla från" })).toHaveFocus();

    await user.click(screen.getByRole("button", { name: "Avbryt" }));

    expect(native.unpair).not.toHaveBeenCalled();
    expect(onUnpaired).not.toHaveBeenCalled();
    expect(
      screen.getByRole("button", { name: "Koppla från den här telefonen" }),
    ).toHaveFocus();
  });

  it("disconnects after the confirmation and hands over with the server's answer", async () => {
    const user = userEvent.setup();
    const native = fakeNative(answer);
    native.unpair.mockResolvedValue({ serverRevoked: false });
    const { onUnpaired } = panel(native);

    await user.click(
      await screen.findByRole("button", {
        name: "Koppla från den här telefonen",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Koppla från" }));

    expect(native.unpair).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(onUnpaired).toHaveBeenCalledWith(false));
  });

  it("says so when disconnecting failed, and stays", async () => {
    const user = userEvent.setup();
    const native = fakeNative(answer);
    native.unpair.mockRejectedValue(new Error("unknown"));
    const { onUnpaired } = panel(native);

    await user.click(
      await screen.findByRole("button", {
        name: "Koppla från den här telefonen",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Koppla från" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Telefonen kunde inte kopplas från.",
    );
    expect(onUnpaired).not.toHaveBeenCalled();
  });
});

describe("SettingsPanel: Back", () => {
  it("is named after the room the settings were opened from", async () => {
    const user = userEvent.setup();
    const { onBack } = panel(fakeNative(answer), { from: "journal" });

    expect(
      screen.queryByRole("button", { name: "Tillbaka till Arbete" }),
    ).toBeNull();
    await user.click(
      screen.getByRole("button", { name: "Tillbaka till Dagbok" }),
    );
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it("is named in English after the room in an English app", () => {
    panel(fakeNative(answer), { from: "shopping", locale: "en" });

    // The accessible name's prefix follows the document's meta (BackHeader); the label is the panel's language.
    expect(screen.getByRole("button", { name: /Shopping$/ })).toBeVisible();
  });
});

describe("the settings in the mobile app", () => {
  function app(native: FakeNative, platform = platformFor()) {
    render(
      <PairingGate native={native} platform={platform} locale="sv">
        <MobileApp
          transport={new CompanionRoomTransport(native)}
          platform={platform}
          locale="sv"
          native={native}
        />
      </PairingGate>,
    );
    return platform;
  }

  async function openSettings(user: ReturnType<typeof userEvent.setup>) {
    await screen.findByText("Skicka offert");
    await user.click(screen.getByRole("button", { name: "Fler val" }));
    // In Kontroll's place: the companion has no list_trash, so Kontroll is not offered.
    expect(screen.queryByRole("button", { name: "Kontroll" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Inställningar" }));
    await screen.findByRole("heading", { name: "Inställningar" });
  }

  it("opens from ⋯ and closes with ‹ Arbete, giving the focus back to ⋯", async () => {
    const user = userEvent.setup();
    app(fakeNative(answer));

    await openSettings(user);
    expect(await screen.findByText("Aviseringar är på.")).toBeVisible();
    expect(screen.queryByText("Skicka offert")).not.toBeVisible();

    await user.click(
      screen.getByRole("button", { name: "Tillbaka till Arbete" }),
    );

    expect(screen.queryByRole("heading", { name: "Inställningar" })).toBeNull();
    expect(screen.getByText("Skicka offert")).toBeVisible();
    expect(screen.getByRole("button", { name: "Fler val" })).toHaveFocus();
  });

  it("closes with system Back before the shell gets it", async () => {
    const user = userEvent.setup();
    const platform = app(fakeNative(answer));
    await openSettings(user);

    let went = false;
    await waitFor(() => {
      went = platform.pressBack();
    });
    expect(went).toBe(true);
    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { name: "Inställningar" }),
      ).toBeNull(),
    );
    expect(screen.getByText("Skicka offert")).toBeVisible();
  });

  it("after disconnecting, the pairing form is back with a line that says so", async () => {
    const user = userEvent.setup();
    const native = fakeNative(answer);
    app(native);
    await openSettings(user);

    await user.click(
      await screen.findByRole("button", {
        name: "Koppla från den här telefonen",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Koppla från" }));

    expect(
      await screen.findByRole("heading", { name: "Koppla till din Sidekick" }),
    ).toBeVisible();
    expect(screen.getByText("Telefonen är frånkopplad.")).toBeVisible();
    expect(screen.queryByText("Skicka offert")).toBeNull();
  });

  it("asks the owner to revoke on the server when the server could not confirm", async () => {
    const user = userEvent.setup();
    const native = fakeNative(answer);
    native.unpair.mockResolvedValue({ serverRevoked: false });
    app(native);
    await openSettings(user);

    await user.click(
      await screen.findByRole("button", {
        name: "Koppla från den här telefonen",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Koppla från" }));

    expect(
      await screen.findByText(
        "Telefonen är frånkopplad, men servern kunde inte bekräfta det. Be den som sköter servern spärra telefonen, eller koppla den på nytt.",
      ),
    ).toBeVisible();
  });
});

describe("the settings exist only in the mobile app", () => {
  it("are not offered by a mobile shell without the native plugin", async () => {
    const user = userEvent.setup();
    render(
      <MobileApp
        transport={new CompanionRoomTransport(fakeNative(answer))}
        platform={platformFor()}
        locale="sv"
      />,
    );
    await screen.findByText("Skicka offert");
    await user.click(screen.getByRole("button", { name: "Fler val" }));

    expect(screen.queryByRole("button", { name: "Inställningar" })).toBeNull();
  });

  it("have the same texts in Swedish and English (locale parity)", () => {
    expect(Object.keys(settingsLabelsEn).sort()).toEqual(
      Object.keys(settingsLabelsSv).sort(),
    );
    expect(Object.keys(settingsLabelsEn.outcomes).sort()).toEqual(
      Object.keys(settingsLabelsSv.outcomes).sort(),
    );
  });
});

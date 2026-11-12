import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useContext } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CompanionRoomTransport } from "@/mobile/companion-transport";
import { MobileApp } from "@/mobile/mobile-app";
import {
  PairingGate,
  PairingGateContext,
  READING_NOTE_AFTER_MS,
} from "@/mobile/pairing-gate";
import { pairingLabelsEn, pairingLabelsSv } from "@/mobile/pairing-labels";
import type { PairingLink } from "@/mobile/pairing-link";
import type { MobilePlatform } from "@/mobile/platform";
import { fakeNative, nativeError, ok } from "./helpers/fake-native";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

const CODE = "rspair_abcdefghijklmnop";
const link: PairingLink = { serverUrl: "https://other.example", code: CODE };

function platformFor(options: { launchLink?: PairingLink } = {}) {
  let deliver: ((next: PairingLink) => void) | undefined;
  const platform: MobilePlatform = {
    onBack: () => () => undefined,
    launchSearch: () => "",
    onLaunchSearch: () => () => undefined,
    onResume: () => () => undefined,
    safeAreaInsets: () => undefined,
    pairingLink: () => options.launchLink,
    onPairingLink: (listener) => {
      deliver = listener;
      return () => {
        deliver = undefined;
      };
    },
  };
  return { platform, open: (next: PairingLink) => act(() => deliver?.(next)) };
}

/** The app inside the gate, reduced to what it reads from the gate's context. */
function Probe() {
  const gate = useContext(PairingGateContext);
  return (
    <div>
      <p>Appen</p>
      {gate?.linkNotice ? (
        <button onClick={gate.dismissLinkNotice}>{gate.linkNotice.text}</button>
      ) : null}
    </div>
  );
}

describe("B1: pairing a phone that is already paired", () => {
  async function pairWith(
    native: ReturnType<typeof fakeNative>,
    locale: "sv" | "en" = "sv",
  ) {
    const user = userEvent.setup();
    render(
      <PairingGate
        native={native}
        platform={platformFor().platform}
        locale={locale}
      >
        <p>Appen</p>
      </PairingGate>,
    );
    await user.type(
      await screen.findByLabelText(
        locale === "en" ? "Server address" : "Serveradress",
      ),
      "https://sidekick.example",
    );
    await user.type(
      screen.getByLabelText(locale === "en" ? "Pairing code" : "Kopplingskod"),
      CODE,
    );
    await user.click(
      screen.getByRole("button", {
        name: locale === "en" ? "Connect" : "Koppla",
      }),
    );
  }

  it("reads the status again and opens the app when the phone is in fact paired", async () => {
    const native = fakeNative(() => ok({}), {
      paired: false,
      pair: () => {
        throw nativeError("already_paired");
      },
    });
    native.status
      .mockResolvedValueOnce({ paired: false })
      .mockResolvedValue({ paired: true, serverHost: "sidekick.example" });

    await pairWith(native);

    expect(await screen.findByText("Appen")).toBeTruthy();
    expect(
      screen.queryByText(pairingLabelsSv.errors.already_paired),
    ).toBeNull();
    expect(native.status).toHaveBeenCalledTimes(2);
  });

  it("keeps the sentence as the reserve when the status says the phone is not paired", async () => {
    const native = fakeNative(() => ok({}), {
      paired: false,
      pair: () => {
        throw nativeError("already_paired");
      },
    });

    await pairWith(native, "en");

    expect(
      await screen.findByText(pairingLabelsEn.errors.already_paired),
    ).toBeTruthy();
    expect(screen.queryByText("Appen")).toBeNull();
    expect(screen.getByRole("button", { name: "Connect" })).toBeEnabled();
  });

  it("keeps the sentence when the status cannot be read", async () => {
    const native = fakeNative(() => ok({}), {
      paired: false,
      pair: () => {
        throw nativeError("already_paired");
      },
    });
    native.status
      .mockResolvedValueOnce({ paired: false })
      .mockRejectedValue(new Error("unreadable"));

    await pairWith(native);

    expect(
      await screen.findByText(pairingLabelsSv.errors.already_paired),
    ).toBeTruthy();
  });
});

describe("B2: a pairing link on a phone that is already paired", () => {
  it("says so once in the app, with the host the phone is paired to, and can be dismissed", async () => {
    const user = userEvent.setup();
    const { platform, open } = platformFor();
    render(
      <PairingGate
        native={fakeNative(() => ok({}))}
        platform={platform}
        locale="sv"
      >
        <Probe />
      </PairingGate>,
    );
    await screen.findByText("Appen");
    open(link);

    const notice = await screen.findByRole("button", {
      name: "Telefonen är redan kopplad till sidekick.example. Koppla från i Inställningar för att byta.",
    });
    await user.click(notice);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("says so for a link that opened the cold start of a paired phone, in English", async () => {
    render(
      <PairingGate
        native={fakeNative(() => ok({}))}
        platform={platformFor({ launchLink: link }).platform}
        locale="en"
      >
        <Probe />
      </PairingGate>,
    );

    expect(
      await screen.findByText(
        "This phone is already connected to sidekick.example. Disconnect in Settings to switch.",
      ),
    ).toBeTruthy();
  });

  it("says nothing when no link came", async () => {
    render(
      <PairingGate
        native={fakeNative(() => ok({}))}
        platform={platformFor().platform}
        locale="sv"
      >
        <Probe />
      </PairingGate>,
    );
    await screen.findByText("Appen");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("is drawn by the mobile app as a status line", async () => {
    const native = fakeNative(() => ok({}));
    const { platform, open } = platformFor();
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
    await waitFor(() => expect(native.status).toHaveBeenCalled());
    open(link);
    open(link);

    const line = await screen.findByText(/Telefonen är redan kopplad till/);
    expect(line.closest("[role=status]")).toHaveClass("mobile-link-notice");
    await userEvent.click(screen.getByRole("button", { name: "Stäng" }));
    expect(screen.queryByText(/Telefonen är redan kopplad till/)).toBeNull();
  });
});

describe("B3: the cold start of a paired phone", () => {
  it("shows no heading while the pairing is read, and no text before the delay", () => {
    vi.useFakeTimers();
    const native = fakeNative(() => ok({}));
    native.status.mockReturnValue(new Promise(() => undefined));
    render(
      <PairingGate
        native={native}
        platform={platformFor().platform}
        locale="sv"
      >
        <p>Appen</p>
      </PairingGate>,
    );

    expect(screen.queryByRole("heading")).toBeNull();
    expect(screen.queryByText(pairingLabelsSv.loading)).toBeNull();

    act(() => {
      vi.advanceTimersByTime(READING_NOTE_AFTER_MS + 1);
    });
    expect(screen.getByText(pairingLabelsSv.loading)).toBeTruthy();
    expect(screen.queryByRole("heading")).toBeNull();
  });

  it("covers the screen with the shell's background until the rooms are known", () => {
    const native = fakeNative(() => ok({}));
    native.status.mockReturnValue(new Promise(() => undefined));
    const { platform } = platformFor();
    const { container } = render(
      <MobileApp
        transport={new CompanionRoomTransport(native)}
        platform={platform}
        locale="en"
        native={native}
      />,
    );

    expect(container.querySelector(".mobile-shell--loading")).not.toBeNull();
  });
});

describe("locale parity of the new texts", () => {
  it("has every new text in both languages", () => {
    for (const labels of [pairingLabelsSv, pairingLabelsEn]) {
      expect(labels.linkIgnored).toContain("{host}");
      expect(labels.linkIgnoredNoHost).not.toContain("{host}");
      expect(labels.dismiss.length).toBeGreaterThan(0);
    }
  });
});

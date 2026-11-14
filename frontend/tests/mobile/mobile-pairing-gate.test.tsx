import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { nativeErrorCode } from "@/mobile/sidekick-native";
import { PairingGate } from "@/mobile/pairing-gate";
import { withScheme } from "@/mobile/pairing-validation";
import {
  pairingErrorMessage,
  pairingLabelsEn,
  pairingLabelsSv,
} from "@/mobile/pairing-labels";
import type { MobilePlatform } from "@/mobile/platform";
import { fakeNative, nativeError, ok } from "@tests/helpers/fake-native";

afterEach(cleanup);

function platformWithBack() {
  const handlers: Array<() => boolean> = [];
  const platform: MobilePlatform = {
    onBack: (handler) => {
      handlers.push(handler);
      return () => void handlers.splice(handlers.indexOf(handler), 1);
    },
    launchSearch: () => "",
    onLaunchSearch: () => () => undefined,
    onResume: () => () => undefined,
    safeAreaInsets: () => undefined,
  };
  return { platform, back: () => handlers.at(-1)?.() ?? false, handlers };
}

function mount(
  native: ReturnType<typeof fakeNative>,
  locale: "sv" | "en" = "sv",
) {
  const { platform, ...rest } = platformWithBack();
  render(
    <PairingGate native={native} platform={platform} locale={locale}>
      <p>Appen</p>
    </PairingGate>,
  );
  return rest;
}

describe("PairingGate", () => {
  it("mounts the app at once when the phone is already paired", async () => {
    const native = fakeNative(() => ok({}));
    mount(native);
    expect(await screen.findByText("Appen")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Koppla" })).toBeNull();
  });

  it("shows the form when unpaired and pairs with a scheme-completed address", async () => {
    const user = userEvent.setup();
    const native = fakeNative(() => ok({}), { paired: false });
    mount(native);

    // The title also shows while the pairing is read; the form is there once its field is.
    await user.type(
      await screen.findByLabelText("Serveradress"),
      "sidekick.example",
    );
    await user.type(
      screen.getByLabelText("Kopplingskod"),
      "  rspair_abcdefghijklmnop ",
    );
    await user.click(screen.getByRole("button", { name: "Koppla" }));

    expect(await screen.findByText("Appen")).toBeTruthy();
    expect(native.pair).toHaveBeenCalledWith({
      serverUrl: "https://sidekick.example",
      pairingSecret: "rspair_abcdefghijklmnop",
    });
  });

  it("masks the pairing code, reveals it on request, and still takes a pasted code", async () => {
    const user = userEvent.setup();
    const native = fakeNative(() => ok({}), { paired: false });
    mount(native);

    const field = await screen.findByLabelText("Kopplingskod");
    expect(field).toHaveAttribute("type", "password");
    // Not an SMS code: no one-time-code autofill.
    expect(field).not.toHaveAttribute("autocomplete", "one-time-code");

    await user.click(field);
    await user.paste("rspair_abcdefghijklmnop");
    expect(field).toHaveValue("rspair_abcdefghijklmnop");

    const reveal = screen.getByRole("button", { name: "Visa koden" });
    expect(reveal).toHaveAttribute("aria-pressed", "false");
    await user.click(reveal);
    expect(field).toHaveAttribute("type", "text");
    await user.click(screen.getByRole("button", { name: "Dölj koden" }));
    expect(field).toHaveAttribute("type", "password");
  });

  it("does not call pair while a field is empty", async () => {
    const user = userEvent.setup();
    const native = fakeNative(() => ok({}), { paired: false });
    mount(native);

    await screen.findByLabelText("Serveradress");
    await user.type(screen.getByLabelText("Serveradress"), "sidekick.example");
    await user.click(screen.getByRole("button", { name: "Koppla" }));
    expect(native.pair).not.toHaveBeenCalled();
  });

  it("shows the server's closed code as a calm line and keeps what was typed", async () => {
    const user = userEvent.setup();
    const native = fakeNative(() => ok({}), {
      paired: false,
      pair: () => {
        throw nativeError("pairing_invalid");
      },
    });
    mount(native);

    await user.type(
      await screen.findByLabelText("Serveradress"),
      "https://sidekick.example",
    );
    await user.type(
      screen.getByLabelText("Kopplingskod"),
      "rspair_abcdefghijklmnop",
    );
    await user.click(screen.getByRole("button", { name: "Koppla" }));

    expect((await screen.findByRole("alert")).textContent).toBe(
      pairingLabelsSv.errors.pairing_invalid,
    );
    expect(screen.getByLabelText("Serveradress")).toHaveValue(
      "https://sidekick.example",
    );
    expect(screen.queryByText("Appen")).toBeNull();
    // It can be tried again.
    expect(screen.getByRole("button", { name: "Koppla" })).toBeEnabled();
  });

  it("returns to the form with a line when the server refuses the credential", async () => {
    const native = fakeNative(() => ok({}));
    mount(native);
    await screen.findByText("Appen");

    act(() => native.losePairing());

    await screen.findByRole("heading", { name: "Koppla till din Sidekick" });
    expect(screen.getByText(pairingLabelsSv.lost)).toBeTruthy();
    expect(screen.queryByText("Appen")).toBeNull();
  });

  it("offers a retry when the pairing cannot be read", async () => {
    const user = userEvent.setup();
    const native = fakeNative(() => ok({}));
    native.status.mockRejectedValueOnce(nativeError("internal"));
    mount(native);

    await screen.findByText(pairingLabelsSv.statusFailed);
    await user.click(screen.getByRole("button", { name: "Försök igen" }));
    expect(await screen.findByText("Appen")).toBeTruthy();
  });

  it("leaves the app on Back: the form has no layer of its own", async () => {
    const native = fakeNative(() => ok({}), { paired: false });
    const { back, handlers } = mount(native);
    await screen.findByLabelText("Serveradress");
    await waitFor(() => expect(handlers).toHaveLength(1));
    // false: the platform leaves the app.
    expect(back()).toBe(false);
  });

  it("speaks English when the app language is English", async () => {
    const native = fakeNative(() => ok({}), { paired: false });
    mount(native, "en");
    // The title also shows while the pairing is read; wait for the form itself.
    expect(await screen.findByLabelText("Server address")).toBeTruthy();
    expect(
      screen.getByRole("heading", { name: "Connect to your Sidekick" }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Connect" })).toBeTruthy();
  });
});

describe("pairing helpers", () => {
  it("completes an address without a scheme and leaves a full one alone", () => {
    expect(withScheme("sidekick.example")).toBe("https://sidekick.example");
    expect(withScheme(" http://10.0.2.2:8101 ")).toBe("http://10.0.2.2:8101");
    expect(withScheme("   ")).toBe("");
  });

  it("keeps Swedish and English texts in step (locale parity)", () => {
    expect(Object.keys(pairingLabelsEn).sort()).toEqual(
      Object.keys(pairingLabelsSv).sort(),
    );
    expect(Object.keys(pairingLabelsEn.errors).sort()).toEqual(
      Object.keys(pairingLabelsSv.errors).sort(),
    );
  });

  it("maps any unknown code to the general line", () => {
    expect(pairingErrorMessage(pairingLabelsSv, "something_new")).toBe(
      pairingLabelsSv.errors.fallback,
    );
    expect(pairingErrorMessage(pairingLabelsSv, "fallback")).toBe(
      pairingLabelsSv.errors.fallback,
    );
    expect(pairingErrorMessage(pairingLabelsSv, "network")).toBe(
      pairingLabelsSv.errors.network,
    );
  });

  it("gives an already paired phone its own line in both locales", () => {
    expect(pairingErrorMessage(pairingLabelsSv, "already_paired")).toBe(
      "Telefonen är redan kopplad. Koppla från först om du vill koppla om.",
    );
    expect(pairingErrorMessage(pairingLabelsEn, "already_paired")).toBe(
      "This phone is already connected. Disconnect first to connect again.",
    );
  });

  it("reads only a closed code from a plugin rejection", () => {
    expect(nativeErrorCode(nativeError("pairing_invalid"))).toBe(
      "pairing_invalid",
    );
    expect(nativeErrorCode(new Error("boom"))).toBe("unknown");
    expect(nativeErrorCode({ code: "Has Spaces" })).toBe("unknown");
    expect(nativeErrorCode(null)).toBe("unknown");
  });
});

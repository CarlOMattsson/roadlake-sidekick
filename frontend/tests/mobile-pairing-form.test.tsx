import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PairingGate } from "@/mobile/pairing-gate";
import { pairingLabelsEn, pairingLabelsSv } from "@/mobile/pairing-labels";
import { parsePairingLink, type PairingLink } from "@/mobile/pairing-link";
import {
  codeProblem,
  hostOf,
  serverProblem,
} from "@/mobile/pairing-validation";
import type { MobilePlatform } from "@/mobile/platform";
import { fakeNative, nativeError, ok } from "./helpers/fake-native";

afterEach(cleanup);

const CODE = "rspair_abcdefghijklmnop";

function mount(
  native: ReturnType<typeof fakeNative>,
  options: {
    locale?: "sv" | "en";
    launchLink?: PairingLink;
  } = {},
) {
  let deliver: ((link: PairingLink) => void) | undefined;
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
  render(
    <PairingGate
      native={native}
      platform={platform}
      locale={options.locale ?? "sv"}
    >
      <p>Appen</p>
    </PairingGate>,
  );
  return { open: (link: PairingLink) => act(() => deliver?.(link)) };
}

describe("pairing form validation", () => {
  it("flags both empty fields by the fields and pairs nothing", async () => {
    const user = userEvent.setup();
    const native = fakeNative(() => ok({}), { paired: false });
    mount(native);

    await user.click(await screen.findByRole("button", { name: "Koppla" }));

    const server = screen.getByLabelText("Serveradress");
    const code = screen.getByLabelText("Kopplingskod");
    expect(server).toHaveAttribute("aria-invalid", "true");
    expect(code).toHaveAttribute("aria-invalid", "true");
    expect(server).toHaveFocus();
    expect(
      screen.getByText(pairingLabelsSv.fieldErrors.serverRequired),
    ).toHaveAttribute("id", server.getAttribute("aria-describedby"));
    expect(code.getAttribute("aria-describedby")).toContain(
      screen.getByText(pairingLabelsSv.fieldErrors.codeRequired).id,
    );
    expect(native.pair).not.toHaveBeenCalled();
  });

  it("flags a malformed address on the address field and a short code on the code field", async () => {
    const user = userEvent.setup();
    const native = fakeNative(() => ok({}), { paired: false });
    mount(native);

    await user.type(await screen.findByLabelText("Serveradress"), "side kick");
    await user.type(screen.getByLabelText("Kopplingskod"), "xy");
    await user.click(screen.getByRole("button", { name: "Koppla" }));

    expect(
      screen.getByText(pairingLabelsSv.fieldErrors.serverInvalid),
    ).toBeTruthy();
    expect(
      screen.getByText(pairingLabelsSv.fieldErrors.codeShort),
    ).toBeTruthy();
    expect(native.pair).not.toHaveBeenCalled();

    // Typing in a field clears its line.
    await user.type(screen.getByLabelText("Serveradress"), ".example");
    expect(
      screen.queryByText(pairingLabelsSv.fieldErrors.serverInvalid),
    ).toBeNull();
    expect(
      screen.getByText(pairingLabelsSv.fieldErrors.codeShort),
    ).toBeTruthy();
  });

  it("shows the server's refusal of the code by the code field", async () => {
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
      "sidekick.example",
    );
    await user.type(screen.getByLabelText("Kopplingskod"), CODE);
    await user.click(screen.getByRole("button", { name: "Koppla" }));

    const line = await screen.findByText(
      pairingLabelsSv.errors.pairing_invalid,
    );
    expect(
      screen.getByLabelText("Kopplingskod").getAttribute("aria-describedby"),
    ).toContain(line.id);
    expect(screen.getByLabelText("Kopplingskod")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
  });

  it("submits from the keyboard: Enter in the code field is the IME's go action", async () => {
    const user = userEvent.setup();
    const native = fakeNative(() => ok({}), { paired: false });
    mount(native);

    await user.type(
      await screen.findByLabelText("Serveradress"),
      "sidekick.example",
    );
    expect(screen.getByLabelText("Kopplingskod")).toHaveAttribute(
      "enterkeyhint",
      "go",
    );
    await user.type(screen.getByLabelText("Kopplingskod"), `${CODE}{Enter}`);

    expect(await screen.findByText("Appen")).toBeTruthy();
    expect(native.pair).toHaveBeenCalledWith({
      serverUrl: "https://sidekick.example",
      pairingSecret: CODE,
    });
  });

  it("scrolls the button into view when a field takes focus", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const scroll = vi.fn();
    const original = Object.getOwnPropertyDescriptor(
      Element.prototype,
      "scrollIntoView",
    );
    Element.prototype.scrollIntoView = scroll;
    try {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      mount(fakeNative(() => ok({}), { paired: false }));
      await user.click(await screen.findByLabelText("Kopplingskod"));
      await act(() => vi.advanceTimersByTimeAsync(300));
      expect(scroll).toHaveBeenCalled();
    } finally {
      if (original)
        Object.defineProperty(Element.prototype, "scrollIntoView", original);
      else Reflect.deleteProperty(Element.prototype, "scrollIntoView");
      vi.useRealTimers();
    }
  });

  it("explains where the code comes from, in the phone's language", async () => {
    const native = fakeNative(() => ok({}), { paired: false });
    mount(native, { locale: "en" });

    await screen.findByLabelText("Server address");
    expect(screen.getByText(pairingLabelsEn.helpTitle)).toBeTruthy();
    expect(screen.getByText(pairingLabelsEn.helpBody)).toBeTruthy();
  });
});

describe("pairing link", () => {
  const link: PairingLink = {
    serverUrl: "https://sidekick.example",
    code: CODE,
  };

  it("asks before pairing and never pairs by itself", async () => {
    const native = fakeNative(() => ok({}), { paired: false });
    mount(native, { launchLink: link });

    expect(
      await screen.findByRole("heading", {
        name: "Koppla till sidekick.example?",
      }),
    ).toBeTruthy();
    expect(native.pair).not.toHaveBeenCalled();
    expect(screen.queryByText("Appen")).toBeNull();
  });

  it("pairs with the link's values once the user confirms", async () => {
    const user = userEvent.setup();
    const native = fakeNative(() => ok({}), { paired: false });
    mount(native, { launchLink: link });

    await user.click(await screen.findByRole("button", { name: "Koppla" }));

    expect(await screen.findByText("Appen")).toBeTruthy();
    expect(native.pair).toHaveBeenCalledWith({
      serverUrl: "https://sidekick.example",
      pairingSecret: CODE,
    });
  });

  it("drops the link and shows an empty form when the user cancels", async () => {
    const user = userEvent.setup();
    const native = fakeNative(() => ok({}), { paired: false });
    mount(native, { launchLink: link });

    await user.click(await screen.findByRole("button", { name: "Avbryt" }));

    expect(screen.getByLabelText("Serveradress")).toHaveValue("");
    expect(screen.getByLabelText("Kopplingskod")).toHaveValue("");
    expect(native.pair).not.toHaveBeenCalled();
  });

  it("asks when a link arrives while the form is open", async () => {
    const native = fakeNative(() => ok({}), { paired: false });
    const { open } = mount(native);
    await screen.findByLabelText("Serveradress");

    open(link);

    expect(
      await screen.findByRole("heading", {
        name: "Koppla till sidekick.example?",
      }),
    ).toBeTruthy();
    expect(native.pair).not.toHaveBeenCalled();
  });

  it("goes back to the filled-in form with the refusal by the code field", async () => {
    const user = userEvent.setup();
    const native = fakeNative(() => ok({}), {
      paired: false,
      pair: () => {
        throw nativeError("pairing_invalid");
      },
    });
    mount(native, { launchLink: link });

    await user.click(await screen.findByRole("button", { name: "Koppla" }));

    await screen.findByText(pairingLabelsSv.errors.pairing_invalid);
    await waitFor(() =>
      expect(screen.getByLabelText("Serveradress")).toHaveValue(
        "https://sidekick.example",
      ),
    );
  });

  it("ignores a link on a phone that is already paired", async () => {
    const native = fakeNative(() => ok({}));
    mount(native, { launchLink: link });

    expect(await screen.findByText("Appen")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: /Koppla till/ })).toBeNull();
  });
});

describe("parsePairingLink", () => {
  const encoded = encodeURIComponent("https://sidekick.example");

  it("reads the server and the code", () => {
    expect(
      parsePairingLink(`sidekick://pair?server=${encoded}&code=${CODE}`),
    ).toEqual({ serverUrl: "https://sidekick.example", code: CODE });
  });

  it.each([
    undefined,
    "",
    "sidekick://open?view=today",
    `sidekick://pair?code=${CODE}`,
    `sidekick://pair?server=${encoded}`,
    `sidekick://pair?server=${encoded}&server=${encoded}&code=${CODE}`,
    `sidekick://pair?server=${encodeURIComponent("https://s.example/mcp")}&code=${CODE}`,
    `sidekick://pair?server=${encodeURIComponent("http://s.example")}&code=${CODE}`,
    `sidekick://pair?server=${encoded}&code=short`,
    `sidekick://pair?server=${encoded}&code=${"a".repeat(2000)}`,
    `https://pair?server=${encoded}&code=${CODE}`,
  ])("is no link: %s", (url) => {
    expect(parsePairingLink(url)).toBeUndefined();
  });
});

describe("validation and language helpers", () => {
  it("accepts an origin and refuses everything else", () => {
    expect(serverProblem("sidekick.example")).toBeUndefined();
    expect(serverProblem("https://sidekick.example:8443/")).toBeUndefined();
    expect(serverProblem("http://10.0.2.2:8101")).toBeUndefined();
    expect(serverProblem("  ")).toBe("required");
    expect(serverProblem("sidekick")).toBeUndefined();
    expect(serverProblem("https://sidekick")).toBeUndefined();
    expect(serverProblem("https://nas:8443")).toBeUndefined();
    expect(serverProblem("side kick")).toBe("invalid");
    expect(serverProblem("http://nas")).toBe("invalid");
    expect(serverProblem("https://nas/path")).toBe("invalid");
    expect(serverProblem("https://user@nas")).toBe("invalid");
    expect(serverProblem("http://sidekick.example")).toBe("invalid");
    expect(serverProblem("https://sidekick.example/mcp")).toBe("invalid");
    expect(serverProblem("https://user@sidekick.example")).toBe("invalid");
    expect(serverProblem("https://sidekick.example?x=1")).toBe("invalid");
  });

  it("checks the code like the phone does (16 to 128 of A-Z a-z 0-9 _ -)", () => {
    expect(codeProblem(CODE)).toBeUndefined();
    expect(codeProblem("")).toBe("required");
    expect(codeProblem("rspair_short")).toBe("short");
    expect(codeProblem(`${CODE} extra`)).toBe("invalid");
    expect(codeProblem("a".repeat(129))).toBe("invalid");
  });

  it("names the host to confirm", () => {
    expect(hostOf("sidekick.example:8443")).toBe("sidekick.example:8443");
    expect(hostOf("::")).toBe("");
  });

  it("keeps the field and confirmation texts in step (locale parity)", () => {
    expect(Object.keys(pairingLabelsEn.fieldErrors).sort()).toEqual(
      Object.keys(pairingLabelsSv.fieldErrors).sort(),
    );
    for (const labels of [pairingLabelsSv, pairingLabelsEn])
      expect(labels.confirmTitle).toContain("{host}");
  });
});

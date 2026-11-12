import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  APP_LANGUAGE_KEY,
  chooseAppLanguage,
  startAppLanguage,
} from "@/mobile/app-language";
import { LanguageSwitch } from "@/mobile/language-switch";
import { LAST_SERVER_KEY, PairingGate } from "@/mobile/pairing-gate";
import { pairingLabelsEn, pairingLabelsSv } from "@/mobile/pairing-labels";
import type { MobilePlatform } from "@/mobile/platform";
import { SettingsPanel } from "@/mobile/settings-panel";
import { settingsLabelsEn, settingsLabelsSv } from "@/mobile/settings-labels";
import {
  licenseLabelsEn,
  licenseLabelsSv,
} from "@/features/mcp-apps/license-labels";
import { fakeNative, ok } from "./helpers/fake-native";

const CODE = "rspair_abcdefghijklmnop";

function freshDocument(meta?: string): Document {
  const doc = document.implementation.createHTMLDocument("app");
  if (meta) {
    const tag = doc.createElement("meta");
    tag.name = "sidekick-app-locale";
    tag.content = meta;
    doc.head.append(tag);
  }
  return doc;
}

const metaOf = (doc: Document) =>
  doc
    .querySelector<HTMLMetaElement>('meta[name="sidekick-app-locale"]')
    ?.getAttribute("content");

const platform: MobilePlatform = {
  onBack: () => () => undefined,
  launchSearch: () => "",
  onLaunchSearch: () => () => undefined,
  onResume: () => () => undefined,
  safeAreaInsets: () => undefined,
  pairingLink: () => undefined,
  onPairingLink: () => () => undefined,
};

afterEach(() => {
  cleanup();
  localStorage.clear();
});

describe("the app language on the phone (ua-3)", () => {
  it("starts in Swedish when nothing is chosen and the bundle says nothing", () => {
    const doc = freshDocument();
    expect(startAppLanguage(doc)).toBe("sv");
    expect(metaOf(doc)).toBe("sv");
  });

  it("starts in the bundle's language when nothing is chosen", () => {
    const doc = freshDocument("en");
    expect(startAppLanguage(doc)).toBe("en");
  });

  it("starts in the owner's choice over the bundle's, and writes it into the meta", () => {
    localStorage.setItem(APP_LANGUAGE_KEY, "en");
    const doc = freshDocument("sv");
    expect(startAppLanguage(doc)).toBe("en");
    expect(metaOf(doc)).toBe("en");
  });

  it("ignores a stored value that is no language of the app", () => {
    localStorage.setItem(APP_LANGUAGE_KEY, "de");
    expect(startAppLanguage(freshDocument())).toBe("sv");
  });

  it("keeps a choice, so the next start opens in it", () => {
    const doc = freshDocument("sv");
    chooseAppLanguage("en", doc);
    expect(localStorage.getItem(APP_LANGUAGE_KEY)).toBe("en");
    expect(metaOf(doc)).toBe("en");
    expect(startAppLanguage(freshDocument("sv"))).toBe("en");
  });
});

describe("LanguageSwitch", () => {
  it("names each language in itself, presses the chosen one and reports only a change", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<LanguageSwitch locale="sv" onChange={onChange} label="Språk" />);
    const group = screen.getByRole("group", { name: "Språk" });
    const sv = within(group).getByRole("button", { name: "Svenska" });
    const en = within(group).getByRole("button", { name: "English" });
    expect(sv).toHaveAttribute("aria-pressed", "true");
    expect(sv).toHaveAttribute("lang", "sv");
    expect(en).toHaveAttribute("aria-pressed", "false");
    expect(en).toHaveAttribute("lang", "en");
    await user.click(sv);
    expect(onChange).not.toHaveBeenCalled();
    await user.click(en);
    expect(onChange).toHaveBeenCalledWith("en");
  });

  it("is in Inställningar, first, in both languages", async () => {
    const user = userEvent.setup();
    const onLocale = vi.fn();
    const { rerender } = render(
      <SettingsPanel
        native={fakeNative(() => ok({}))}
        locale="sv"
        from="work"
        refreshKey={0}
        onBack={vi.fn()}
        onUnpaired={vi.fn()}
        onLocale={onLocale}
      />,
    );
    expect(screen.getByRole("heading", { name: "Språk" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "English" }));
    expect(onLocale).toHaveBeenCalledWith("en");
    rerender(
      <SettingsPanel
        native={fakeNative(() => ok({}))}
        locale="en"
        from="work"
        refreshKey={0}
        onBack={vi.fn()}
        onUnpaired={vi.fn()}
        onLocale={onLocale}
      />,
    );
    expect(screen.getByRole("heading", { name: "Language" })).toBeVisible();
    expect(screen.getByRole("button", { name: "English" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("is a small switch on the pairing screen", async () => {
    const user = userEvent.setup();
    const onLocale = vi.fn();
    render(
      <PairingGate
        native={fakeNative(() => ok({}), { paired: false })}
        platform={platform}
        locale="sv"
        onLocale={onLocale}
      >
        <p>Appen</p>
      </PairingGate>,
    );
    const group = await screen.findByRole("group", { name: "Språk" });
    expect(group).toHaveClass("mobile-language--compact");
    await user.click(within(group).getByRole("button", { name: "English" }));
    expect(onLocale).toHaveBeenCalledWith("en");
  });
});

describe("the pairing form remembers the last server (ua-17)", () => {
  it("fills in the address of the last pairing", async () => {
    const user = userEvent.setup();
    const first = fakeNative(() => ok({}), { paired: false });
    render(
      <PairingGate native={first} platform={platform} locale="sv">
        <p>Appen</p>
      </PairingGate>,
    );
    await user.type(
      await screen.findByLabelText("Serveradress"),
      "sidekick.example",
    );
    await user.type(screen.getByLabelText("Kopplingskod"), `${CODE}{Enter}`);
    expect(await screen.findByText("Appen")).toBeTruthy();
    expect(localStorage.getItem(LAST_SERVER_KEY)).toBe(
      "https://sidekick.example",
    );
    cleanup();

    render(
      <PairingGate
        native={fakeNative(() => ok({}), { paired: false })}
        platform={platform}
        locale="sv"
      >
        <p>Appen</p>
      </PairingGate>,
    );
    expect(await screen.findByLabelText("Serveradress")).toHaveValue(
      "https://sidekick.example",
    );
    expect(screen.getByLabelText("Kopplingskod")).toHaveValue("");
  });
});

describe("Aviseringar when the server sends none (ua-6)", () => {
  it("says so plainly, offers no fix and keeps the test button off", async () => {
    const user = userEvent.setup();
    const native = fakeNative(() => ok({}), { pushEnabled: false });
    native.pushStatus.mockResolvedValue({
      distributor: false,
      registered: false,
      permission: "prompt",
    });
    render(
      <SettingsPanel
        native={native}
        locale="sv"
        from="work"
        refreshKey={0}
        onBack={vi.fn()}
        onUnpaired={vi.fn()}
      />,
    );
    expect(
      await screen.findByText(settingsLabelsSv.push.serverOff),
    ).toBeVisible();
    expect(
      screen.queryByRole("button", { name: settingsLabelsSv.push.getNtfy }),
    ).toBeNull();
    const test = screen.getByRole("button", {
      name: settingsLabelsSv.sendTest,
    });
    expect(test).toHaveAttribute("aria-disabled", "true");
    await user.click(test);
    expect(native.sendTestPush).not.toHaveBeenCalled();
  });
});

describe("locale parity of the new words", () => {
  it("has a language heading and a server-off line in both languages", () => {
    expect(settingsLabelsSv.languageHeading).toBe("Språk");
    expect(settingsLabelsEn.languageHeading).toBe("Language");
    expect(settingsLabelsEn.push.serverOff).not.toBe(
      settingsLabelsSv.push.serverOff,
    );
    expect(Object.keys(settingsLabelsEn.push).sort()).toEqual(
      Object.keys(settingsLabelsSv.push).sort(),
    );
    expect(Object.keys(pairingLabelsEn).sort()).toEqual(
      Object.keys(pairingLabelsSv).sort(),
    );
    expect(pairingLabelsSv.language).toBe("Språk");
    expect(pairingLabelsEn.language).toBe("Language");
  });

  it("names the license coin's text in both languages (ua-7)", () => {
    expect(licenseLabelsSv.footFree).toBe("Gratisversion");
    expect(licenseLabelsEn.footFree).toBe("Free version");
    expect(licenseLabelsSv.footExpired).toBe("Licensen har gått ut");
    expect(licenseLabelsEn.footExpired).toBe("License expired");
  });
});

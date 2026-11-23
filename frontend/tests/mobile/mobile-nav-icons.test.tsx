import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CompanionRoomTransport } from "@/mobile/companion-transport";
import { APP_NAV_ICONS_KEY, type AppNavIcons } from "@/mobile/app-nav-icons";
import { MobileApp } from "@/mobile/mobile-app";
import { PairingGate } from "@/mobile/pairing-gate";
import type { MobilePlatform } from "@/mobile/platform";
import { SettingsPanel } from "@/mobile/settings-panel";
import { settingsLabelsEn, settingsLabelsSv } from "@/mobile/settings-labels";
import { fakeNative, ok, type FakeNative } from "@tests/helpers/fake-native";
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

function platformFor(): MobilePlatform {
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
  localStorage.clear();
  document.head.innerHTML = "";
});

describe("the room bar choice in Inställningar", () => {
  const LOCALES = [
    ["sv", settingsLabelsSv],
    ["en", settingsLabelsEn],
  ] as const;

  function panel(
    locale: "sv" | "en",
    navIcons?: {
      value: AppNavIcons;
      onChange: (next: AppNavIcons) => void;
    },
  ) {
    render(
      <SettingsPanel
        native={fakeNative(() => ok({}))}
        locale={locale}
        from="work"
        refreshKey={0}
        onBack={vi.fn()}
        onUnpaired={vi.fn()}
        navIcons={navIcons}
      />,
    );
  }

  it("names the group and its options differently in the two languages", () => {
    expect(settingsLabelsSv.stripHeading).toBe("Rumsraden");
    expect(settingsLabelsEn.stripHeading).toBe("Room bar");
    expect(settingsLabelsSv.strip).toEqual({
      off: "Text",
      label: "Båda",
      only: "Ikoner",
    });
    expect(settingsLabelsEn.strip).toEqual({
      off: "Text",
      label: "Both",
      only: "Icons",
    });
  });

  it.each(LOCALES)(
    "draws three options in %s with the current one pressed",
    (locale, labels) => {
      panel(locale, { value: "label", onChange: vi.fn() });
      expect(
        screen.getByRole("heading", { name: labels.stripHeading }),
      ).toBeVisible();
      const group = screen.getByRole("group", { name: labels.stripHeading });
      const buttons = within(group).getAllByRole("button");
      expect(buttons.map((button) => button.textContent)).toEqual([
        labels.strip.off,
        labels.strip.label,
        labels.strip.only,
      ]);
      expect(
        buttons.filter(
          (button) => button.getAttribute("aria-pressed") === "true",
        ),
      ).toEqual([buttons[1]]);
    },
  );

  it.each(LOCALES)(
    "reports the option pressed in %s, and nothing for the pressed one",
    async (locale, labels) => {
      const user = userEvent.setup();
      const onChange = vi.fn();
      panel(locale, { value: "off", onChange });
      const group = screen.getByRole("group", { name: labels.stripHeading });
      await user.click(
        within(group).getByRole("button", { name: labels.strip.off }),
      );
      expect(onChange).not.toHaveBeenCalled();
      await user.click(
        within(group).getByRole("button", { name: labels.strip.only }),
      );
      expect(onChange).toHaveBeenLastCalledWith("only");
      await user.click(
        within(group).getByRole("button", { name: labels.strip.label }),
      );
      expect(onChange).toHaveBeenLastCalledWith("label");
      expect(onChange).toHaveBeenCalledTimes(2);
    },
  );

  it.each(LOCALES)(
    "has no such group without the prop in %s",
    (locale, labels) => {
      panel(locale);
      expect(
        screen.queryByRole("group", { name: labels.stripHeading }),
      ).toBeNull();
      expect(
        screen.queryByRole("heading", { name: labels.stripHeading }),
      ).toBeNull();
    },
  );
});

describe("the room bar choice in the mobile app", () => {
  function app(native: FakeNative = fakeNative(answer)) {
    const platform = platformFor();
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
  }
  // The settings screen covers the rooms, which then are out of the accessibility tree; the strip stays in the DOM.
  function strip() {
    return document.querySelector<HTMLElement>("nav.sk-rooms")!;
  }
  function roomCells() {
    return Array.from(
      strip().querySelectorAll<HTMLButtonElement>(
        ".sk-rooms__tab:not(.sk-rooms__more)",
      ),
    );
  }
  async function ready() {
    await screen.findByText("Skicka offert");
  }
  async function openSettings(user: ReturnType<typeof userEvent.setup>) {
    await user.click(screen.getByRole("button", { name: "Fler val" }));
    await user.click(screen.getByRole("button", { name: "Inställningar" }));
    await screen.findByRole("heading", { name: "Inställningar" });
  }

  it("starts with the names alone", async () => {
    app();
    await ready();
    expect(strip()).not.toHaveAttribute("data-icons");
    expect(roomCells().length).toBeGreaterThan(0);
    for (const cell of roomCells()) {
      expect(cell.textContent).not.toBe("");
      expect(cell.querySelector("svg")).toBeNull();
    }
    expect(localStorage.getItem(APP_NAV_ICONS_KEY)).toBeNull();
  });

  it("switches the strip to glyphs alone and keeps the choice", async () => {
    const user = userEvent.setup();
    app();
    await ready();
    await openSettings(user);
    await user.click(screen.getByRole("button", { name: "Ikoner" }));
    expect(localStorage.getItem(APP_NAV_ICONS_KEY)).toBe("only");
    expect(screen.getByRole("button", { name: "Ikoner" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(strip()).toHaveAttribute("data-icons", "only");
    for (const cell of roomCells()) {
      expect(cell.textContent).toBe("");
      expect(cell).toHaveAttribute("aria-label");
      expect(cell).toHaveAttribute("title", cell.getAttribute("aria-label"));
    }
  });

  it("starts in a choice kept from before", async () => {
    localStorage.setItem(APP_NAV_ICONS_KEY, "label");
    app();
    await ready();
    expect(strip()).toHaveAttribute("data-icons", "label");
    for (const cell of roomCells()) {
      expect(cell.querySelector("svg")).not.toBeNull();
      expect(cell.querySelector(".sk-rooms__name")).not.toBeNull();
    }
  });

  it("starts with names alone when the kept value is none of the three", async () => {
    localStorage.setItem(APP_NAV_ICONS_KEY, "sparkles");
    app();
    await ready();
    expect(strip()).not.toHaveAttribute("data-icons");
    for (const cell of roomCells()) {
      expect(cell.querySelector("svg")).toBeNull();
    }
  });

  it("ignores a kept auto, which a phone's choice does not offer, and starts with names alone", async () => {
    localStorage.setItem(APP_NAV_ICONS_KEY, "auto");
    app();
    await ready();
    expect(strip()).not.toHaveAttribute("data-icons");
    for (const cell of roomCells()) {
      expect(cell.querySelector("svg")).toBeNull();
    }
  });
});

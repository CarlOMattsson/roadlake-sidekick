import {
  act,
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { HostFeatures } from "@/features/mcp-apps/bridge";
import {
  SidekickShell,
  type RoomRegistry,
  type ShellRoomProps,
} from "@/features/mcp-apps/sidekick-shell";
import {
  licenseLabelsEn,
  licenseLabelsSv,
} from "@/features/mcp-apps/license-labels";
import {
  LicenseFoot,
  LicenseHostContext,
  LicenseRow,
  type LicenseHost,
} from "@/features/mcp-apps/license-mark";
import {
  declareLicense,
  licenseAt,
  licenseFrom,
  parseLicenseMeta,
  readLicense,
  type License,
} from "@/features/mcp-apps/license-state";
import { ROOM_IDS, type RoomId } from "@/features/mcp-apps/router";
import { CardFoot } from "@/features/mcp-apps/ui/card";
import { updateReminderLabelsSv } from "@/features/mcp-apps/update-reminder-labels";
import { AgendaMore } from "@/features/work-app/agenda/agenda-toolbar";
import { workSv } from "@/features/work-app/shared/labels";

// The license signal (see docs/decisions/log.md D-083): the backend declares the display state as one JSON meta, `sidekick-license`. These are
// fixtures of that contract (the backend is built in parallel); no network, no key in the document.
const NOW = new Date("2026-11-09T12:00:00Z");
const now = () => NOW;
const UNLICENSED: License = { state: "unlicensed" };
const LICENSED: License = {
  state: "licensed",
  licensee: "Alex Exempel",
  kind: "personal",
  expires: "2027-11-09",
};
const EXPIRED: License = {
  state: "expired",
  licensee: "Alex Exempel",
  kind: "personal",
  expires: "2026-11-03",
};
const LOCAL: HostFeatures = {
  serverTools: true,
  message: true,
  openLinks: true,
};
const RESERVE: HostFeatures = {
  serverTools: false,
  message: true,
  openLinks: false,
};

function meta(content: string) {
  const element = document.createElement("meta");
  element.name = "sidekick-license";
  element.content = content;
  document.head.append(element);
}

function rooms(list: string) {
  const element = document.createElement("meta");
  element.name = "sidekick-rooms";
  element.content = list;
  document.head.append(element);
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  document.head.innerHTML = "";
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  document.head.innerHTML = "";
});

describe("the declared state", () => {
  it("reads the JSON meta; `invalid` reads as unlicensed; fields other than state may be absent", () => {
    meta('{"state":"invalid"}');
    expect(readLicense()).toEqual({ state: "unlicensed" });
    expect(
      parseLicenseMeta(
        '{"state":"licensed","licensee":"Example AB","kind":"org","expires":"2027-01-31"}',
      ),
    ).toEqual({
      state: "licensed",
      licensee: "Example AB",
      kind: "org",
      expires: "2027-01-31",
    });
  });

  it("knows nothing without a meta, from text that is not JSON, or of a state it does not know", () => {
    expect(readLicense()).toBeUndefined();
    expect(parseLicenseMeta("unpaid")).toBeUndefined();
    expect(licenseFrom({ state: "unpaid" })).toBeUndefined();
    expect(licenseFrom({ licensee: "x" })).toBeUndefined();
  });

  it("counts a license whose last day has passed on this clock as expired, the last day itself as licensed", () => {
    expect(licenseAt(LICENSED, NOW)?.state).toBe("licensed");
    expect(licenseAt({ ...LICENSED, expires: "2026-11-09" }, NOW)?.state).toBe(
      "licensed",
    );
    expect(licenseAt({ ...LICENSED, expires: "2026-11-08" }, NOW)?.state).toBe(
      "expired",
    );
  });

  it("is never told the key: the meta holds the display state only", () => {
    declareLicense(LICENSED);
    const content = document
      .querySelector('meta[name="sidekick-license"]')
      ?.getAttribute("content");
    expect(JSON.parse(content ?? "")).toEqual(LICENSED);
  });
});

function card() {
  return render(
    <section className="sk-card">
      <CardFoot>
        <button type="button" className="sk-btn--open">
          Öppna Agenda
        </button>
      </CardFoot>
    </section>,
  );
}

describe("the inline card's foot", () => {
  it("draws nothing extra without a declared license (an older server)", () => {
    const { container } = card();
    expect(container.querySelector(".sk-card__foot")).toBeNull();
    expect(
      screen.queryByRole("button", { name: licenseLabelsSv.mark }),
    ).toBeNull();
  });

  it("draws no coin when licensed", () => {
    meta(JSON.stringify(LICENSED));
    const { container } = card();
    expect(container.querySelector(".sk-license-mark")).toBeNull();
  });

  it("puts the coin, named and without text, at the end of the open row; a tap folds the row out in the card", async () => {
    const user = userEvent.setup();
    meta(JSON.stringify(UNLICENSED));
    const { container } = card();
    const foot = container.querySelector(".sk-card__foot");
    const coin = screen.getByRole("button", { name: licenseLabelsSv.mark });
    expect(foot?.lastElementChild).toBe(coin);
    expect(coin.textContent).toBe("");
    expect(coin.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
    expect(coin.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText(licenseLabelsSv.unlicensed)).toBeNull();

    await user.click(coin);
    expect(coin.getAttribute("aria-expanded")).toBe("true");
    const row = document.getElementById(
      coin.getAttribute("aria-controls") ?? "",
    );
    expect(row).not.toBeNull();
    expect(within(row!).getByText(licenseLabelsSv.unlicensed)).toBeTruthy();
    // "Köp licens" waits for the owner's address (LICENSE_BUY_URL is empty): no button that leads nowhere, and the
    // row says that keys are on sale soon where the button would be.
    expect(within(row!).getByText(licenseLabelsSv.buySoon)).toBeTruthy();
    expect(
      within(row!).queryByRole("button", { name: licenseLabelsSv.buy }),
    ).toBeNull();
    expect(within(row!).queryByRole("link")).toBeNull();

    await user.click(coin);
    expect(coin.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText(licenseLabelsSv.unlicensed)).toBeNull();
  });

  it("names the coin in English with the app language", () => {
    const locale = document.createElement("meta");
    locale.name = "sidekick-app-locale";
    locale.content = "en";
    document.head.append(locale);
    meta(JSON.stringify(EXPIRED));
    card();
    expect(
      screen.getByRole("button", { name: licenseLabelsEn.mark }),
    ).toBeTruthy();
  });
});

describe("the license row", () => {
  it("says the free version, licensed with name and last day, or expired with the day", () => {
    meta(JSON.stringify(UNLICENSED));
    const { rerender } = render(<LicenseRow locale="sv" now={now} />);
    expect(screen.getByText(licenseLabelsSv.unlicensed)).toBeTruthy();

    act(() => declareLicense(LICENSED));
    rerender(<LicenseRow locale="sv" now={now} />);
    expect(
      screen.getByText("Licensierad till Alex Exempel · t.o.m. 9 nov 2027"),
    ).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();

    act(() => declareLicense(EXPIRED));
    rerender(<LicenseRow locale="en" now={now} />);
    expect(
      screen.getByText(
        "Your license expired on Tue 3 Nov. You’re welcome to buy a new one.",
      ),
    ).toBeTruthy();
  });

  it("draws nothing without a declared license", () => {
    const { container } = render(<LicenseRow locale="sv" now={now} />);
    expect(container.innerHTML).toBe("");
  });

  it("offers no key field on a host that cannot call tools", () => {
    meta(JSON.stringify(UNLICENSED));
    render(<LicenseRow locale="sv" now={now} />);
    expect(
      screen.queryByRole("button", { name: licenseLabelsSv.enterKey }),
    ).toBeNull();
  });

  function withHost(host: LicenseHost) {
    return render(
      <LicenseHostContext.Provider value={host}>
        <LicenseRow locale="sv" now={now} />
        <section className="sk-card">
          <CardFoot>
            <button type="button">Öppna</button>
          </CardFoot>
        </section>
      </LicenseHostContext.Provider>,
    );
  }

  it("saves a key through set_license_key; licensed, the coin goes everywhere at once and the key is gone", async () => {
    const user = userEvent.setup();
    meta(JSON.stringify(UNLICENSED));
    const call = vi.fn().mockResolvedValue({ ...LICENSED, accepted: true });
    withHost({ call });
    expect(
      screen.getByRole("button", { name: licenseLabelsSv.mark }),
    ).toBeTruthy();
    await user.click(
      screen.getByRole("button", { name: licenseLabelsSv.enterKey }),
    );
    const field = screen.getByRole("textbox", {
      name: licenseLabelsSv.keyField,
    });
    expect(document.activeElement).toBe(field);
    expect(field.getAttribute("autocomplete")).toBe("off");
    expect(field.getAttribute("spellcheck")).toBe("false");
    await user.type(field, "  SIDEKICK-KEY-123  ");
    await user.click(
      screen.getByRole("button", { name: licenseLabelsSv.save }),
    );

    expect(call).toHaveBeenCalledWith("set_license_key", {
      key: "SIDEKICK-KEY-123",
    });
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toBe(
        licenseLabelsSv.saved,
      ),
    );
    expect(
      screen.getByText("Licensierad till Alex Exempel · t.o.m. 9 nov 2027"),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: licenseLabelsSv.mark }),
    ).toBeNull();
    expect(document.body.innerHTML).not.toContain("SIDEKICK-KEY-123");
    expect(document.head.innerHTML).not.toContain("SIDEKICK-KEY-123");
  });

  it("says calmly by the field when the server does not accept the key, and keeps the field", async () => {
    const user = userEvent.setup();
    meta(JSON.stringify(UNLICENSED));
    const call = vi
      .fn()
      .mockResolvedValue({ state: "invalid", accepted: false });
    withHost({ call });
    await user.click(
      screen.getByRole("button", { name: licenseLabelsSv.enterKey }),
    );
    await user.type(screen.getByRole("textbox"), "fel");
    await user.click(
      screen.getByRole("button", { name: licenseLabelsSv.save }),
    );
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toBe(
        licenseLabelsSv.invalidKey,
      ),
    );
    expect(screen.getByRole("textbox")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: licenseLabelsSv.mark }),
    ).toBeTruthy();
  });

  it("shows the shared error with a retry when no answer came", async () => {
    const user = userEvent.setup();
    meta(JSON.stringify(UNLICENSED));
    const call = vi
      .fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce({ ...LICENSED, accepted: true });
    withHost({ call });
    await user.click(
      screen.getByRole("button", { name: licenseLabelsSv.enterKey }),
    );
    await user.type(screen.getByRole("textbox"), "nyckel");
    await user.click(
      screen.getByRole("button", { name: licenseLabelsSv.save }),
    );
    const retry = await screen.findByRole("button", { name: /försök igen/i });
    await user.click(retry);
    await waitFor(() => expect(call).toHaveBeenCalledTimes(2));
    expect(call.mock.calls[1]).toEqual(["set_license_key", { key: "nyckel" }]);
  });

  it("closes the field on Escape and gives the focus back to its button", async () => {
    const user = userEvent.setup();
    meta(JSON.stringify(UNLICENSED));
    withHost({ call: vi.fn() });
    await user.click(
      screen.getByRole("button", { name: licenseLabelsSv.enterKey }),
    );
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: licenseLabelsSv.enterKey }),
    );
  });
});

// ---- The full view: the shell's foot and where the coin leads.

function Stub(props: ShellRoomProps) {
  return <h2>{`${props.entry.room}/${props.entry.view}`}</h2>;
}
function ControlStub() {
  return (
    <div>
      <h2>control</h2>
      <LicenseRow locale="sv" />
    </div>
  );
}
/** A Work room with the real ⋯ of the agenda (Kontroll off: the panel holds the row). */
function WorkWithMore() {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <h2>work</h2>
      <AgendaMore
        labels={workSv}
        open={open}
        onOpenChange={setOpen}
        onRefresh={() => {}}
      />
    </div>
  );
}
const registry = {
  ...(Object.fromEntries(ROOM_IDS.map((room) => [room, Stub])) as Record<
    RoomId,
    typeof Stub
  >),
  control: ControlStub,
  work: WorkWithMore,
} as RoomRegistry;

function shell(
  features: HostFeatures = LOCAL,
  host: LicenseHost = {},
  start: { room: RoomId; view: string } = { room: "work", view: "agenda" },
) {
  return render(
    <LicenseHostContext.Provider value={host}>
      <SidekickShell
        locale="sv"
        rooms={registry}
        start={start}
        full
        features={features}
        onSendMessage={vi.fn().mockResolvedValue(true)}
      />
    </LicenseHostContext.Provider>,
  );
}

function rowLead(text: string) {
  return screen.getByText(text);
}

describe("the full view's foot", () => {
  it("draws no coin without a declared license, nor when licensed", () => {
    const { container, unmount } = shell();
    expect(container.querySelector(".sk-license-mark")).toBeNull();
    unmount();
    meta(JSON.stringify(LICENSED));
    const again = shell();
    expect(again.container.querySelector(".sk-license-mark")).toBeNull();
  });

  it("stands last in the room; with Kontroll on, a tap opens Kontroll and the row there takes the focus", async () => {
    const user = userEvent.setup();
    meta(JSON.stringify(UNLICENSED));
    const { container } = shell();
    const coin = screen.getByRole("button", { name: licenseLabelsSv.mark });
    const roomsShell = container.querySelector(".sk-rooms-shell");
    expect(roomsShell?.lastElementChild?.contains(coin)).toBe(true);
    await user.click(coin);
    await waitFor(() =>
      expect(document.activeElement).toBe(rowLead(licenseLabelsSv.unlicensed)),
    );
    expect(screen.getByRole("heading", { name: "control" })).toBeTruthy();
    // Kontroll holds the row: no coin there.
    expect(
      screen.queryByRole("button", { name: licenseLabelsSv.mark }),
    ).toBeNull();
  });

  it("with Kontroll off (work only), a tap opens the room's ⋯ on the row, which takes the focus", async () => {
    const user = userEvent.setup();
    rooms("work");
    meta(JSON.stringify(EXPIRED));
    shell();
    expect(screen.queryByRole("navigation")).toBeNull();
    const more = screen.getByRole("button", { name: workSv.moreActions });
    expect(more.getAttribute("aria-expanded")).toBe("false");
    await user.click(
      screen.getByRole("button", { name: licenseLabelsSv.mark }),
    );
    expect(more.getAttribute("aria-expanded")).toBe("true");
    await waitFor(() =>
      expect(document.activeElement?.textContent).toMatch(
        /^Licensen gick ut tis 3 nov\./,
      ),
    );
  });

  it("on a host with its own settings (the phone), a tap opens them", async () => {
    const user = userEvent.setup();
    meta(JSON.stringify(UNLICENSED));
    const openSettings = vi.fn();
    shell(LOCAL, { openSettings });
    await user.click(
      screen.getByRole("button", { name: licenseLabelsSv.mark }),
    );
    expect(openSettings).toHaveBeenCalledTimes(1);
    expect(openSettings).toHaveBeenCalledWith("work");
  });

  it("tells the host's settings which room the coin was tapped in", async () => {
    const user = userEvent.setup();
    meta(JSON.stringify(UNLICENSED));
    const openSettings = vi.fn();
    shell(LOCAL, { openSettings }, { room: "journal", view: "day" });
    await user.click(
      screen.getByRole("button", { name: licenseLabelsSv.mark }),
    );
    expect(openSettings).toHaveBeenCalledWith("journal");
  });

  it("folds the row out in place when no place holds it (a host that cannot navigate to Kontroll)", async () => {
    const user = userEvent.setup();
    meta(JSON.stringify(UNLICENSED));
    shell(RESERVE);
    const coin = screen.getByRole("button", { name: licenseLabelsSv.mark });
    await user.click(coin);
    expect(coin.getAttribute("aria-expanded")).toBe("true");
    await waitFor(() =>
      expect(document.activeElement).toBe(rowLead(licenseLabelsSv.unlicensed)),
    );
  });
});

describe("next to the update dot", () => {
  function declareUpdate() {
    const DAY = 24 * 60 * 60 * 1000;
    const metas: [string, string][] = [
      ["sidekick-build-commit", "abc1234"],
      ["sidekick-build-date", new Date(NOW.getTime() - 20 * DAY).toISOString()],
      ["sidekick-update-days", "14"],
    ];
    for (const [name, content] of metas) {
      const element = document.createElement("meta");
      element.name = name;
      element.content = content;
      document.head.append(element);
    }
  }

  it("leaves the ⋯ button's name and dot to the update reminder; the coin is never on ⋯", () => {
    meta(JSON.stringify(UNLICENSED));
    const { unmount } = render(
      <AgendaMore
        labels={workSv}
        open={false}
        onOpenChange={() => {}}
        onRefresh={() => {}}
      />,
    );
    const plain = screen.getByRole("button", { name: workSv.moreActions });
    expect(plain.querySelector(".sk-update-dot")).toBeNull();
    expect(
      plain.querySelector(".sk-license-mark, svg circle + path"),
    ).toBeNull();
    unmount();

    declareUpdate();
    render(
      <AgendaMore
        labels={workSv}
        open={false}
        onOpenChange={() => {}}
        onRefresh={() => {}}
      />,
    );
    const marked = screen.getByRole("button", {
      name: `${workSv.moreActions} – ${updateReminderLabelsSv.moreSuffix}`,
    });
    expect(marked.querySelectorAll(".sk-update-dot")).toHaveLength(1);
    expect(marked.getAttribute("aria-label")).not.toMatch(/licens/i);
  });

  it("puts the update row first and the license row last in the ⋯ panel when Kontroll is off", () => {
    rooms("work");
    declareUpdate();
    meta(JSON.stringify(UNLICENSED));
    const { container } = render(
      <AgendaMore
        labels={workSv}
        open
        onOpenChange={() => {}}
        onRefresh={() => {}}
      />,
    );
    const rows = container.querySelectorAll(".sk-update-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]?.classList.contains("sk-license-row")).toBe(false);
    expect(rows[1]?.classList.contains("sk-license-row")).toBe(true);
  });
});

describe("LicenseFoot", () => {
  it("draws nothing licensed, and nothing without a meta", () => {
    const { container, rerender } = render(
      <LicenseFoot locale="sv" onShow={() => true} />,
    );
    expect(container.innerHTML).toBe("");
    act(() => declareLicense(LICENSED));
    rerender(<LicenseFoot locale="sv" onShow={() => true} />);
    expect(container.innerHTML).toBe("");
    act(() => declareLicense(UNLICENSED));
    rerender(<LicenseFoot locale="sv" onShow={() => true} />);
    expect(container.querySelector(".sk-license-mark")).not.toBeNull();
  });
});

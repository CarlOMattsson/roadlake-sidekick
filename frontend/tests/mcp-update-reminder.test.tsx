import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ControlApp } from "@/features/control-app/control-app";
import { controlEn, controlSv } from "@/features/control-app/labels";
import type { ControlTransport } from "@/features/control-app/transport";
import {
  updateReminderLabelsEn,
  updateReminderLabelsSv,
} from "@/features/mcp-apps/update-reminder-labels";
import {
  dismissUpdateNotice,
  readUpdateNotice,
} from "@/features/mcp-apps/update-notice";
import {
  UPDATE_COMMAND,
  UpdateReminderRow,
  useMoreMark,
} from "@/features/mcp-apps/update-reminder";
import { AgendaMore } from "@/features/work-app/agenda/agenda-toolbar";
import { ContactsView } from "@/features/work-app/contacts/contacts-list";
import type { WorkTransport } from "@/features/work-app/transport/transport";
import { workEn, workSv } from "@/features/work-app/shared/labels";

// The update reminder works offline: the backend declares the running commit, its date and the number of days as
// meta tags, and the app counts the age with its own clock (SIDEKICK_UPDATE_REMINDER_DAYS).
const DAY = 24 * 60 * 60 * 1000;
const NOW = new Date("2026-11-20T12:00:00Z");
const now = () => NOW;

function declare(
  options: {
    commit?: string;
    ageDays?: number;
    days?: number;
    date?: string;
    rooms?: string;
  } = {},
) {
  const {
    commit = "abc1234",
    ageDays = 20,
    days = 14,
    date = new Date(NOW.getTime() - ageDays * DAY).toISOString(),
    rooms,
  } = options;
  document.head.innerHTML =
    `<meta name="sidekick-build-commit" content="${commit}">` +
    `<meta name="sidekick-build-date" content="${date}">` +
    `<meta name="sidekick-update-days" content="${days}">` +
    (rooms === undefined
      ? ""
      : `<meta name="sidekick-rooms" content="${rooms}">`);
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  localStorage.clear();
  delete document.documentElement.dataset.updateDismissed;
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  document.head.innerHTML = "";
});

describe("readUpdateNotice", () => {
  it("reminds from the number of days the document declares, counted whole", () => {
    declare({ ageDays: 14, days: 14 });
    expect(readUpdateNotice(document, NOW)).toEqual({
      commit: "abc1234",
      ageDays: 14,
    });
    declare({
      date: new Date(NOW.getTime() - 14 * DAY + 60_000).toISOString(),
    });
    expect(readUpdateNotice(document, NOW)).toBeUndefined();
  });

  it.each([
    ["the code is younger", { ageDays: 3 }],
    ["the reminder is off (0 days)", { days: 0 }],
    ["the date is unreadable", { date: "yesterday" }],
    ["the commit is empty", { commit: "" }],
  ])("is silent when %s", (_name, options) => {
    declare(options);
    expect(readUpdateNotice(document, NOW)).toBeUndefined();
  });

  it("is silent when the document declares nothing (off, unknown date, or a host without the meta)", () => {
    document.head.innerHTML = "";
    expect(readUpdateNotice(document, NOW)).toBeUndefined();
  });

  it("never counts a commit from the future as negative", () => {
    declare({ ageDays: -2, days: 1 });
    expect(readUpdateNotice(document, NOW)).toBeUndefined();
  });
});

function Probe({ label }: { label: string }) {
  const mark = useMoreMark(label);
  return (
    <button type="button" aria-label={mark.label}>
      {mark.dot}
    </button>
  );
}

describe("the ⋯ button", () => {
  it("has no dot and keeps its name while no reminder stands", () => {
    declare({ ageDays: 2 });
    const { container } = render(<Probe label="Fler alternativ" />);
    expect(
      screen.getByRole("button", { name: "Fler alternativ" }),
    ).toBeTruthy();
    expect(container.querySelector(".sk-update-dot")).toBeNull();
  });

  it("gets a calm dot and says it in its accessible name", () => {
    declare();
    const { container } = render(<Probe label="Fler alternativ" />);
    const button = screen.getByRole("button", {
      name: "Fler alternativ – uppdatering finns att hämta",
    });
    const dot = container.querySelector(".sk-update-dot");
    expect(button.contains(dot)).toBe(true);
    expect(dot?.getAttribute("aria-hidden")).toBe("true");
  });

  it("follows the app language", () => {
    declare();
    document.head.insertAdjacentHTML(
      "beforeend",
      '<meta name="sidekick-app-locale" content="en">',
    );
    render(<Probe label="More options" />);
    expect(
      screen.getByRole("button", {
        name: "More options – update available",
      }),
    ).toBeTruthy();
  });

  it("is the Work room's own ⋯ in both languages", () => {
    declare();
    for (const labels of [workSv, workEn]) {
      document.head.insertAdjacentHTML(
        "beforeend",
        `<meta name="sidekick-app-locale" content="${labels === workSv ? "sv" : "en"}">`,
      );
      const { unmount } = render(
        <AgendaMore
          labels={labels}
          open={false}
          onOpenChange={() => {}}
          onRefresh={() => {}}
        />,
      );
      const suffix =
        labels === workSv
          ? updateReminderLabelsSv.moreSuffix
          : updateReminderLabelsEn.moreSuffix;
      const button = screen.getByRole("button", {
        name: `${labels.moreActions} – ${suffix}`,
      });
      expect(button.getAttribute("aria-expanded")).toBe("false");
      unmount();
      document.head.querySelector('meta[name="sidekick-app-locale"]')?.remove();
    }
  });

  it("keeps its dot when the Control room is off, since the ⋯ menu holds the row there", () => {
    declare({ rooms: "work,journal" });
    const { container } = render(<Probe label="Fler alternativ" />);
    expect(container.querySelector(".sk-update-dot")).not.toBeNull();
  });

  it("loses its dot at once when the reminder is dismissed for this commit", () => {
    declare();
    const { container } = render(<Probe label="Fler alternativ" />);
    expect(container.querySelector(".sk-update-dot")).not.toBeNull();
    act(() => dismissUpdateNotice("abc1234"));
    expect(container.querySelector(".sk-update-dot")).toBeNull();
    expect(
      screen.getByRole("button", { name: "Fler alternativ" }),
    ).toBeTruthy();
  });
});

describe("the row in Control", () => {
  it("shows the age, the commit and the update command in a code element", () => {
    declare();
    render(<UpdateReminderRow locale="sv" now={now} />);
    expect(
      screen.getByText("Sidekick är 20 dagar gammal (commit abc1234)"),
    ).toBeTruthy();
    const code = screen.getByText(UPDATE_COMMAND);
    expect(code.tagName).toBe("CODE");
    expect(UPDATE_COMMAND).toBe("tools/work.sh update");
    expect(
      screen.getByRole("button", { name: "Påminn inte för den här versionen" }),
    ).toBeTruthy();
  });

  it("speaks English with the English setting, and one day in the singular", () => {
    declare({ ageDays: 1, days: 1 });
    render(<UpdateReminderRow locale="en" now={now} />);
    expect(
      screen.getByText("This version is 1 day old (commit abc1234)"),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", {
        name: "Don’t remind me about this version",
      }),
    ).toBeTruthy();
    expect(screen.getByText("Update with", { exact: false })).toBeTruthy();
  });

  it("draws nothing while no reminder stands", () => {
    declare({ ageDays: 1 });
    const { container } = render(<UpdateReminderRow locale="sv" now={now} />);
    expect(container.firstChild).toBeNull();
  });

  it("is dismissed per commit: a quiet line takes its place and the focus rests there", async () => {
    declare();
    const user = userEvent.setup();
    const { container } = render(<UpdateReminderRow locale="sv" now={now} />);
    await user.click(
      screen.getByRole("button", { name: "Påminn inte för den här versionen" }),
    );
    const line = screen.getByRole("status");
    expect(line.textContent).toBe(updateReminderLabelsSv.dismissed);
    expect(document.activeElement).toBe(line);
    expect(container.querySelector("code")).toBeNull();
    expect(localStorage["sidekick.updateDismissed"]).toBe("abc1234");
  });

  it("keeps the answer for the session when the frame has no storage", () => {
    declare();
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const { container } = render(<Probe label="Fler alternativ" />);
    act(() => dismissUpdateNotice("abc1234"));
    expect(container.querySelector(".sk-update-dot")).toBeNull();
    vi.restoreAllMocks();
  });

  it("comes back for a newer commit that is old too, not for the one dismissed", () => {
    declare({ commit: "abc1234" });
    dismissUpdateNotice("abc1234");
    const first = render(<UpdateReminderRow locale="sv" now={now} />);
    expect(first.container.firstChild).toBeNull();
    first.unmount();

    declare({ commit: "def5678", ageDays: 5 });
    const young = render(<UpdateReminderRow locale="sv" now={now} />);
    expect(young.container.firstChild).toBeNull();
    young.unmount();

    declare({ commit: "def5678", ageDays: 15 });
    render(<UpdateReminderRow locale="sv" now={now} />);
    expect(
      screen.getByText("Sidekick är 15 dagar gammal (commit def5678)"),
    ).toBeTruthy();
  });

  it("reads an earlier dismissal from the frame's storage", () => {
    declare();
    localStorage["sidekick.updateDismissed"] = "abc1234";
    const { container } = render(<UpdateReminderRow locale="sv" now={now} />);
    expect(container.firstChild).toBeNull();
  });
});

describe("Control's full view", () => {
  const transport: ControlTransport = {
    trash: vi.fn(() =>
      Promise.resolve({ items: [], has_more: false, next_cursor: null }),
    ),
    restore: vi.fn(),
    changes: vi.fn(),
    undoPurchase: vi.fn(),
    memoryStatus: vi.fn(),
    setMemory: vi.fn(),
    activity: vi.fn(),
  };
  const view = (labels: typeof controlSv, heading: boolean) => (
    <ControlApp
      transport={transport}
      labels={labels}
      initialView="trash"
      initialData={{ trash: { items: [], has_more: false, next_cursor: null } }}
      heading={heading}
      now={now}
    />
  );

  it("holds the row under the tabs", () => {
    declare();
    render(view(controlSv, true));
    const row = screen
      .getByText("Sidekick är 20 dagar gammal (commit abc1234)")
      .closest(".sk-update-row") as HTMLElement;
    expect(within(row).getByText(UPDATE_COMMAND)).toBeTruthy();
  });

  it("speaks English in the English app", () => {
    declare();
    render(view({ ...controlEn, locale: "en" }, true));
    expect(
      screen.getByText("This version is 20 days old (commit abc1234)"),
    ).toBeTruthy();
  });

  it("leaves the small card alone, which has no room for it", () => {
    declare();
    render(view(controlSv, false));
    expect(screen.queryByText(UPDATE_COMMAND)).toBeNull();
  });
});

describe("the row in the ⋯ menu when the Control room is off", () => {
  const AGE = "Sidekick är 20 dagar gammal (commit abc1234)";
  const DISMISS = "Påminn inte för den här versionen";

  function WorkMenu() {
    return (
      <AgendaMore
        labels={workSv}
        open
        onOpenChange={() => {}}
        onRefresh={() => {}}
      />
    );
  }

  function contacts() {
    return (
      <ContactsView
        frame={{ kind: "contacts", q: "", includeArchived: false }}
        onChange={vi.fn()}
        transport={
          {
            listContacts: vi
              .fn()
              .mockResolvedValue({ items: [], next_cursor: null }),
          } as unknown as WorkTransport
        }
        labels={workSv}
        moves={0}
        onOpen={vi.fn()}
        onRoute={vi.fn()}
      />
    );
  }

  it("shows the age, the commit, the copyable command and the dismissal in Work's ⋯ panel", () => {
    declare({ rooms: "work" });
    render(<WorkMenu />);
    const panel = screen.getByText(AGE).closest(".work-agenda-bar-panel");
    expect(panel).not.toBeNull();
    const code = within(panel as HTMLElement).getByText(UPDATE_COMMAND);
    expect(code.tagName).toBe("CODE");
    expect(
      within(panel as HTMLElement).getByRole("button", { name: DISMISS }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", {
        name: `${workSv.moreActions} – ${updateReminderLabelsSv.moreSuffix}`,
      }),
    ).toBeTruthy();
  });

  it("shows it in the Contacts room's ⋯ panel too, in the app language", async () => {
    declare({ rooms: "work,contacts" });
    document.head.insertAdjacentHTML(
      "beforeend",
      '<meta name="sidekick-app-locale" content="en">',
    );
    render(contacts());
    expect(
      await screen.findByText("This version is 20 days old (commit abc1234)"),
    ).toBeTruthy();
    // The panel is closed (hidden) until ⋯ opens it, so the button is found with hidden: true.
    expect(
      screen.getByRole("button", {
        name: "Don’t remind me about this version",
        hidden: true,
      }),
    ).toBeTruthy();
  });

  it("hides both the dot and the row once the owner dismisses it, and says so in the menu", async () => {
    declare({ rooms: "work" });
    const user = userEvent.setup();
    const { container } = render(<WorkMenu />);
    expect(container.querySelector(".sk-update-dot")).not.toBeNull();
    await user.click(screen.getByRole("button", { name: DISMISS }));
    expect(container.querySelector(".sk-update-dot")).toBeNull();
    expect(screen.queryByText(AGE)).toBeNull();
    expect(container.querySelector("code")).toBeNull();
    expect(screen.getByRole("status").textContent).toBe(
      updateReminderLabelsSv.dismissed,
    );
    expect(
      screen.getByRole("button", { name: workSv.moreActions }),
    ).toBeTruthy();
    expect(localStorage["sidekick.updateDismissed"]).toBe("abc1234");
  });

  it("draws no row while the reminder is quiet", () => {
    declare({ rooms: "work", ageDays: 2 });
    render(<WorkMenu />);
    expect(screen.queryByText(UPDATE_COMMAND)).toBeNull();
  });

  it("changes nothing with the Control room on: the dot stays, the menu keeps Kontroll and holds no row", async () => {
    for (const rooms of ["work,control", undefined]) {
      declare({ rooms });
      const { container, unmount } = render(
        <AgendaMore
          labels={workSv}
          open
          onOpenChange={() => {}}
          onRefresh={() => {}}
          control={{ label: "Kontroll", onOpen: () => {} }}
        />,
      );
      expect(container.querySelector(".sk-update-dot")).not.toBeNull();
      expect(screen.getByRole("button", { name: "Kontroll" })).toBeTruthy();
      expect(screen.queryByText(UPDATE_COMMAND)).toBeNull();
      unmount();
    }
    declare({ rooms: "work,contacts,control" });
    render(contacts());
    await screen.findByRole("heading", { name: workSv.contacts });
    expect(screen.queryByText(UPDATE_COMMAND)).toBeNull();
  });
});

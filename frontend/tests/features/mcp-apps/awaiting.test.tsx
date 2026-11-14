import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  AwaitingResult,
  awaitingLabelsFor,
} from "@/features/mcp-apps/awaiting";
import { sidekickShellLabelsFor } from "@/features/mcp-apps/sidekick-shell-labels";

import { readRepoFile } from "@tests/helpers/source-files";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

/** The text of the status that assistive technology gets: everything outside the aria-hidden parts. */
function spokenText(node: Node): string {
  if (node instanceof Element && node.getAttribute("aria-hidden") === "true")
    return "";
  if (node.nodeType === Node.TEXT_NODE) return node.textContent ?? "";
  return Array.from(node.childNodes).map(spokenText).join("");
}

describe.each([
  {
    name: "sv",
    locale: "sv",
    loading: "Laddar…",
    rooms: ["Arbete", "Dagbok", "Kontakter", "Inköp"],
    text: "Väntar på data från Claude. Be Claude öppna den igen.",
  },
  {
    name: "en",
    locale: "en-US",
    loading: "Loading…",
    rooms: ["Work", "Journal", "Contacts", "Shopping"],
    text: "Still waiting for data from Claude. Ask Claude to open this again.",
  },
])("AwaitingResult ($name)", ({ locale, loading, rooms, text }) => {
  it("is a busy status with the strip, a loading line and four rows, and only the loading line before the timeout", () => {
    const { container } = render(
      <AwaitingResult locale={locale} timeoutMs={8000} />,
    );

    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("aria-busy", "true");
    // The only text a screen reader gets is the visible loading line; the explanation waits for the timeout.
    expect(spokenText(status)).toBe(loading);
    expect(screen.queryByText(text)).not.toBeInTheDocument();
    // Without a room only the strip and the four rows are hidden from assistive tech: no view row, no chips.
    expect(container.querySelectorAll('[aria-hidden="true"]')).toHaveLength(2);
    // The strip is drawn as the real one: the four room names as text, none marked, hidden from assistive tech.
    const strip = container.querySelector(".sidekick-wait-strip");
    expect(strip).toHaveAttribute("aria-hidden", "true");
    expect(
      Array.from(
        strip?.querySelectorAll(".sidekick-wait-room") ?? [],
        (room) => room.textContent,
      ),
    ).toEqual(rooms);
    expect(strip?.querySelector('[data-current="true"]')).toBeNull();
    expect(container.querySelector(".sidekick-wait-tabs")).toBeNull();
    expect(container.querySelector(".sidekick-wait-create")).toBeNull();
    expect(container.querySelector(".sidekick-wait-chips")).toBeNull();
    // The loading line is always read, never drawn (family.css hides it everywhere); no extra sr span.
    expect(container.querySelector(".sidekick-wait-line")).toHaveTextContent(
      loading,
    );
    expect(container.querySelector(".sidekick-wait-sr")).toBeNull();
    // Each row holds a glyph, a title bar and a meta bar; rows 2 and 4 add a second title bar (one and two lines alternate).
    expect(container.querySelectorAll(".sidekick-wait-row")).toHaveLength(4);
    expect(
      container.querySelectorAll(".sidekick-wait-row .sidekick-wait-block"),
    ).toHaveLength(14);
    const titleBars = Array.from(
      container.querySelectorAll(".sidekick-wait-row"),
      (row) => row.querySelectorAll(".sidekick-wait-row-title").length,
    );
    expect(titleBars).toEqual([1, 2, 1, 2]);
    expect(container.querySelector("svg")).toBeNull();
  });

  it("shows the explanation once timeoutMs has elapsed", () => {
    render(<AwaitingResult locale={locale} timeoutMs={8000} />);

    act(() => {
      vi.advanceTimersByTime(7999);
    });
    expect(screen.queryByText(text)).not.toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.getByRole("status")).toHaveTextContent(text);
  });

  it("restarts the wait when timeoutMs changes", () => {
    const { rerender } = render(
      <AwaitingResult locale={locale} timeoutMs={1000} />,
    );

    rerender(<AwaitingResult locale={locale} timeoutMs={5000} />);

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(screen.queryByText(text)).not.toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(4000);
    });
    expect(screen.getByRole("status")).toHaveTextContent(text);
  });
});

describe("AwaitingResult with the room the tool belongs to", () => {
  it("marks the room in the strip and draws Arbete's real tab row and section heading, inert and hidden from assistive tech", () => {
    const { container } = render(
      <AwaitingResult locale="sv" room="work" view="board" />,
    );

    expect(
      container.querySelector('.sidekick-wait-strip [data-current="true"]'),
    ).toHaveTextContent("Arbete");
    // The head is the real components, drawn for the eye only: inert and aria-hidden, never read or focused.
    const head = container.querySelector(".sidekick-wait-head");
    expect(head).toHaveAttribute("aria-hidden", "true");
    expect(head).toHaveAttribute("inert");
    const tabs = Array.from(
      head?.querySelectorAll(".work-view-tabs__tab") ?? [],
      (tab) => tab.textContent,
    );
    expect(tabs).toEqual(["Agenda", "Status", "Projekt"]);
    expect(
      head?.querySelector('.work-view-tabs__tab[aria-pressed="true"]'),
    ).toHaveTextContent("Status");
    // Search and + (held off while loading) and ⋯; no standing create field (designsystem §3 Skapa).
    const icons = head?.querySelectorAll(".sk-iconbtn");
    expect(icons).toHaveLength(3);
    expect(icons?.[0]).toHaveAttribute("aria-disabled", "true");
    expect(icons?.[1]).toHaveAttribute("aria-disabled", "true");
    expect(icons?.[2]).not.toHaveAttribute("aria-disabled");
    expect(head?.querySelector("input")).toBeNull();
    // The skeleton never guesses the groups: one heading bar, then five rows.
    const rows = container.querySelector(".sidekick-wait-rows")?.children ?? [];
    expect(
      Array.from(rows, (el) =>
        el.classList.contains("sidekick-wait-section") ? "|" : "r",
      ).join(""),
    ).toBe("|rrrrr");
    // No chips and no stand-in rows for the header: the rows are the five skeleton rows only.
    expect(container.querySelector(".sidekick-wait-chip")).toBeNull();
    expect(container.querySelector(".sidekick-wait-chips")).toBeNull();
    expect(container.querySelectorAll(".sidekick-wait-row")).toHaveLength(5);
    // The loading line is read through the status role and never drawn: it is the only spoken text.
    const status = screen.getByRole("status");
    expect(container.querySelector(".sidekick-wait-line")).toHaveTextContent(
      "Laddar uppgifter…",
    );
    expect(spokenText(status)).toBe("Laddar uppgifter…");
  });

  it("draws Kontroll's strip with no room marked, the Back row '‹ Work', the title Memory and control under it and the tabs, with the chosen view marked", () => {
    const { container } = render(
      <AwaitingResult locale="en-US" room="control" view="changes" />,
    );

    // The strip is always drawn in the full view, with no room marked: the way back looks the same everywhere.
    const strip = container.querySelector(".sidekick-wait-strip");
    expect(strip).toHaveAttribute("aria-hidden", "true");
    expect(strip?.querySelector(".sidekick-wait-room")).not.toBeNull();
    expect(strip?.querySelector('[data-current="true"]')).toBeNull();
    const head = container.querySelector(".sidekick-wait-head");
    expect(head).toHaveAttribute("aria-hidden", "true");
    // The button keeps the parent's name for assistive technology.
    expect(
      head?.querySelector(".sk-back-header__back")?.getAttribute("aria-label"),
    ).toMatch(/ Work$/);
    expect(head?.querySelector(".sk-back-header__back svg")).not.toBeNull();
    // The Back row names where it leads, like every other Back; the view's name is a visible title under it.
    expect(head?.querySelector(".sk-back-header__label")).toHaveTextContent(
      "Work",
    );
    expect(head?.querySelector(".sk-back-header--heading")).toBeNull();
    expect(head?.querySelector("h2.control-title")).toHaveTextContent(
      "Memory and control",
    );
    expect(head?.querySelector(".sk-back-header__title")).toBeNull();
    expect(
      Array.from(
        head?.querySelectorAll(".sk-segmented__option") ?? [],
        (tab) => tab.textContent,
      ),
    ).toEqual(["Deleted", "History", "Sidekick’s memory"]);
    // A changes result opens the History tab, which holds the changes.
    expect(
      head?.querySelector('.sk-segmented__option[aria-pressed="true"]'),
    ).toHaveTextContent("History");
    expect(head?.querySelector(".control-intro")).toBeNull();
    expect(container.querySelector(".sidekick-wait-line")).toHaveTextContent(
      "Loading…",
    );
  });

  it("draws no strip and no header in an inline card, only the line and the rows", () => {
    const { container } = render(
      <AwaitingResult locale="sv" room="work" view="agenda" full={false} />,
    );

    expect(container.querySelector(".sidekick-wait-strip")).toBeNull();
    expect(container.querySelector(".sidekick-wait-head")).toBeNull();
    expect(container.querySelector(".sidekick-wait-line")).toHaveTextContent(
      "Laddar uppgifter…",
    );
    expect(container.querySelectorAll(".sidekick-wait-row")).toHaveLength(4);
  });
});

describe("AwaitingResult labels", () => {
  it("names the same rooms in Swedish and English", () => {
    expect(Object.keys(awaitingLabelsFor("sv").loadingRoom).sort()).toEqual(
      Object.keys(awaitingLabelsFor("en").loadingRoom).sort(),
    );
  });
});

describe("AwaitingResult defaults", () => {
  const swText = "Väntar på data från Claude. Be Claude öppna den igen.";

  it("waits 8 seconds before explaining the wait", () => {
    render(<AwaitingResult locale="sv" />);

    act(() => {
      vi.advanceTimersByTime(7999);
    });
    expect(screen.queryByText(swText)).not.toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.getByRole("status")).toHaveTextContent(swText);
  });
});

describe("the static placeholder in the built document", () => {
  const built = readRepoFile("backend/src/sidekick/mcp/apps/sidekick.html");

  it.each(["sv", "en"] as const)(
    "carries the %s room names and loading line of the app, hidden for the other language",
    (locale) => {
      const { rooms } = sidekickShellLabelsFor(locale);
      const names = [rooms.work, rooms.journal, rooms.contacts, rooms.shopping]
        .map((name) => `<span class="sidekick-wait-room">${name}</span>`)
        .join("");
      expect(built).toContain(
        `<div aria-hidden="true" class="sidekick-wait-strip" data-wait-locale="${locale}">${names}</div>`,
      );
      expect(built).toContain(
        `<p class="sidekick-wait-line" data-wait-locale="${locale}">${awaitingLabelsFor(locale).loading}</p>`,
      );
    },
  );

  it("takes its language from the declared app locale before the bundle runs", () => {
    expect(built).toContain('meta[name="sidekick-app-locale"]');
    expect(built).toContain(
      'html[lang="en"] [data-wait-locale="sv"],html[lang="sv"] [data-wait-locale="en"]{display:none}',
    );
  });
});

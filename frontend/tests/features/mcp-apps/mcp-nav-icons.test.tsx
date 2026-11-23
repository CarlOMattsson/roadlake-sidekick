import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { HostFeatures } from "@/features/mcp-apps/bridge";
import {
  declaredNavIcons,
  navIcons,
  navIconsFrom,
  stripFace,
  type NavIcons,
} from "@/features/mcp-apps/nav-icons";
import {
  SidekickShell,
  type RoomRegistry,
  type ShellRoomProps,
} from "@/features/mcp-apps/sidekick-shell";
import {
  sidekickShellLabelsEn,
  sidekickShellLabelsSv,
} from "@/features/mcp-apps/sidekick-shell-labels";
import type { NavEntry } from "@/features/mcp-apps/nav-state";
import { ROOM_IDS } from "@/features/mcp-apps/router";

// The room strip's cells draw the names alone by default (`auto`). jsdom has no frame width, so `auto` is never a phone's
// frame here: a phone's frame at an ordinary text size draws a glyph before the open room's name instead (stripFace,
// tested below and in the e2e spec). The other modes are the same at every width: the names alone (`off`), a glyph
// before each name (`label`) or the glyphs alone (`only`). The mode comes from the shell's own prop, or else from the
// app document's `sidekick-nav-icons` meta.
const LOCAL: HostFeatures = {
  serverTools: true,
  message: true,
  openLinks: true,
};

function Stub(props: ShellRoomProps) {
  return (
    <div data-testid={`room-${props.entry.room}`}>
      <h2>{`${props.entry.room}/${props.entry.view}`}</h2>
    </div>
  );
}
const rooms = Object.fromEntries(
  ROOM_IDS.map((room) => [room, Stub]),
) as RoomRegistry;
const workStart: NavEntry = { room: "work", view: "agenda" };

const LOCALES = [
  ["sv", sidekickShellLabelsSv, "Rum"],
  ["en", sidekickShellLabelsEn, "Rooms"],
] as const;

function setup(
  over: Partial<Parameters<typeof SidekickShell>[0]> = {},
  start: NavEntry = workStart,
) {
  return render(
    <SidekickShell
      locale="sv"
      rooms={rooms}
      start={start}
      full
      features={LOCAL}
      onSendMessage={vi.fn().mockResolvedValue(true)}
      {...over}
    />,
  );
}
function strip(label: string | RegExp = /^(Rum|Rooms)$/) {
  return screen.getByRole("navigation", { name: label });
}
function cells() {
  return Array.from(
    strip().querySelectorAll<HTMLButtonElement>(".sk-rooms__tab"),
  );
}
function roomCells() {
  return cells().filter((cell) => !cell.classList.contains("sk-rooms__more"));
}
function moreCell() {
  return strip().querySelector<HTMLButtonElement>(".sk-rooms__more")!;
}
function declare(content: string | undefined) {
  document.head.innerHTML =
    content === undefined
      ? ""
      : `<meta name="sidekick-nav-icons" content="${content}">`;
}

beforeEach(() => {
  localStorage.clear();
});
afterEach(() => {
  cleanup();
  document.head.innerHTML = "";
});

describe("navIcons()", () => {
  it("is auto when the document declares nothing", () => {
    expect(navIcons()).toBe("auto");
  });

  it.each(["auto", "off", "label", "only"] as const)(
    "reads %s from the meta",
    (mode) => {
      declare(mode);
      expect(navIcons()).toBe(mode);
    },
  );

  it("is auto for a value that is none of the four", () => {
    declare("both");
    expect(navIcons()).toBe("auto");
    declare("");
    expect(navIcons()).toBe("auto");
  });

  it("reads the meta of the document it is given", () => {
    const doc = document.implementation.createHTMLDocument("app");
    const tag = doc.createElement("meta");
    tag.name = "sidekick-nav-icons";
    tag.content = "only";
    doc.head.append(tag);
    expect(navIcons(doc)).toBe("only");
    expect(navIcons()).toBe("auto");
  });

  it("narrows an untrusted string with navIconsFrom", () => {
    expect(navIconsFrom("auto")).toBe("auto");
    expect(navIconsFrom("label")).toBe("label");
    expect(navIconsFrom("only")).toBe("only");
    expect(navIconsFrom("off")).toBe("off");
    expect(navIconsFrom("ONLY")).toBeUndefined();
    expect(navIconsFrom("")).toBeUndefined();
    expect(navIconsFrom(null)).toBeUndefined();
    expect(navIconsFrom(undefined)).toBeUndefined();
  });
});

describe("declaredNavIcons()", () => {
  it("is undefined when the document declares nothing", () => {
    expect(declaredNavIcons()).toBeUndefined();
  });

  it("is undefined for a value that is none of the four", () => {
    declare("both");
    expect(declaredNavIcons()).toBeUndefined();
    declare("");
    expect(declaredNavIcons()).toBeUndefined();
  });

  it.each(["auto", "off", "label", "only"] as const)(
    "reads the mode %s when the meta declares it",
    (mode) => {
      declare(mode);
      expect(declaredNavIcons()).toBe(mode);
    },
  );
});

describe("stripFace()", () => {
  it.each([
    ["auto", true, "label"],
    ["auto", false, "off"],
    ["off", true, "off"],
    ["off", false, "off"],
    ["label", true, "label"],
    ["label", false, "label"],
    ["only", true, "only"],
    ["only", false, "only"],
  ] as const)("draws %s with phone %s as %s", (mode, phone, face) => {
    expect(stripFace(mode, phone)).toBe(face);
  });
});

describe.each(LOCALES)("the room strip in %s", (locale, labels, navName) => {
  const names = [
    labels.rooms.start,
    labels.rooms.work,
    labels.rooms.journal,
    labels.rooms.shopping,
  ];

  /** The names alone: the markup a strip without glyphs has, as it always had. */
  function expectNamesAlone() {
    const nav = strip(navName);
    expect(nav).not.toHaveAttribute("data-icons");
    expect(roomCells().map((cell) => cell.textContent)).toEqual(names);
    for (const cell of roomCells()) {
      expect(cell.querySelector("svg")).toBeNull();
      expect(cell).not.toHaveAttribute("aria-label");
      expect(cell).not.toHaveAttribute("title");
    }
    // Mer has its ⌄ and nothing else.
    expect(moreCell().querySelectorAll("svg")).toHaveLength(1);
    expect(moreCell()).toHaveTextContent(new RegExp(`^${labels.more}$`));
    expect(moreCell()).not.toHaveAttribute("aria-label");
    expect(moreCell()).not.toHaveAttribute("title");
  }

  it("draws the names alone with the markup it always had when off is chosen", () => {
    setup({ locale, navIcons: "off" });
    expectNamesAlone();
  });

  // jsdom has no phone frame, so the default draws what the wide frame draws: the names alone, as `off`.
  it.each([
    ["no prop and no meta", () => setup({ locale })],
    ["the prop auto", () => setup({ locale, navIcons: "auto" })],
  ])("draws the names alone by default, with %s", (_, run) => {
    run();
    expectNamesAlone();
  });

  it.each(["prop", "meta"] as const)(
    "draws a glyph before each name in label mode, set by the %s",
    (source) => {
      if (source === "meta") declare("label");
      setup({ locale, ...(source === "prop" ? { navIcons: "label" } : {}) });
      expect(strip(navName)).toHaveAttribute("data-icons", "label");
      expect(roomCells()).toHaveLength(names.length);
      roomCells().forEach((cell, index) => {
        expect(cell.querySelectorAll("svg")).toHaveLength(1);
        expect(cell.querySelector("svg")).toHaveAttribute(
          "aria-hidden",
          "true",
        );
        expect(cell.querySelector(".sk-rooms__name")).toHaveTextContent(
          names[index] ?? "",
        );
        expect(cell).toHaveAttribute("aria-label", names[index] ?? "");
        expect(cell).not.toHaveAttribute("title");
      });
      // Mer: its glyph and its ⌄, then the name.
      expect(moreCell().querySelectorAll("svg")).toHaveLength(2);
      expect(moreCell()).toHaveTextContent(new RegExp(`^${labels.more}$`));
      expect(moreCell()).toHaveAttribute("aria-label", labels.more);
      expect(moreCell()).not.toHaveAttribute("title");
    },
  );

  it.each(["prop", "meta"] as const)(
    "draws the glyphs alone in only mode, set by the %s, each cell named",
    (source) => {
      if (source === "meta") declare("only");
      setup({ locale, ...(source === "prop" ? { navIcons: "only" } : {}) });
      expect(strip(navName)).toHaveAttribute("data-icons", "only");
      expect(roomCells()).toHaveLength(names.length);
      roomCells().forEach((cell, index) => {
        expect(cell.textContent).toBe("");
        expect(cell.querySelectorAll("svg")).toHaveLength(1);
        expect(cell).toHaveAttribute("aria-label", names[index] ?? "");
        expect(cell).toHaveAttribute("title", names[index] ?? "");
      });
      expect(moreCell().textContent).toBe("");
      expect(moreCell()).toHaveAttribute("aria-label", labels.more);
      expect(moreCell()).toHaveAttribute("title", labels.more);
      expect(moreCell()).not.toHaveAttribute("aria-current");
      expect(
        screen.getByRole("button", { name: labels.rooms.journal }),
      ).toBeVisible();
    },
  );

  it.each(["auto", "label", "only"] as const)(
    "names the Mer cell for the room of Mer that is open in %s mode",
    (mode) => {
      setup({ locale, navIcons: mode }, { room: "contacts", view: "list" });
      const more = moreCell();
      expect(more).toHaveAttribute("aria-current", "page");
      expect(more).toHaveAttribute(
        "aria-label",
        labels.moreWith(labels.rooms.contacts),
      );
      if (mode === "only") {
        expect(more.textContent).toBe("");
        expect(more).toHaveAttribute("title", labels.rooms.contacts);
      } else {
        expect(more).toHaveTextContent(labels.rooms.contacts);
        expect(more).not.toHaveAttribute("title");
      }
    },
  );

  it("keeps Mer's menu rows as names in every mode", () => {
    for (const mode of ["auto", "off", "label", "only"] as const) {
      setup({ locale, navIcons: mode });
      fireEvent.click(moreCell());
      const menu = screen.getByRole("group", { name: labels.moreMenu });
      const row = menu.querySelector("button");
      expect(row).toHaveTextContent(labels.rooms.contacts);
      expect(row?.querySelector("svg")).toBeNull();
      cleanup();
    }
  });
});

describe("which source wins", () => {
  it("lets the prop win over the meta", () => {
    declare("only");
    setup({ navIcons: "label" });
    expect(strip()).toHaveAttribute("data-icons", "label");
    cleanup();
    setup({ navIcons: "off" });
    expect(strip()).not.toHaveAttribute("data-icons");
    expect(roomCells()[0]).toHaveTextContent("Start");
  });

  it("falls back to the meta without a prop", () => {
    declare("label");
    setup();
    expect(strip()).toHaveAttribute("data-icons", "label");
  });

  it("ignores a meta of off without a prop, and draws the names alone", () => {
    declare("off");
    setup();
    expect(strip()).not.toHaveAttribute("data-icons");
    for (const cell of roomCells()) {
      expect(cell.querySelector("svg")).toBeNull();
    }
  });

  it("falls back to the default, the names alone in jsdom, for an unknown meta value", () => {
    declare("sparkles");
    setup();
    expect(strip()).not.toHaveAttribute("data-icons");
    expect(roomCells().map((cell) => cell.textContent)).toEqual([
      "Start",
      "Arbete",
      "Dagbok",
      "Inköp",
    ]);
    for (const cell of roomCells()) {
      expect(cell.querySelector("svg")).toBeNull();
    }
  });
});

describe("the strip with glyphs alone, from the keyboard", () => {
  it.each(["sv", "en"] as const)(
    "opens Mer on a press and lists its room as text in %s",
    (locale) => {
      const labels =
        locale === "sv" ? sidekickShellLabelsSv : sidekickShellLabelsEn;
      const mode: NavIcons = "only";
      setup({ locale, navIcons: mode });
      const more = moreCell();
      expect(more).toHaveAttribute("aria-expanded", "false");
      fireEvent.click(more);
      expect(more).toHaveAttribute("aria-expanded", "true");
      const menu = screen.getByRole("group", { name: labels.moreMenu });
      expect(menu).toHaveTextContent(labels.rooms.contacts);
    },
  );

  it("opens Mer with the arrow down and puts the focus on its first room", () => {
    setup({ navIcons: "only" });
    const more = moreCell();
    more.focus();
    fireEvent.keyDown(more, { key: "ArrowDown" });
    expect(screen.getByRole("button", { name: "Kontakter" })).toHaveFocus();
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    expect(more).toHaveFocus();
  });

  it("goes to a room by its glyph cell without a model turn", () => {
    const onSendMessage = vi.fn().mockResolvedValue(true);
    setup({ navIcons: "only", onSendMessage });
    fireEvent.click(screen.getByRole("button", { name: "Inköp" }));
    expect(
      document.querySelector('[data-room="shopping"]'),
    ).not.toHaveAttribute("hidden");
    expect(screen.getByRole("button", { name: "Inköp" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(onSendMessage).not.toHaveBeenCalled();
  });
});

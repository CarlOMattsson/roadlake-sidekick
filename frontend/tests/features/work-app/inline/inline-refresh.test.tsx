import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { WorkRoom } from "@/features/work-app/room";
import {
  refreshLabelsEn,
  refreshLabelsSv,
} from "@/features/work-app/inline/inline-refresh-labels";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import type { RoomProps } from "@/features/mcp-apps/room-types";
import { deferred } from "@tests/helpers/deferred";
import {
  agendaItems,
  installFixedClock,
} from "@tests/helpers/inline-summary-fixtures";

// The inline Board and Agenda cards read themselves again from a corner button. These are simulated-host tests (the
// work room with a plain transport and a fixed clock), not a test in a real Claude or Android host. The fixed clock
// is 25 Oct 2026, 12:00 UTC, which is 13:00 in the owner's zone.
installFixedClock();

function task(id: string, title: string, status: string, due: string) {
  return { kind: "task", id, title, status, due_at: due, version: 1 };
}

const before = task(
  "t1",
  "Ring Anna om offerten",
  "todo",
  "2026-10-26T09:00:00Z",
);
const after = task("t2", "Skicka fakturan", "todo", "2026-10-26T10:00:00Z");

/** A get_work_board result as the host hands it to the card: the columns, and the filters it was read with. */
function boardResult(item: ReturnType<typeof task>, filters: object = {}) {
  return {
    columns: { todo: [item], in_progress: [], completed: [] },
    filters,
    next_cursor: null,
  };
}

function agendaResult(items: unknown[], filters: object = {}) {
  return { items, filters, next_cursor: null };
}

type Call = (name: string, args: object) => Promise<unknown>;

function setup(
  initial: unknown,
  call: Call,
  over: Partial<RoomProps> & {
    supportsTool?: (name: string) => boolean;
  } = {},
) {
  const { supportsTool, ...props } = over;
  const callMock = vi.fn(call);
  const view = render(
    <WorkRoom
      mode="inline"
      initial={initial}
      resultId={1}
      fullscreenAvailable
      transport={
        {
          call: callMock,
          requestDisplayMode: vi.fn().mockResolvedValue("inline"),
          updateModelContext: vi.fn().mockResolvedValue(undefined),
          supportsTool,
        } as unknown as RoomProps["transport"]
      }
      {...props}
    />,
  );
  return { call: callMock, ...view };
}

function setLocale(lang: string) {
  document.head.innerHTML = `<meta name="sidekick-app-locale" content="${lang}">`;
}

beforeEach(() => setLocale("en"));

const locales = [
  ["en", refreshLabelsEn, workEn, "Updated 13:00"],
  ["sv", refreshLabelsSv, workSv, "Uppdaterad 13:00"],
] as const;

describe("the refresh labels", () => {
  it("have the same keys in Swedish and English", () => {
    expect(Object.keys(refreshLabelsSv).sort()).toEqual(
      Object.keys(refreshLabelsEn).sort(),
    );
  });
});

describe.each(locales)(
  "the inline Board card refresh (%s)",
  (lang, words, work, stamp) => {
    beforeEach(() => setLocale(lang));

    it("reads the board again with its filters, shows the new data and the time, and keeps focus on the button", async () => {
      const { call } = setup(boardResult(before, { status: "todo" }), () =>
        Promise.resolve(boardResult(after, { status: "todo" })),
      );
      expect(screen.getByText(before.title)).toBeInTheDocument();
      const button = screen.getByRole("button", { name: words.refresh });
      expect(button).toHaveAttribute("title", words.refresh);
      await userEvent.click(button);
      expect(await screen.findByText(after.title)).toBeInTheDocument();
      expect(screen.queryByText(before.title)).toBeNull();
      expect(call).toHaveBeenCalledWith(
        "get_work_board",
        expect.objectContaining({ status: "todo" }),
      );
      expect(
        screen.getByText(`${work.title} · ${work.status} · ${stamp}`),
      ).toBeInTheDocument();
      // The card was not drawn again: the same button, still focused.
      expect(screen.getByRole("button", { name: words.refresh })).toBe(button);
      expect(button).toHaveFocus();
      expect(button).not.toHaveAttribute("aria-busy");
    });

    it("says it could not refresh, keeps the data, and the next successful refresh removes the line", async () => {
      let fail = true;
      setup(boardResult(before), () =>
        fail
          ? Promise.reject(new Error("down"))
          : Promise.resolve(boardResult(after)),
      );
      await userEvent.click(
        screen.getByRole("button", { name: words.refresh }),
      );
      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent(words.failed);
      expect(alert).toHaveClass("work-compact-status");
      expect(alert).toHaveAttribute("data-tone", "overdue");
      expect(screen.getByText(before.title)).toBeInTheDocument();
      // No successful refresh yet, so the head still says the date.
      expect(screen.getByRole("heading", { level: 2 })).not.toHaveTextContent(
        stamp,
      );
      fail = false;
      await userEvent.click(
        screen.getByRole("button", { name: words.refresh }),
      );
      expect(await screen.findByText(after.title)).toBeInTheDocument();
      expect(screen.queryByRole("alert")).toBeNull();
    });

    it("is busy while it reads: aria-busy, aria-disabled, a polite line, and a second press reads nothing", async () => {
      const answer = deferred<unknown>();
      const { call } = setup(boardResult(before), () => answer.promise);
      const button = screen.getByRole("button", { name: words.refresh });
      await userEvent.click(button);
      expect(button).toHaveAttribute("aria-busy", "true");
      expect(button).toHaveAttribute("aria-disabled", "true");
      expect(button).not.toBeDisabled();
      expect(screen.getByText(words.refreshing)).toHaveAttribute(
        "aria-live",
        "polite",
      );
      await userEvent.click(button);
      expect(call).toHaveBeenCalledTimes(1);
      answer.resolve(boardResult(after));
      expect(await screen.findByText(after.title)).toBeInTheDocument();
      await waitFor(() => expect(button).not.toHaveAttribute("aria-busy"));
      expect(screen.queryByText(words.refreshing)).toBeNull();
    });

    it("has no button when the host does not let the app call tools, or cannot answer get_work_board", () => {
      const first = setup(boardResult(before), vi.fn(), { toolCalls: false });
      expect(screen.queryByRole("button", { name: words.refresh })).toBeNull();
      first.unmount();
      setup(boardResult(before), vi.fn(), {
        supportsTool: (name) => name !== "get_work_board",
      });
      expect(screen.queryByRole("button", { name: words.refresh })).toBeNull();
      // The card itself is still drawn.
      expect(screen.getByText(before.title)).toBeInTheDocument();
    });

    it("has the button when only another tool is missing", () => {
      setup(boardResult(before), vi.fn(), {
        supportsTool: (name) => name !== "get_work_agenda",
      });
      expect(
        screen.getByRole("button", { name: words.refresh }),
      ).toBeInTheDocument();
    });
  },
);

describe.each(locales)(
  "the inline Agenda card refresh (%s)",
  (lang, words, work, stamp) => {
    beforeEach(() => setLocale(lang));

    it("reads the agenda again with its filters and puts the time in the kicker", async () => {
      const fresh = [
        {
          ...agendaItems[2]!,
          id: "019f0000-0000-7000-8000-0000000000b9",
          title: "Boka tid hos tandläkaren",
        },
      ];
      const { call } = setup(
        agendaResult(agendaItems, { status: "todo" }),
        () => Promise.resolve(agendaResult(fresh, { status: "todo" })),
      );
      expect(screen.getByText(/^(Work|Arbete) · /)).toBeInTheDocument();
      await userEvent.click(
        screen.getByRole("button", { name: words.refresh }),
      );
      expect(
        await screen.findByText(/Boka tid hos tandläkaren/),
      ).toBeInTheDocument();
      expect(screen.queryByText(/Betala faktura/)).toBeNull();
      expect(call).toHaveBeenCalledWith(
        "get_work_agenda",
        expect.objectContaining({ status: "todo" }),
      );
      // The kicker is the app, the view and the time of the last read.
      expect(
        screen.getByText(`${work.title} · Agenda · ${stamp}`),
      ).toBeInTheDocument();
      expect(screen.getByRole("button", { name: words.refresh })).toHaveFocus();
    });

    it("fails calmly: the line under the kicker, the rows kept, and a retry that works", async () => {
      let fail = true;
      setup(agendaResult(agendaItems), () =>
        fail
          ? Promise.reject(new Error("down"))
          : Promise.resolve(agendaResult([agendaItems[0]!])),
      );
      await userEvent.click(
        screen.getByRole("button", { name: words.refresh }),
      );
      expect(await screen.findByRole("alert")).toHaveTextContent(words.failed);
      expect(screen.getByText(/Betala faktura/)).toBeInTheDocument();
      fail = false;
      await userEvent.click(
        screen.getByRole("button", { name: words.refresh }),
      );
      await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
      expect(screen.queryByText(/Skriv offerten/)).toBeNull();
    });

    it("refreshes the waiting card too, and appends the time to its kicker", async () => {
      const { call } = setup(agendaResult([], { waiting: "waiting" }), () =>
        Promise.resolve(agendaResult([], { waiting: "waiting" })),
      );
      await userEvent.click(
        screen.getByRole("button", { name: words.refresh }),
      );
      await waitFor(() =>
        expect(
          screen.getByText(
            (text) =>
              text.startsWith(`${work.title} · `) &&
              text.endsWith(` · ${stamp}`),
          ),
        ).toBeInTheDocument(),
      );
      expect(call).toHaveBeenCalledWith(
        "get_work_agenda",
        expect.objectContaining({ waiting: "waiting" }),
      );
    });

    it("has no button when the host does not let the app call tools, or cannot answer get_work_agenda", () => {
      const first = setup(agendaResult(agendaItems), vi.fn(), {
        toolCalls: false,
      });
      expect(screen.queryByRole("button", { name: words.refresh })).toBeNull();
      first.unmount();
      setup(agendaResult(agendaItems), vi.fn(), {
        supportsTool: (name) => name !== "get_work_agenda",
      });
      expect(screen.queryByRole("button", { name: words.refresh })).toBeNull();
    });
  },
);

describe("the full view", () => {
  it("has no corner refresh button (it has its own refresh)", async () => {
    const { container } = setup(
      boardResult(before),
      (name) =>
        name === "get_work_board"
          ? Promise.resolve(boardResult(before))
          : Promise.reject(new Error(`unexpected ${name}`)),
      { mode: "full", fullscreenAvailable: false },
    );
    await waitFor(() =>
      expect(screen.getAllByText(before.title).length).toBeGreaterThan(0),
    );
    expect(container.querySelector(".work-inline-refresh")).toBeNull();
  });
});

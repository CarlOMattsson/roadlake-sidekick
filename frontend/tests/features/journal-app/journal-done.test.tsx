// «Gjort» in the diary's day view (Gjort 2026-11-08): the count line,
// folded and open, no section when nothing was done, an older answer without `done`, and the transport's check.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { doneCountLine } from "@/features/journal-app/done-section";
import { journalEn, journalSv } from "@/features/journal-app/labels";
import { JournalView } from "@/features/journal-app/journal-view";
import {
  createJournalTransport,
  doneFrom,
  rootFromToolResult,
  type JournalDay,
  type JournalDone,
  type JournalTransport,
} from "@/features/journal-app/transport";

const DATE = "2026-11-03";
const at = (hm: string) => `${DATE}T${hm}:00Z`;

function done(overrides: Partial<JournalDone> = {}): JournalDone {
  return {
    tasks: [
      {
        id: "t1",
        title: "Betala elräkningen",
        completed_at: at("07:40"),
        project_title: null,
        recurring: false,
      },
      {
        id: "t2",
        title: "Beställ kakel",
        completed_at: at("14:20"),
        project_title: "Renovering av köket",
        recurring: false,
      },
      {
        id: "t3",
        title: "Boka tvättstugan",
        completed_at: at("10:30"),
        project_title: null,
        recurring: true,
      },
    ],
    steps: [
      {
        id: "s1",
        title: "Mät väggytan",
        task_id: "t2",
        task_title: "Beställ kakel",
        completed_at: at("13:10"),
      },
    ],
    purchases: [
      {
        id: "p1",
        title: "Fogmassa",
        list_id: "l2",
        list_title: "Bygghandeln",
        purchased_at: at("11:40"),
      },
      {
        id: "p2",
        title: "Havregryn",
        list_id: "l1",
        list_title: "Veckohandling",
        purchased_at: at("16:05"),
      },
      {
        id: "p3",
        title: "Smör",
        list_id: "l1",
        list_title: "Veckohandling",
        purchased_at: at("16:07"),
      },
    ],
    counts: { tasks: 3, steps: 1, purchases: 3 },
    truncated: false,
    ...overrides,
  };
}

const none: JournalDone = {
  tasks: [],
  steps: [],
  purchases: [],
  counts: { tasks: 0, steps: 0, purchases: 0 },
  truncated: false,
};

function day(extra: Partial<JournalDay> = {}): JournalDay {
  return {
    journal_date: DATE,
    entries: [],
    next_cursor: null,
    summary: {
      journal_date: DATE,
      exists: true,
      status: "current",
      content: { overview: "Dagen handlade om köket." },
    },
    ...extra,
  };
}

function transport(): JournalTransport {
  return {
    getDay: vi.fn((date: string) =>
      Promise.resolve(day({ journal_date: date })),
    ),
    listEntryDates: vi.fn(() => Promise.resolve([])),
    getEntry: vi.fn(),
    getSource: vi.fn(),
    getDraft: vi.fn(),
    updateDraft: vi.fn(),
    rejectDraft: vi.fn(),
    finalizeDraft: vi.fn(),
  };
}

/** The count line as read: the no-break spaces of done-section.tsx as plain spaces. */
const plain = (text: string) => text.replace(/\u00a0/g, " ");

describe("Gjort count line", () => {
  it("names only the nonzero parts, with Swedish and English singular and plural", () => {
    expect(plain(doneCountLine(done(), journalSv))).toBe(
      "3 uppgifter · 1 steg · 3 varor köpta",
    );
    expect(plain(doneCountLine(done(), journalEn))).toBe(
      "3 tasks · 1 step · 3 items bought",
    );
    const one = done({ counts: { tasks: 1, steps: 0, purchases: 1 } });
    expect(plain(doneCountLine(one, journalSv))).toBe(
      "1 uppgift · 1 vara köpt",
    );
    expect(plain(doneCountLine(one, journalEn))).toBe("1 task · 1 item bought");
    const steps = done({ counts: { tasks: 0, steps: 4, purchases: 0 } });
    expect(plain(doneCountLine(steps, journalSv))).toBe("4 steg");
    expect(plain(doneCountLine(steps, journalEn))).toBe("4 steps");
    expect(doneCountLine(none, journalSv)).toBe("");
  });

  it("breaks only before «·», never inside a part", () => {
    const line = doneCountLine(done(), journalSv);
    // The only ordinary spaces stand right before a «·».
    expect(line.match(/ (?!·)/g)).toBeNull();
    expect(line).toBe(
      "3\u00a0uppgifter ·\u00a01\u00a0steg ·\u00a03\u00a0varor\u00a0köpta",
    );
  });

  it("counts the real totals when the server cut a list, and the open list says how many more", async () => {
    const user = userEvent.setup();
    const cut = done({
      counts: { tasks: 53, steps: 1, purchases: 3 },
      truncated: true,
    });
    expect(plain(doneCountLine(cut, journalSv))).toBe(
      "53 uppgifter · 1 steg · 3 varor köpta",
    );
    render(
      <JournalView
        transport={transport()}
        initial={{ kind: "day", page: day({ done: cut }) }}
        labels={journalSv}
      />,
    );
    await user.click(screen.getByRole("button", { name: /^Gjort/ }));
    expect(screen.getByText("+50 fler")).toBeInTheDocument();
    // Only the cut list says it: steps and purchases are whole.
    expect(screen.getAllByText(/^\+\d+ fler$/)).toHaveLength(1);
  });
});

describe("Gjort section", () => {
  it("is folded by default with the count line in its fold row, and opens to the read-only rows", async () => {
    const user = userEvent.setup();
    render(
      <JournalView
        transport={transport()}
        initial={{ kind: "day", page: day({ done: done() }) }}
        labels={journalSv}
      />,
    );
    const fold = screen.getByRole("button", { name: /^Gjort/ });
    expect(fold).toHaveAttribute("aria-expanded", "false");
    expect(plain(fold.textContent ?? "")).toContain(
      "3 uppgifter · 1 steg · 3 varor köpta",
    );
    expect(screen.queryByText("Betala elräkningen")).toBeNull();

    await user.click(fold);
    expect(fold).toHaveAttribute("aria-expanded", "true");
    const section = screen.getByRole("region", { name: "Gjort" });
    const tasks = within(section).getByRole("list", { name: "Uppgifter" });
    expect(within(tasks).getAllByRole("listitem")).toHaveLength(3);
    expect(within(tasks).getByText("Beställ kakel")).toBeInTheDocument();
    expect(tasks).toHaveTextContent("Renovering av köket");
    expect(tasks).toHaveTextContent("Återkommande");
    const steps = within(section).getByRole("list", { name: "Steg" });
    expect(steps).toHaveTextContent("Mät väggytan");
    expect(steps).toHaveTextContent("Beställ kakel");
    // The bought items: one row per list, in the order the lists first appear, the items as the row's text.
    const bought = within(section).getByRole("list", { name: "Köpta varor" });
    const lists = within(bought).getAllByRole("listitem");
    expect(
      lists.map((li) => li.querySelector(".sk-row-primary")?.textContent),
    ).toEqual(["Bygghandeln", "Veckohandling"]);
    expect(lists[1]).toHaveTextContent("2 varor");
    expect(lists[1]).toHaveTextContent("Havregryn, Smör");
    // Read-only: nothing in the open section is a control but the fold row itself.
    expect(within(section).getAllByRole("button")).toEqual([fold]);
    expect(within(section).queryByRole("checkbox")).toBeNull();

    await user.click(fold);
    expect(screen.queryByText("Betala elräkningen")).toBeNull();
  });

  it("stands under the day's summary, before the notes heading", () => {
    render(
      <JournalView
        transport={transport()}
        initial={{
          kind: "day",
          page: day({
            done: done(),
            entries: [
              {
                id: "e1",
                source_id: "src1",
                journal_date: DATE,
                occurred_at: at("08:15"),
                title: "Morgonpromenad",
                summary: null,
                key_points: [],
                project_ids: [],
                task_ids: [],
                contact_ids: [],
                tags: [],
                archived: false,
                version: 1,
              },
            ],
          }),
        }}
        labels={journalSv}
      />,
    );
    const summary = document.querySelector(".journal-day-summary");
    expect(summary?.nextElementSibling).toHaveClass("journal-done");
    expect(summary?.nextElementSibling?.nextElementSibling).toHaveTextContent(
      "Anteckningar",
    );
  });

  it("shows on an empty day after its empty state, in English", () => {
    render(
      <JournalView
        transport={transport()}
        initial={{
          kind: "day",
          page: day({
            summary: {
              journal_date: DATE,
              exists: false,
              status: null,
              content: null,
            },
            done: done({
              tasks: done().tasks.slice(0, 1),
              steps: [],
              purchases: [],
              counts: { tasks: 1, steps: 0, purchases: 0 },
            }),
          }),
        }}
        labels={journalEn}
        onTellClaude={vi.fn()}
      />,
    );
    const fold = screen.getByRole("button", { name: /^Done/ });
    expect(plain(fold.textContent ?? "")).toContain("1 task");
    expect(
      document.querySelector(".journal-empty-state")?.nextElementSibling,
    ).toHaveClass("journal-done");
  });

  it("is not shown when every count is zero", () => {
    render(
      <JournalView
        transport={transport()}
        initial={{ kind: "day", page: day({ done: none }) }}
        labels={journalSv}
      />,
    );
    expect(screen.queryByRole("button", { name: /^Gjort/ })).toBeNull();
    expect(document.querySelector(".journal-done")).toBeNull();
  });

  it("is not shown for an older answer without `done`, and the day still draws", () => {
    render(
      <JournalView
        transport={transport()}
        initial={{ kind: "day", page: day() }}
        labels={journalSv}
      />,
    );
    expect(screen.getByText("Dagen handlade om köket.")).toBeInTheDocument();
    expect(document.querySelector(".journal-done")).toBeNull();
  });
});

describe("Gjort in the transport", () => {
  const structured = {
    journal_date: DATE,
    entries: [],
    next_cursor: null,
    summary: { journal_date: DATE, exists: false, status: null, content: null },
  };

  it("keeps a well-formed `done` on the root day and leaves it out of an older answer", () => {
    const withDone = rootFromToolResult({ ...structured, done: done() });
    expect(withDone?.kind === "day" && withDone.page.done).toEqual(done());
    const older = rootFromToolResult(structured);
    expect(older?.kind).toBe("day");
    expect(older?.kind === "day" && "done" in older.page).toBe(false);
  });

  it("drops a malformed `done` instead of drawing it, and fills counts and truncated it lacks", () => {
    expect(doneFrom({ tasks: "x", steps: [], purchases: [] })).toBeUndefined();
    expect(
      doneFrom({ tasks: [{ id: 1, title: "x" }], steps: [], purchases: [] }),
    ).toBeUndefined();
    expect(doneFrom(null)).toBeUndefined();
    const { tasks, steps, purchases } = done();
    const lists = { tasks, steps, purchases };
    expect(doneFrom(lists)).toEqual({
      ...lists,
      counts: { tasks: 3, steps: 1, purchases: 3 },
      truncated: false,
    });
  });

  it("checks `done` on a day the view reads itself", async () => {
    const call = vi.fn(() =>
      Promise.resolve({ ...structured, done: { tasks: null } }),
    );
    const read = await createJournalTransport(call as never).getDay(DATE);
    expect(read.journal_date).toBe(DATE);
    expect("done" in read).toBe(false);
    call.mockResolvedValueOnce({ ...structured, done: done() } as never);
    expect(
      (await createJournalTransport(call as never).getDay(DATE)).done,
    ).toEqual(done());
  });

  it("draws a 200 answer with no entries as the empty day, with Gjort when something was done", async () => {
    // The server now answers a day without notes with 200, `entries: []` and `done`, not not_found.
    const emptyWithDone = {
      ...structured,
      done: {
        ...done(),
        steps: [],
        purchases: [],
        counts: { tasks: 3, steps: 0, purchases: 0 },
      },
    };
    const call = vi.fn(() => Promise.resolve(emptyWithDone));
    const read = await createJournalTransport(call as never).getDay(DATE);
    expect(read.entries).toEqual([]);
    const root = rootFromToolResult(emptyWithDone);
    expect(root?.kind).toBe("day");
    for (const page of [read, root?.kind === "day" ? root.page : read]) {
      const { unmount } = render(
        <JournalView
          transport={transport()}
          initial={{ kind: "day", page }}
          labels={journalSv}
          onTellClaude={vi.fn()}
        />,
      );
      expect(
        screen.getByText("Inget skrivet den här dagen."),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", {
          name: /^Skicka till Claude: Jag vill berätta om .+ så att det sparas i dagboken\.$/,
        }),
      ).toBeInTheDocument();
      expect(screen.queryByText("Anteckningar")).toBeNull();
      const fold = screen.getByRole("button", { name: /^Gjort/ });
      expect(fold.textContent?.replace(/\u00a0/g, " ")).toContain(
        "3 uppgifter",
      );
      unmount();
    }
  });

  it("still reads not_found from an older server as the empty day, and other errors stay errors", async () => {
    const notFound = Object.assign(new Error("nf"), { code: "not_found" });
    const gone = createJournalTransport(vi.fn(() => Promise.reject(notFound)));
    const empty = await gone.getDay(DATE);
    expect(empty.entries).toEqual([]);
    expect(empty.done).toBeUndefined();
    const broken = createJournalTransport(
      vi.fn(() => Promise.reject(new Error("boom"))),
    );
    await expect(broken.getDay(DATE)).rejects.toThrow("boom");
  });
});

describe("Gjort rows per kind", () => {
  /** Six tasks: three more than a kind shows before "Visa alla (6)". */
  function busy(): JournalDone {
    const base = done();
    const extra = ["Ring Bo", "Skicka offerten", "Boka hantverkare"].map(
      (title, index) => ({
        id: `t${index + 4}`,
        title,
        completed_at: at(`1${index + 5}:00`),
        project_title: null,
        recurring: false,
      }),
    );
    return done({
      tasks: [...base.tasks, ...extra],
      counts: { ...base.counts, tasks: 6 },
    });
  }

  it("shows three rows of a kind and opens the rest in place, and folds them again", async () => {
    const user = userEvent.setup();
    render(
      <JournalView
        transport={transport()}
        initial={{ kind: "day", page: day({ done: busy() }) }}
        labels={journalSv}
      />,
    );
    await user.click(screen.getByRole("button", { name: /^Gjort/ }));
    const section = screen.getByRole("region", { name: "Gjort" });
    const tasks = within(section).getByRole("list", { name: "Uppgifter" });
    expect(within(tasks).getAllByRole("listitem")).toHaveLength(3);
    const more = within(section).getByRole("button", {
      name: journalSv.moreShowAll(6),
    });
    expect(more).toHaveAttribute("aria-expanded", "false");
    expect(more).toHaveAttribute("aria-controls", tasks.id);
    // Steps (1) and purchases (2 lists) are within the limit: no button of their own.
    expect(
      within(section).getAllByRole("button", { name: /Visa alla/ }),
    ).toHaveLength(1);

    await user.click(more);
    expect(within(tasks).getAllByRole("listitem")).toHaveLength(6);
    expect(more).toHaveAttribute("aria-expanded", "true");
    expect(more).toHaveTextContent(journalSv.showFewer);
    expect(more).toHaveFocus();

    await user.click(more);
    expect(within(tasks).getAllByRole("listitem")).toHaveLength(3);
  });

  it("starts the next day with three rows again, the section still open", async () => {
    const user = userEvent.setup();
    const shown = busy();
    const reading = transport();
    vi.mocked(reading.getDay).mockImplementation((date: string) =>
      Promise.resolve(day({ journal_date: date, done: shown })),
    );
    render(
      <JournalView
        transport={reading}
        initial={{ kind: "day", page: day({ done: shown }) }}
        labels={journalEn}
        fullscreen
      />,
    );
    await user.click(screen.getByRole("button", { name: /^Done/ }));
    await user.click(
      screen.getByRole("button", { name: journalEn.moreShowAll(6) }),
    );
    expect(
      within(screen.getByRole("list", { name: "Tasks" })).getAllByRole(
        "listitem",
      ),
    ).toHaveLength(6);

    await user.click(screen.getByRole("button", { name: /^Mon 2 November/ }));
    await waitFor(() =>
      expect(reading.getDay).toHaveBeenCalledWith("2026-11-02"),
    );
    await waitFor(() =>
      expect(
        within(screen.getByRole("list", { name: "Tasks" })).getAllByRole(
          "listitem",
        ),
      ).toHaveLength(3),
    );
    expect(
      screen.getByRole("button", { name: journalEn.moreShowAll(6) }),
    ).toHaveAttribute("aria-expanded", "false");
  });

  it("says the server's cut once the kind is shown in full", async () => {
    const user = userEvent.setup();
    const base = busy();
    const cut = {
      ...base,
      counts: { ...base.counts, tasks: 60 },
      truncated: true,
    };
    render(
      <JournalView
        transport={transport()}
        initial={{ kind: "day", page: day({ done: cut }) }}
        labels={journalSv}
      />,
    );
    await user.click(screen.getByRole("button", { name: /^Gjort/ }));
    expect(screen.queryByText("+54 fler")).toBeNull();
    // The server sent part of the kind, so the button does not promise all of it.
    expect(
      screen.queryByRole("button", { name: journalSv.moreShowAll(6) }),
    ).toBeNull();
    await user.click(
      screen.getByRole("button", { name: journalSv.moreShowMore(3) }),
    );
    expect(screen.getByText("+54 fler")).toBeInTheDocument();
  });
});

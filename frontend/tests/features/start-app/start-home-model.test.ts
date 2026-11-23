import { describe, expect, it } from "vitest";

import { HOME_LABELS, homeLabelsFor } from "@/features/start-app/home/labels";
import {
  automationsMeta,
  failedParts,
  homeHeading,
  isQuiet,
  isStartHome,
  phraseTitle,
  PHRASE_TITLE_MAX,
  readyRows,
  readyTime,
  recordTarget,
  sinceLastLine,
  suggestionsMeta,
  todayMeta,
  todayMore,
  waitingMeta,
  waitingMore,
} from "@/features/start-app/home/model";
import {
  fullStart,
  homeIds,
  partlyStart,
  quietStart,
} from "../../e2e/start-home-fixtures";
import { inboxPage } from "../../e2e/suggestions-fixtures";

const sv = homeLabelsFor("sv");
const en = homeLabelsFor("en");
const now = new Date("2026-11-23T08:00:00Z");
const none = new Set<string>();

function keysOf(value: object, prefix = ""): string[] {
  return Object.entries(value).flatMap(([key, entry]) =>
    typeof entry === "object" && entry !== null
      ? keysOf(entry as object, `${prefix}${key}.`)
      : [`${prefix}${key}`],
  );
}

describe("the home view's labels", () => {
  it("have the same keys in Swedish and English", () => {
    expect(keysOf(HOME_LABELS.sv).sort()).toEqual(
      keysOf(HOME_LABELS.en).sort(),
    );
  });

  it("fall back to Swedish, the app's first language", () => {
    expect(homeLabelsFor("fr").openAgenda).toBe("Öppna Agenda");
    expect(homeLabelsFor("en-GB").openAgenda).toBe("Open Agenda");
  });
});

describe("reading get_start", () => {
  it("knows a get_start answer from a list result", () => {
    expect(isStartHome(fullStart)).toBe(true);
    expect(isStartHome(quietStart)).toBe(true);
    expect(isStartHome(inboxPage)).toBe(false);
    expect(isStartHome({ day: "today" })).toBe(false);
    expect(isStartHome(null)).toBe(false);
  });

  it("titles the page with the day, in both languages", () => {
    expect(homeHeading("2026-11-23", sv.dateLocale)).toBe("Måndag 23 november");
    expect(homeHeading("2026-11-23", en.dateLocale)).toBe("Monday 23 November");
  });

  it("says when a conversation became ready, to the minute", () => {
    expect(readyTime("17:00:00")).toBe("17:00");
    expect(readyTime("7:05")).toBe("07:05");
    expect(readyTime("soon")).toBe("soon");
  });

  it("names only the parts that failed and have a place on the page", () => {
    expect(failedParts(partlyStart)).toEqual(["today"]);
    expect(
      failedParts({
        day: "2026-11-23",
        unavailable: [
          { part: "more", error: "unavailable" },
          { part: "insight", error: "unavailable" },
          { part: "waiting", error: "unavailable" },
        ],
      }),
    ).toEqual(["waiting"]);
    expect(failedParts(fullStart)).toEqual([]);
  });

  it("calls a day quiet only when nothing asks for the owner", () => {
    expect(isQuiet(quietStart, none)).toBe(true);
    expect(isQuiet(fullStart, none)).toBe(false);
    // A failed part is not quiet: the page says what it could not read.
    expect(
      isQuiet(
        { day: "2026-11-23", unavailable: partlyStart.unavailable },
        none,
      ),
    ).toBe(false);
    // Pending suggestions alone keep the day quiet: their row stands under the line.
    expect(
      isQuiet(
        {
          day: "2026-11-23",
          suggestions: { pending_count: 2, automation_count: 1 },
        },
        none,
      ),
    ).toBe(true);
  });

  it("leaves out a ready conversation skipped here", () => {
    expect(readyRows(fullStart, none)).toHaveLength(1);
    expect(readyRows(fullStart, new Set([homeIds.evening]))).toHaveLength(0);
    expect(
      isQuiet(
        { day: "2026-11-23", ready: fullStart.ready },
        new Set([homeIds.evening]),
      ),
    ).toBe(true);
  });
});

describe("the rows of today", () => {
  const [late, recent, due] = fullStart.today!.items;

  it("say how late an overdue task is, in the overdue tone", () => {
    expect(todayMeta(late!, now, sv)).toEqual({
      due: "8 dagar försenad",
      overdue: true,
      project: undefined,
    });
    expect(todayMeta(recent!, now, en)).toEqual({
      due: "2 days overdue",
      overdue: true,
      project: "Köksrenovering",
    });
  });

  it("say today with the owner's clock time", () => {
    expect(todayMeta(due!, now, sv)).toEqual({
      due: "Idag 16:00",
      overdue: false,
      project: undefined,
    });
    expect(todayMeta({ ...due!, due_at: null }, now, en).due).toBe("Today");
  });

  it("count what the rows do not show", () => {
    expect(todayMore(fullStart.today!)).toBe(1);
    expect(
      todayMore({ ...fullStart.today!, overdue_count: 1, today_count: 2 }),
    ).toBe(0);
  });

  it("open a Task or a Project, and nothing for another kind", () => {
    expect(recordTarget(late!)).toEqual({
      room: "work",
      view: "task",
      id: homeIds.overdueOld,
      label: "Boka tid hos tandläkaren",
    });
    expect(recordTarget({ ...late!, kind: "project" })?.view).toBe("project");
    expect(recordTarget({ ...late!, kind: "step" })).toBeUndefined();
  });
});

describe("what waits on others", () => {
  const [erik, nobody] = fullStart.waiting!.items;

  it("names the contact and the day it began", () => {
    expect(waitingMeta(erik!, now, sv)).toBe("Erik Sjöstrand · sedan 13 nov");
    expect(waitingMeta(erik!, now, en)).toBe("Erik Sjöstrand · since 13 Nov");
  });

  it("gives only the day when the name could not be read", () => {
    expect(waitingMeta(nobody!, now, sv)).toBe("sedan 18 nov");
  });

  it("counts the rest", () => {
    expect(waitingMore(fullStart.waiting!)).toBe(1);
    expect(sv.waitingMore(1, true)).toBe("1+ till väntar");
  });
});

describe("the ways to the suggestions and the automations", () => {
  it("say how many suggestions wait, and nothing when none do", () => {
    expect(suggestionsMeta(fullStart, sv)).toBe("5 väntar på ditt svar");
    expect(suggestionsMeta(partlyStart, en)).toBe("1 waits for your answer");
    expect(suggestionsMeta(quietStart, sv)).toBeUndefined();
  });

  it("put what failed today before what happened since the last look", () => {
    expect(automationsMeta(partlyStart, sv)).toEqual({
      text: "1 misslyckades idag",
      failed: true,
    });
    expect(automationsMeta(fullStart, sv)).toEqual({
      text: "Sedan sist: 3 körningar · 5 nya förslag",
      failed: false,
    });
    expect(automationsMeta(quietStart, sv)).toBeUndefined();
  });

  it("leave every count of nothing out of the since-last line", () => {
    const window = fullStart.since_last!;
    expect(
      sinceLastLine(
        {
          ...window,
          runs: 1,
          failed_runs: 1,
          suggestions_created: 0,
          suggestions_decided: 2,
        },
        en,
      ),
    ).toBe("Since you last looked: 1 run · 1 failed · 2 answered");
    expect(
      sinceLastLine({ ...window, runs: 0, suggestions_created: 0 }, sv),
    ).toBeUndefined();
  });
});

describe("the phrase that starts a ready conversation", () => {
  it("names it on one line, and asks for nothing the title says", () => {
    expect(phraseTitle("  Kvälls\ngenomgång ")).toBe("Kvälls genomgång");
    expect(phraseTitle("Säg ”hej”")).toBe("Säg 'hej'");
    expect(sv.startMessage(phraseTitle("Morgonplan"), homeIds.evening)).toBe(
      `Starta det färdiga samtalet ”Morgonplan” (${homeIds.evening}).`,
    );
  });

  it("cuts a long title at a word", () => {
    const long = `${"ord ".repeat(40)}slut`;
    const cut = phraseTitle(long);
    expect(cut.length).toBeLessThanOrEqual(PHRASE_TITLE_MAX + 1);
    expect(cut.endsWith("ord…")).toBe(true);
  });
});

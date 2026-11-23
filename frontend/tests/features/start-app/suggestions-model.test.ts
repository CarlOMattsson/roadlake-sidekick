import { describe, expect, it } from "vitest";

import {
  suggestionLabelsFor,
  suggestionsEn,
  suggestionsSv,
} from "@/features/start-app/suggestions/labels";
import {
  appendPage,
  appliedTarget,
  inboxOf,
  isDecisions,
  isSuggestionDetail,
  isSuggestionPage,
  isUndo,
  payloadChanges,
  sourceQuotes,
  suggestionIdOf,
  suggestionTitle,
  suggestionTrust,
  waitingCount,
  wholeGroup,
} from "@/features/start-app/suggestions/model";
import {
  details,
  emptyPage,
  groupItems,
  inboxPage,
  reviewItems,
  sid,
} from "../../e2e/suggestions-fixtures";

const sv = suggestionLabelsFor("sv-SE");
const en = suggestionLabelsFor("en");

function keysOf(value: unknown, prefix = ""): string[] {
  if (typeof value !== "object" || value === null) return [prefix];
  return Object.entries(value).flatMap(([key, inner]) =>
    keysOf(inner, prefix ? `${prefix}.${key}` : key),
  );
}

describe("the inbox's texts", () => {
  it("have the same keys in Swedish and English", () => {
    expect(keysOf(suggestionsSv).sort()).toEqual(keysOf(suggestionsEn).sort());
  });

  it("are Swedish unless the locale is English", () => {
    expect(suggestionLabelsFor("sv").title).toBe("Förslag");
    expect(suggestionLabelsFor("fr").title).toBe("Förslag");
    expect(suggestionLabelsFor("en-GB").title).toBe("Suggestions");
  });

  it("end receipts without a full stop", () => {
    for (const t of [sv, en])
      for (const line of [
        t.approved("X"),
        t.dismissed("X"),
        t.approvedMany(3),
        t.undone(2),
        t.undoFailed,
        t.groupChanged,
      ])
        expect(line.endsWith(".")).toBe(false);
  });
});

describe("a suggestion's title", () => {
  it("puts the server's English line in the app's words and keeps the value", () => {
    expect(suggestionTitle("create_task", "Create task: Ring Karin", sv)).toBe(
      "Skapa uppgift: Ring Karin",
    );
    expect(
      suggestionTitle("create_contact", "Create contact: Lena Holm", en),
    ).toBe("Create contact: Lena Holm");
    expect(suggestionTitle("create_task", "Create task", sv)).toBe(
      "Skapa uppgift",
    );
  });

  it("shows a line without the known prefix as it is", () => {
    expect(suggestionTitle("create_task", "Något annat", sv)).toBe(
      "Något annat",
    );
  });
});

describe("the inbox's order", () => {
  it("puts the server's group first, each card of it once, and every other pending card to review", () => {
    const { groups, review } = inboxOf(inboxPage);
    expect(groups).toHaveLength(1);
    expect(groups[0]!.items.map((item) => item.id)).toEqual(
      groupItems.map((item) => item.id),
    );
    expect(review.map((item) => item.id)).toEqual(
      reviewItems.map((item) => item.id),
    );
    expect(waitingCount(inboxPage)).toBe(7);
    expect(waitingCount(emptyPage)).toBe(0);
  });

  it("adds no card to a group the server did not put there, and drops a group whose cards are not on the page", () => {
    const page = {
      ...inboxPage,
      groups: [{ ...inboxPage.groups[0]!, suggestion_ids: [sid(99)] }],
    };
    const { groups, review } = inboxOf(page);
    expect(groups).toEqual([]);
    expect(review).toHaveLength(7);
  });

  it("appends a next page without repeating a card or a group", () => {
    const next = {
      ...inboxPage,
      items: [reviewItems[0]!, { ...reviewItems[0]!, id: sid(50) }],
      next_cursor: null,
    };
    const both = appendPage({ ...inboxPage, next_cursor: "c" }, next);
    expect(both.items).toHaveLength(8);
    expect(both.groups).toHaveLength(1);
    expect(both.next_cursor).toBeNull();
  });
});

describe("the server's group", () => {
  it("tells the whole group from a part of it", () => {
    const group = inboxPage.groups[0]!;
    expect(wholeGroup(group, [...group.suggestion_ids].reverse())).toBe(true);
    expect(wholeGroup(group, group.suggestion_ids.slice(0, 3))).toBe(false);
  });
});

describe("the card's trust", () => {
  it("reads the check and the flags as the decision family does", () => {
    expect(suggestionTrust(groupItems[0]!, "sv").state).toBe("ok");
    expect(suggestionTrust(reviewItems[0]!, "sv").state).toBe("unsure");
    expect(suggestionTrust(reviewItems[1]!, "sv").state).toBe("suspicious");
    expect(suggestionTrust(reviewItems[2]!, "sv").state).toBe("off");
  });
});

describe("the detail's words", () => {
  it("lists what a contact would get, without repeating its name", () => {
    expect(payloadChanges(details[sid(5)]!, sv)).toEqual([
      { label: "Roll", value: "Projektledare" },
      { label: "Företag", value: "Holm Bygg" },
      { label: "E-post", value: "lena.holm@example.org" },
    ]);
  });

  it("names a task's day, a priority other than normal, and a project only as one", () => {
    const changes = payloadChanges(
      {
        effect: "create_task",
        payload: {
          title: "X",
          due_on: "2026-11-27",
          priority: "high",
          project_id: sid(1),
        },
      },
      sv,
    );
    expect(changes.map((change) => change.label)).toEqual([
      "Förfaller",
      "Prioritet",
      "Projekt",
    ]);
    expect(changes[1]!.value).toBe("Hög");
    expect(changes[2]!.value).toBe("I ett projekt");
    expect(changes[0]!.value).toMatch(/27/);
  });

  it("quotes the source facts under a label that says where they come from", () => {
    expect(sourceQuotes(details[sid(5)]!, sv)).toEqual([
      {
        label: "Ur mejlet, inte skrivet av Sidekick",
        text: "Re: Köket på Storgatan\nLena Holm · lena.holm@example.org · Projektledare",
      },
    ]);
    expect(sourceQuotes(details[sid(7)]!, sv)).toEqual([]);
  });
});

describe("the shapes the room reads", () => {
  it("tells the tools' answers apart", () => {
    expect(isSuggestionPage(inboxPage)).toBe(true);
    expect(isSuggestionDetail({ suggestion: details[sid(5)] })).toBe(true);
    expect(isSuggestionDetail({ suggestion: { id: sid(5) } })).toBe(false);
    expect(suggestionIdOf({ suggestion: { id: sid(5) } })).toBe(sid(5));
    expect(
      isDecisions({
        items: [{ suggestion_id: sid(1), state: "applied" }],
      }),
    ).toBe(true);
    expect(isUndo({ suggestion_id: sid(1), trashed: null })).toBe(true);
    expect(isSuggestionPage({ items: [] })).toBe(false);
  });

  it("leads an applied card to its Task or Contact", () => {
    expect(appliedTarget({ id: sid(1), kind: "task" })).toMatchObject({
      room: "work",
      view: "task",
    });
    expect(appliedTarget({ id: sid(1), kind: "contact" })).toMatchObject({
      room: "contacts",
      view: "contact",
    });
    expect(appliedTarget({ id: sid(1), kind: "other" })).toBeUndefined();
    expect(appliedTarget(null)).toBeUndefined();
  });
});

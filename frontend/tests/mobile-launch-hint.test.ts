import { describe, expect, it } from "vitest";

import { parseLaunchHint, startEntryOf } from "@/mobile/launch-hint";

const ID = "019f0000-0000-7000-8000-0000000000a1";

describe("parseLaunchHint", () => {
  it.each([
    ["", { view: "today" }],
    ["?view=today", { view: "today" }],
    ["?view=settings", { view: "settings" }],
    [`?view=task&id=${ID}`, { view: "task", id: ID }],
    [`view=task&id=${ID.toUpperCase()}`, { view: "task", id: ID }],
    [`?id=${ID}&view=task&utm=1`, { view: "task", id: ID }],
  ])("reads %j", (search, hint) => {
    expect(parseLaunchHint(search)).toEqual(hint);
  });

  it.each([
    ["an unknown view", "?view=contacts"],
    ["a view in other case", "?view=Task&id=" + ID],
    ["no view", `?id=${ID}`],
    ["a task without an id", "?view=task"],
    ["a malformed id", "?view=task&id=123"],
    ["a path as the id", `?view=task&id=${ID}/../x`],
    ["a script as the id", "?view=task&id=<script>"],
    ["a repeated view", `?view=today&view=task&id=${ID}`],
    ["settings repeated with another view", "?view=settings&view=task"],
    ["a repeated id", `?view=task&id=${ID}&id=${ID}`],
    ["an overlong string", "?view=task&id=" + "a".repeat(600)],
  ])("opens Today for %s", (_label, search) => {
    expect(parseLaunchHint(search)).toEqual({ view: "today" });
  });

  it("opens Today for a missing or non-string value", () => {
    expect(parseLaunchHint(undefined)).toEqual({ view: "today" });
    expect(parseLaunchHint(null)).toEqual({ view: "today" });
  });
});

describe("startEntryOf", () => {
  it("starts Today on the Work room's own home and a task on its detail", () => {
    expect(startEntryOf({ view: "today" })).toEqual({
      room: "work",
      view: "root",
    });
    // The settings open on top of Today, which stays under them.
    expect(startEntryOf({ view: "settings" })).toEqual({
      room: "work",
      view: "root",
    });
    expect(startEntryOf({ view: "task", id: ID })).toEqual({
      room: "work",
      view: "task",
      id: ID,
    });
  });
});

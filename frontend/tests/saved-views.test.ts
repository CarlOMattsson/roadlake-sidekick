import { describe, expect, it } from "vitest";
import {
  definitionToFilters,
  filtersToDefinition,
  isArchivedView,
  isSaveBlocked,
  namesSeveralPriorities,
  SAVED_VIEW_NAME_MAX,
  upsertView,
  viewNameProblem,
  viewsOfTab,
} from "@/features/work-app/saved-views";
import {
  savedViewsLabelsEn,
  savedViewsLabelsFor,
  savedViewsLabelsSv,
} from "@/features/work-app/saved-views-labels";
import type {
  WorkFilters,
  WorkSavedView,
  WorkSavedViewDefinition,
} from "@/features/work-app/transport";

function view(
  id: string,
  definition: WorkSavedViewDefinition,
  archived: string | null = null,
): WorkSavedView {
  return {
    id,
    name: `Vy ${id}`,
    definition,
    version: 1,
    archived_at: archived,
  };
}

describe("filtersToDefinition", () => {
  it("keeps every board filter, trimmed, with the tab and context all", () => {
    const { definition, dropped } = filtersToDefinition("board", {
      q: "  Anna ",
      status: "todo",
      priority: "high",
      tags: ["jobb", "  vår "],
      tag_match: "all",
      archive: "active",
      actionable: "now",
      attention: "requested",
      estimate: "estimated",
      waiting: "waiting",
    });
    expect(definition).toEqual({
      view: "board",
      context: "all",
      q: "Anna",
      status: "todo",
      priority: "high",
      tags: ["jobb", "vår"],
      tag_match: "all",
      archive: "active",
      actionable: "now",
      attention: "requested",
      estimate: "estimated",
      waiting: "waiting",
    });
    expect(dropped).toEqual([]);
  });

  it("keeps kind, sort and group for the agenda only", () => {
    const { definition, dropped } = filtersToDefinition("agenda", {
      kind: "task",
      sort: "due_asc",
      group: "status",
    });
    expect(definition).toEqual({
      view: "agenda",
      context: "all",
      kind: "task",
      sort: "due_asc",
      group: "status",
    });
    expect(dropped).toEqual([]);
  });

  it("drops kind, sort and group on the board, and lists them", () => {
    const { definition, dropped } = filtersToDefinition("board", {
      kind: "task",
      sort: "due_asc",
      group: "status",
      status: "blocked",
    });
    expect(definition).toEqual({
      view: "board",
      context: "all",
      status: "blocked",
    });
    expect(dropped).toEqual(["kind", "sort", "group"]);
  });

  it("refuses a single Project's board: project_id is dropped and blocks the save", () => {
    const { dropped } = filtersToDefinition("board", {
      project_id: "019f0000-0000-7000-8000-0000000000p1",
    });
    expect(dropped).toEqual(["project_id"]);
    expect(isSaveBlocked(dropped)).toBe(true);
  });

  it("treats project_id on the agenda as unknown, since the agenda takes no project", () => {
    const { dropped } = filtersToDefinition("agenda", { project_id: "x" });
    expect(dropped).toEqual(["project_id"]);
  });

  it("does not block a save without project_id", () => {
    const { dropped } = filtersToDefinition("agenda", { status: "todo" });
    expect(isSaveBlocked(dropped)).toBe(false);
  });

  it("drops values outside their sets and lists the key once", () => {
    const { definition, dropped } = filtersToDefinition("agenda", {
      status: "done",
      priority: "vip",
      sort: "random",
      archive: "everything",
      kind: "meeting",
    });
    expect(definition).toEqual({ view: "agenda", context: "all" });
    expect(dropped).toEqual(["status", "priority", "sort", "archive", "kind"]);
  });

  it("drops empty values: a blank query, an empty tag list and an empty priority list", () => {
    const { definition, dropped } = filtersToDefinition("board", {
      q: "   ",
      tags: [],
      priority: [],
    });
    expect(definition).toEqual({ view: "board", context: "all" });
    expect(dropped).toEqual(["q", "tags", "priority"]);
  });

  it("turns a list of priorities into priorities, keeping up to four valid values", () => {
    const { definition, dropped } = filtersToDefinition("board", {
      priority: ["high", "urgent"],
    });
    expect(definition.priorities).toEqual(["high", "urgent"]);
    expect(definition.priority).toBeUndefined();
    expect(dropped).toEqual([]);
  });

  it("keeps the valid priorities of a list and lists the priority key for the refused ones", () => {
    const { definition, dropped } = filtersToDefinition("board", {
      priority: ["high", "vip"],
    });
    expect(definition.priorities).toEqual(["high"]);
    expect(dropped).toEqual(["priority"]);
  });

  it("keeps four priorities at most and lists the priority key when more were given", () => {
    const { definition, dropped } = filtersToDefinition("board", {
      priority: ["low", "normal", "high", "urgent", "low"],
    });
    expect(definition.priorities).toEqual(["low", "normal", "high", "urgent"]);
    expect(dropped).toEqual(["priority"]);
  });

  it("keeps at most five tags and skips tags that are blank or longer than 80 characters", () => {
    const { definition, dropped } = filtersToDefinition("board", {
      tags: ["a", "b", "c", "d", "e", "f"],
    });
    expect(definition.tags).toEqual(["a", "b", "c", "d", "e"]);
    expect(dropped).toEqual(["tags"]);

    const long = filtersToDefinition("board", { tags: ["x".repeat(81)] });
    expect(long.definition.tags).toBeUndefined();
    expect(long.dropped).toEqual(["tags"]);

    const mixed = filtersToDefinition("board", {
      tags: ["ok", " ", "y".repeat(80)],
    });
    expect(mixed.definition.tags).toEqual(["ok", "y".repeat(80)]);
    expect(mixed.dropped).toEqual(["tags"]);
  });

  it("reads one tag given as text as a list of one", () => {
    const { definition } = filtersToDefinition("board", { tags: "jobb" });
    expect(definition.tags).toEqual(["jobb"]);
  });

  it("drops a query longer than 200 characters", () => {
    const { definition, dropped } = filtersToDefinition("board", {
      q: "q".repeat(201),
    });
    expect(definition.q).toBeUndefined();
    expect(dropped).toEqual(["q"]);
  });

  it("drops a list where a single value is set, and unknown keys", () => {
    const { definition, dropped } = filtersToDefinition("board", {
      status: ["todo", "blocked"],
      page: "2",
    });
    expect(definition).toEqual({ view: "board", context: "all" });
    expect(dropped).toEqual(["status", "page"]);
  });

  it("skips a key whose value is undefined without listing it", () => {
    const { dropped } = filtersToDefinition("board", {
      status: undefined,
    } as unknown as WorkFilters);
    expect(dropped).toEqual([]);
  });
});

describe("definitionToFilters", () => {
  it("skips null and absent keys", () => {
    expect(
      definitionToFilters({
        view: "agenda",
        context: "all",
        q: null,
        status: null,
        priority: null,
        priorities: null,
        tags: null,
        sort: undefined,
      }),
    ).toEqual({});
  });

  it("reads one priority in a list as priority", () => {
    expect(
      definitionToFilters({
        view: "board",
        context: "all",
        priorities: ["high"],
      }),
    ).toEqual({ priority: "high" });
  });

  it("skips a list of several priorities", () => {
    expect(
      definitionToFilters({
        view: "board",
        context: "all",
        priorities: ["high", "urgent"],
      }),
    ).toEqual({});
  });

  it("prefers a single priority field, and skips it when it is outside the set", () => {
    expect(
      definitionToFilters({
        view: "board",
        context: "all",
        priority: "urgent",
        priorities: ["low"],
      }),
    ).toEqual({ priority: "urgent" });
    expect(
      definitionToFilters({ view: "board", context: "all", priority: "vip" }),
    ).toEqual({});
  });

  it("skips values outside their sets and a query longer than 200 characters", () => {
    expect(
      definitionToFilters({
        view: "agenda",
        context: "all",
        status: "done",
        sort: "random",
        kind: "task",
        q: "q".repeat(201),
      }),
    ).toEqual({ kind: "task" });
  });

  it("keeps a valid query, trimmed, and skips a blank one", () => {
    expect(
      definitionToFilters({ view: "board", context: "all", q: " Anna " }),
    ).toEqual({ q: "Anna" });
    expect(
      definitionToFilters({ view: "board", context: "all", q: "   " }),
    ).toEqual({});
  });

  it("drops invalid tags and keeps at most five", () => {
    expect(
      definitionToFilters({
        view: "board",
        context: "all",
        tags: ["", "ok", "x".repeat(81), "a", "b", "c", "d"],
      }),
    ).toEqual({ tags: ["ok", "a", "b", "c", "d"] });
    expect(
      definitionToFilters({ view: "board", context: "all", tags: [""] }),
    ).toEqual({});
  });

  it("gives back the filters a board saved, when every value is valid", () => {
    const filters = {
      q: "Anna",
      status: "todo",
      priority: "high",
      tags: ["jobb"],
      tag_match: "any",
      archive: "all",
      actionable: "later",
      attention: "all",
      estimate: "unestimated",
      waiting: "not_waiting",
    };
    expect(
      definitionToFilters(filtersToDefinition("board", filters).definition),
    ).toEqual(filters);
  });

  it("reads a saved list of one priority back as priority", () => {
    const { definition } = filtersToDefinition("board", {
      priority: ["urgent"],
    });
    expect(definitionToFilters(definition)).toEqual({ priority: "urgent" });
  });
});

describe("namesSeveralPriorities", () => {
  it("is true for a list of several priorities, which opens without a priority filter", () => {
    const definition: WorkSavedViewDefinition = {
      view: "board",
      context: "all",
      priorities: ["high", "urgent"],
    };
    expect(namesSeveralPriorities(definition)).toBe(true);
    expect(definitionToFilters(definition)).toEqual({});
  });

  it("is false for one priority, in the list or in the field", () => {
    expect(
      namesSeveralPriorities({
        view: "board",
        context: "all",
        priorities: ["high"],
      }),
    ).toBe(false);
    expect(
      namesSeveralPriorities({
        view: "board",
        context: "all",
        priority: "urgent",
        priorities: ["low", "high"],
      }),
    ).toBe(false);
  });

  it("is false when no priority is named", () => {
    expect(
      namesSeveralPriorities({ view: "board", context: "all", priority: null }),
    ).toBe(false);
  });
});

describe("viewNameProblem", () => {
  it("refuses an empty or blank name", () => {
    expect(viewNameProblem("")).toBe("required");
    expect(viewNameProblem("   ")).toBe("required");
  });

  it("accepts a name of one to 120 characters once trimmed", () => {
    expect(viewNameProblem(" Mina möten ")).toBeUndefined();
    expect(viewNameProblem("a")).toBeUndefined();
    expect(viewNameProblem("å".repeat(SAVED_VIEW_NAME_MAX))).toBeUndefined();
  });

  it("refuses a name longer than 120 characters, counted as characters", () => {
    expect(viewNameProblem("a".repeat(SAVED_VIEW_NAME_MAX + 1))).toBe(
      "tooLong",
    );
    expect(
      viewNameProblem(`  ${"a".repeat(SAVED_VIEW_NAME_MAX)}  `),
    ).toBeUndefined();
  });
});

describe("view list helpers", () => {
  it("lists only the views saved for the tab", () => {
    const views = [
      view("a", { view: "agenda", context: "all" }),
      view("b", { view: "board", context: "all" }),
      view("c", { view: "agenda", context: "all" }),
    ];
    expect(viewsOfTab(views, "agenda").map((item) => item.id)).toEqual([
      "a",
      "c",
    ]);
    expect(viewsOfTab(views, "board").map((item) => item.id)).toEqual(["b"]);
  });

  it("knows an archived view from an active one", () => {
    expect(isArchivedView(view("a", { view: "agenda", context: "all" }))).toBe(
      false,
    );
    expect(
      isArchivedView(
        view("a", { view: "agenda", context: "all" }, "2026-10-01T10:00:00Z"),
      ),
    ).toBe(true);
  });

  it("replaces a listed view in place and puts an unlisted one at the top", () => {
    const first = view("a", { view: "agenda", context: "all" });
    const second = view("b", { view: "agenda", context: "all" });
    const renamed = { ...first, name: "Nytt namn", version: 2 };
    expect(upsertView([first, second], renamed)).toEqual([renamed, second]);

    const added = view("c", { view: "agenda", context: "all" });
    expect(upsertView([first, second], added)).toEqual([added, first, second]);
  });
});

describe("saved views labels", () => {
  it("has the same keys in Swedish and English", () => {
    expect(Object.keys(savedViewsLabelsEn).sort()).toEqual(
      Object.keys(savedViewsLabelsSv).sort(),
    );
  });

  it("has a function where Swedish has one, and a text where it has text", () => {
    for (const key of Object.keys(
      savedViewsLabelsSv,
    ) as (keyof typeof savedViewsLabelsSv)[]) {
      expect(typeof savedViewsLabelsEn[key]).toBe(
        typeof savedViewsLabelsSv[key],
      );
    }
  });

  it("picks Swedish for sv locales and English otherwise", () => {
    expect(savedViewsLabelsFor("sv-SE")).toBe(savedViewsLabelsSv);
    expect(savedViewsLabelsFor("en-GB")).toBe(savedViewsLabelsEn);
  });
});

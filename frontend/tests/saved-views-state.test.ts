import { describe, expect, it } from "vitest";

import {
  initialSavedViewsState,
  savedViewsReducer,
  type SavedViewsAction,
  type SavedViewsState,
} from "@/features/work-app/saved-views/saved-views-state";
import type { WorkSavedView } from "@/features/work-app/transport/transport";

function view(id: string, patch: Partial<WorkSavedView> = {}): WorkSavedView {
  return { id, name: `View ${id}`, version: 1, ...patch } as WorkSavedView;
}

function run(
  state: SavedViewsState,
  ...actions: SavedViewsAction[]
): SavedViewsState {
  return actions.reduce(savedViewsReducer, state);
}

const loaded = run(initialSavedViewsState, {
  type: "listLoaded",
  views: [view("a"), view("b")],
});

describe("savedViewsReducer: the list", () => {
  it("starts loading with no views, then holds the list", () => {
    expect(initialSavedViewsState).toMatchObject({
      views: undefined,
      listPhase: "loading",
      showArchived: false,
    });
    expect(loaded.listPhase).toBe("ready");
    expect(loaded.views?.map((item) => item.id)).toEqual(["a", "b"]);
  });

  it("goes back to loading for another read and keeps the views meanwhile", () => {
    const state = run(loaded, { type: "listLoading" });
    expect(state.listPhase).toBe("loading");
    expect(state.views).toHaveLength(2);
  });

  it("a failed read shows the error and keeps the views", () => {
    const state = run(loaded, { type: "listFailed" });
    expect(state.listPhase).toBe("error");
    expect(state.views).toHaveLength(2);
  });

  it("holds the archive switch", () => {
    expect(
      run(loaded, { type: "showArchivedSet", value: true }).showArchived,
    ).toBe(true);
  });
});

describe("savedViewsReducer: saving the current view", () => {
  it("typing clears the refusal; a refusal is held until then", () => {
    const refused = run(loaded, { type: "nameRefused", problem: "required" });
    expect(refused.nameProblem).toBe("required");
    const typed = run(refused, { type: "nameChanged", value: "My view" });
    expect(typed).toMatchObject({ name: "My view", nameProblem: undefined });
  });

  it("a saved view joins the front of the list and empties the form", () => {
    const state = run(
      loaded,
      { type: "nameChanged", value: "New" },
      { type: "saved", view: view("n", { name: "New" }), notice: "Saved New" },
    );
    expect(state.views?.map((item) => item.id)).toEqual(["n", "a", "b"]);
    expect(state).toMatchObject({
      name: "",
      nameProblem: undefined,
      notice: "Saved New",
    });
  });

  it("saving before the list has answered still holds the view", () => {
    const state = run(initialSavedViewsState, {
      type: "saved",
      view: view("n"),
      notice: "Saved",
    });
    expect(state.views?.map((item) => item.id)).toEqual(["n"]);
  });
});

describe("savedViewsReducer: renaming", () => {
  it("starts with the current name, follows typing and keeps the refusal text", () => {
    const started = run(loaded, {
      type: "renameStarted",
      view: view("a", { name: "Old" }),
    });
    expect(started.editing).toEqual({ id: "a", value: "Old" });
    const typed = run(started, { type: "renameTyped", id: "a", value: "Ne" });
    expect(typed.editing).toEqual({ id: "a", value: "Ne" });
    const refused = run(typed, {
      type: "renameRefused",
      id: "a",
      value: "",
      problem: "required",
    });
    expect(refused.editing).toEqual({
      id: "a",
      value: "",
      problem: "required",
    });
    expect(
      run(refused, { type: "renameTyped", id: "a", value: "x" }).editing
        ?.problem,
    ).toBeUndefined();
  });

  it("a cancel closes the row; a rename replaces the view in place and closes it", () => {
    const started = run(loaded, { type: "renameStarted", view: view("a") });
    expect(run(started, { type: "renameCancelled" }).editing).toBeUndefined();
    const renamed = run(started, {
      type: "renamed",
      view: view("a", { name: "Fresh", version: 2 }),
      notice: "Renamed",
    });
    expect(renamed.editing).toBeUndefined();
    expect(renamed.views?.map((item) => item.name)).toEqual([
      "Fresh",
      "View b",
    ]);
    expect(renamed.notice).toBe("Renamed");
  });
});

describe("savedViewsReducer: archive and restore", () => {
  it("archiving keeps the answer for the Undo line, clears the notice and closes its own rename row", () => {
    const state = run(
      loaded,
      { type: "renameStarted", view: view("a") },
      { type: "renamed", view: view("b"), notice: "Renamed" },
      { type: "renameStarted", view: view("a") },
      {
        type: "archived",
        view: view("a", { name: "View a", version: 4 }),
      },
    );
    expect(state.undo).toEqual({ id: "a", name: "View a", version: 4 });
    expect(state.notice).toBe("");
    expect(state.editing).toBeUndefined();
  });

  it("archiving another view leaves a rename row open", () => {
    const state = run(
      loaded,
      { type: "renameStarted", view: view("a") },
      { type: "archived", view: view("b", { version: 2 }) },
    );
    expect(state.editing?.id).toBe("a");
    expect(state.undo?.id).toBe("b");
  });

  it("restoring clears its own Undo line and says so; another Undo line stays", () => {
    const archived = run(loaded, {
      type: "archived",
      view: view("a", { version: 2 }),
    });
    const restored = run(archived, {
      type: "restored",
      view: view("a", { version: 3 }),
      notice: "Restored View a",
    });
    expect(restored.undo).toBeUndefined();
    expect(restored.notice).toBe("Restored View a");
    const other = run(archived, {
      type: "restored",
      view: view("b", { version: 3 }),
      notice: "Restored View b",
    });
    expect(other.undo?.id).toBe("a");
  });
});

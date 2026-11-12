import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useTabTools } from "@/features/work-app/fullscreen/parts/use-tab-tools";

describe("useTabTools", () => {
  it("gives the focus back to the button that opened search or the new-Task field", () => {
    const { result } = renderHook(() => useTabTools());
    const search = document.createElement("button");
    const create = document.createElement("button");
    document.body.append(search, create);
    result.current.searchToggle.current = search;
    result.current.createToggle.current = create;

    act(() => result.current.openSearch("agenda"));
    act(() => result.current.closeSearch("agenda"));
    expect(document.activeElement).toBe(search);
    expect(result.current.state.searchOpen.agenda).toBe(false);

    act(() => result.current.openCreate("agenda"));
    act(() => result.current.closeCreate("agenda"));
    expect(document.activeElement).toBe(create);
    search.remove();
    create.remove();
  });

  it("keeps the depth setters stable across renders and updates the depth", () => {
    const { result, rerender } = renderHook(() => useTabTools());
    const before = result.current.setDepth.board;
    act(() => result.current.setDepth.board(2));
    rerender();
    expect(result.current.setDepth.board).toBe(before);
    expect(result.current.state.depth.board).toBe(2);
  });
});

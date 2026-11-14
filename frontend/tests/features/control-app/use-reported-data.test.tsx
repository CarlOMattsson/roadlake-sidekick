import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useReportedData } from "@/features/control-app/use-reported-data";

describe("useReportedData", () => {
  it("tells the card in the same step as the change, without waiting for a frame or an effect", () => {
    const onData = vi.fn();
    // `initial` must keep its identity between renders, as the cards' data does: a new one is a fresh read.
    const initial = ["a", "b"];
    const { result } = renderHook(() => useReportedData(initial, onData));
    expect(onData).not.toHaveBeenCalled();

    act(() => {
      result.current[1]((current) => current.filter((item) => item !== "a"));
      // Inside the same step, before any render or effect could run.
      expect(onData).toHaveBeenCalledTimes(1);
      expect(onData).toHaveBeenCalledWith(["b"]);
    });
  });

  it("builds the next data from the newest one, also for two changes in a row", () => {
    const onData = vi.fn();
    const { result } = renderHook(() => useReportedData<number>(1, onData));

    act(() => {
      result.current[1]((current) => current + 1);
      result.current[1]((current) => current + 1);
    });

    expect(onData.mock.calls).toEqual([[2], [3]]);
  });

  it("takes a new initial as a fresh read: shown, not reported back, and onFresh runs", () => {
    const onData = vi.fn();
    const onFresh = vi.fn();
    const { result, rerender } = renderHook(
      ({ initial }) => useReportedData(initial, onData, onFresh),
      { initialProps: { initial: ["a"] } },
    );

    act(() => rerender({ initial: ["x", "y"] }));

    expect(result.current[0]).toEqual(["x", "y"]);
    expect(onData).not.toHaveBeenCalled();
    expect(onFresh).toHaveBeenCalledTimes(1);
    act(() => result.current[1]((current) => [...current, "z"]));
    expect(onData).toHaveBeenCalledWith(["x", "y", "z"]);
  });
});

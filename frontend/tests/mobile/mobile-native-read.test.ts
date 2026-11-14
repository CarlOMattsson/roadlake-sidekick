import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useNativeRead } from "@/mobile/use-native-read";

describe("useNativeRead", () => {
  it("goes from reading to ready with the value", async () => {
    const read = vi.fn(() => Promise.resolve("on"));
    const { result } = renderHook(() => useNativeRead(read, 0));
    expect(result.current[0]).toEqual({ phase: "reading" });
    await waitFor(() =>
      expect(result.current[0]).toEqual({ phase: "ready", value: "on" }),
    );
  });

  it("fails, and the retry reads again", async () => {
    const read = vi
      .fn<() => Promise<string>>()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce("back");
    const { result } = renderHook(() => useNativeRead(read, 0));
    await waitFor(() => expect(result.current[0]).toEqual({ phase: "failed" }));
    act(() => result.current[1]());
    expect(result.current[0]).toEqual({ phase: "reading" });
    await waitFor(() =>
      expect(result.current[0]).toEqual({ phase: "ready", value: "back" }),
    );
    expect(read).toHaveBeenCalledTimes(2);
  });

  it("reads again when the refresh key changes", async () => {
    const read = vi.fn(() => Promise.resolve(1));
    const { rerender } = renderHook(({ key }) => useNativeRead(read, key), {
      initialProps: { key: 0 },
    });
    await waitFor(() => expect(read).toHaveBeenCalledTimes(1));
    rerender({ key: 1 });
    await waitFor(() => expect(read).toHaveBeenCalledTimes(2));
  });

  it("ignores an answer that arrives after unmount", async () => {
    let resolve: (value: string) => void = () => undefined;
    const read = () => new Promise<string>((done) => (resolve = done));
    const { result, unmount } = renderHook(() => useNativeRead(read, 0));
    unmount();
    resolve("late");
    await Promise.resolve();
    expect(result.current[0]).toEqual({ phase: "reading" });
  });
});

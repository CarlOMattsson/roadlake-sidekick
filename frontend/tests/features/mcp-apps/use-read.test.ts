import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useRead } from "@/features/mcp-apps/ui/use-read";

describe("useRead", () => {
  it("goes from reading to ready with the value", async () => {
    const read = vi.fn(() => Promise.resolve("on"));
    const { result } = renderHook(() => useRead(read, 0));
    expect(result.current[0]).toEqual({ phase: "reading" });
    await waitFor(() =>
      expect(result.current[0]).toEqual({ phase: "ready", value: "on" }),
    );
  });

  it("fails, and the retry reads again", async () => {
    const offline = new Error("offline");
    const read = vi
      .fn<() => Promise<string>>()
      .mockRejectedValueOnce(offline)
      .mockResolvedValueOnce("back");
    const { result } = renderHook(() => useRead(read, 0));
    await waitFor(() =>
      expect(result.current[0]).toEqual({ phase: "failed", cause: offline }),
    );
    act(() => result.current[1]());
    expect(result.current[0]).toEqual({ phase: "reading" });
    await waitFor(() =>
      expect(result.current[0]).toEqual({ phase: "ready", value: "back" }),
    );
    expect(read).toHaveBeenCalledTimes(2);
  });

  it("reads again when the refresh key changes", async () => {
    const read = vi.fn(() => Promise.resolve(1));
    const { rerender } = renderHook(({ key }) => useRead(read, key), {
      initialProps: { key: 0 },
    });
    await waitFor(() => expect(read).toHaveBeenCalledTimes(1));
    rerender({ key: 1 });
    await waitFor(() => expect(read).toHaveBeenCalledTimes(2));
  });

  it("ignores an answer that arrives after unmount", async () => {
    let resolve: (value: string) => void = () => undefined;
    const read = () => new Promise<string>((done) => (resolve = done));
    const { result, unmount } = renderHook(() => useRead(read, 0));
    unmount();
    resolve("late");
    await Promise.resolve();
    expect(result.current[0]).toEqual({ phase: "reading" });
  });

  it("reads nothing without a read", () => {
    const { result } = renderHook(() => useRead<string>(undefined));
    expect(result.current[0]).toEqual({ phase: "reading" });
  });

  it("starts from a result it already holds and reads again only on a retry", async () => {
    const read = vi.fn(() => Promise.resolve("fresh"));
    const { result } = renderHook(() => useRead(read, 0, "held"));
    expect(result.current[0]).toEqual({ phase: "ready", value: "held" });
    expect(read).not.toHaveBeenCalled();
    act(() => result.current[1]());
    await waitFor(() =>
      expect(result.current[0]).toEqual({ phase: "ready", value: "fresh" }),
    );
    expect(read).toHaveBeenCalledTimes(1);
  });

  it("treats a read that throws at once as a failed read", async () => {
    const cause = new Error("sync");
    const read = (): Promise<string> => {
      throw cause;
    };
    const { result } = renderHook(() => useRead(read));
    await waitFor(() =>
      expect(result.current[0]).toEqual({ phase: "failed", cause }),
    );
  });

  it("keeps the last result on screen while a refresh is read", async () => {
    let resolve: (value: number) => void = () => undefined;
    const read = vi
      .fn<() => Promise<number>>()
      .mockResolvedValueOnce(1)
      .mockImplementationOnce(() => new Promise((done) => (resolve = done)));
    const { result, rerender } = renderHook(({ key }) => useRead(read, key), {
      initialProps: { key: 0 },
    });
    await waitFor(() =>
      expect(result.current[0]).toEqual({ phase: "ready", value: 1 }),
    );
    rerender({ key: 1 });
    expect(result.current[0]).toEqual({ phase: "ready", value: 1 });
    resolve(2);
    await waitFor(() =>
      expect(result.current[0]).toEqual({ phase: "ready", value: 2 }),
    );
  });

  it("replaces the result with a value the caller got another way", async () => {
    const read = vi.fn(() => Promise.resolve("read"));
    const { result } = renderHook(() => useRead(read));
    await waitFor(() =>
      expect(result.current[0]).toEqual({ phase: "ready", value: "read" }),
    );
    act(() => result.current[2]("written"));
    expect(result.current[0]).toEqual({ phase: "ready", value: "written" });
  });
});

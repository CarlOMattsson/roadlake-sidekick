import { useEffect } from "react";
import { act, render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useRowQueue } from "@/features/mcp-apps/ui/row-queue";
import type { RowQueue } from "@/features/mcp-apps/ui/row-queue";

function mount() {
  const holder = { queue: undefined as unknown as RowQueue };
  function Probe() {
    const queue = useRowQueue();
    useEffect(() => {
      holder.queue = queue;
    });
    return null;
  }
  render(<Probe />);
  return holder;
}

describe("useRowQueue", () => {
  it("runs the tasks of one row in order and reports the waiting one", async () => {
    const h = mount();
    const order: string[] = [];
    let release: () => void = () => undefined;
    const first = new Promise<void>((resolve) => (release = resolve));
    let all: Promise<void> = Promise.resolve();
    act(() => {
      void h.queue.enqueue("a", async () => {
        order.push("a1");
        await first;
        order.push("a1 done");
      });
      all = h.queue.enqueue("a", () => {
        order.push("a2");
        return Promise.resolve();
      });
    });
    expect(h.queue.queued("a")).toBe(true);
    expect(h.queue.pending("a")).toBe(2);
    await act(async () => {
      release();
      await all;
    });
    expect(order).toEqual(["a1", "a1 done", "a2"]);
    expect(h.queue.pending("a")).toBe(0);
    expect(h.queue.queued("a")).toBe(false);
  });

  it("does not make other rows wait and survives a task that throws", async () => {
    const h = mount();
    const order: string[] = [];
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => (release = resolve));
    let b: Promise<void> = Promise.resolve();
    let afterThrow: Promise<void> = Promise.resolve();
    act(() => {
      void h.queue.enqueue("a", async () => {
        await gate;
        throw new Error("boom");
      });
      afterThrow = h.queue.enqueue("a", () => {
        order.push("a2");
        return Promise.resolve();
      });
      b = h.queue.enqueue("b", () => {
        order.push("b");
        return Promise.resolve();
      });
    });
    await act(async () => {
      await b;
    });
    expect(order).toEqual(["b"]);
    await act(async () => {
      release();
      await afterThrow;
    });
    expect(order).toEqual(["b", "a2"]);
  });
});

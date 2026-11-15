import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { OfflineSupport } from "@/features/mcp-apps/room-types";
import { useSentRefresh } from "@/mobile/use-sent-refresh";

// The rooms read again when what waited in the phone's outbox has left it, so the stand-ins are replaced by the stored records.

/** An outbox whose waiting ids a test sets, and whose change the test announces. */
function outbox(initial: string[] = []) {
  let waiting = new Set(initial);
  const listeners = new Set<() => void>();
  const offline: Pick<OfflineSupport, "queuedRecordIds" | "onQueueChanged"> = {
    queuedRecordIds: vi.fn(() => Promise.resolve(waiting)),
    onQueueChanged: vi.fn((listener: () => void) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    }),
  };
  return {
    offline,
    listeners,
    /** The outbox now holds `ids`, and a run of it has ended. */
    change: async (ids: string[]) => {
      waiting = new Set(ids);
      await act(async () => {
        for (const listener of [...listeners]) listener();
        await Promise.resolve();
      });
    },
    settle: () => act(() => Promise.resolve()),
  };
}

describe("useSentRefresh", () => {
  it("reads again when a waiting id has left the outbox", async () => {
    const phone = outbox(["queued-key-1", "task-1"]);
    const onSent = vi.fn();
    renderHook(() => useSentRefresh(phone.offline, onSent));
    await phone.settle();
    expect(onSent).not.toHaveBeenCalled();

    await phone.change(["task-1"]);

    expect(onSent).toHaveBeenCalledTimes(1);
  });

  it("does not read again when an id only came to wait", async () => {
    const phone = outbox(["task-1"]);
    const onSent = vi.fn();
    renderHook(() => useSentRefresh(phone.offline, onSent));
    await phone.settle();

    await phone.change(["task-1", "queued-key-2"]);

    expect(onSent).not.toHaveBeenCalled();
  });

  it("does not read again when nothing changed in what waits", async () => {
    const phone = outbox(["task-1"]);
    const onSent = vi.fn();
    renderHook(() => useSentRefresh(phone.offline, onSent));
    await phone.settle();

    await phone.change(["task-1"]);

    expect(onSent).not.toHaveBeenCalled();
  });

  it("reads again once for each id that leaves, not for the one that came before", async () => {
    const phone = outbox();
    const onSent = vi.fn();
    renderHook(() => useSentRefresh(phone.offline, onSent));
    await phone.settle();

    await phone.change(["queued-key-1"]);
    expect(onSent).not.toHaveBeenCalled();
    await phone.change([]);
    expect(onSent).toHaveBeenCalledTimes(1);
    await phone.change([]);
    expect(onSent).toHaveBeenCalledTimes(1);
  });

  it("stops listening when the room goes away", async () => {
    const phone = outbox(["task-1"]);
    const onSent = vi.fn();
    const view = renderHook(() => useSentRefresh(phone.offline, onSent));
    await phone.settle();
    expect(phone.listeners.size).toBe(1);

    view.unmount();

    expect(phone.listeners.size).toBe(0);
    await phone.change([]);
    expect(onSent).not.toHaveBeenCalled();
  });

  it("does nothing for a host that has no such outbox", async () => {
    const onSent = vi.fn();
    const onQueueChanged = vi.fn(() => () => undefined);

    renderHook(() => useSentRefresh({ onQueueChanged }, onSent));
    renderHook(() => useSentRefresh(undefined, onSent));
    await act(() => Promise.resolve());

    expect(onQueueChanged).not.toHaveBeenCalled();
    expect(onSent).not.toHaveBeenCalled();
  });

  it("carries on when the outbox cannot be read", async () => {
    const phone = outbox(["task-1"]);
    const onSent = vi.fn();
    renderHook(() => useSentRefresh(phone.offline, onSent));
    await phone.settle();

    vi.mocked(phone.offline.queuedRecordIds!).mockRejectedValueOnce(
      new Error("unavailable"),
    );
    await phone.change([]);
    expect(onSent).not.toHaveBeenCalled();

    await phone.change([]);
    expect(onSent).toHaveBeenCalledTimes(1);
  });
});

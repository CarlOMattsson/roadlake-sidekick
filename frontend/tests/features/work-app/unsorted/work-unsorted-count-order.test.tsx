import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type {
  WorkTask,
  WorkTransport,
} from "@/features/work-app/transport/transport";
import { useUnsorted } from "@/features/work-app/unsorted/use-unsorted";
import { deferred } from "@tests/helpers/deferred";

/*
 * The count of the "Att sortera" row comes from reads that can overtake each other: a slow read that started before a
 * newer one must not put its older count back when it answers last.
 */

function tasks(count: number): WorkTask[] {
  return Array.from({ length: count }, (_, index) => ({
    id: `019f0000-0000-7000-8000-00000000c${index}`,
    title: `Uppgift ${index}`,
    status: "todo",
    due_at: null,
    version: 1,
    domain_id: null,
  }));
}

type Page = { items: WorkTask[]; next_cursor: string | null };

describe("useUnsorted: the count of the row", () => {
  it("keeps the newest count when an older read answers after it", async () => {
    const older = deferred<Page>();
    const newer = deferred<Page>();
    const listUnsortedTasks = vi
      .fn()
      .mockReturnValueOnce(older.promise)
      .mockReturnValueOnce(newer.promise);
    const transport = { listUnsortedTasks } as unknown as WorkTransport;
    const { result, rerender } = renderHook(
      ({ refreshKey }) =>
        useUnsorted({
          transport,
          active: true,
          refreshKey,
          onRoute: undefined,
        }),
      { initialProps: { refreshKey: 0 } },
    );
    // A write elsewhere asks for the count again while the first read is still on its way.
    rerender({ refreshKey: 1 });
    expect(listUnsortedTasks).toHaveBeenCalledTimes(2);

    await act(async () => {
      newer.resolve({ items: tasks(2), next_cursor: null });
      await newer.promise;
    });
    expect(result.current.unsorted).toEqual({ count: 2, more: false });
    await act(async () => {
      older.resolve({ items: tasks(5), next_cursor: null });
      await older.promise;
    });
    expect(result.current.unsorted).toEqual({ count: 2, more: false });
  });
});

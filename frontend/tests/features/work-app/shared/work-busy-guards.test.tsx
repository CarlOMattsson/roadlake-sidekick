import { act, render, renderHook, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { WorkCard } from "@/features/work-app/inline/work-card";
import type { CardStatusWriter } from "@/features/work-app/inline/work-card";
import { NewContact } from "@/features/work-app/contacts/new-contact";
import { cardLabelsEn } from "@/features/work-app/shared/card-labels";
import { workEn } from "@/features/work-app/shared/labels";
import { useSingleFlight } from "@/features/work-app/shared/use-single-flight";
import { useWorkWrite } from "@/features/work-app/shared/use-work-write";
import { StepCreate } from "@/features/work-app/steps/step-create";
import { SavedViewReceipt } from "@/features/work-app/saved-views/saved-view-receipt";
import { useTabReads } from "@/features/work-app/fullscreen/parts/use-tab-reads";
import type {
  WorkAgendaPage,
  WorkCardFrame,
  WorkSavedViewDefinition,
  WorkTransport,
} from "@/features/work-app/transport/transport";

import { deferred } from "@tests/helpers/deferred";

/** Two presses that reach the page before React re-renders, which a disabled button cannot stop. */
function pressTwiceInOneTick(button: HTMLElement) {
  act(() => {
    button.click();
    button.click();
  });
}

describe("the single-flight guard", () => {
  it("lets one start through until it leaves, and counts a newer generation as a new flight", () => {
    const { result } = renderHook(() => useSingleFlight());

    expect(result.current.enter()).toBe(true);
    expect(result.current.enter()).toBe(false);
    result.current.leave();
    expect(result.current.enter()).toBe(true);
    result.current.leave();

    expect(result.current.enter(1)).toBe(true);
    expect(result.current.enter(1)).toBe(false);
    expect(result.current.enter(2)).toBe(true);
    // The older read answers late: it must not free the newer one.
    result.current.leave(1);
    expect(result.current.enter(2)).toBe(false);
    result.current.leave(2);
    expect(result.current.enter(2)).toBe(true);
  });

  it("answers whether any flight runs, and keeps one object across renders", () => {
    const { result, rerender } = renderHook(() => useSingleFlight());
    const first = result.current;

    expect(result.current.isRunning()).toBe(false);
    result.current.enter(3);
    expect(result.current.isRunning()).toBe(true);
    result.current.leave(3);
    expect(result.current.isRunning()).toBe(false);

    rerender();
    expect(result.current).toBe(first);
  });
});

describe("two presses in one tick", () => {
  it("marks a card row done once", () => {
    const answer = deferred<never>();
    const updateTask = vi.fn(() => answer.promise);
    const writer = {
      getTask: vi.fn(),
      updateTask,
    } as unknown as CardStatusWriter;
    const frame: WorkCardFrame = {
      kind: "card",
      items: [
        {
          kind: "task",
          id: "019f0000-0000-7000-8000-000000000001",
          title: "Ring leverantören",
          status: "todo",
          due_at: null,
          version: 2,
        },
      ],
      total: 1,
      truncated: false,
    };
    render(
      <WorkCard
        state="ready"
        labels={cardLabelsEn}
        frame={frame}
        onOpen={vi.fn()}
        writer={writer}
      />,
    );

    pressTwiceInOneTick(screen.getByRole("button", { name: "Done" }));

    expect(updateTask).toHaveBeenCalledTimes(1);
  });

  it("clears a saved view once", () => {
    const answer = deferred<boolean>();
    const onClear = vi.fn(() => answer.promise);
    render(
      <SavedViewReceipt
        text="Showing view Blocked"
        clearLabel="Show all"
        failedText="Failed"
        onClear={onClear}
      />,
    );

    pressTwiceInOneTick(screen.getByRole("button", { name: "Show all" }));

    expect(onClear).toHaveBeenCalledTimes(1);
  });

  it("sends a shared list write once, then accepts the next after it settles", async () => {
    const answer = deferred<string>();
    const send = vi.fn(() => answer.promise);
    const { result } = renderHook(() => useWorkWrite());

    let first: Promise<string | undefined> | undefined;
    let second: Promise<string | undefined> | undefined;
    act(() => {
      first = result.current.run("move", send);
      second = result.current.run("move", send);
    });
    expect(send).toHaveBeenCalledTimes(1);
    expect(await second).toBeUndefined();

    await act(async () => {
      answer.resolve("done");
      await first;
    });
    expect(result.current.busy).toBe(false);
    act(() => {
      void result.current.run("move-again", send);
    });
    expect(send).toHaveBeenCalledTimes(2);
  });

  // The create field holds back a second Enter itself; the retry button after a failed write reaches the write directly.
  it("retries a failed Contact create once", async () => {
    const user = userEvent.setup();
    const createContact = vi
      .fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockReturnValue(deferred<never>().promise);
    render(
      <NewContact
        transport={{ createContact } as unknown as WorkTransport}
        labels={workEn}
        onCreated={vi.fn()}
      />,
    );
    await user.click(screen.getByRole("button", { name: workEn.newContact }));
    await user.type(
      screen.getByRole("textbox", { name: workEn.newContact }),
      "Bo Berg{Enter}",
    );

    pressTwiceInOneTick(
      await screen.findByRole("button", { name: workEn.retry }),
    );

    expect(createContact).toHaveBeenCalledTimes(2);
  });

  it("retries a failed Step create once", async () => {
    const user = userEvent.setup();
    const createTaskStep = vi
      .fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockReturnValue(deferred<never>().promise);
    render(
      <StepCreate
        taskId="task-1"
        transport={{ createTaskStep } as unknown as WorkTransport}
        labels={workEn}
        onWriteStart={vi.fn()}
        onCreated={vi.fn()}
      />,
    );
    await user.click(screen.getByRole("button", { name: workEn.addStep }));
    await user.type(screen.getByLabelText(workEn.stepTitle), "Ring{Enter}");

    pressTwiceInOneTick(
      await screen.findByRole("button", { name: workEn.retry }),
    );

    expect(createTaskStep).toHaveBeenCalledTimes(2);
  });
});

describe("saved views opened and left in a tab", () => {
  const view: WorkSavedViewDefinition = {
    view: "agenda",
    context: "all",
    status: "blocked",
  };
  const blocked: WorkAgendaPage = {
    items: [
      {
        kind: "task",
        id: "019f0000-0000-7000-8000-0000000000a2",
        title: "Blocked item",
        status: "blocked",
        due_at: null,
        version: 1,
        project_id: null,
        agenda_group: "today",
      },
    ],
    next_cursor: null,
  };
  const everything: WorkAgendaPage = { items: [], next_cursor: null };

  function mountReads(getWorkAgenda: ReturnType<typeof vi.fn>) {
    const onViewApplied = vi.fn();
    const onViewCleared = vi.fn();
    const hook = renderHook(() =>
      useTabReads({
        transport: { getWorkAgenda } as unknown as WorkTransport,
        offers: () => false,
        initialTab: "agenda",
        firstFrame: undefined,
        failure: undefined,
        onViewApplied,
        onViewCleared,
      }),
    );
    return { ...hook, onViewApplied, onViewCleared };
  }

  function shownPage(entry: unknown) {
    const shown = entry as { status: string; frame?: { page: unknown } };
    return shown.status === "ready" ? shown.frame?.page : undefined;
  }

  it("shows the own list when the view was opened first and answers last", async () => {
    const viewAnswer = deferred<WorkAgendaPage>();
    const getWorkAgenda = vi
      .fn()
      .mockReturnValueOnce(viewAnswer.promise)
      .mockResolvedValueOnce(everything);
    const { result, onViewApplied, onViewCleared } = mountReads(getWorkAgenda);

    let opened!: Promise<boolean>;
    act(() => {
      opened = result.current.applyView("agenda", view, "Blocked");
    });
    await act(async () => {
      await result.current.clearView("agenda");
    });
    await act(async () => {
      viewAnswer.resolve(blocked);
      await opened;
    });

    expect(shownPage(result.current.entries.agenda)).toBe(everything);
    expect(onViewCleared).toHaveBeenCalledTimes(1);
    expect(onViewApplied).not.toHaveBeenCalled();
    // The older call was replaced, not failed: nothing for the caller to report.
    await expect(opened).resolves.toBe(true);
  });

  it("shows the view when the own list was asked for first and answers last", async () => {
    const listAnswer = deferred<WorkAgendaPage>();
    const getWorkAgenda = vi
      .fn()
      .mockReturnValueOnce(listAnswer.promise)
      .mockResolvedValueOnce(blocked);
    const { result, onViewApplied, onViewCleared } = mountReads(getWorkAgenda);

    let left!: Promise<boolean>;
    act(() => {
      left = result.current.clearView("agenda");
    });
    await act(async () => {
      await result.current.applyView("agenda", view, "Blocked");
    });
    await act(async () => {
      listAnswer.resolve(everything);
      await left;
    });

    expect(shownPage(result.current.entries.agenda)).toBe(blocked);
    expect(onViewApplied).toHaveBeenCalledTimes(1);
    expect(onViewCleared).not.toHaveBeenCalled();
  });
});

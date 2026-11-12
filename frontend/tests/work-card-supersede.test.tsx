import { render, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { cardLabelsEn, cardLabelsSv } from "@/features/work-app/card-labels";
import {
  WORK_CARD_CHANNEL,
  WorkCard,
  type CardStatusWriter,
} from "@/features/work-app/work-card";
import { rootFromToolResult } from "@/features/work-app/transport";
import type {
  WorkCardFrame,
  WorkItemRecord,
  WorkTask,
} from "@/features/work-app/transport";

const TASK_ID = "019f0000-0000-7000-8000-000000000001";
const OLDER = "2026-10-25T10:00:00Z";
const YOUNGER = "2026-10-25T10:05:00Z";

/**
 * Fictional BroadcastChannel: channels with the same name see each other's messages, senders do
 * not receive their own, and delivery is asynchronous like the real API. The names of the channels
 * opened are recorded so the test can check the channel name.
 */
type Listener = (event: { data: unknown }) => void;

class FakeBroadcastChannel {
  static groups = new Map<string, Set<FakeBroadcastChannel>>();
  static opened: string[] = [];

  private listeners = new Set<Listener>();
  private closed = false;

  constructor(readonly name: string) {
    FakeBroadcastChannel.opened.push(name);
    this.group().add(this);
  }

  addEventListener(type: string, listener: Listener): void {
    if (type === "message") this.listeners.add(listener);
  }

  removeEventListener(type: string, listener: Listener): void {
    if (type === "message") this.listeners.delete(listener);
  }

  postMessage(data: unknown): void {
    for (const peer of this.group()) {
      if (peer === this) continue;
      const payload = structuredClone(data);
      setTimeout(() => peer.deliver(payload), 0);
    }
  }

  close(): void {
    this.closed = true;
    this.group().delete(this);
  }

  private deliver(data: unknown): void {
    if (this.closed) return;
    for (const listener of this.listeners) listener({ data });
  }

  private group(): Set<FakeBroadcastChannel> {
    let members = FakeBroadcastChannel.groups.get(this.name);
    if (!members) {
      members = new Set();
      FakeBroadcastChannel.groups.set(this.name, members);
    }
    return members;
  }
}

beforeEach(() => {
  FakeBroadcastChannel.groups.clear();
  FakeBroadcastChannel.opened = [];
  vi.stubGlobal("BroadcastChannel", FakeBroadcastChannel);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function item(overrides: Partial<WorkItemRecord> = {}): WorkItemRecord {
  return {
    kind: "task",
    id: TASK_ID,
    title: "Ring leverantören",
    status: "todo",
    due_at: null,
    version: 2,
    ...overrides,
  };
}

function frame(issuedAt?: string): WorkCardFrame {
  const base: WorkCardFrame = {
    kind: "card",
    items: [item()],
    total: 1,
    truncated: false,
  };
  return issuedAt === undefined ? base : { ...base, issuedAt };
}

function taskAt(version: number, status = "todo"): { task: WorkTask } {
  return {
    task: {
      id: TASK_ID,
      title: "Ring leverantören",
      status,
      due_at: null,
      version,
    },
  };
}

function writerMock(): {
  writer: CardStatusWriter;
  getTask: ReturnType<typeof vi.fn>;
  updateTask: ReturnType<typeof vi.fn>;
} {
  const getTask = vi.fn(() => Promise.resolve(taskAt(5)));
  const updateTask = vi.fn((_id: string, version: number) =>
    Promise.resolve(taskAt(version + 1, "completed")),
  );
  return {
    writer: {
      getTask,
      updateTask,
    } as unknown as CardStatusWriter,
    getTask,
    updateTask,
  };
}

describe("work card supersession", () => {
  it("uses the sidekick-work-cards channel", () => {
    render(
      <WorkCard
        state="ready"
        labels={cardLabelsEn}
        frame={frame(OLDER)}
        onOpen={() => undefined}
      />,
    );

    expect(WORK_CARD_CHANNEL).toBe("sidekick-work-cards");
    expect(FakeBroadcastChannel.opened).toContain("sidekick-work-cards");
  });

  it("marks an older card replaced in Swedish and disables its actions", async () => {
    const { writer, updateTask } = writerMock();
    const announce = vi.fn();
    const onOpen = vi.fn();
    const older = render(
      <WorkCard
        state="ready"
        labels={cardLabelsSv}
        frame={frame(OLDER)}
        onOpen={onOpen}
        writer={writer}
        announce={announce}
      />,
    );
    const younger = render(
      <WorkCard
        state="ready"
        labels={cardLabelsSv}
        frame={frame(YOUNGER)}
        onOpen={() => undefined}
        writer={writer}
        announce={() => undefined}
      />,
    );

    const olderCard = within(older.container);
    await waitFor(() =>
      expect(olderCard.getByRole("status")).toHaveTextContent(
        "Ersatt av ett nyare kort",
      ),
    );
    expect(
      olderCard.getByRole("button", { name: "Visa alla (1)" }),
    ).toBeDisabled();
    for (const button of olderCard.getAllByRole("button", {
      name: /Klar|Blockerad|Pågår|Att göra/,
    })) {
      expect(button).toBeDisabled();
    }

    const user = userEvent.setup();
    await user.click(olderCard.getByRole("button", { name: "Klar" }));
    expect(updateTask).not.toHaveBeenCalled();
    expect(announce).not.toHaveBeenCalled();
    expect(onOpen).not.toHaveBeenCalled();
    younger.unmount();
  });

  it("marks an older card replaced in English", async () => {
    const { writer } = writerMock();
    const older = render(
      <WorkCard
        state="ready"
        labels={cardLabelsEn}
        frame={frame(OLDER)}
        onOpen={() => undefined}
        writer={writer}
        announce={() => undefined}
      />,
    );
    const younger = render(
      <WorkCard
        state="ready"
        labels={cardLabelsEn}
        frame={frame(YOUNGER)}
        onOpen={() => undefined}
        writer={writer}
        announce={() => undefined}
      />,
    );

    await waitFor(() =>
      expect(within(older.container).getByRole("status")).toHaveTextContent(
        "Replaced by a newer card",
      ),
    );
    expect(
      within(older.container).getByRole("button", { name: "Show all (1)" }),
    ).toBeDisabled();
    younger.unmount();
  });

  it("keeps the newest card editable and announces its status change", async () => {
    const { writer, updateTask } = writerMock();
    const announce = vi.fn();
    const older = render(
      <WorkCard
        state="ready"
        labels={cardLabelsEn}
        frame={frame(OLDER)}
        onOpen={() => undefined}
        writer={writer}
        announce={() => undefined}
      />,
    );
    const younger = render(
      <WorkCard
        state="ready"
        labels={cardLabelsEn}
        frame={frame(YOUNGER)}
        onOpen={() => undefined}
        writer={writer}
        announce={announce}
      />,
    );

    await waitFor(() =>
      expect(within(older.container).getByRole("status")).toHaveTextContent(
        cardLabelsEn.superseded,
      ),
    );
    const youngerCard = within(younger.container);
    expect(youngerCard.queryByText(cardLabelsEn.superseded)).toBeNull();
    expect(
      youngerCard.getByRole("button", { name: "Show all (1)" }),
    ).toBeEnabled();

    const user = userEvent.setup();
    await user.click(youngerCard.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(announce).toHaveBeenCalledTimes(1));
    expect(updateTask).toHaveBeenCalledTimes(1);
    expect(announce).toHaveBeenCalledWith(
      cardLabelsEn.statusChanged.replace("{status}", "done"),
    );
    older.unmount();
  });

  it("never supersedes a card whose frame has no issued_at", async () => {
    const { writer, updateTask } = writerMock();
    const announce = vi.fn();
    const first = render(
      <WorkCard
        state="ready"
        labels={cardLabelsEn}
        frame={frame()}
        onOpen={() => undefined}
        writer={writer}
        announce={announce}
      />,
    );
    const second = render(
      <WorkCard
        state="ready"
        labels={cardLabelsEn}
        frame={frame(YOUNGER)}
        onOpen={() => undefined}
        writer={writer}
        announce={() => undefined}
      />,
    );

    // Give the channel time to deliver any announcement before asserting.
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(
      within(first.container).queryByText(cardLabelsEn.superseded),
    ).toBeNull();
    const user = userEvent.setup();
    await user.click(
      within(first.container).getByRole("button", { name: "Done" }),
    );
    await waitFor(() => expect(announce).toHaveBeenCalledTimes(1));
    expect(updateTask).toHaveBeenCalledTimes(1);
    second.unmount();
  });
});

describe("work card issued_at from the tool result", () => {
  it("carries a valid card.issued_at into the frame", () => {
    expect(
      rootFromToolResult({
        card: {
          kind: "work_changes",
          total: 0,
          truncated: false,
          items: [],
          issued_at: OLDER,
        },
      }),
    ).toEqual({
      kind: "card",
      items: [],
      total: 0,
      truncated: false,
      issuedAt: OLDER,
    });
  });

  it("leaves issuedAt out when card.issued_at is missing or unreadable", () => {
    const missing = rootFromToolResult({
      card: { kind: "work_changes", total: 0, truncated: false, items: [] },
    });
    const unreadable = rootFromToolResult({
      card: {
        kind: "work_changes",
        total: 0,
        truncated: false,
        items: [],
        issued_at: "not a time",
      },
    });
    expect(missing).toEqual({
      kind: "card",
      items: [],
      total: 0,
      truncated: false,
    });
    expect(missing).not.toHaveProperty("issuedAt");
    expect(unreadable).not.toHaveProperty("issuedAt");
  });
});

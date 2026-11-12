import { act, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { JournalRoom } from "@/features/journal-app/room";
import type { RoomTransport } from "@/features/mcp-apps/room-types";

// Performance: a journal room mounted without a result reads today's day only while it is shown
// (props.active !== false). Hidden, it reads nothing; shown, it reads the day once. The numbers are counts of
// host tool calls on the transport mock.

function localToday(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

const emptyDay = {
  journal_date: localToday(),
  entries: [],
  next_cursor: null,
  summary: {
    journal_date: localToday(),
    exists: false,
    status: null,
    content: null,
  },
};

function host() {
  const names: string[] = [];
  const call = vi.fn((name: string) => {
    names.push(name);
    if (name === "get_journal_day") return Promise.resolve(emptyDay);
    if (name === "list_journal_entries")
      return Promise.resolve({ entries: [] });
    return Promise.resolve({});
  });
  const transport = {
    call,
    requestDisplayMode: vi.fn().mockResolvedValue("fullscreen"),
    updateModelContext: vi.fn().mockResolvedValue(undefined),
  } as unknown as RoomTransport;
  const days = () => names.filter((name) => name === "get_journal_day").length;
  return { transport, names, days };
}

async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

beforeEach(() => {
  document.head.innerHTML = '<meta name="sidekick-app-locale" content="en">';
});

it("a full room mounted hidden without a result makes no get_journal_day read; shown, it makes exactly one", async () => {
  const fake = host();
  const view = (active: boolean) => (
    <JournalRoom mode="full" transport={fake.transport} active={active} />
  );
  const { rerender } = render(view(false));
  await settle();
  console.info("[perf] journal hidden: tool calls =", fake.names.length);
  expect(fake.days()).toBe(0);
  expect(fake.names).toEqual([]);

  rerender(view(true));
  await settle();
  console.info("[perf] journal shown: get_journal_day =", fake.days(), {
    all: fake.names,
  });
  expect(fake.days()).toBe(1);

  // Hidden and shown again: the room already has its day and reads it no more.
  rerender(view(false));
  rerender(view(true));
  await settle();
  expect(fake.days()).toBe(1);
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("a full room mounted shown without a result reads the day once", async () => {
  const fake = host();
  render(<JournalRoom mode="full" transport={fake.transport} />);
  await settle();
  expect(fake.days()).toBe(1);
});

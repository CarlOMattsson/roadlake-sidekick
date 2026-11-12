import { act, cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fillLabel } from "@/features/work-app/agenda-undo";
import { workEn } from "@/features/work-app/labels";
import { WorkRoom } from "@/features/work-app/room";
import type { RoomTransport } from "@/features/mcp-apps/room-types";
import { ShoppingRoom } from "@/features/shopping-app/room";
import type {
  ShoppingDetail,
  ShoppingItem,
} from "@/features/shopping-app/transport";

// Performance: the host tool calls a room makes after it opens with a result, and for one tap. The room is the real
// room on its real transport (createShoppingTransport / createWorkTransport); only the host's `call` is a mock that
// records the tool names. The counts are printed with console.info.

const READ_TOOLS = new Set([
  "get_shopping_list",
  "list_shopping_lists",
  "list_contacts",
  "get_work_agenda",
  "get_work_board",
  "get_work_hierarchy",
  "list_tasks",
  "list_saved_work_views",
  "list_domains",
  "get_task",
]);

function tally(names: readonly string[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const name of names) out[name] = (out[name] ?? 0) + 1;
  return out;
}
const reads = (names: readonly string[]) =>
  names.filter((name) => READ_TOOLS.has(name));

async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

/** A host whose tool calls are recorded by name and answered by `answer`. */
function host(answer: (name: string, args: unknown) => unknown) {
  const names: string[] = [];
  const call = vi.fn((name: string, args?: unknown) => {
    names.push(name);
    try {
      return Promise.resolve(answer(name, args));
    } catch (error) {
      return Promise.reject(error instanceof Error ? error : new Error(name));
    }
  });
  const transport = {
    call,
    requestDisplayMode: vi.fn().mockResolvedValue("fullscreen"),
    updateModelContext: vi.fn().mockResolvedValue(undefined),
  } as unknown as RoomTransport;
  return { transport, names };
}

beforeEach(() => {
  document.head.innerHTML = '<meta name="sidekick-app-locale" content="en">';
});
afterEach(() => cleanup());

describe("Shopping: calls after open and for one purchase", () => {
  const list = {
    id: "019f0000-0000-7000-8000-000000000001",
    name: "Weekly shopping",
    version: 1,
    archived: false,
    created_at: "2026-10-24T12:00:00Z",
    updated_at: "2026-10-24T12:00:00Z",
  };
  function item(id: string, name: string): ShoppingItem {
    return {
      id,
      list_id: list.id,
      name,
      quantity: "1",
      unit: "st",
      note: null,
      occasion: null,
      offer: null,
      offer_status: "none",
      product_url: null,
      purchased: false,
      purchased_at: null,
      recipient_contact_id: null,
      store: null,
      target_date: null,
      created_at: "2026-10-24T12:00:00Z",
      updated_at: "2026-10-24T12:00:00Z",
      version: 1,
    };
  }
  const milk = item("019f0000-0000-7000-8000-0000000000a1", "Milk");
  const detail: ShoppingDetail = {
    shopping_list: list,
    evaluated_on: "2026-10-24",
    next_offset: null,
    items: [milk, item("019f0000-0000-7000-8000-0000000000a2", "Bread")],
  };

  it("fullscreen with a result reads only the register of lists; one purchase tap is one set_shopping_item_purchased and no read of the list", async () => {
    const user = userEvent.setup();
    const fake = host((name) => {
      if (name === "list_shopping_lists")
        return { lists: [detail.shopping_list], next_offset: null };
      if (name === "set_shopping_item_purchased")
        return { item: { ...milk, purchased: true, version: 2 } };
      throw new Error(`unexpected ${name}`);
    });
    render(
      <ShoppingRoom
        mode="full"
        transport={fake.transport}
        initial={detail}
        resultId={1}
      />,
    );
    // The store view (fullscreen): the ring ticks the item, the row beside it opens the form; no checkbox.
    const box = await screen.findByRole("button", { name: /^Mark Milk as / });
    await settle();
    console.info("[perf] shopping fullscreen open with result:", {
      total: fake.names.length,
      calls: tally(fake.names),
    });
    expect(fake.names).toEqual(["list_shopping_lists"]);

    await user.click(box);
    await settle();
    console.info("[perf] shopping one purchase tap:", {
      total: fake.names.length,
      calls: tally(fake.names),
      reads: reads(fake.names).length,
    });
    expect(fake.names).toEqual([
      "list_shopping_lists",
      "set_shopping_item_purchased",
    ]);
    expect(fake.names).not.toContain("get_shopping_list");
    // The same ring now says it can be undone (the purchase is held, so the row stays in place).
    expect(box).toHaveAccessibleName("Mark Milk as not bought");
  });
});

describe("Work: calls after open and for one done tap", () => {
  const task = {
    kind: "task",
    id: "019f0000-0000-7000-8000-0000000000a1",
    title: "Agenda-uppgift",
    status: "todo",
    due_at: null,
    version: 1,
    project_id: null,
    agenda_group: "today",
  };

  it("fullscreen agenda with active=true reads only the To sort count (1); a done tap is one update_task and 0 reads", async () => {
    const user = userEvent.setup();
    const fake = host((name) => {
      if (name === "list_tasks") return { tasks: [], next_cursor: null };
      if (name === "list_saved_work_views") return { saved_views: [] };
      if (name === "update_task")
        return { task: { ...task, status: "completed", version: 2 } };
      throw new Error(`unexpected ${name}`);
    });
    render(
      <WorkRoom
        mode="full"
        transport={fake.transport}
        initial={{ items: [task], next_cursor: null }}
        resultId={1}
        active
      />,
    );
    await screen.findByText("Agenda-uppgift");
    await settle();
    const opened = tally(fake.names);
    console.info("[perf] work fullscreen agenda open with result:", {
      total: fake.names.length,
      calls: opened,
    });
    // The agenda is the result itself; the To sort count is the only read. The saved views are read when their panel
    // opens, not at mount (so this is 0, not 1).
    expect(opened).toEqual({ list_tasks: 1 });
    expect(fake.names).not.toContain("list_saved_work_views");

    const before = fake.names.length;
    await user.click(
      screen.getByRole("button", {
        name: fillLabel(workEn.agendaComplete, { title: task.title }),
      }),
    );
    await settle();
    const after = fake.names.slice(before);
    console.info("[perf] work one done tap:", {
      total: after.length,
      calls: tally(after),
      reads: reads(after).length,
    });
    expect(after).toEqual(["update_task"]);
    expect(reads(after)).toEqual([]);
  });
});

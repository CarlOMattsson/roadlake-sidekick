import {
  boardLabelsEn,
  boardLabelsSv,
} from "@/features/work-app/board/board-labels";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { RoomMessageContext } from "@/features/mcp-apps/ui/room-context";
import { shoppingEn, shoppingSv } from "@/features/shopping-app/labels";
import { ShoppingView } from "@/features/shopping-app/shopping-view";
import type {
  ShoppingDetail,
  ShoppingTransport,
} from "@/features/shopping-app/transport";
import { WorkNewTaskContext } from "@/features/work-app/shared/empty-actions";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import { WorkEmpty } from "@/features/work-app/shared/work-empty";
import type { WorkTransport } from "@/features/work-app/transport/transport";
import { renderAgenda } from "@tests/helpers/agenda-triage-fixtures";

// The empty Agenda, Status and shopping list explain themselves and offer a way on, as Kontakter and Dagbok do.

describe("Empty Agenda and Status", () => {
  it("says what the Agenda is for, with an example for Claude", () => {
    renderAgenda([], { getWorkAgenda: vi.fn() } as unknown as WorkTransport);
    expect(screen.getByText(workEn.agendaEmpty)).toBeVisible();
    expect(screen.getByText(workEn.agendaEmptyHint)).toBeVisible();
    expect(screen.getByText(`“${workEn.workEmptyAsk}”`)).toBeVisible();
  });

  it("sends the example to Claude and opens the new-Task field when the room offers them", async () => {
    const user = userEvent.setup();
    const send = vi.fn(() => Promise.resolve(true));
    const newTask = vi.fn();
    render(
      <RoomMessageContext.Provider value={send}>
        <WorkNewTaskContext.Provider value={newTask}>
          <WorkEmpty
            title={boardLabelsSv.empty}
            hint={boardLabelsSv.emptyHint}
            labels={workSv}
          />
        </WorkNewTaskContext.Provider>
      </RoomMessageContext.Provider>,
    );
    await user.click(screen.getByRole("button", { name: /Påminn mig/ }));
    expect(send).toHaveBeenCalledWith(workSv.workEmptyAsk);
    await user.click(screen.getByRole("button", { name: workSv.emptyAddTask }));
    expect(newTask).toHaveBeenCalledTimes(1);
  });

  it("offers no New task button without a tab row to create in", () => {
    render(
      <WorkEmpty
        title={boardLabelsEn.empty}
        hint={boardLabelsEn.emptyHint}
        labels={workEn}
      />,
    );
    expect(
      screen.queryByRole("button", { name: workEn.emptyAddTask }),
    ).toBeNull();
  });
});

describe("Empty shopping list", () => {
  const list = {
    id: "019f0000-0000-7000-8000-000000000001",
    name: "Veckohandling",
    version: 1,
    archived: false,
    created_at: "2026-10-24T12:00:00Z",
    updated_at: "2026-10-24T12:00:00Z",
  };
  const empty: ShoppingDetail = {
    shopping_list: list,
    evaluated_on: "2026-10-24",
    next_offset: null,
    items: [],
  };
  const transport = (): ShoppingTransport => ({
    lists: vi.fn().mockResolvedValue({ lists: [list], next_offset: null }),
    get: vi.fn().mockResolvedValue(empty),
    contacts: vi.fn().mockResolvedValue({ contacts: [] }),
    create: vi.fn(),
    rename: vi.fn(),
    add: vi.fn().mockResolvedValue({}),
    update: vi.fn(),
    purchase: vi.fn().mockResolvedValue({}),
  });

  it("in fullscreen: no 0 of 0 bought, a line on what the list is for, and + Add item that opens the field", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <ShoppingView
        transport={transport()}
        labels={shoppingEn}
        initial={empty}
        fullscreen
      />,
    );
    await waitFor(() =>
      expect(screen.getByText(shoppingEn.empty)).toBeVisible(),
    );
    expect(screen.getByText(shoppingEn.emptyHint)).toBeVisible();
    expect(container.querySelector(".shopping-progress")).toBeNull();
    const box = container.querySelector(".sk-empty") as HTMLElement;
    await user.click(
      within(box).getByRole("button", { name: shoppingEn.addItem }),
    );
    expect(
      screen.getByRole("textbox", { name: shoppingEn.addItem }),
    ).toHaveFocus();
    expect(container.querySelector(".sk-empty")).toBeNull();
  });

  it("has the same words in Swedish", () => {
    expect(shoppingSv.emptyHint).toMatch(/handla/);
    expect(workSv.agendaEmptyHint).toMatch(/när/);
  });
});

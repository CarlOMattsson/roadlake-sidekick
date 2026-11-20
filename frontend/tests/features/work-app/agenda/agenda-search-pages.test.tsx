import { agendaLabelsEn } from "@/features/work-app/agenda/agenda-labels";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { expect, it, vi } from "vitest";

import { AgendaView } from "@/features/work-app/agenda/agenda";
import { workEn } from "@/features/work-app/shared/labels";
import type {
  WorkAgendaFrame,
  WorkItemRecord,
  WorkTransport,
} from "@/features/work-app/transport/transport";

function task(id: string, title: string): WorkItemRecord {
  return {
    kind: "task",
    id: `019f0000-0000-7000-8000-0000000000${id}`,
    title,
    status: "todo",
    due_at: null,
    version: 1,
    agenda_group: "today",
  };
}

const first = task("b1", "Skicka offert");
const second = task("b2", "Boka plattsättare");

/** The agenda's frame lives in a parent, as in the work view, so a page that lands is shown. */
function Harness({
  transport,
  initial,
}: {
  transport: WorkTransport;
  initial: WorkAgendaFrame;
}) {
  const [frame, setFrame] = useState(initial);
  return (
    <AgendaView
      frame={frame}
      onChange={setFrame}
      transport={transport}
      labels={workEn}
      moves={0}
      onOpen={vi.fn()}
    />
  );
}

it("reads the remaining pages while a search is typed, so a hit on a later page shows and no Show more stands under one hit", async () => {
  const user = userEvent.setup();
  const getWorkAgenda = vi
    .fn()
    .mockResolvedValue({ items: [second], next_cursor: null });
  const transport = { getWorkAgenda } as unknown as WorkTransport;
  render(
    <Harness
      transport={transport}
      initial={{
        kind: "agenda",
        filters: {},
        page: { items: [first], next_cursor: "page-2" },
      }}
    />,
  );
  expect(screen.getByRole("button", { name: workEn.more })).toBeInTheDocument();

  await user.type(
    screen.getByRole("searchbox", { name: agendaLabelsEn.filter }),
    "platts",
  );

  expect(
    await screen.findByRole("button", { name: second.title }),
  ).toBeInTheDocument();
  expect(getWorkAgenda).toHaveBeenCalledTimes(1);
  expect(getWorkAgenda).toHaveBeenCalledWith({}, "page-2");
  expect(screen.queryByRole("button", { name: workEn.more })).toBeNull();
});

it("says there is no hit only once every page is read", async () => {
  const user = userEvent.setup();
  let land: (value: unknown) => void = () => undefined;
  const getWorkAgenda = vi.fn().mockReturnValue(
    new Promise((resolve) => {
      land = resolve;
    }),
  );
  const transport = { getWorkAgenda } as unknown as WorkTransport;
  render(
    <Harness
      transport={transport}
      initial={{
        kind: "agenda",
        filters: {},
        page: { items: [first], next_cursor: "page-2" },
      }}
    />,
  );
  await user.type(
    screen.getByRole("searchbox", { name: agendaLabelsEn.filter }),
    "xyzqq",
  );
  expect(screen.queryByText(/xyzqq/)).toBeNull();
  land({ items: [second], next_cursor: null });
  expect(await screen.findByText(/xyzqq/)).toBeInTheDocument();
});

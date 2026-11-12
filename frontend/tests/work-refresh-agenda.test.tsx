import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { expect, it, vi } from "vitest";

import { AgendaView } from "@/features/work-app/agenda";
import { workEn } from "@/features/work-app/labels";
import type {
  WorkAgendaFrame,
  WorkItemRecord,
  WorkTransport,
} from "@/features/work-app/transport";

const SKICKA_ID = "019f0000-0000-7000-8000-0000000000a1";
const FAKTURA_ID = "019f0000-0000-7000-8000-0000000000a3";

const skicka: WorkItemRecord = {
  kind: "task",
  id: SKICKA_ID,
  title: "Skicka offert",
  status: "todo",
  due_at: null,
  version: 1,
  agenda_group: "today",
};
const faktura: WorkItemRecord = {
  kind: "task",
  id: FAKTURA_ID,
  title: "Skicka faktura",
  status: "todo",
  due_at: null,
  version: 1,
  agenda_group: "today",
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

/** The agenda's frame lives in a parent, as in the work view, so a read that lands replaces the page. */
function Harness({
  transport,
  initial,
  refreshKey,
}: {
  transport: WorkTransport;
  initial: WorkAgendaFrame;
  refreshKey: number;
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
      refreshKey={refreshKey}
    />
  );
}

it("reads again in place when refreshKey changes: the filter stays, old rows stay until the answer lands", async () => {
  const user = userEvent.setup();
  const answer = deferred<{ items: WorkItemRecord[]; next_cursor: null }>();
  const getWorkAgenda = vi.fn().mockReturnValue(answer.promise);
  const transport = { getWorkAgenda } as unknown as WorkTransport;
  const initial: WorkAgendaFrame = {
    kind: "agenda",
    filters: {},
    page: { items: [skicka], next_cursor: null },
  };
  const { rerender } = render(
    <Harness transport={transport} initial={initial} refreshKey={0} />,
  );

  await user.type(
    screen.getByRole("searchbox", { name: workEn.agendaFilter }),
    "Skicka",
  );
  rerender(<Harness transport={transport} initial={initial} refreshKey={1} />);

  expect(getWorkAgenda).toHaveBeenCalledTimes(1);
  expect(getWorkAgenda).toHaveBeenCalledWith({});
  expect(
    screen.getByRole("button", { name: skicka.title }),
  ).toBeInTheDocument();

  act(() => {
    answer.resolve({ items: [skicka, faktura], next_cursor: null });
  });

  expect(
    await screen.findByRole("button", { name: faktura.title }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: skicka.title }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("searchbox", { name: workEn.agendaFilter }),
  ).toHaveValue("Skicka");
});

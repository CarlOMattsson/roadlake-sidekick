import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { expect, it, vi } from "vitest";

import { ContactsView } from "@/features/work-app/contacts/contacts-list";
import { workEn } from "@/features/work-app/shared/labels";
import type {
  WorkContactsFrame,
  WorkContactSummary,
  WorkTransport,
} from "@/features/work-app/transport/transport";
import { deferred } from "@tests/helpers/deferred";

const bo: WorkContactSummary = {
  id: "id-bo",
  display_name: "Bo",
  archived: false,
};
const bosse: WorkContactSummary = {
  id: "id-bosse",
  display_name: "Bosse",
  archived: false,
};

/** The list's frame lives in a parent, as in the work view, so a read that lands replaces the page. */
function Harness({
  transport,
  initial,
  refreshKey,
}: {
  transport: WorkTransport;
  initial: WorkContactsFrame;
  refreshKey: number;
}) {
  const [frame, setFrame] = useState(initial);
  return (
    <ContactsView
      frame={frame}
      onChange={(_before, next) => setFrame(next)}
      transport={transport}
      labels={workEn}
      moves={0}
      onOpen={vi.fn()}
      refreshKey={refreshKey}
    />
  );
}

it("reads the list again in place with the same search and archive switch, and keeps both", async () => {
  const answer = deferred<{
    items: WorkContactSummary[];
    next_cursor: null;
  }>();
  const listContacts = vi.fn().mockReturnValue(answer.promise);
  const transport = { listContacts } as unknown as WorkTransport;
  const initial: WorkContactsFrame = {
    kind: "contacts",
    q: "Bo",
    includeArchived: true,
    page: {
      items: [bo],
      next_cursor: null,
      q: "Bo",
      includeArchived: true,
    },
  };
  const { rerender } = render(
    <Harness transport={transport} initial={initial} refreshKey={0} />,
  );

  expect(listContacts).not.toHaveBeenCalled();
  rerender(<Harness transport={transport} initial={initial} refreshKey={1} />);

  expect(listContacts).toHaveBeenCalledTimes(1);
  expect(listContacts).toHaveBeenCalledWith({
    q: "Bo",
    includeArchived: true,
  });
  expect(screen.getByRole("button", { name: bo.display_name })).toBeVisible();

  act(() => {
    answer.resolve({ items: [bo, bosse], next_cursor: null });
  });

  expect(
    await screen.findByRole("button", { name: bosse.display_name }),
  ).toBeInTheDocument();
  expect(screen.getByLabelText(workEn.searchContacts)).toHaveValue("Bo");
  // The archive switch sits in the "⋯" panel, which is closed until it is opened.
  await userEvent.click(
    screen.getByRole("button", { name: workEn.moreActions }),
  );
  expect(
    screen.getByRole("checkbox", { name: workEn.showArchived }),
  ).toBeChecked();
});

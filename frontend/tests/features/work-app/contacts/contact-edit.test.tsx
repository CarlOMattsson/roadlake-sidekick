import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ContactEditor } from "@/features/work-app/contacts/contact-edit";
import { workEn } from "@/features/work-app/shared/labels";
import type { WorkContactRecord } from "@/features/work-app/transport/transport";

const anna: WorkContactRecord = {
  id: "019f0000-0000-7000-8000-0000000000c1",
  display_name: "Anna Andersson",
  email: null,
  phone: null,
  context_note: "Vill ha offerten före fredag.",
  relationship: null,
  organization: null,
  role: null,
  address: null,
  aliases: [],
  archived: false,
  archived_at: null,
  version: 3,
};

describe("Contact editor action row", () => {
  it("keeps Save and Cancel in one sticky row at the foot of the form", () => {
    render(
      <ContactEditor
        contact={anna}
        busy={false}
        saveFailed={false}
        rejected={false}
        onSave={vi.fn()}
        onCancel={vi.fn()}
        onAddAlias={vi.fn()}
        onRemoveAlias={vi.fn()}
        labels={workEn}
      />,
    );

    const save = screen.getByRole("button", { name: workEn.save });
    const cancel = screen.getByRole("button", { name: workEn.cancel });
    const row = save.parentElement;

    expect(row).toHaveClass("work-actions-sticky");
    expect(cancel.parentElement).toBe(row);
    expect(row?.nextElementSibling).toBeNull();
  });
});

describe("Contact editor layout", () => {
  function renderEditor() {
    return render(
      <ContactEditor
        contact={anna}
        busy={false}
        saveFailed={false}
        rejected={false}
        onSave={vi.fn()}
        onCancel={vi.fn()}
        onAddAlias={vi.fn()}
        onRemoveAlias={vi.fn()}
        labels={workEn}
      />,
    );
  }

  it("lists the nicknames after Role and Note, last before the action row", () => {
    renderEditor();
    const group = screen.getByRole("group", { name: workEn.aliasesHeading });
    const after = Node.DOCUMENT_POSITION_FOLLOWING;
    for (const label of [
      workEn.email,
      workEn.phone,
      workEn.slack,
      workEn.relationship,
      workEn.organization,
      workEn.role,
      workEn.address,
      workEn.contextNote,
    ]) {
      expect(
        screen.getByLabelText(label).compareDocumentPosition(group) & after,
      ).toBeTruthy();
    }
    const row = screen.getByRole("button", { name: workEn.save }).parentElement;
    expect(group.compareDocumentPosition(row as Element) & after).toBeTruthy();
  });

  it("carries the class that gives the fields room above the sticky row", () => {
    renderEditor();
    expect(screen.getByRole("form", { name: workEn.edit })).toHaveClass(
      "work-contact-edit",
    );
  });

  it("scrolls a focused field into view with the sticky row's room, without animation", async () => {
    const user = userEvent.setup();
    renderEditor();
    const slack = screen.getByLabelText(workEn.slack);
    const scroll = vi.fn();
    slack.scrollIntoView = scroll;
    await user.click(slack);
    expect(scroll).toHaveBeenCalledWith({ block: "nearest" });
  });
});

describe("Contact editor, a refused save", () => {
  function editor(rejected: boolean) {
    return (
      <ContactEditor
        contact={anna}
        busy={false}
        saveFailed={false}
        rejected={rejected}
        onSave={vi.fn()}
        onCancel={vi.fn()}
        onAddAlias={vi.fn()}
        onRemoveAlias={vi.fn()}
        labels={workEn}
      />
    );
  }

  it("names the Slack field and the link it takes when the Slack value was refused", async () => {
    const user = userEvent.setup();
    const { rerender } = render(editor(false));
    await user.type(screen.getByLabelText(workEn.slack), "@anna.andersson");
    rerender(editor(true));

    expect(screen.getByLabelText(workEn.slack)).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(screen.getByText(workEn.slackInvalid)).toBeInTheDocument();
    expect(screen.queryByText(workEn.invalidChange)).not.toBeInTheDocument();
  });

  it("says the values were refused beside Save when no Slack value was changed", () => {
    render(editor(true));

    expect(screen.getByText(workEn.invalidChange)).toBeInTheDocument();
    expect(screen.queryByText(workEn.slackInvalid)).not.toBeInTheDocument();
  });
});

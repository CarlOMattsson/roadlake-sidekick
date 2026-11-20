import { fireEvent, render, screen } from "@testing-library/react";
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
  it("keeps Save and Cancel in one row at the foot of the form, in the flow (never over a field)", () => {
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

    expect(row).toHaveClass("sk-form-actions");
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

  function editorFor(contact: WorkContactRecord, onCancel = vi.fn()) {
    return (
      <ContactEditor
        contact={contact}
        busy={false}
        saveFailed={false}
        rejected={false}
        onSave={vi.fn()}
        onCancel={onCancel}
        onAddAlias={vi.fn()}
        onRemoveAlias={vi.fn()}
        labels={workEn}
      />
    );
  }

  it("does nothing on Escape while a field differs from what was saved", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    render(editorFor(anna, onCancel));
    await user.type(screen.getByLabelText(workEn.role), "Grundare");
    await user.keyboard("{Escape}");
    expect(onCancel).not.toHaveBeenCalled();
    expect(screen.getByLabelText(workEn.role)).toHaveValue("Grundare");
  });

  it("empties the nickname field on Escape and leaves the editor open", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    render(editorFor(anna, onCancel));
    const field = screen.getByLabelText(workEn.aliasValue);
    await user.type(field, "Annie");
    await user.keyboard("{Escape}");
    expect(field).toHaveValue("");
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("closes the remove-nickname question on Escape and leaves the editor open", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    const withAlias = {
      ...anna,
      aliases: [
        { id: "a1", value: "Annie", created_at: "2026-11-01T00:00:00Z" },
      ],
    };
    render(editorFor(withAlias, onCancel));
    await user.click(
      screen.getByRole("button", { name: workEn.removeAliasFor("Annie") }),
    );
    expect(
      screen.getByRole("button", { name: workEn.confirmChange }),
    ).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(
      screen.queryByRole("button", { name: workEn.confirmChange }),
    ).not.toBeInTheDocument();
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("cancels on Escape from a field, as the Cancel button does, and not while a save is in flight", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    const editor = (busy: boolean) => (
      <ContactEditor
        contact={anna}
        busy={busy}
        saveFailed={false}
        rejected={false}
        onSave={vi.fn()}
        onCancel={onCancel}
        onAddAlias={vi.fn()}
        onRemoveAlias={vi.fn()}
        labels={workEn}
      />
    );
    const { rerender } = render(editor(false));
    await user.click(screen.getByLabelText(workEn.role));
    await user.keyboard("{Escape}");
    expect(onCancel).toHaveBeenCalledTimes(1);
    rerender(editor(true));
    fireEvent.keyDown(screen.getByLabelText(workEn.role), { key: "Escape" });
    expect(onCancel).toHaveBeenCalledTimes(1);
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

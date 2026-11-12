import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ContactEditor } from "@/features/work-app/contact-edit";
import { workEn } from "@/features/work-app/labels";
import type { WorkContactRecord } from "@/features/work-app/transport";

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

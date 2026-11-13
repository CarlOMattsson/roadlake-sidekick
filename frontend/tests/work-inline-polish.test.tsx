import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { cardLabelsEn } from "@/features/work-app/shared/card-labels";
import { ContactsView } from "@/features/work-app/contacts/contacts-list";
import { ContactAliases } from "@/features/work-app/contacts/contact-aliases";
import { workEn } from "@/features/work-app/shared/labels";
import { WorkCard } from "@/features/work-app/inline/work-card";
import type {
  WorkCardFrame,
  WorkContactAlias,
  WorkContactSummary,
  WorkContactsFrame,
  WorkItemRecord,
  WorkTransport,
} from "@/features/work-app/transport/transport";

import { readStylesheet } from "./helpers/stylesheet";

const TASK: WorkItemRecord = {
  kind: "task",
  id: "019f0000-0000-7000-8000-000000000001",
  title: "Ring leverantören",
  status: "in_progress",
  due_at: null,
  version: 2,
};

const CARD: WorkCardFrame = {
  kind: "card",
  items: [TASK],
  total: 1,
  truncated: false,
};

function contact(name: string): WorkContactSummary {
  return { id: `id-${name}`, display_name: name, archived: false };
}

describe("contact list rows start on the left", () => {
  it("renders each name inside the row's open button, which contacts.css aligns to the start", () => {
    const frame: WorkContactsFrame = {
      kind: "contacts",
      q: "",
      includeArchived: false,
      page: {
        items: [contact("Anna Andersson")],
        next_cursor: null,
        q: "",
        includeArchived: false,
      },
    };
    const { container } = render(
      <ContactsView
        frame={frame}
        onChange={() => undefined}
        transport={{ listContacts: vi.fn() } as unknown as WorkTransport}
        labels={workEn}
        moves={0}
        onOpen={() => undefined}
      />,
    );

    expect(
      container.querySelector(".work-contact-list .sk-row-open"),
    ).toHaveTextContent("Anna Andersson");
  });

  it("aligns the row to the start in contacts.css, above the shared button centring", () => {
    const css = readStylesheet("features/work-app/contacts/contacts.css");

    expect(
      css.rule(".sidekick-work .work-contact-list .sk-row-open"),
    ).toMatchObject({ "justify-content": "flex-start", "text-align": "start" });
  });
});

describe("contact aliases show the heading once", () => {
  it("shows the alias field label as visible text, not only for assistive technology", () => {
    const aliases: WorkContactAlias[] = [
      { id: "a1", value: "Kompis", created_at: "2026-10-01T10:00:00Z" },
    ];
    render(
      <ContactAliases
        aliases={aliases}
        busy={false}
        editable
        onAdd={() => undefined}
        onRemove={() => undefined}
        labels={workEn}
      />,
    );

    const field = screen.getByLabelText(workEn.aliasValue);
    expect(field.tagName).toBe("INPUT");
    const label = field.closest("div")?.querySelector("label");
    expect(label).not.toHaveClass("work-visually-hidden");
    expect(label).toHaveTextContent("New alternative name");
  });
});

describe("inline Open shows that the host is answering", () => {
  it("marks Open busy, disabled and relabelled while the host answers, then restores it", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    const { rerender } = render(
      <WorkCard
        state="ready"
        labels={cardLabelsEn}
        frame={CARD}
        onOpen={onOpen}
        opening={false}
        openingLabel={workEn.opening}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Show all (1)" }));
    expect(onOpen).toHaveBeenCalledTimes(1);

    rerender(
      <WorkCard
        state="ready"
        labels={cardLabelsEn}
        frame={CARD}
        onOpen={onOpen}
        opening
        openingLabel={workEn.opening}
      />,
    );
    const busy = screen.getByRole("button", { name: workEn.opening });
    expect(busy).toHaveAttribute("aria-busy", "true");
    expect(busy).toBeDisabled();
    // A press while the host answers does not ask again.
    await user.click(busy);
    expect(onOpen).toHaveBeenCalledTimes(1);

    rerender(
      <WorkCard
        state="ready"
        labels={cardLabelsEn}
        frame={CARD}
        onOpen={onOpen}
        opening={false}
        openingLabel={workEn.opening}
      />,
    );
    const idle = screen.getByRole("button", { name: "Show all (1)" });
    expect(idle).toBeEnabled();
    expect(idle).not.toHaveAttribute("aria-busy");
  });
});

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ContactWays } from "@/features/work-app/contacts/contact-card";
import {
  changedContactFields,
  draftFromContact,
} from "@/features/work-app/contacts/contact-edit";
import { hierarchyDetailLabelsEn } from "@/features/work-app/hierarchy/hierarchy-detail-labels";
import type { WorkContactRecord } from "@/features/work-app/transport/transport";
import { clearWire } from "@/lib/mcp/clear-wire";

const SLACK = "https://acme.slack.com/team/U01ABC23DEF";

const anna: WorkContactRecord = {
  id: "019f0000-0000-7000-8000-0000000000c1",
  display_name: "Anna Andersson",
  email: null,
  phone: null,
  context_note: null,
  relationship: null,
  organization: null,
  role: null,
  address: null,
  aliases: [],
  archived: false,
  archived_at: null,
  version: 3,
};

const labels = hierarchyDetailLabelsEn;

describe("The Slack row of a contact's details", () => {
  it("shows the workspace and opens the profile link through the host", async () => {
    const onOpenLink = vi.fn();
    render(
      <ContactWays
        contact={{ ...anna, slack: SLACK }}
        labels={labels}
        onOpenLink={onOpenLink}
      />,
    );

    await userEvent.click(
      screen.getByRole("button", {
        name: new RegExp(`^${labels.waysToReach}`),
      }),
    );
    const link = screen.getByRole("link", { name: "acme.slack.com" });
    expect(link).toHaveAttribute("href", SLACK);

    await userEvent.click(link);
    expect(onOpenLink).toHaveBeenCalledWith(SLACK);
  });

  it("is an ordinary link when the host cannot open links", async () => {
    render(<ContactWays contact={{ ...anna, slack: SLACK }} labels={labels} />);

    await userEvent.click(
      screen.getByRole("button", {
        name: new RegExp(`^${labels.waysToReach}`),
      }),
    );
    expect(
      screen.getByRole("link", { name: "acme.slack.com" }),
    ).toHaveAttribute("href", SLACK);
  });

  it("names Slack in the meta line and has no row without a link", () => {
    const { rerender, container } = render(
      <ContactWays
        contact={{ ...anna, phone: "070-123", slack: SLACK }}
        labels={labels}
      />,
    );
    expect(container.textContent).toContain("Phone and Slack");

    rerender(
      <ContactWays contact={{ ...anna, phone: "070-123" }} labels={labels} />,
    );
    expect(container.textContent).not.toContain("Slack");

    rerender(<ContactWays contact={anna} labels={labels} />);
    expect(container.textContent).toBe("");
  });
});

describe("Editing the Slack link of a contact", () => {
  it("sends the link when it is entered, and clears it when it is emptied", () => {
    const base = draftFromContact({ ...anna, slack: null });
    const entered = { ...base, slack: ` ${SLACK} ` };
    expect(changedContactFields({ values: entered, base })).toEqual({
      slack: SLACK,
    });

    const linked = draftFromContact({ ...anna, slack: SLACK });
    expect(changedContactFields({ values: linked, base: linked })).toEqual({});
    expect(
      changedContactFields({
        values: { ...linked, slack: "  " },
        base: linked,
      }),
    ).toEqual({ slack: null });
  });

  it("is sent to the server as a name in the clear list", () => {
    expect(
      clearWire("update_contact", {
        contact_id: anna.id,
        changes: { slack: null, role: "Chef" },
      }),
    ).toEqual({
      contact_id: anna.id,
      changes: { role: "Chef" },
      clear: ["slack"],
    });
  });
});

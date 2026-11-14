import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  inlineSummaryLabelsEn,
  inlineSummaryLabelsSv,
} from "@/features/work-app/inline/inline-summary-labels";
import {
  workEn,
  workSv,
  type WorkLabels,
} from "@/features/work-app/shared/labels";
import { WorkView } from "@/features/work-app/view/work-view";
import {
  rootFromToolResult,
  type WorkContactRecord,
  type WorkTransport,
} from "@/features/work-app/transport/transport";

const anna: WorkContactRecord = {
  id: "019f0000-0000-7000-8000-0000000000c1",
  display_name: "Anna Andersson",
  email: "anna@example.com",
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

/** A get_contact_context answer with the given number of linked Projects and Tasks. */
function contextOf(
  projects: number,
  tasks: number,
  tasksNext: string | null = null,
) {
  return Promise.resolve({
    contact: anna,
    projects: {
      items: Array.from({ length: projects }, (_, i) => ({
        id: `p${i}`,
        title: `Projekt ${i}`,
        status: "active",
      })),
      next_cursor: null,
    },
    tasks: {
      items: Array.from({ length: tasks }, (_, i) => ({
        id: `t${i}`,
        title: `Uppgift ${i}`,
        status: "todo",
        due_at: null,
      })),
      next_cursor: tasksNext,
    },
  });
}

function transport(read: () => Promise<unknown> = () => contextOf(2, 3)) {
  return {
    getContactContext: vi.fn(read),
  } as unknown as WorkTransport & {
    getContactContext: ReturnType<typeof vi.fn>;
  };
}

/** The inline root of a Contact, as a tool result opens it, with fullscreen offered. */
function renderInline(work: WorkTransport, onFullscreen = vi.fn()) {
  const view = render(
    <WorkView
      transport={work}
      initial={rootFromToolResult({ contact: anna })}
      labels={workEn}
      inlineLabels={inlineSummaryLabelsEn}
      fullscreen={onFullscreen}
    />,
  );
  return { ...view, onFullscreen };
}

describe("inline Contact card", () => {
  it("shows role · organization on the meta line, the relationship as a chip, never the address", async () => {
    const profiled: WorkContactRecord = {
      ...anna,
      relationship: "Kund",
      organization: "Acme AB",
      role: "Inköpschef",
      address: "Storgatan 1, Stockholm",
    };
    const work = transport();
    const { container } = render(
      <WorkView
        transport={work}
        initial={rootFromToolResult({ contact: profiled })}
        labels={workEn}
        inlineLabels={inlineSummaryLabelsEn}
        fullscreen={vi.fn()}
      />,
    );

    expect(
      await screen.findByText(
        `Inköpschef · Acme AB · ${inlineSummaryLabelsEn.projectCount}: 2 · ${inlineSummaryLabelsEn.taskCount}: 3`,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Kund")).toHaveClass("work-chip");
    expect(container.textContent).not.toContain("Storgatan");
    expect(container.textContent).not.toContain(profiled.address ?? "");
  });

  it("names its nicknames on one line and opens the contact with a button that says so", async () => {
    const nicknamed: WorkContactRecord = {
      ...anna,
      aliases: [
        { id: "a1", value: "Annie", created_at: "2026-11-01T10:00:00Z" },
        { id: "a2", value: "A. A.", created_at: "2026-11-01T10:00:00Z" },
      ],
    };
    render(
      <WorkView
        transport={transport()}
        initial={rootFromToolResult({ contact: nicknamed })}
        labels={workEn}
        inlineLabels={inlineSummaryLabelsEn}
        fullscreen={vi.fn()}
      />,
    );

    expect(
      await screen.findByText(
        inlineSummaryLabelsEn.alsoKnownAs("Annie, A. A."),
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Open contact" }),
    ).toBeInTheDocument();
  });

  it("shows no form fields, only the name, the e-mail and the counts", async () => {
    const work = transport();
    const { container } = renderInline(work);

    expect(container.querySelectorAll("input, textarea, select")).toHaveLength(
      0,
    );
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("button", { name: workEn.save })).toBeNull();
    expect(screen.queryByRole("button", { name: workEn.edit })).toBeNull();
    expect(screen.getByText(anna.display_name)).toBeInTheDocument();
    expect(
      await screen.findByText(
        `${anna.email} · ${inlineSummaryLabelsEn.projectCount}: 2 · ${inlineSummaryLabelsEn.taskCount}: 3`,
      ),
    ).toBeInTheDocument();
    expect(work.getContactContext).toHaveBeenCalledWith(anna.id);
  });

  it("labels the card Contact in English, without the app name above it", () => {
    const { container } = renderInline(transport());

    const card = screen.getByRole("region", { name: workEn.contact });
    expect(workEn.contact).toBe("Contact");
    expect(within(card).getByText("Contact")).toHaveClass("work-compact-kind");
    expect(container.querySelector("header")).toBeNull();
  });

  it("labels the card Kontakt in Swedish", () => {
    render(
      <WorkView
        transport={transport()}
        initial={rootFromToolResult({ contact: anna })}
        labels={workSv}
        inlineLabels={inlineSummaryLabelsSv}
        fullscreen={vi.fn()}
      />,
    );

    const card = screen.getByRole("region", { name: workSv.contact });
    expect(workSv.contact).toBe("Kontakt");
    expect(within(card).getByText("Kontakt")).toHaveClass("work-compact-kind");
    // The visually hidden heading names the Contact card, not the app.
    expect(
      screen.getByRole("heading", { level: 1, name: workSv.contact }),
    ).toHaveClass("work-visually-hidden");
    expect(screen.queryByText("Arbete")).toBeNull();
  });

  it("Open asks the host for fullscreen and does not open the editor inline", async () => {
    const { onFullscreen } = renderInline(transport());

    await userEvent.click(
      screen.getByRole("button", { name: inlineSummaryLabelsEn.showContact }),
    );
    expect(onFullscreen).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: workEn.save })).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("button", { name: workEn.back })).toBeNull();
  });

  it("leaves out a count of zero", async () => {
    renderInline(transport(() => contextOf(0, 1)));

    expect(
      await screen.findByText(
        new RegExp(`${inlineSummaryLabelsEn.taskCount}: 1`),
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(new RegExp(inlineSummaryLabelsEn.projectCount)),
    ).toBeNull();
  });

  it("marks a count as at least N when the Tasks continue on another page", async () => {
    renderInline(transport(() => contextOf(1, 2, "next")));

    expect(
      await screen.findByText(
        new RegExp(`${inlineSummaryLabelsEn.taskCount}: 2\\+`),
      ),
    ).toBeInTheDocument();
  });

  it("keeps the name and Open when the counts cannot be read", async () => {
    const work = transport(() => Promise.reject(new Error("offline")));
    renderInline(work);

    await waitFor(() => expect(work.getContactContext).toHaveBeenCalled());
    expect(screen.getByText(anna.display_name)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: inlineSummaryLabelsEn.showContact }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(new RegExp(inlineSummaryLabelsEn.taskCount)),
    ).toBeNull();
  });
});

describe("fullscreen Contact view", () => {
  const profiled: WorkContactRecord = {
    ...anna,
    relationship: "Kund",
    organization: "Acme AB",
    role: "Inköpschef",
    address: "Storgatan 1, Stockholm",
  };

  /** A Contact root in a fullscreen host: no fullscreen offer, so the header and the full card show. */
  function renderFullscreen(
    work: WorkTransport,
    labels: WorkLabels,
    inlineLabels: typeof inlineSummaryLabelsEn,
    contact: WorkContactRecord = profiled,
  ) {
    return render(
      <WorkView
        transport={work}
        initial={rootFromToolResult({ contact })}
        labels={labels}
        inlineLabels={inlineLabels}
        shortcuts
      />,
    );
  }

  it("labels the header Contact, not the app name, when a Contact is shown", () => {
    const { container } = renderFullscreen(
      transport(),
      workEn,
      inlineSummaryLabelsEn,
    );

    const header = container.querySelector("header");
    expect(header).not.toBeNull();
    expect(
      within(header as HTMLElement).getByRole("heading", { level: 1 }),
    ).toHaveTextContent(workEn.contact);
    expect(screen.queryByText(workEn.title)).toBeNull();
  });

  it("labels the header Kontakt in Swedish, not Arbete", () => {
    const { container } = renderFullscreen(
      transport(),
      workSv,
      inlineSummaryLabelsSv,
    );

    const header = container.querySelector("header");
    expect(
      within(header as HTMLElement).getByRole("heading", { level: 1 }),
    ).toHaveTextContent("Kontakt");
    expect(screen.queryByText("Arbete")).toBeNull();
  });

  it("shows the address as a line on the fullscreen card when the Contact has one", async () => {
    renderFullscreen(transport(), workEn, inlineSummaryLabelsEn);

    expect(await screen.findByText(profiled.address ?? "")).toHaveClass(
      "work-compact-status",
    );
    expect(screen.getByText("Inköpschef · Acme AB")).toBeInTheDocument();
  });

  it("leaves the address line out when the Contact has none", async () => {
    const { container } = renderFullscreen(
      transport(),
      workEn,
      inlineSummaryLabelsEn,
      { ...profiled, address: null },
    );

    await screen.findByText("Inköpschef · Acme AB");
    expect(container.textContent).not.toContain("Storgatan");
  });

  it("keeps the address off the inline card, which is only a summary", async () => {
    const work = transport();
    const { container } = render(
      <WorkView
        transport={work}
        initial={rootFromToolResult({ contact: profiled })}
        labels={workEn}
        inlineLabels={inlineSummaryLabelsEn}
        fullscreen={vi.fn()}
      />,
    );

    await waitFor(() => expect(work.getContactContext).toHaveBeenCalled());
    expect(container.textContent).not.toContain("Storgatan");
  });
});

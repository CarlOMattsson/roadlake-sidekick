import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  inlineSummaryLabelsEn,
  inlineSummaryLabelsFor,
  inlineSummaryLabelsSv,
} from "@/features/work-app/inline/inline-summary-labels";
import {
  AgendaSummary,
  InlineRow,
} from "@/features/work-app/inline/inline-summary";
import { workEn } from "@/features/work-app/shared/labels";
import { WorkView } from "@/features/work-app/view/work-view";
import {
  type WorkFrame,
  type WorkItemRecord,
  type WorkTransport,
} from "@/features/work-app/transport/transport";
import {
  agendaItems,
  installFixedClock,
} from "./helpers/inline-summary-fixtures";
import { readSource } from "./helpers/source-files";
import { readStylesheet } from "./helpers/stylesheet";

installFixedClock();

/** Dotted paths to every string leaf, so a missing key on either side shows up. */
function flatKeys(value: unknown, prefix = ""): string[] {
  if (typeof value !== "object" || value === null) return [prefix];
  return Object.entries(value).flatMap(([key, child]) =>
    flatKeys(child, prefix ? `${prefix}.${key}` : key),
  );
}

describe("WorkView inline root agenda and Contact list", () => {
  const contacts = [
    { id: "c1", display_name: "Anna Lind" },
    { id: "c2", display_name: "Bo Berg" },
  ];
  const agendaRoot: WorkFrame = {
    kind: "agenda",
    filters: {},
    page: { items: agendaItems, next_cursor: null },
  };
  const contactsRoot: WorkFrame = {
    kind: "contacts",
    q: "",
    includeArchived: false,
  };

  function workWith(): WorkTransport {
    return {
      listContacts: vi
        .fn()
        .mockResolvedValue({ items: contacts, next_cursor: null }),
      getWorkAgenda: vi.fn(),
    } as unknown as WorkTransport;
  }

  it("shows the agenda summary with Open when fullscreen is offered, and not the full list", () => {
    render(
      <WorkView
        transport={workWith()}
        initial={agendaRoot}
        labels={workEn}
        inlineLabels={inlineSummaryLabelsEn}
        fullscreen={vi.fn()}
      />,
    );
    expect(screen.getByText("1 today, 2 overdue")).toBeInTheDocument();
    // The bottom Open is the only button of the summary besides the rows, which open their record.
    for (const button of screen.getAllByRole("button", {
      name: /^Open Agenda/,
    })) {
      expect(button).toBeVisible();
    }
    // The summary lists the overdue records, then today's; upcoming ones stay in fullscreen.
    expect(screen.getByText("Betala faktura")).toBeInTheDocument();
    expect(screen.getByText("Ring Anna")).toBeInTheDocument();
    expect(screen.queryByText("Städa garaget")).toBeNull();
  });

  it("shows the full agenda when the host cannot show fullscreen", () => {
    render(
      <WorkView
        transport={workWith()}
        initial={agendaRoot}
        labels={workEn}
        inlineLabels={inlineSummaryLabelsEn}
        fullscreen={undefined}
      />,
    );
    expect(screen.getByText("Betala faktura")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open Agenda" })).toBeNull();
  });

  it("reads the first Contact page for the count and the first names when the root has no page", async () => {
    const work = workWith();
    render(
      <WorkView
        transport={work}
        initial={contactsRoot}
        labels={workEn}
        inlineLabels={inlineSummaryLabelsEn}
        fullscreen={vi.fn()}
      />,
    );
    expect(await screen.findByText("2 contacts")).toBeInTheDocument();
    expect(work.listContacts).toHaveBeenCalledWith({
      q: "",
      includeArchived: false,
    });
    expect(screen.getByText("Anna Lind")).toBeInTheDocument();
    expect(screen.getByText("Bo Berg")).toBeInTheDocument();
  });

  it("lists the exact match of the search text first, for a question like who is Anna", async () => {
    const work = {
      listContacts: vi.fn().mockResolvedValue({
        items: [
          { id: "c2", display_name: "Anna Lind" },
          { id: "c1", display_name: "Anna" },
        ],
        next_cursor: null,
      }),
    } as unknown as WorkTransport;
    render(
      <WorkView
        transport={work}
        initial={{ kind: "contacts", q: "Anna", includeArchived: false }}
        labels={workEn}
        inlineLabels={inlineSummaryLabelsEn}
        fullscreen={vi.fn()}
      />,
    );
    expect(await screen.findByText("Matches: 2")).toBeInTheDocument();
    expect(work.listContacts).toHaveBeenCalledWith({
      q: "Anna",
      includeArchived: false,
    });
    const card = screen.getByRole("region", {
      name: inlineSummaryLabelsEn.kind.contacts,
    });
    const titles = [...card.querySelectorAll(".work-compact-row-title")].map(
      (node) => node.textContent,
    );
    expect(titles).toEqual(["Anna", "Anna Lind"]);
  });

  it("shows the full Contact list when the host cannot show fullscreen", async () => {
    render(
      <WorkView
        transport={workWith()}
        initial={contactsRoot}
        labels={workEn}
        inlineLabels={inlineSummaryLabelsEn}
        fullscreen={undefined}
      />,
    );
    expect(await screen.findByText("Anna Lind")).toBeInTheDocument();
  });
});

describe("inline row meta and open chevron", () => {
  // Nine days before the fixed clock (25 Oct 2026, 12:00 UTC): overdue, and in progress.
  const overdueTask: WorkItemRecord = {
    kind: "task",
    id: "019f0000-0000-7000-8000-0000000000e1",
    title: "Skriv offerten",
    status: "in_progress",
    due_at: "2026-10-16T09:00:00Z",
    agenda_group: "overdue",
  };

  it("gives the time before the status in the row's meta and in its name, in English", () => {
    render(
      <AgendaSummary
        page={{ items: [overdueTask], next_cursor: null }}
        labels={inlineSummaryLabelsEn}
        onOpen={vi.fn()}
      />,
    );
    const row = screen.getByRole("button", {
      name: "Skriv offerten, 9 days overdue, In progress",
    });
    const meta = row.querySelector(".work-compact-row-meta");
    expect(
      Array.from(meta?.children ?? [], (part) => part.textContent),
    ).toEqual(["9 days overdue", "In progress"]);
    expect(meta?.firstElementChild).toHaveAttribute("data-tone", "overdue");
  });

  it("gives the time before the status in Swedish, '9 dagar försenad' then 'Pågår'", () => {
    render(
      <AgendaSummary
        page={{ items: [overdueTask], next_cursor: null }}
        labels={inlineSummaryLabelsSv}
        onOpen={vi.fn()}
      />,
    );
    const row = screen.getByRole("button", {
      name: "Skriv offerten, 9 dagar försenad, Pågår",
    });
    const meta = row.querySelector(".work-compact-row-meta");
    expect(
      Array.from(meta?.children ?? [], (part) => part.textContent),
    ).toEqual(["9 dagar försenad", "Pågår"]);
  });

  it("puts the open chevron between the title and the meta, hidden from assistive technology, and opens the row", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    render(
      <ul>
        <InlineRow
          title="Skriv offerten"
          meta={[
            { text: "9 days overdue", tone: "overdue" },
            { text: "In progress" },
          ]}
          onOpen={onOpen}
        />
      </ul>,
    );
    const row = screen.getByRole("button", {
      name: "Skriv offerten, 9 days overdue, In progress",
    });
    expect(Array.from(row.children, (child) => child.className)).toEqual([
      "work-compact-row-title",
      "work-open-chevron",
      "work-compact-row-meta",
    ]);
    const chevron = row.querySelector(".work-open-chevron");
    expect(chevron).toHaveAttribute("aria-hidden", "true");
    expect(chevron?.querySelector("svg")).not.toBeNull();
    await user.click(row);
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("lays the open row out as the title and the chevron on one line, with the meta under them", () => {
    const css = readStylesheet("features/work-app/inline/inline-summary.css");

    expect(
      css.rule(
        ".sidekick-work :is(.work-compact-agenda, .work-compact-board) .work-compact-open",
      )["grid-template-columns"],
    ).toBe("minmax(0, 1fr) auto");
  });
});

describe("inline summary labels", () => {
  it("has the same keys in Swedish and English", () => {
    expect(flatKeys(inlineSummaryLabelsSv).sort()).toEqual(
      flatKeys(inlineSummaryLabelsEn).sort(),
    );
  });

  it("picks Swedish only for Swedish host locales", () => {
    expect(inlineSummaryLabelsFor("sv-SE")).toBe(inlineSummaryLabelsSv);
    expect(inlineSummaryLabelsFor("en-US")).toBe(inlineSummaryLabelsEn);
    expect(inlineSummaryLabelsFor("")).toBe(inlineSummaryLabelsEn);
  });

  it("is self-contained: the summary and its labels import no Sidekick app catalogue or components", () => {
    for (const file of [
      "inline/inline-summary.tsx",
      "inline/inline-summary-labels.ts",
    ]) {
      const source = readSource(`features/work-app/${file}`);
      expect(source, file).not.toMatch(/from\s+["']@\/(i18n|components)/);
    }
  });
});

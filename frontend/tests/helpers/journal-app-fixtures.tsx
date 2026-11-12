import { render, screen, within } from "@testing-library/react";
import type userEvent from "@testing-library/user-event";
import { vi, type Mock } from "vitest";
import { journalEn } from "@/features/journal-app/labels";
import { JournalView } from "@/features/journal-app/journal-view";
import type {
  JournalDay,
  JournalDraft,
  JournalEntry,
  JournalFrame,
  JournalPendingItem,
  JournalSource,
  JournalTaskProposal,
  JournalTransport,
} from "@/features/journal-app/transport";

export const entryId = "019f0000-0000-7000-8000-0000000000e1";
export const otherEntryId = "019f0000-0000-7000-8000-0000000000e2";
export const savedEntryId = "019f0000-0000-7000-8000-0000000000e3";
export const sourceId = "019f0000-0000-7000-8000-0000000000s1";
/** Pending rows with one draft each, titled "Draft 0" to "Draft <count - 1>". */
export function pendingRows(count: number): JournalPendingItem[] {
  return Array.from({ length: count }, (_, n) => ({
    source_id: `${sourceId}-${n}`,
    journal_date: "2026-10-24",
    source_type: "manual_text",
    source_created_at: "2026-10-24T09:31:00Z",
    character_count: 42,
    state: "draft_pending_review",
    draft_id: `draft-${n}`,
    draft_title: `Draft ${n}`,
  }));
}
/** Saving with undecided suggestions asks first; these tests decide nothing more, so they save without them. */
export async function clickSave(user: ReturnType<typeof userEvent.setup>) {
  const without = screen.queryByRole("button", {
    name: journalEn.saveWithoutThem,
  });
  await user.click(
    without ?? screen.getByRole("button", { name: "Yes, save entry" }),
  );
}

export const entry: JournalEntry = {
  id: entryId,
  source_id: sourceId,
  journal_date: "2026-10-24",
  occurred_at: "2026-10-24T09:30:00Z",
  title: "Mötet om offerten",
  summary: "Kunden vill ha offerten före fredag.",
  key_points: [{ kind: "commitment", text: "Skicka offerten på torsdag." }],
  project_ids: ["019f0000-0000-7000-8000-0000000000p1"],
  task_ids: [],
  contact_ids: ["019f0000-0000-7000-8000-0000000000c1"],
  archived: false,
  version: 1,
};
export const otherEntry: JournalEntry = {
  ...entry,
  id: otherEntryId,
  source_id: "019f0000-0000-7000-8000-0000000000s2",
  title: "Injected <img src=x onerror=alert(1)>",
  summary: null,
  occurred_at: null,
  key_points: [],
  archived: true,
};
export const source: JournalSource = {
  id: sourceId,
  source_type: "manual_text",
  journal_date: "2026-10-24",
  occurred_at: "2026-10-24T09:30:00Z",
  source_recorded_at: "2026-10-24T09:31:00Z",
  language: "sv",
  created_at: "2026-10-24T09:31:00Z",
  raw_text: "Råtext: Anna vill ha offerten före fredag.",
};

export function day(journalDate: string, entries: JournalEntry[]): JournalDay {
  return {
    journal_date: journalDate,
    entries,
    next_cursor: null,
    summary: {
      journal_date: journalDate,
      exists: true,
      status: "current",
      content: { overview: "Dagen handlade om offerten." },
    },
  };
}

/** A day with neither notes nor a summary: the empty day, which keeps its whole button. */
export function emptyDay(journalDate: string): JournalDay {
  return {
    journal_date: journalDate,
    entries: [],
    next_cursor: null,
    summary: {
      journal_date: journalDate,
      exists: false,
      status: null,
      content: null,
    },
  };
}

export const draftId = "019f0000-0000-7000-8000-0000000000d1";
export const projectId = "019f0000-0000-7000-8000-0000000000p1";
export const taskId = "019f0000-0000-7000-8000-0000000000t1";
export const contactAnna = "019f0000-0000-7000-8000-0000000000c1";
export const contactBo = "019f0000-0000-7000-8000-0000000000c2";
export const createProposal: JournalTaskProposal = {
  proposal_id: "019f0000-0000-7000-8000-0000000000a1",
  type: "create_task",
  title: "Ring kunden",
  description: "Bekräfta leveransdatum.",
  project_id: projectId,
  priority: "high",
  due_at: null,
  contact_ids: [contactAnna],
};
export const updateProposal: JournalTaskProposal = {
  proposal_id: "019f0000-0000-7000-8000-0000000000a2",
  type: "update_task",
  task_id: taskId,
  expected_task_version: 3,
  status: "completed",
};
export function draftFixture(
  overrides: Partial<JournalDraft> = {},
): JournalDraft {
  return {
    id: draftId,
    source_id: sourceId,
    journal_date: "2026-10-24",
    state: "pending_review",
    title: "Utkast om offerten",
    summary: "Kunden vill ha offerten före fredag.",
    key_points: [{ kind: "commitment", text: "Skicka offerten på torsdag." }],
    suggestions: {
      projects: [{ id: projectId, rationale: "Offerten hör till projektet." }],
      tasks: [{ id: taskId, rationale: null }],
      contacts: [{ id: contactAnna, rationale: null }],
    },
    task_proposals: [createProposal, updateProposal],
    task_proposal_count: 2,
    catalog: {
      projects: [{ id: projectId, label: "Projekt Offert" }],
      tasks: [{ id: taskId, label: "Skicka offert", status: "todo" }],
      contacts: [
        { id: contactAnna, label: "Anna Andersson" },
        { id: contactBo, label: "Bo Berg" },
      ],
    },
    version: 1,
    ...overrides,
  };
}
export const draftRoot: JournalFrame = { kind: "draft", id: draftId };

export type TransportMock = { [K in keyof JournalTransport]: Mock };

export function transportMock(
  overrides: Partial<TransportMock> = {},
): TransportMock {
  return {
    getDay: vi.fn((journalDate: string) =>
      Promise.resolve(
        day(
          journalDate,
          journalDate === "2026-10-24" ? [entry, otherEntry] : [],
        ),
      ),
    ),
    getEntry: vi.fn((id: string) =>
      Promise.resolve({
        entry:
          id === otherEntryId
            ? otherEntry
            : id === savedEntryId
              ? { ...entry, id: savedEntryId, title: "Sparad post" }
              : entry,
      }),
    ),
    getSource: vi.fn(() => Promise.resolve({ source })),
    getDraft: vi.fn(() => Promise.resolve({ draft: draftFixture(), source })),
    updateDraft: vi.fn((_id: string, version: number) =>
      Promise.resolve({
        draft: { id: draftId, state: "pending_review", version: version + 1 },
      }),
    ),
    rejectDraft: vi.fn((_id: string, version: number) =>
      Promise.resolve({
        draft: { id: draftId, state: "rejected", version: version + 1 },
      }),
    ),
    finalizeDraft: vi.fn(() =>
      Promise.resolve({
        entry: { ...entry, id: savedEntryId, title: "Sparad post" },
        created_task_ids: ["019f0000-0000-7000-8000-0000000000k1"],
        updated_task_ids: [],
      }),
    ),
    ...overrides,
  };
}

export const dayRoot: JournalFrame = {
  kind: "day",
  page: day("2026-10-24", [entry, otherEntry]),
};

/**
 * The Approve or Decline button of one suggestion or task proposal. `prefix` starts the name of its
 * decision group ("Decision for <prefix>"), so the caller need not repeat the whole label.
 */
export function decisionButton(
  prefix: string,
  choice: "Approve" | "Decline" = "Approve",
): HTMLElement {
  const group = screen.getByRole("group", {
    name: (name) => name.startsWith(`Decision for ${prefix}`),
  });
  return within(group).getByRole("button", { name: choice });
}

export function renderDraft(
  transport: TransportMock,
  labels: typeof journalEn = journalEn,
  initial: JournalFrame = draftRoot,
) {
  return render(
    <JournalView transport={transport} initial={initial} labels={labels} />,
  );
}
export function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
export const OFFERTEN = "Utkast om offerten";

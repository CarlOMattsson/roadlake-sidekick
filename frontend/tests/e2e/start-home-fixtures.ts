/**
 * get_start in the shape the server answers, for the simulated host and the view tests. The day is Monday 23 November
 * 2026 in the owner's zone; the specs fix the clock at 08:00 UTC that day. Synthetic data only.
 */
import type { StartHome } from "../../src/features/start-app/home/model";

const hid = (n: number) =>
  `019f0000-0000-7000-8000-${String(900 + n).padStart(12, "0")}`;

export const homeIds = {
  evening: hid(1),
  morning: hid(2),
  overdueOld: hid(10),
  overdueRecent: hid(11),
  dueToday: hid(12),
  waitingErik: hid(20),
  waitingNone: hid(21),
};

/** A full day: every part has something to say. */
export const fullStart: StartHome = {
  day: "2026-11-23",
  insight: {
    code: "waiting_long",
    written_by: "system",
    text: "Du har väntat på Erik Sjöstrand i 10 dagar.",
  },
  ready: {
    items: [
      {
        id: homeIds.evening,
        title: "Morgonplan",
        kind: "morning_plan",
        local_time: "07:00",
        version: 3,
      },
    ],
  },
  suggestions: { pending_count: 5, automation_count: 2 },
  today: {
    overdue_count: 2,
    today_count: 2,
    truncated: true,
    items: [
      {
        id: homeIds.overdueOld,
        kind: "task",
        title: "Boka tid hos tandläkaren",
        version: 2,
        agenda_group: "overdue",
        due_at: "2026-11-15T22:59:00Z",
        project_title: null,
      },
      {
        id: homeIds.overdueRecent,
        kind: "task",
        title: "Godkänn designförslaget för köket",
        version: 1,
        agenda_group: "overdue",
        due_at: "2026-11-21T09:00:00Z",
        project_title: "Köksrenovering",
      },
      {
        id: homeIds.dueToday,
        kind: "task",
        title: "Skicka offerten till Lena",
        version: 4,
        agenda_group: "today",
        due_at: "2026-11-23T15:00:00Z",
        project_title: null,
      },
    ],
  },
  waiting: {
    total: 3,
    capped: false,
    items: [
      {
        id: homeIds.waitingErik,
        title: "Besked om hyresgästen",
        version: 1,
        waiting_since: "2026-11-13T09:00:00Z",
        days: 10,
        contact_id: hid(30),
        contact_name: "Erik Sjöstrand",
      },
      {
        id: homeIds.waitingNone,
        title: "Svar från kommunen om bygglovet",
        version: 1,
        waiting_since: "2026-11-18T09:00:00Z",
        days: 5,
        contact_id: null,
        contact_name: null,
      },
    ],
  },
  since_last: {
    since: "2026-11-22T18:00:00Z",
    runs: 3,
    failed_runs: 0,
    suggestions_created: 5,
    suggestions_decided: 0,
  },
  more: { contacts: 42, automations_failed_today: null },
};

/** A day with nothing that asks for the owner. */
export const quietStart: StartHome = { day: "2026-11-23" };

/** The insight a model wrote, and a part that failed. */
export const partlyStart: StartHome = {
  day: "2026-11-23",
  insight: {
    code: "automation_summary",
    written_by: "ai",
    text: "Morgonmejlet hittade två nya fakturor och en fråga från Lena om offerten.",
  },
  suggestions: { pending_count: 1, automation_count: 1 },
  more: { contacts: null, automations_failed_today: 1 },
  unavailable: [{ part: "today", error: "unavailable" }],
};

/** What skip_ready_conversation answers (the conversation record; the home view only needs it to succeed). */
export const skipped = {
  conversation: {
    cadence: {
      frequency: "daily",
      interval: 1,
      weekdays: [],
      day_of_month: null,
      last_weekday: false,
      until: null,
      local_time: "07:00",
    },
    created_at: "2026-11-01T07:00:00Z",
    day: "2026-11-23",
    day_state: "skipped",
    id: homeIds.evening,
    ingredients: ["tasks_due_today"],
    instruction: "Gå igenom dagens uppgifter med mig.",
    instruction_edited_by_model: false,
    instruction_verified: false,
    instruction_written_by: "claude",
    kind: "morning_plan",
    ready: false,
    state: "active",
    title: "Morgonplan",
    updated_at: "2026-11-23T08:00:00Z",
    version: 4,
  },
};

/** The part of update_task's answer the home view reads: the Task's status and the version the write left. */
export const taskReply = (
  id: string,
  status: "completed" | "todo",
  version: number,
) => ({ task: { id, status, version } });

/** The day after the first task of today is done: that row and its share of the counts are gone. */
export const afterTick: StartHome = {
  ...fullStart,
  today: fullStart.today && {
    ...fullStart.today,
    overdue_count: 1,
    items: fullStart.today.items.filter((row) => row.id !== homeIds.overdueOld),
  },
};

const ok = (structuredContent: unknown) => ({ structuredContent });

/** The host's answers for the home view, as the simulated host takes them. */
export const homeReplies = {
  get_start: {
    __sequence: [ok(fullStart), ok({ ...fullStart, ready: undefined })],
  },
  skip_ready_conversation: ok(skipped),
};

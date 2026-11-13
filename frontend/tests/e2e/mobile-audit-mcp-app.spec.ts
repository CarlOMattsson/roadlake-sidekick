import { mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "@playwright/test";
import type { CDPSession, FrameLocator, Locator, Page } from "@playwright/test";
import { assertAuditClean } from "./mobile-audit-gate";
import { goRoom } from "./app-navigation-fixtures";
import {
  deliverToolResult,
  openSimulatedApp,
  readBuiltApp,
  setHostContext,
  simulatedHostState,
  waitForAppInitialized,
} from "./mcp-host-fixture";

// MOBILE AUDIT on the SIMULATED host (see mcp-host-fixture.ts). This is not a real Claude or
// Android test: every tool answer and every host message is a fixture, and the iframe is a plain
// sandboxed iframe in headless Chromium. The spec measures and takes screenshots; it asserts
// nothing about product quality, so it never fails on a defect. Run it with
// playwright.mobile-audit.config.ts. Output goes to the system temp folder below (override with MOBILE_AUDIT_OUT).
//
// AUDIT_SHOTS=1 also writes the screenshots (skarm/hel and the flow shots) to that folder. Without
// it no screenshot is taken and the iframe/viewport is not resized. Measurements, metrics JSON and
// assertions always run.

const SHOTS = process.env.AUDIT_SHOTS === "1";
const OUT = process.env.MOBILE_AUDIT_OUT ?? join(tmpdir(), "sidekick-mobil");
mkdirSync(OUT, { recursive: true });
mkdirSync(`${OUT}/metrics`, { recursive: true });

const SIZES = [
  { width: 360, height: 780 },
  { width: 390, height: 844 },
  { width: 430, height: 932 },
];
const THEMES = ["light", "dark"] as const;
// Only the middle size in light and dark is taken for the extra steps of a scenario.

const day = 86_400_000;
const iso = (offsetDays: number, hour = 9) => {
  const date = new Date(Date.now() + offsetDays * day);
  date.setUTCHours(hour, 0, 0, 0);
  return date.toISOString();
};
const uid = (prefix: number, n: number) =>
  `019f0000-0000-7000-8${prefix}00-${String(n).padStart(12, "0")}`;

// ---------- Work fixtures ----------

const accents = ["blue", "green", "amber", "violet", null];
const titles = [
  "Ring Anna om offerten",
  "Skicka faktura till Bergström Bygg AB för oktober",
  "Boka mötet med revisorn om momsdeklarationen",
  "Köp present till Lisas födelsedag",
  "Uppdatera webbplatsens personuppgiftspolicy enligt dataskyddsförordningen",
  "Städa garaget",
  "Beställ nya däck",
  "Förbered styrelsemötet",
  "Svara Östen Åkesson",
  "Renovera badrummet: vattenfördröjning och golvvärme",
  "Lämna in deklarationen",
  "Årsredovisningen",
  "Planera semestern",
  "Ring försäkringsbolaget angående skadeanmälan",
  "Hämta paketet",
  "Bokföring september",
  "Gratulera Pelle",
  "Backa upp telefonen",
];
const projects = [
  null,
  "Webbplats",
  "Renovering badrum",
  "Bokslut 2026 och årsredovisning",
  null,
];
function task(
  n: number,
  status: string,
  options: Record<string, unknown> = {},
) {
  return {
    kind: "task",
    id: uid(1, n),
    title: titles[n % titles.length],
    status,
    due_at: n % 3 === 0 ? null : iso((n % 9) - 3),
    version: 1,
    project_id: null,
    project_title: projects[n % projects.length],
    priority: n % 4 === 0 ? "high" : "normal",
    domain_accent: accents[n % accents.length],
    ...options,
  };
}
const board = {
  columns: {
    todo: [0, 1, 2, 3, 4, 5, 6].map((n) => task(n, "todo")),
    in_progress: [7, 8, 9, 10, 11].map((n) => task(n, "in_progress")),
    blocked: [12, 13, 14, 15].map((n) => task(n, "blocked")),
    completed: [16, 17, 18, 19, 20, 21].map((n) => task(n, "completed")),
  },
  next_cursor: "cursor-2",
};
const agenda = {
  items: [
    ...[0, 1, 2].map((n) =>
      task(n, "todo", { agenda_group: "overdue", due_at: iso(-n - 1) }),
    ),
    ...[3, 4, 5, 6].map((n) =>
      task(n, "in_progress", { agenda_group: "today", due_at: iso(0, 14) }),
    ),
    ...[7, 8, 9, 10, 11, 12].map((n) =>
      task(n, "todo", { agenda_group: "upcoming", due_at: iso(n - 5) }),
    ),
  ],
  next_cursor: null,
};
const workChanges = {
  card: {
    kind: "work_changes",
    items: [0, 1, 2, 3, 4, 5, 6, 7].map((n) =>
      task(
        n,
        (["todo", "in_progress", "blocked", "completed"] as const)[n % 4] ??
          "todo",
      ),
    ),
    total: 11,
    truncated: true,
    issued_at: iso(0),
  },
};
const hierarchy = {
  nodes: [
    {
      kind: "domain",
      id: "d1",
      parent_id: null,
      title: "Företaget",
      accent: "blue",
    },
    {
      kind: "domain",
      id: "d2",
      parent_id: null,
      title: "Hem och familj",
      accent: "green",
    },
    {
      kind: "process",
      id: "pr1",
      parent_id: "d1",
      title: "Ekonomi och bokslut",
    },
    { kind: "process", id: "pr2", parent_id: "d1", title: "Försäljning" },
    {
      kind: "project",
      id: "p1",
      parent_id: "pr1",
      title: "Bokslut 2026 och årsredovisning",
      status: "active",
      version: 1,
    },
    {
      kind: "project",
      id: "p2",
      parent_id: "pr2",
      title: "Webbplats",
      status: "active",
      version: 1,
    },
    {
      kind: "project",
      id: "p3",
      parent_id: "d2",
      title: "Renovering badrum",
      status: "active",
      version: 1,
    },
    {
      kind: "project",
      id: "p4",
      parent_id: "d2",
      title: "Semester sommar",
      status: "active",
      version: 1,
    },
    {
      kind: "task",
      id: "t1",
      parent_id: "p1",
      title: "Lämna in deklarationen",
      status: "todo",
      version: 1,
    },
  ],
  truncated: false,
  tasks: [
    {
      id: "t1",
      parent_id: "p1",
      title: "Lämna in deklarationen",
      status: "todo",
      version: 1,
      due_at: iso(2),
      steps: [
        { id: "s1", title: "Samla kvitton", status: "completed" },
        { id: "s2", title: "Kontrollera moms", status: "todo" },
      ],
    },
    {
      id: "t2",
      parent_id: "p3",
      title: "Beställ kakel och klinker till badrummet",
      status: "in_progress",
      version: 1,
      due_at: null,
      steps: [],
    },
  ],
};
const fullTask = {
  id: uid(1, 1),
  project_id: uid(2, 1),
  domain_id: null,
  process_id: null,
  derived_domain_id: null,
  title: "Skicka faktura till Bergström Bygg AB för oktober",
  description:
    "Fakturan ska innehålla timmar för oktober, material enligt kvitto och moms. Skicka kopia till ekonomiavdelningen.",
  status: "in_progress",
  priority: "high",
  due_at: iso(1),
  completed_at: null,
  created_at: iso(-10),
  updated_at: iso(-1),
  version: 3,
};
const steps = {
  items: [
    {
      id: uid(3, 1),
      task_id: fullTask.id,
      title: "Samla kvitton",
      status: "completed",
      position: 1,
      version: 1,
    },
    {
      id: uid(3, 2),
      task_id: fullTask.id,
      title: "Räkna ihop timmar för oktober",
      status: "todo",
      position: 2,
      version: 1,
    },
    {
      id: uid(3, 3),
      task_id: fullTask.id,
      title: "Skicka kopia till ekonomiavdelningen",
      status: "todo",
      position: 3,
      version: 1,
    },
  ],
  next_cursor: null,
};
const contactRecord = (n: number, name: string) => ({
  id: uid(4, n),
  display_name: name,
  email: `kontakt${n}@example.org`,
  phone: "+46 70 174 06 05",
  context_note:
    "Träffades på mässan i Göteborg. Föredrar mejl framför telefon.",
  relationship: "Kund",
  organization: "Bergström Bygg AB",
  role: "Inköpschef",
  address: "Storgatan 12, 411 38 Göteborg",
  aliases: [
    { id: uid(5, n), value: "Bergström", created_at: iso(-30) },
    { id: uid(5, n + 1), value: "Kalle B", created_at: iso(-30) },
  ],
  archived: false,
  archived_at: null,
  created_at: iso(-60),
  updated_at: iso(-2),
  version: 2,
});
const names = [
  "Anna Andersson",
  "Bo Berg",
  "Cecilia Carlsson",
  "David Dahl",
  "Erik Ek",
  "Åsa Lind",
  "Östen Åkesson",
  "Karin Karlsson",
  "Lars-Göran Lindqvist",
  "Maria Månsson",
  "Nils Nilsson",
  "Olof Olsson",
];
const contactList = {
  contacts: names.map((name, n) => ({
    id: uid(4, n),
    display_name: name,
    archived: false,
  })),
  next_cursor: null,
  q: "",
  include_archived: false,
};
const contactContext = {
  contact: contactRecord(0, "Anna Andersson"),
  projects: {
    items: [
      { id: "p1", title: "Bokslut 2026 och årsredovisning", status: "active" },
      { id: "p2", title: "Webbplats", status: "active" },
    ],
    next_cursor: null,
  },
  tasks: {
    items: [0, 1, 2, 3, 4].map((n) => ({
      id: uid(1, n),
      title: titles[n],
      status: "todo",
      due_at: iso(n - 2),
    })),
    next_cursor: null,
  },
};
const projectRecord = {
  id: uid(2, 1),
  title: "Bokslut 2026 och årsredovisning",
  description: "Allt som behövs för bokslutet, från kvitton till revisorn.",
  status: "active",
  start_date: "2026-09-01",
  target_date: "2026-12-15",
  created_at: iso(-60),
  updated_at: iso(-2),
  version: 2,
};

const workReplies: Record<string, unknown> = {
  get_work_board: { structuredContent: board },
  get_work_agenda: { structuredContent: agenda },
  get_work_hierarchy: { structuredContent: hierarchy },
  list_contacts: { structuredContent: contactList },
  get_task: { structuredContent: { task: fullTask } },
  get_project: { structuredContent: { project: projectRecord } },
  list_tasks: {
    structuredContent: {
      tasks: [0, 1, 2].map((n) => task(n, "todo")),
      next_cursor: null,
    },
  },
  list_task_steps: { structuredContent: steps },
  list_task_contacts: {
    structuredContent: {
      items: [contactRecord(0, "Anna Andersson"), contactRecord(1, "Bo Berg")],
      next_cursor: null,
    },
  },
  get_contact_context: { structuredContent: contactContext },
  update_task: { structuredContent: { task: { ...fullTask, version: 4 } } },
  reorder_work_board_column: { structuredContent: { ok: true } },
};

// ---------- Journal fixtures ----------

const jEntry = (n: number, title: string) => ({
  id: uid(6, n),
  source_id: uid(7, n),
  journal_date: "2026-10-28",
  occurred_at: iso(-1, 8 + n),
  title,
  summary:
    "Kunden vill ha offerten före fredag. Vi pratade även om leveranstider, garanti och vem som ska hålla i kontakten med bygget under november.",
  key_points: [
    { kind: "commitment", text: "Skicka offerten på torsdag." },
    { kind: "decision", text: "Vi kör på fast pris, inte löpande räkning." },
    { kind: "question", text: "Behöver vi underentreprenör för el?" },
  ],
  project_ids: [],
  task_ids: [uid(1, 1)],
  contact_ids: [uid(4, 0)],
  archived: false,
  version: 1,
});
const jDay = {
  journal_date: "2026-10-28",
  entries: [
    jEntry(1, "Mötet med Anna om offerten"),
    jEntry(2, "Telefonsamtal med revisorn om momsen och bokslutet"),
    jEntry(3, "Tankar efter promenaden"),
    jEntry(4, "Lunch med Bo"),
  ],
  next_cursor: null,
  summary: {
    journal_date: "2026-10-28",
    exists: true,
    origin: "generated",
    status: "current",
    content: {
      overview:
        "Dagen handlade om offerten till Bergström Bygg, ett samtal med revisorn och en lång promenad där flera idéer om webbplatsen kom upp.",
    },
  },
};
const jPending = {
  items: [
    {
      source_id: uid(7, 1),
      journal_date: "2026-10-28",
      source_type: "manual_text",
      source_created_at: iso(-1),
      character_count: 1420,
      state: "draft_pending_review",
      draft_id: uid(8, 1),
      draft_title: "Utkast om mötet med Anna och offerten",
    },
    {
      source_id: uid(7, 2),
      journal_date: "2026-10-27",
      source_type: "voice_transcript",
      source_created_at: iso(-2),
      character_count: 5200,
      state: "draft_pending_review",
      draft_id: uid(8, 2),
      draft_title: "Utkast om renoveringen",
    },
    {
      source_id: uid(7, 3),
      journal_date: "2026-10-26",
      source_type: "manual_text",
      source_created_at: iso(-3),
      character_count: 90,
      state: "no_draft",
      draft_id: null,
      draft_title: null,
    },
  ],
};
const jDraft = {
  draft: {
    id: uid(8, 1),
    source_id: uid(7, 1),
    journal_date: "2026-10-28",
    state: "pending_review",
    title: "Utkast om mötet med Anna och offerten",
    summary:
      "Kunden vill ha offerten före fredag. Vi pratade även om leveranstider och garanti.",
    key_points: [
      { kind: "commitment", text: "Skicka offerten på torsdag." },
      { kind: "decision", text: "Fast pris." },
    ],
    suggestions: {
      projects: [
        { id: "p1", rationale: "Offerten hör till bokslutsprojektet." },
      ],
      tasks: [
        { id: uid(1, 1), rationale: "Samma uppgift som nämns i texten." },
      ],
      contacts: [{ id: uid(4, 0), rationale: "Anna nämns vid namn." }],
    },
    task_proposals: [
      {
        proposal_id: "tp1",
        type: "create_task",
        title: "Skicka offerten till Anna på torsdag",
        description: "Inkludera leveranstider och garanti.",
        project_id: "p1",
        priority: "high",
        due_at: iso(2),
        contact_ids: [uid(4, 0)],
      },
      {
        proposal_id: "tp2",
        type: "update_task",
        task_id: uid(1, 1),
        expected_task_version: 1,
        title: "Skicka faktura till Bergström Bygg AB för oktober",
        due_at: iso(4),
        priority: "high",
      },
    ],
    task_proposal_count: 2,
    catalog: {
      projects: [
        { id: "p1", label: "Bokslut 2026 och årsredovisning" },
        { id: "p2", label: "Webbplats" },
        { id: "p3", label: "Renovering badrum" },
      ],
      tasks: [
        {
          id: uid(1, 1),
          label: "Skicka faktura till Bergström Bygg AB för oktober",
          status: "todo",
        },
        { id: uid(1, 2), label: "Boka mötet med revisorn", status: "todo" },
      ],
      contacts: [
        { id: uid(4, 0), label: "Anna Andersson", context: "Kund" },
        { id: uid(4, 1), label: "Bo Berg", context: "Revisor" },
      ],
    },
    version: 1,
  },
  source: {
    id: uid(7, 1),
    source_type: "manual_text",
    journal_date: "2026-10-28",
    occurred_at: null,
    source_recorded_at: null,
    language: "sv",
    created_at: iso(-1),
    raw_text:
      "Pratade med Anna om offerten. Hon vill ha den före fredag, helst på torsdag. Vi pratade om leveranstider, garanti och vem som håller i kontakten. Jag lovade att skicka en uppdaterad faktura också. Anna nämnde att hon har ett projekt på gång i Göteborg som vi kan vara med på.",
  },
};
const jSource = { source: jDraft.source };
const journalReplies: Record<string, unknown> = {
  get_journal_day: { structuredContent: jDay },
  get_journal_entry: { structuredContent: { entry: jDay.entries[0] } },
  get_journal_source: { structuredContent: jSource },
  get_journal_draft: { structuredContent: jDraft },
};

// ---------- Shopping fixtures ----------

const sList = {
  id: uid(9, 1),
  name: "Veckohandling och presenter",
  version: 1,
  archived: false,
  created_at: iso(-20),
  updated_at: iso(-1),
};
const sItem = (
  n: number,
  name: string,
  extra: Record<string, unknown> = {},
) => ({
  id: uid(9, 10 + n),
  list_id: sList.id,
  name,
  quantity: "1",
  unit: null,
  store: null,
  note: null,
  recipient_contact_id: null,
  occasion: null,
  target_date: null,
  product_url: null,
  offer: null,
  offer_status: "none",
  purchased: false,
  purchased_at: null,
  version: 1,
  created_at: iso(-5),
  updated_at: iso(-1),
  ...extra,
});
const sDetail = {
  shopping_list: sList,
  items: [
    sItem(1, "Mjölk", { quantity: "2", unit: "l", store: "ICA" }),
    sItem(2, "Bröd", { store: "ICA" }),
    sItem(3, "Potatis", {
      quantity: "2",
      unit: "kg",
      store: "ICA",
      note: "Gärna fast sort",
    }),
    sItem(4, "Present till Lisas födelsedag: bok om trädgårdsodling", {
      store: "Akademibokhandeln",
      occasion: "Födelsedag",
      target_date: "2026-11-05",
      product_url: "https://example.org/bok",
      offer: "Extrapris 199 kr",
      offer_status: "active",
    }),
    sItem(5, "Diskmedel", { store: "Willys" }),
    sItem(6, "Batterier AA", { quantity: "8", store: "Clas Ohlson" }),
    sItem(7, "Kaffe", { store: "ICA", purchased: true, purchased_at: iso(-1) }),
    sItem(8, "Ägg", { store: "ICA", purchased: true, purchased_at: iso(-1) }),
  ],
  next_offset: null,
  evaluated_on: "2026-10-29",
};
const shoppingReplies: Record<string, unknown> = {
  list_shopping_lists: {
    structuredContent: { lists: [sList], next_offset: null },
  },
  get_shopping_list: { structuredContent: sDetail },
};

// ---------- Host contexts ----------

const hostInline = (theme: string) => ({
  locale: "sv",
  theme,
  displayMode: "inline",
  availableDisplayModes: ["inline"],
});
const hostInlineOffer = (theme: string) => ({
  locale: "sv",
  theme,
  displayMode: "inline",
  availableDisplayModes: ["inline", "fullscreen"],
});
const hostFull = (theme: string) => ({
  locale: "sv",
  theme,
  displayMode: "fullscreen",
  availableDisplayModes: ["inline", "fullscreen"],
});

// ---------- Scenario machinery ----------

type Step = (app: FrameLocator, page: Page) => Promise<void>;
type Scenario = {
  name: string;
  resource: "work" | "journal" | "shopping";
  host: (theme: string) => Record<string, unknown>;
  /** hostCapabilities of the simulated host; without them the app shows no room strip. */
  capabilities?: Record<string, unknown>;
  result: unknown;
  replies: Record<string, unknown>;
  /** Interactions after the result is delivered, before measuring. */
  steps?: Step;
  /** The inline iframe grows with the content; fullscreen keeps the device height. */
  fullscreen?: boolean;
  /** Takes the extra plain-tap flows and records them in the metrics. */
  probe?: Step;
};

/** A board card's title (the row's long-press target; a card has no ⋯ button). */
const CARD_TITLE =
  ".work-card-head > button:not(.work-card-done):not(.work-drag-handle)";
const longPressCard =
  (nth = 0): Step =>
  async (app) => {
    await app
      .locator(CARD_TITLE)
      .nth(nth)
      .dispatchEvent("contextmenu", undefined, { timeout: 8000 });
    await settle();
  };
const settle = (ms = 500) => new Promise((resolve) => setTimeout(resolve, ms));
const chain =
  (...steps: Step[]): Step =>
  async (app, page) => {
    for (const step of steps) await step(app, page);
  };
const tab =
  (nameStart: RegExp): Step =>
  async (app) => {
    await app
      .getByRole("button", { name: nameStart })
      .first()
      .click({ timeout: 6000 });
    await settle(700);
  };
const buttonText =
  (nameMatch: RegExp, nth = 0): Step =>
  async (app) => {
    await app
      .getByRole("button", { name: nameMatch })
      .nth(nth)
      .click({ timeout: 8000 });
    await settle(600);
  };

/** The ⋯ of the record on screen, then one of its entries: Edit lives there, not on the compact inline card. */
const menuEntry =
  (entry: RegExp): Step =>
  async (app) => {
    await app
      .getByRole("button", { name: /^(Fler alternativ|More options)$/ })
      .last()
      .click({ timeout: 8000 });
    await settle(300);
    await app
      .getByRole("button", { name: entry })
      .first()
      .click({ timeout: 8000 });
    await settle(600);
  };
/** The compact inline Task/Project/Contact card opens the full record in place through its own button. */
const SHOW_MORE = /^(Öppna uppgiften|Open task)/;
const SHOW_PROJECT = /^(Öppna projektet|Open project)/;
const OPEN_CONTACT = /^(Öppna kontakten|Open contact)$/;

const scenarios: Scenario[] = [
  // ----- Work: board / kanban -----
  {
    name: "work-01-tavla-inline-sammanfattning",
    resource: "work",
    host: hostInlineOffer,
    result: board,
    replies: workReplies,
  },
  {
    // Inline, a host without fullscreen shows the board as a summary: the oldest overdue rows and an
    // "Öppna Status · N fler" button. There are no board cards to probe here, so this scenario measures
    // the summary's tap targets; work-02b measures the full board the summary opens in place.
    name: "work-02-tavla-inline-sammanfattning-utan-helskarm",
    resource: "work",
    host: hostInline,
    result: board,
    replies: workReplies,
    probe: summaryProbe(),
  },
  {
    name: "work-02b-tavla-inline-oppnad-hel",
    resource: "work",
    host: hostInline,
    result: board,
    replies: workReplies,
    steps: buttonText(/^(Öppna Status|Open Status)/),
    probe: boardProbe(),
  },
  {
    name: "work-03-tavla-helskarm",
    resource: "work",
    host: hostFull,
    result: board,
    replies: workReplies,
    fullscreen: true,
    probe: boardProbe(),
  },
  {
    name: "work-04-tavla-helskarm-flytta-meny",
    resource: "work",
    host: hostFull,
    result: board,
    replies: workReplies,
    fullscreen: true,
    steps: longPressCard(1),
  },
  {
    // No chip row. The statuses are sections on one page; this scenario scrolls to Pågår.
    name: "work-05-tavla-helskarm-sektion-pagar",
    resource: "work",
    host: hostFull,
    result: board,
    replies: workReplies,
    fullscreen: true,
    steps: async (app) => {
      await app
        .getByRole("region", { name: /^Pågår|^In progress/ })
        .scrollIntoViewIfNeeded({ timeout: 8000 });
      await settle(600);
    },
  },
  {
    name: "work-06-tavla-tom",
    resource: "work",
    host: hostFull,
    result: {
      columns: { todo: [], in_progress: [], blocked: [], completed: [] },
      next_cursor: null,
    },
    replies: workReplies,
    fullscreen: true,
  },
  // ----- Work: agenda -----
  {
    name: "work-07-agenda-helskarm",
    resource: "work",
    host: hostFull,
    result: agenda,
    replies: workReplies,
    fullscreen: true,
  },
  {
    name: "work-08-agenda-inline",
    resource: "work",
    host: hostInline,
    result: agenda,
    replies: workReplies,
  },
  {
    name: "work-09-agenda-helskarm-statusmeny",
    resource: "work",
    host: hostFull,
    result: agenda,
    replies: workReplies,
    fullscreen: true,
    steps: async (app) => {
      const trigger = app.getByRole("button", {
        name: /Ändra status|Change status|Flytta/i,
      });
      if (await trigger.count()) await trigger.first().click();
      await settle();
    },
  },
  // ----- Work: hierarchy -----
  {
    name: "work-10-hierarki-inline-sammanfattning",
    resource: "work",
    host: hostInlineOffer,
    result: hierarchy,
    replies: workReplies,
  },
  {
    name: "work-11-hierarki-inline-trad",
    resource: "work",
    host: hostInline,
    result: hierarchy,
    replies: workReplies,
  },
  {
    name: "work-12-hierarki-helskarm",
    resource: "work",
    host: hostFull,
    result: hierarchy,
    replies: workReplies,
    fullscreen: true,
  },
  {
    name: "work-13-hierarki-helskarm-projekt-oppet",
    resource: "work",
    host: hostFull,
    result: hierarchy,
    replies: workReplies,
    fullscreen: true,
    steps: async (app) => {
      // The Projects list is flat: tap the Project row to open its page.
      await app
        .getByRole("button", { name: /Bokslut 2026/ })
        .first()
        .click();
      await settle(800);
    },
  },
  // ----- Work: task detail -----
  {
    name: "work-14-uppgift-detalj-inline",
    resource: "work",
    host: hostInline,
    result: { task: fullTask },
    replies: workReplies,
  },
  {
    name: "work-15-uppgift-redigera",
    resource: "work",
    host: hostInline,
    result: { task: fullTask },
    replies: workReplies,
    // The compact card has no Edit: open the full Task with "Öppna uppgiften", then Edit from its ⋯ menu.
    steps: chain(buttonText(SHOW_MORE), menuEntry(/^(Redigera|Edit)$/)),
  },
  {
    name: "work-16-uppgift-ny-konakt-lank",
    resource: "work",
    host: hostInline,
    result: { task: fullTask },
    replies: workReplies,
    // "Länka kontakt" is now "Koppla kontakt" and sits on the opened Task, not on the compact card.
    steps: chain(
      buttonText(SHOW_MORE),
      buttonText(/Koppla kontakt|Link contact/),
    ),
  },
  {
    name: "work-17-projekt-detalj",
    resource: "work",
    host: hostInline,
    result: { project: projectRecord },
    replies: workReplies,
  },
  {
    name: "work-18-projekt-redigera",
    resource: "work",
    host: hostInline,
    result: { project: projectRecord },
    replies: workReplies,
    // The compact card shows no Edit: open the full Project with "Öppna projektet"; Edit is in its ⋯.
    steps: chain(buttonText(SHOW_PROJECT), menuEntry(/^(Redigera|Edit)$/)),
  },
  // ----- Work: cards and contacts -----
  {
    name: "work-19-andringskort-inline",
    resource: "work",
    host: hostInlineOffer,
    result: workChanges,
    replies: workReplies,
  },
  {
    name: "work-20-andringskort-inline-utan-helskarm",
    resource: "work",
    host: hostInline,
    result: workChanges,
    replies: workReplies,
  },
  {
    name: "work-21-kontakter-inline-sammanfattning",
    resource: "work",
    host: hostInlineOffer,
    result: contactList,
    replies: workReplies,
  },
  {
    name: "work-22-kontakter-inline-hel-lista",
    resource: "work",
    host: hostInline,
    result: contactList,
    replies: workReplies,
  },
  {
    name: "work-23-kontakter-helskarm",
    resource: "work",
    host: hostFull,
    result: contactList,
    replies: workReplies,
    fullscreen: true,
  },
  {
    name: "work-24-kontakt-detalj",
    resource: "work",
    host: hostInline,
    result: contactContext,
    replies: workReplies,
  },
  {
    name: "work-25-kontakt-redigera",
    resource: "work",
    host: hostInline,
    result: contactContext,
    replies: workReplies,
    // The compact card shows no Edit: open the full Contact with "Öppna kontakten", then Edit from its ⋯ menu.
    steps: chain(buttonText(OPEN_CONTACT), menuEntry(/^(Redigera|Edit)$/)),
  },
  {
    name: "work-26-kontakt-kort",
    resource: "work",
    host: hostInlineOffer,
    result: { contact: contactRecord(0, "Anna Andersson") },
    replies: workReplies,
  },
  {
    name: "work-27-helskarm-flikar-agenda-till-kontakter",
    resource: "work",
    host: hostFull,
    result: agenda,
    replies: workReplies,
    // Work has the tabs Agenda, Status and Projekt. Contacts is its own room, reached through the
    // room strip (or its picker on a narrow screen), which the host only gets with serverTools.
    capabilities: { serverTools: {}, message: {} },
    fullscreen: true,
    steps: chain(
      tab(/^(Status|Board)$/),
      tab(/^(Projekt|Projects)$/),
      async (app) => {
        await goRoom(app, "Kontakter");
        await settle(700);
      },
    ),
  },
  {
    name: "work-28-fel",
    resource: "work",
    host: hostInline,
    result: undefined,
    replies: workReplies,
  },
  // ----- Journal -----
  {
    name: "journal-01-dag-inline",
    resource: "journal",
    host: hostInline,
    result: jDay,
    replies: journalReplies,
  },
  {
    name: "journal-02-dag-helskarm",
    resource: "journal",
    host: hostFull,
    result: jDay,
    replies: journalReplies,
    fullscreen: true,
  },
  {
    name: "journal-03-post-detalj",
    resource: "journal",
    host: hostInline,
    result: jDay,
    replies: journalReplies,
    steps: buttonText(/Mötet med Anna/),
  },
  {
    name: "journal-04-original-text",
    resource: "journal",
    host: hostInline,
    result: jDay,
    replies: journalReplies,
    steps: chain(
      buttonText(/Mötet med Anna/),
      buttonText(/Visa originaltext|Show original/),
    ),
  },
  {
    name: "journal-05-post-kort",
    resource: "journal",
    host: hostInlineOffer,
    result: { entry: jDay.entries[0] },
    replies: journalReplies,
  },
  {
    name: "journal-06-vantande-lista",
    resource: "journal",
    host: hostInline,
    result: jPending,
    replies: journalReplies,
  },
  {
    name: "journal-07-utkast",
    resource: "journal",
    host: hostInline,
    result: jPending,
    replies: journalReplies,
    steps: buttonText(/Utkast om mötet|Granska|Review|Open|Öppna/),
  },
  {
    name: "journal-08-utkast-helskarm",
    resource: "journal",
    host: hostFull,
    result: { draft: { id: jDraft.draft.id } },
    replies: journalReplies,
    fullscreen: true,
  },
  {
    name: "journal-09-tom-dag",
    resource: "journal",
    host: hostInline,
    result: {
      ...jDay,
      entries: [],
      summary: { ...jDay.summary, exists: false, content: null },
    },
    replies: journalReplies,
  },
  // ----- Shopping -----
  {
    name: "shopping-01-kort-inline",
    resource: "shopping",
    host: hostInlineOffer,
    result: sDetail,
    replies: shoppingReplies,
  },
  {
    name: "shopping-02-lista-inline-utan-helskarm",
    resource: "shopping",
    host: hostInline,
    result: sDetail,
    replies: shoppingReplies,
  },
  {
    name: "shopping-03-lista-helskarm",
    resource: "shopping",
    host: hostFull,
    result: sDetail,
    replies: shoppingReplies,
    fullscreen: true,
  },
  {
    name: "shopping-04-batch-kort",
    resource: "shopping",
    host: hostInlineOffer,
    result: {
      items: [
        { item: sItem(1, "Mjölk", { quantity: "2", unit: "l" }) },
        { item: sItem(2, "Bröd") },
        { item: sItem(3, "Potatis", { quantity: "2", unit: "kg" }) },
      ],
    },
    replies: shoppingReplies,
  },
  {
    name: "shopping-05-lista-tom",
    resource: "shopping",
    host: hostInline,
    result: { ...sDetail, items: [] },
    replies: shoppingReplies,
  },
];

/** Inline summary probe: the tap targets of the rows and of the open button, found by accessible name. */
function summaryProbe(): Step {
  return async (app) => {
    const rect = async (locator: Locator) => {
      const box = await locator.first().boundingBox({ timeout: 8000 });
      return box
        ? { w: Math.round(box.width), h: Math.round(box.height) }
        : null;
    };
    const openName = /^(Öppna Status|Open Status)/;
    const openButton = app.getByRole("button", { name: openName });
    const rows = app.getByRole("button", {
      name: /^(?!Öppna Status|Open Status)/,
    });
    writeFileSync(
      `${OUT}/metrics/_probe-${probeName}.json`,
      JSON.stringify(
        {
          rows: await rows.count(),
          rowRect: await rect(rows),
          openRect: await rect(openButton),
          openLabel: await openButton.first().textContent(),
        },
        null,
        2,
      ),
    );
  };
}

/**
 * Board probe (single layout, one column at a time): the card's controls, then a long press on the card
 * (a card has no ⋯) opens the status group inside the card and a status button other than the current one
 * writes the move.
 */
function boardProbe(): Step {
  return async (app, page) => {
    const summary = await app.locator("body").evaluate(() => {
      const board = document.querySelector<HTMLElement>(".work-board");
      const cards = [...document.querySelectorAll(".work-board li.work-card")];
      const done = document.querySelector<HTMLElement>(".work-card-done");
      const title = document.querySelector<HTMLElement>(
        ".work-card-head > button:not(.work-card-done):not(.work-drag-handle)",
      );
      const rect = (el: Element | null) => {
        if (!el) return null;
        const r = el.getBoundingClientRect();
        return { w: Math.round(r.width), h: Math.round(r.height) };
      };
      return {
        layout: board?.getAttribute("data-layout") ?? null,
        cards: cards.length,
        dragHandles: document.querySelectorAll(".work-drag-handle").length,
        // No chip row; the sections' headings ("Att göra (7)" …) are the statuses shown.
        segments: [
          ...document.querySelectorAll(".work-board .work-column h3"),
        ].map((el) => (el.textContent ?? "").trim()),
        doneRect: rect(done),
        // No ⋯; the card's title carries the long-press hint.
        titleRect: rect(title),
        titleHint: title?.getAttribute("aria-description") ?? null,
        titlePerCard: cards.length,
      };
    });
    // Long press on card 0's title, pick the first status other than the current, record the call.
    const before = (await simulatedHostState(page)).calls.length;
    await app
      .locator(CARD_TITLE)
      .first()
      .dispatchEvent("contextmenu", undefined, { timeout: 8000 });
    await settle(300);
    await settle(400);
    const options = await app
      .locator(".work-card-actions button")
      .allTextContents();
    await app
      .locator(".work-card-choices button[aria-pressed=false]")
      .first()
      .click({ timeout: 8000 });
    await settle(900);
    const calls = (await simulatedHostState(page)).calls.slice(before);
    writeFileSync(
      `${OUT}/metrics/_probe-${probeName}.json`,
      JSON.stringify(
        {
          summary,
          options,
          callsAfterMoveTap: calls.map((c) => ({
            name: c.name,
            changes: (c.arguments as { changes?: unknown }).changes,
          })),
        },
        null,
        2,
      ),
    );
  };
}
let probeName = "";

/** Measures one rendered app inside the iframe. Runs in the browser. */
function measureInFrame() {
  const vw = window.innerWidth;
  const isVisible = (el: Element) => {
    const style = getComputedStyle(el);
    if (style.visibility === "hidden" || style.display === "none") return false;
    if (Number(style.opacity) === 0) return false;
    const r = el.getBoundingClientRect();
    if (r.width <= 1 && r.height <= 1) return false;
    let node: Element | null = el;
    while (node) {
      if (
        node.hasAttribute("hidden") ||
        (node.getAttribute("aria-hidden") === "true" && false)
      )
        return false;
      node = node.parentElement;
    }
    return true;
  };
  const describe = (el: Element) => {
    const tag = el.tagName.toLowerCase();
    const cls = (el.getAttribute("class") ?? "")
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .join(".");
    const label =
      el.getAttribute("aria-label") ??
      (el.textContent ?? "").trim().replace(/\s+/g, " ").slice(0, 40);
    return `${tag}${cls ? "." + cls : ""} "${label}"`;
  };
  const scrollerOf = (el: Element) => {
    let node: Element | null = el.parentElement;
    while (node && node !== document.documentElement) {
      const style = getComputedStyle(node);
      if (
        /(auto|scroll)/.test(style.overflowX) &&
        node.scrollWidth > node.clientWidth + 1
      )
        return node;
      node = node.parentElement;
    }
    return null;
  };
  const doc = document.documentElement;
  const body = document.body;
  const horizontal = {
    docScroll: doc.scrollWidth,
    docClient: doc.clientWidth,
    bodyScroll: body.scrollWidth,
    bodyClient: body.clientWidth,
    overflow:
      doc.scrollWidth > doc.clientWidth || body.scrollWidth > body.clientWidth,
  };
  const all = [...document.querySelectorAll("body *")].filter(isVisible);
  const outside: string[] = [];
  for (const el of all) {
    const r = el.getBoundingClientRect();
    if (r.right > vw + 1 || r.left < -1) {
      if (el.tagName === "svg" || el.closest("svg")) continue;
      const scroller = scrollerOf(el);
      if (!scroller)
        outside.push(
          `${describe(el)} [${Math.round(r.left)}..${Math.round(r.right)}]`,
        );
    }
  }
  const scrollers = all
    .filter((el) => {
      const s = getComputedStyle(el);
      return (
        /(auto|scroll)/.test(s.overflowX) && el.scrollWidth > el.clientWidth + 1
      );
    })
    .map(
      (el) =>
        `${describe(el)} scroll ${el.scrollWidth} / client ${el.clientWidth}`,
    );
  const interactiveSel =
    "button, a[href], input:not([type=hidden]), select, textarea, summary, [role=button], [role=tab], [role=checkbox], [role=switch], [tabindex]:not([tabindex='-1'])";
  const smallTargets: string[] = [];
  const seen = new Set<Element>();
  for (const el of document.querySelectorAll(interactiveSel)) {
    if (seen.has(el) || !isVisible(el)) continue;
    seen.add(el);
    const r = el.getBoundingClientRect();
    // A checkbox hidden under a larger label counts as the label's box.
    let target: Element = el;
    if (
      el instanceof HTMLInputElement &&
      (el.type === "checkbox" || el.type === "radio")
    ) {
      const label = el.closest("label");
      if (label) target = label;
    }
    const tr = target.getBoundingClientRect();
    const w = Math.round(Math.max(r.width, target === el ? 0 : tr.width));
    const h = Math.round(Math.max(r.height, target === el ? 0 : tr.height));
    if (w < 44 || h < 44) smallTargets.push(`${describe(el)} ${w}x${h}`);
  }
  const smallText: { text: string; size: number }[] = [];
  const textSeen = new Set<string>();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let node: Node | null;
  while ((node = walker.nextNode())) {
    const text = (node.textContent ?? "").trim();
    const parent = node.parentElement;
    if (!text || !parent || !isVisible(parent)) continue;
    if (parent.closest("script,style")) continue;
    const size = parseFloat(getComputedStyle(parent).fontSize);
    if (size < 12) {
      const key = `${describe(parent)}|${size}`;
      if (!textSeen.has(key)) {
        textSeen.add(key);
        smallText.push({ text: describe(parent), size });
      }
    }
  }
  const bottom = Math.max(
    doc.scrollHeight,
    ...all.map((el) => el.getBoundingClientRect().bottom + window.scrollY),
  );
  return {
    // "single" (one status at a time) or "columns"; null when the view has no board.
    boardLayout:
      document.querySelector(".work-board")?.getAttribute("data-layout") ??
      null,
    horizontal,
    outside: outside.slice(0, 15),
    outsideCount: outside.length,
    scrollers,
    smallTargets,
    smallText,
    contentHeight: Math.ceil(bottom),
    visibleText: (document.body.innerText ?? "")
      .slice(0, 160)
      .replace(/\s+/g, " "),
  };
}

for (const scenario of scenarios) {
  for (const size of SIZES) {
    for (const theme of THEMES) {
      const id = `${scenario.name}__${size.width}__${theme}`;
      test(`audit ${id}`, async ({ page }) => {
        probeName = id;
        const opened = await openSimulatedApp(page, {
          resource: readBuiltApp(scenario.resource, "sv"),
          width: size.width,
          height: size.height,
          hostContext: scenario.host(theme),
          hostCapabilities: scenario.capabilities,
          replies: scenario.replies,
        });
        await waitForAppInitialized(page);
        if (scenario.result === undefined)
          await deliverToolResult(page, null, true);
        else await deliverToolResult(page, scenario.result);
        await settle(900);
        const app = opened.app;
        let stepError: string | null = null;
        try {
          if (scenario.steps) await scenario.steps(app, page);
        } catch (error) {
          stepError = String(error).slice(0, 200);
        }
        const measured = await app
          .locator("html")
          .evaluate(measureInFrame)
          .catch((error) => ({ error: String(error).slice(0, 200) }));
        let probeError: string | null = null;
        // Screen shot as the host shows it (iframe at device size). Only with AUDIT_SHOTS=1.
        if (SHOTS) await page.screenshot({ path: `${OUT}/${id}__skarm.png` });
        // Probe (it changes the board, so it runs after the measurement).
        if (scenario.probe && theme === "light" && size.width === 390) {
          try {
            await scenario.probe(app, page);
          } catch (error) {
            probeError = String(error).slice(0, 200);
          }
        }
        if (SHOTS) {
          // Full page: grow the iframe to the whole content, as an inline host does.
          const contentHeight =
            (measured as { contentHeight?: number }).contentHeight ??
            size.height;
          const tall = Math.min(Math.max(contentHeight + 8, size.height), 6000);
          await page.setViewportSize({ width: size.width, height: tall });
          await page.evaluate((h) => {
            document.querySelector("iframe")!.style.height = `${h}px`;
          }, tall);
          await settle(400);
          await page.screenshot({
            path: `${OUT}/${id}__hel.png`,
            fullPage: true,
          });
        }
        const calls = (await simulatedHostState(page)).calls.map((c) => c.name);
        writeFileSync(
          `${OUT}/metrics/${id}.json`,
          JSON.stringify(
            {
              id,
              scenario: scenario.name,
              width: size.width,
              theme,
              stepError,
              probeError,
              failures: opened.failures,
              networkRequests: opened.networkRequests(),
              hostCalls: calls,
              measured,
            },
            null,
            2,
          ),
        );
        assertAuditClean({
          id,
          stepError,
          probeError,
          measured,
          failures: opened.failures,
        });
        void setHostContext;
      });
    }
  }
}

// ---------- Touch flows on the board (CDP touch events in headless Chromium, simulated host) ----------
// The board shows one status at a time under 640 px (phone-first design 2.2). There is no drag in
// this layout, so the flows are: switch segment, the done glyph, a long press (contextmenu) on a card then a
// status, a long press then Move up or down, and a vertical swipe on a card that must scroll the page (the
// host sends such a swipe to the conversation, so a card may never swallow it). A card has no ⋯.
// Simulated host: not a real Claude or Android test.

test.describe("touch flows", () => {
  test.use({ hasTouch: true });

  // The whole column (no next_cursor), so Move up and Move down are offered.
  const wholeBoard = { ...board, next_cursor: null };

  async function openBoard(page: Page, height = 844) {
    const opened = await openSimulatedApp(page, {
      resource: readBuiltApp("work", "sv"),
      width: 390,
      height,
      hostContext: hostFull("light"),
      replies: {
        ...workReplies,
        get_work_board: { structuredContent: wholeBoard },
      },
    });
    await waitForAppInitialized(page);
    await deliverToolResult(page, wholeBoard);
    await settle(900);
    return opened.app;
  }
  const layoutOf = (app: FrameLocator) =>
    app.locator(".work-board").getAttribute("data-layout");
  async function touch(
    session: CDPSession,
    type: "touchStart" | "touchMove" | "touchEnd",
    x: number,
    y: number,
  ) {
    await session.send("Input.dispatchTouchEvent", {
      type,
      touchPoints: type === "touchEnd" ? [] : [{ x, y }],
    });
  }
  async function swipe(
    page: Page,
    x: number,
    y: number,
    dx: number,
    dy: number,
  ) {
    const cdp = await page.context().newCDPSession(page);
    await touch(cdp, "touchStart", x, y);
    for (let step = 1; step <= 12; step++) {
      await touch(cdp, "touchMove", x + (dx * step) / 12, y + (dy * step) / 12);
      await settle(16);
    }
    await touch(cdp, "touchEnd", x + dx, y + dy);
    await cdp.detach();
  }
  const scrollY = (app: FrameLocator) =>
    app.locator("html").evaluate(() => window.scrollY);
  // The card's quick choices open on a long press (a contextmenu event on the title, which bubbles
  // to the row), not from a ⋯ button.
  const longPressTitle = (app: FrameLocator, nth = 0) =>
    app
      .locator(CARD_TITLE)
      .nth(nth)
      .dispatchEvent("contextmenu", undefined, { timeout: 8000 });

  test("vertical swipe on the done glyph, the title and the meta line scrolls the page", async ({
    page,
  }) => {
    // A short viewport, so the seven cards of the first segment overflow and the page can scroll.
    const app = await openBoard(page, 560);
    expect(await layoutOf(app)).toBe("single");
    const scrollable = await app
      .locator("html")
      .evaluate((el) => el.scrollHeight - el.clientHeight);
    expect(scrollable).toBeGreaterThan(100);
    const results: Record<string, number> = {};
    for (const start of ["done", "title", "meta"] as const) {
      await app.locator("html").evaluate(() => window.scrollTo(0, 0));
      const target = app
        .locator(
          start === "done"
            ? ".work-card-done"
            : start === "title"
              ? ".work-card-head > button:not(.work-card-done)"
              : ".work-card-meta",
        )
        .first();
      const box = (await target.boundingBox())!;
      await swipe(page, box.x + box.width / 2, box.y + box.height / 2, 0, -150);
      await settle(600);
      results[start] = await scrollY(app);
      // The page rolled with the finger: a card has no touch-action that holds the swipe back.
      expect(results[start], `swipe from the ${start}`).toBeGreaterThan(20);
    }
    const touchActions = await app
      .locator("li.work-card, .work-card-done, .work-card-head > button")
      .evaluateAll((els) => [
        ...new Set(els.map((el) => getComputedStyle(el).touchAction)),
      ]);
    writeFileSync(
      `${OUT}/metrics/_touch-vertical-scroll.json`,
      JSON.stringify(
        {
          layout: await layoutOf(app),
          scrollYAfter150pxSwipe: results,
          scrollable,
          touchActions,
        },
        null,
        2,
      ),
    );
  });

  test("horizontal swipe on a card does not scroll the board sideways", async ({
    page,
  }) => {
    const app = await openBoard(page);
    const box = (await app.locator(".work-card-meta").first().boundingBox())!;
    await swipe(page, box.x + 200, box.y + 10, -220, 0);
    await settle(600);
    const row = await app.locator(".work-columns").evaluate((el) => ({
      left: el.scrollLeft,
      scroll: el.scrollWidth,
      client: el.clientWidth,
    }));
    expect(row.left).toBe(0);
    // + 4: the card's › (.work-open-chevron svg, contacts.css) hangs its empty sides 4 px out of its 24 px box into the
    // page gutter by design (its ink stays inside; the glyph is 32, the box 24); it is invisible and the row still has
    // nothing to scroll. It was + 2 while the row still had a ⋯ (since removed).
    expect(row.scroll).toBeLessThanOrEqual(row.client + 4);
    writeFileSync(
      `${OUT}/metrics/_touch-horizontal-scroll.json`,
      JSON.stringify({ layout: await layoutOf(app), columnsRow: row }, null, 2),
    );
    if (SHOTS)
      await page.screenshot({
        path: `${OUT}/flow-tavla-efter-svep__390__light__skarm.png`,
      });
  });

  test("the status tab lists every status as a section, Klar folded until opened", async ({
    page,
  }) => {
    // The chip row ("Kolumner") is gone. Each status is a section on the one page (phone), and
    // Klar is folded ("Klar (6) ⌄") until it is tapped open.
    const app = await openBoard(page);
    expect(await layoutOf(app)).toBe("single");
    await expect(app.getByRole("group", { name: "Kolumner" })).toHaveCount(0);
    await expect(app.locator(".work-column")).toHaveCount(4);
    await expect(
      app.getByRole("heading", { level: 3, name: "Pågår (5)" }),
    ).toBeVisible();
    await expect(
      app.getByRole("region", { name: /^Pågår/ }).locator("li.work-card"),
    ).toHaveCount(5);
    const fold = app.getByRole("button", { name: /^Klar \(6\)/ });
    await expect(fold).toHaveAttribute("aria-expanded", "false");
    await fold.tap();
    await expect(fold).toHaveAttribute("aria-expanded", "true");
    await expect(
      app.getByRole("region", { name: /^Klar/ }).locator("li.work-card"),
    ).toHaveCount(6);
    if (SHOTS)
      await page.screenshot({
        path: `${OUT}/flow-tavla-sektioner__390__light__skarm.png`,
      });
    writeFileSync(
      `${OUT}/metrics/_touch-sections.json`,
      JSON.stringify(
        {
          layout: await layoutOf(app),
          sections: await app.locator(".work-column").count(),
          shown: await app.locator("li.work-card").count(),
        },
        null,
        2,
      ),
    );
  });

  test("the done glyph marks a card done and the Undo line is in the viewport", async ({
    page,
  }) => {
    const app = await openBoard(page);
    const before = (await simulatedHostState(page)).calls.length;
    await app
      .getByRole("button", { name: /^Markera .* som klar$/ })
      .first()
      .tap();
    // "Klar · Ångra" replaces the card's meta line (one .work-agenda-undo per row).
    await expect(app.locator(".work-agenda-undo")).toBeVisible();
    const calls = (await simulatedHostState(page)).calls
      .slice(before)
      .map((c) => ({
        name: c.name,
        changes: (c.arguments as { changes?: unknown }).changes,
      }));
    expect(calls[0]).toMatchObject({
      name: "update_task",
      changes: { status: "completed" },
    });
    const undo = await app.locator(".work-agenda-undo").evaluate((el) => {
      const r = el.getBoundingClientRect();
      return {
        top: Math.round(r.top),
        bottom: Math.round(r.bottom),
        vh: window.innerHeight,
      };
    });
    writeFileSync(
      `${OUT}/metrics/_touch-done.json`,
      JSON.stringify({ layout: await layoutOf(app), calls, undo }, null, 2),
    );
  });

  test("move via a long press on the card to a status, feedback in the viewport", async ({
    page,
  }) => {
    const app = await openBoard(page);
    const before = (await simulatedHostState(page)).calls.length;
    await longPressTitle(app);
    const group = app.locator(".work-card-actions").first();
    await expect(group.locator(".work-card-choices button")).toHaveCount(4);
    await group
      .locator(".work-card-choices button[aria-pressed=false]")
      .first()
      .tap();
    await expect(app.locator(".work-agenda-undo")).toBeVisible();
    await settle(900);
    if (SHOTS)
      await page.screenshot({
        path: `${OUT}/flow-tavla-efter-flytt__390__light__skarm.png`,
      });
    const calls = (await simulatedHostState(page)).calls
      .slice(before)
      .map((c) => c.name);
    expect(calls).toContain("update_task");
    const undo = await app.locator(".work-agenda-undo").evaluate((el) => {
      const r = el.getBoundingClientRect();
      return {
        top: Math.round(r.top),
        bottom: Math.round(r.bottom),
        vh: window.innerHeight,
      };
    });
    expect(undo.bottom).toBeLessThanOrEqual(undo.vh);
    writeFileSync(
      `${OUT}/metrics/_touch-move-feedback.json`,
      JSON.stringify(
        { layout: await layoutOf(app), calls, undoVisible: undo },
        null,
        2,
      ),
    );
  });

  test("move up and move down in the card's long-press group reorder within the column", async ({
    page,
  }) => {
    const app = await openBoard(page);
    const before = (await simulatedHostState(page)).calls.length;
    // The first card is at the top, so Move up is disabled there and Move down is not.
    await longPressTitle(app);
    const group = app.locator(".work-card-actions").first();
    await expect(
      group.getByRole("button", { name: "Flytta upp" }),
    ).toBeDisabled();
    await group.getByRole("button", { name: "Flytta ned" }).tap();
    await settle(900);
    const calls = (await simulatedHostState(page)).calls
      .slice(before)
      .map((c) => c.name);
    expect(calls).toContain("reorder_work_board_column");
    writeFileSync(
      `${OUT}/metrics/_touch-reorder.json`,
      JSON.stringify({ layout: await layoutOf(app), calls }, null, 2),
    );
  });
});

test("empty shopping list", async ({ page }) => {
  const opened = await openSimulatedApp(page, {
    resource: readBuiltApp("shopping", "sv"),
    width: 390,
    height: 844,
    hostContext: hostInline("light"),
    replies: {
      ...shoppingReplies,
      get_shopping_list: { structuredContent: { ...sDetail, items: [] } },
    },
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, { ...sDetail, items: [] });
  await settle(900);
  if (SHOTS)
    await page.screenshot({
      path: `${OUT}/shopping-05b-lista-tom-riktig__390__light__skarm.png`,
    });
  void opened;
});

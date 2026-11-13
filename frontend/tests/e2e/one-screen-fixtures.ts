// Large fixtures for the "one card, one screen" check (one-screen-mcp-app.spec.ts). Realistic upper
// sizes: 25 agenda tasks, 40 shopping items, 8 journal entries, 30 trash items, 15 steps. Simulated
// host only: nothing here touches a backend.

const day = 86_400_000;
/**
 * The fixed "now" of the fixtures and of the browser clock (page.clock in the spec). The app reads
 * the day in Europe/Stockholm, so a real clock made the fixture's UTC "today" lag by one day just
 * after local midnight, and the due chips and row wrapping changed with the time of run.
 * ONE_SCREEN_NOW=<ISO datetime> overrides it for a date sweep.
 */
export const FIXTURE_NOW = new Date(
  process.env.ONE_SCREEN_NOW ?? "2026-11-04T12:00:00Z",
);
// "Today" is the Europe/Stockholm calendar day of FIXTURE_NOW (as in the app), taken as UTC midnight
// so that `iso` keeps its UTC hours. Otherwise 00:00-02:00 in Stockholm put the fixture one day behind.
const stockholmToday = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Europe/Stockholm",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
}).format(FIXTURE_NOW);
const TODAY_UTC = Date.parse(`${stockholmToday}T00:00:00Z`);
export const iso = (offsetDays: number, hour = 9) => {
  const date = new Date(TODAY_UTC + offsetDays * day);
  date.setUTCHours(hour, 0, 0, 0);
  return date.toISOString();
};
export const uid = (prefix: number, n: number) =>
  `019f0000-0000-7000-8${prefix}00-${String(n).padStart(12, "0")}`;

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
const accents = ["blue", "green", "amber", "violet", null];
const projects = [
  null,
  "Webbplats",
  "Renovering badrum",
  "Bokslut 2026 och årsredovisning",
  null,
];

/** Tags for the n-th record: none, one, or three (two and "+1" on a row), with a long one. */
const tagsOf = (n: number): string[] =>
  [[], ["viktig"], ["kund", "byggprojekt-göteborg", "viktig"]][n % 3]!;

export function task(
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
    tags: tagsOf(n),
    ...options,
  };
}
const range = (from: number, to: number) =>
  Array.from({ length: to - from }, (_, i) => from + i);

// ---------- Work ----------

export const bigBoard = {
  columns: {
    todo: range(0, 10).map((n) => task(n, "todo")),
    in_progress: range(10, 18).map((n) => task(n, "in_progress")),
    blocked: range(18, 23).map((n) => task(n, "blocked")),
    completed: range(23, 33).map((n) => task(n, "completed")),
  },
  next_cursor: "cursor-2",
};
export const bigAgenda = {
  items: [
    ...range(0, 5).map((n) =>
      task(n, "todo", { agenda_group: "overdue", due_at: iso(-n - 1) }),
    ),
    ...range(5, 11).map((n) =>
      task(n, "in_progress", { agenda_group: "today", due_at: iso(0, 14) }),
    ),
    ...range(11, 25).map((n) =>
      task(n, "todo", { agenda_group: "upcoming", due_at: iso(n - 9) }),
    ),
  ],
  next_cursor: null,
};
export const bigWorkChanges = {
  card: {
    kind: "work_changes",
    items: range(0, 12).map((n) =>
      task(
        n,
        (["todo", "in_progress", "blocked", "completed"] as const)[n % 4] ??
          "todo",
      ),
    ),
    total: 30,
    truncated: true,
    issued_at: iso(0),
  },
};
export const bigHierarchy = (() => {
  const nodes: Record<string, unknown>[] = [];
  const hTasks: Record<string, unknown>[] = [];
  for (const d of range(1, 4))
    nodes.push({
      kind: "domain",
      id: `d${d}`,
      parent_id: null,
      title: ["Företaget", "Hem och familj", "Hälsa och fritid"][d - 1],
      accent: accents[d - 1],
    });
  for (const p of range(1, 7))
    nodes.push({
      kind: "process",
      id: `pr${p}`,
      parent_id: `d${(p % 3) + 1}`,
      title: `Process ${p}: ekonomi och bokslut`,
    });
  for (const p of range(1, 16))
    nodes.push({
      kind: "project",
      id: `p${p}`,
      parent_id: `pr${(p % 6) + 1}`,
      title: `Projekt ${p}: ${projects[p % 4] ?? "Övrigt"}`,
      status: "active",
      version: 1,
    });
  for (const t of range(1, 31)) {
    hTasks.push({
      id: `t${t}`,
      parent_id: `p${(t % 15) + 1}`,
      title: titles[t % titles.length],
      status: (["todo", "in_progress", "blocked"] as const)[t % 3],
      version: 1,
      due_at: t % 2 ? iso(t % 7) : null,
      steps: [
        { id: `s${t}a`, title: "Första steget", status: "completed" },
        { id: `s${t}b`, title: "Andra steget", status: "todo" },
      ],
    });
  }
  return { nodes, truncated: false, tasks: hTasks };
})();

export const contactNames = [
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
/** The owner's tag vocabulary (list_tags), used on Contacts, Journal entries, Tasks and Projects alike. */
export const tagVocabulary = {
  tags: (
    [
      ["viktig", 6, 3, 8, 0],
      ["kund", 9, 0, 4, 0],
      ["familj", 4, 2, 0, 0],
      ["styrelse", 2, 4, 0, 1],
      ["byggprojekt-göteborg", 3, 1, 4, 0],
      ["vänta", 1, 2, 0, 0],
    ] as const
  ).map(([slug, contact, journal_entry, task, project], n) => ({
    id: uid(10, n),
    slug,
    label: slug,
    created_at: iso(-40),
    updated_at: iso(-40),
    version: 1,
    usage: { contact, journal_entry, task, project },
  })),
  next_cursor: null,
};
export const bigContactList = {
  contacts: range(0, 40).map((n) => ({
    id: uid(4, n),
    display_name: `${contactNames[n % contactNames.length]}${n >= contactNames.length ? ` ${n}` : ""}`,
    archived: false,
    tags: tagsOf(n),
  })),
  next_cursor: null,
  q: "",
  include_archived: false,
};
export const contactRecord = (n: number, name: string) => ({
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
  tags: ["kund", "viktig", "byggprojekt-göteborg"],
  created_at: iso(-60),
  updated_at: iso(-2),
  version: 2,
});
export const bigContactContext = {
  contact: contactRecord(0, "Anna Andersson"),
  projects: {
    items: range(0, 8).map((n) => ({
      id: `p${n}`,
      title: `Projekt ${n}: ${projects[n % 4] ?? "Övrigt"}`,
      status: "active",
    })),
    next_cursor: null,
  },
  tasks: {
    items: range(0, 12).map((n) => ({
      id: uid(1, n),
      title: titles[n],
      status: "todo",
      due_at: iso(n - 2),
    })),
    next_cursor: null,
  },
};
export const fullTask = {
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
  tags: ["kund", "byggprojekt-göteborg"],
  created_at: iso(-10),
  updated_at: iso(-1),
  version: 3,
};
export const bigSteps = {
  items: range(1, 16).map((n) => ({
    id: uid(3, n),
    task_id: fullTask.id,
    title: `Steg ${n}: ${titles[n % titles.length]}`,
    status: n < 4 ? "completed" : "todo",
    position: n,
    version: 1,
  })),
  next_cursor: null,
};
export const projectRecord = {
  id: uid(2, 1),
  title: "Bokslut 2026 och årsredovisning",
  description: "Allt som behövs för bokslutet, från kvitton till revisorn.",
  status: "active",
  start_date: "2026-09-01",
  target_date: "2026-12-15",
  tags: ["styrelse"],
  created_at: iso(-60),
  updated_at: iso(-2),
  version: 2,
};
export const workReplies: Record<string, unknown> = {
  get_work_board: { structuredContent: bigBoard },
  get_work_agenda: { structuredContent: bigAgenda },
  get_work_hierarchy: { structuredContent: bigHierarchy },
  list_contacts: { structuredContent: bigContactList },
  list_tags: { structuredContent: tagVocabulary },
  get_task: { structuredContent: { task: fullTask } },
  get_project: { structuredContent: { project: projectRecord } },
  list_tasks: {
    structuredContent: {
      tasks: range(0, 20).map((n) => task(n, "todo")),
      next_cursor: null,
    },
  },
  list_task_steps: { structuredContent: bigSteps },
  list_task_contacts: {
    structuredContent: {
      items: [
        contactRecord(0, "Anna Andersson"),
        contactRecord(1, "Bo Berg"),
        contactRecord(2, "Cecilia Carlsson"),
        contactRecord(3, "David Dahl"),
      ],
      next_cursor: null,
    },
  },
  get_contact_context: { structuredContent: bigContactContext },
  list_task_external_references: {
    structuredContent: { items: [], next_cursor: null },
  },
  update_task: { structuredContent: { task: { ...fullTask, version: 4 } } },
};

// ---------- Journal ----------

const jEntry = (n: number, title: string) => ({
  id: uid(6, n),
  source_id: uid(7, n),
  journal_date: "2026-10-28",
  occurred_at: iso(-1, 8 + (n % 12)),
  title,
  summary:
    "Kunden vill ha offerten före fredag. Vi pratade även om leveranstider, garanti och vem som ska hålla i kontakten med bygget under november.",
  key_points: [
    { kind: "commitment", text: "Skicka offerten på torsdag." },
    { kind: "decision", text: "Vi kör på fast pris, inte löpande räkning." },
    { kind: "question", text: "Behöver vi underentreprenör för el?" },
  ],
  project_ids: [uid(2, 0)],
  task_ids: [uid(1, 1)],
  contact_ids: [uid(4, 0), uid(4, 1)],
  tags: tagsOf(n + 1),
  // Long names on purpose: the card cuts them to one line each and still has to fit one screen.
  links: [
    { kind: "contact", id: uid(4, 0), label: "Anna Andersson-Lindqvist" },
    { kind: "contact", id: uid(4, 1), label: "Bo Berg" },
    {
      kind: "project",
      id: uid(2, 0),
      label: "Bokslut 2026 och momsredovisning",
    },
  ],
  archived: false,
  version: 1,
});
const entryTitles = [
  "Mötet med Anna om offerten",
  "Telefonsamtal med revisorn om momsen och bokslutet",
  "Tankar efter promenaden",
  "Lunch med Bo",
  "Planering inför styrelsemötet i november",
  "Samtal med bygget om golvvärmen",
  "Kvällens reflektion om veckan",
  "Idéer till webbplatsen",
];
export const bigJournalDay = {
  journal_date: "2026-10-28",
  entries: range(0, 8).map((n) => jEntry(n + 1, entryTitles[n]!)),
  next_cursor: null,
  summary: {
    journal_date: "2026-10-28",
    exists: true,
    origin: "generated",
    status: "current",
    content: {
      overview:
        "Dagen handlade om offerten till Bergström Bygg, ett samtal med revisorn och en lång promenad där flera idéer om webbplatsen kom upp. På kvällen planerade jag styrelsemötet och funderade över vad som ska prioriteras under november, bland annat bokslutet, renoveringen och semesterplaneringen för nästa sommar.",
    },
  },
};
export const bigJournalPending = {
  items: range(1, 11).map((n) => ({
    source_id: uid(7, n),
    journal_date: "2026-10-28",
    source_type: n % 2 ? "manual_text" : "voice_transcript",
    source_created_at: iso(-n),
    character_count: 900 + n * 120,
    state: n % 4 === 0 ? "no_draft" : "draft_pending_review",
    draft_id: n % 4 === 0 ? null : uid(8, n),
    draft_title:
      n % 4 === 0 ? null : `Utkast ${n} om mötet med Anna och offerten`,
  })),
};
export const bigJournalDraft = {
  draft: {
    id: uid(8, 1),
    source_id: uid(7, 1),
    journal_date: "2026-10-28",
    state: "pending_review",
    title: "Utkast om mötet med Anna och offerten",
    summary:
      "Kunden vill ha offerten före fredag. Vi pratade även om leveranstider och garanti. Därefter gick vi igenom projektplanen, budgeten och vem som ansvarar för vad under november.",
    key_points: [
      { kind: "commitment", text: "Skicka offerten på torsdag." },
      { kind: "decision", text: "Fast pris." },
      { kind: "question", text: "Behöver vi underentreprenör för el?" },
      { kind: "commitment", text: "Ring revisorn före fredag." },
      { kind: "decision", text: "Vi skjuter upp golvvärmen till våren." },
    ],
    suggestions: {
      projects: [
        { id: "p1", rationale: "Offerten hör till bokslutsprojektet." },
        { id: "p2", rationale: "Webbplatsen nämns i texten." },
      ],
      tasks: range(1, 3).map((n) => ({
        id: uid(1, n),
        rationale: "Samma uppgift som nämns i texten.",
      })),
      contacts: [
        { id: uid(4, 0), rationale: "Anna nämns vid namn." },
        { id: uid(4, 1), rationale: "Bo nämns vid namn." },
      ],
    },
    task_proposals: range(1, 9).map((n) => ({
      proposal_id: `tp${n}`,
      type: "create_task",
      title: `Förslag ${n}: ${titles[n]}`,
      description: "Inkludera leveranstider och garanti.",
      project_id: "p1",
      priority: n % 2 ? "high" : "normal",
      due_at: iso(n),
      contact_ids: [uid(4, 0)],
    })),
    task_proposal_count: 8,
    catalog: {
      projects: [
        { id: "p1", label: "Bokslut 2026 och årsredovisning" },
        { id: "p2", label: "Webbplats" },
        { id: "p3", label: "Renovering badrum" },
      ],
      tasks: range(1, 4).map((n) => ({
        id: uid(1, n),
        label: titles[n],
        status: "todo",
      })),
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
      "Pratade med Anna om offerten. Hon vill ha den före fredag, helst på torsdag. Vi pratade om leveranstider, garanti och vem som håller i kontakten. Jag lovade att skicka en uppdaterad faktura också.",
  },
};
export const journalReplies: Record<string, unknown> = {
  get_journal_day: { structuredContent: bigJournalDay },
  get_journal_entry: { structuredContent: { entry: bigJournalDay.entries[0] } },
  get_journal_source: {
    structuredContent: { source: bigJournalDraft.source },
  },
  get_journal_draft: { structuredContent: bigJournalDraft },
  list_pending_journal: { structuredContent: bigJournalPending },
  list_tags: { structuredContent: tagVocabulary },
};

// ---------- Shopping ----------

export const sList = {
  id: uid(9, 1),
  name: "Veckohandling och presenter",
  version: 1,
  archived: false,
  created_at: iso(-20),
  updated_at: iso(-1),
};
export const sItem = (
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
const wares = [
  "Mjölk",
  "Bröd",
  "Potatis",
  "Diskmedel",
  "Batterier AA",
  "Kaffe",
  "Ägg",
  "Present till Lisas födelsedag: bok om trädgårdsodling",
];
const stores = ["ICA", "Willys", "Clas Ohlson", "Akademibokhandeln"];
export const bigShoppingDetail = {
  shopping_list: sList,
  items: range(1, 41).map((n) =>
    sItem(n, `${wares[n % wares.length]} ${n}`, {
      quantity: String((n % 4) + 1),
      store: stores[n % stores.length],
      purchased: n > 30,
      purchased_at: n > 30 ? iso(-1) : null,
    }),
  ),
  next_offset: null,
  evaluated_on: "2026-10-29",
};
export const shoppingReplies: Record<string, unknown> = {
  list_shopping_lists: {
    structuredContent: { lists: [sList], next_offset: null },
  },
  get_shopping_list: { structuredContent: bigShoppingDetail },
};
// Three shops, six open rows and two bought rows. Each shop heading takes a line of the compact budget,
// so the card must fold the third shop behind "Show all (6)" and still stay within 560 px.
export const threeStoreShoppingDetail = {
  shopping_list: sList,
  items: [
    sItem(101, "Mjölk", { quantity: "2.000", unit: "l", store: "ICA" }),
    sItem(102, "Ägg", { quantity: "12.000", unit: "st", store: "ICA" }),
    sItem(103, "Bröd", { quantity: "1.000", unit: null, store: "Willys" }),
    sItem(104, "Kaffe", { quantity: "1", unit: null, store: "Willys" }),
    sItem(105, "Batterier AA", {
      quantity: "4",
      unit: "st",
      store: "Clas Ohlson",
    }),
    sItem(106, "Diskmedel", {
      quantity: "1",
      unit: null,
      store: "Clas Ohlson",
    }),
    sItem(107, "Mjölk", {
      quantity: "1",
      unit: "l",
      store: "ICA",
      purchased: true,
      purchased_at: iso(-1),
    }),
    sItem(108, "Bröd", {
      quantity: "1.000",
      unit: null,
      store: "Willys",
      purchased: true,
      purchased_at: iso(-1),
    }),
  ],
  next_offset: null,
  evaluated_on: "2026-10-29",
};
export const bigShoppingBatch = {
  items: range(1, 11).map((n) => ({
    item: sItem(n, `${wares[n % wares.length]} ${n}`),
  })),
};

// ---------- Control ----------

// The longest realistic titles lead the rows, so the four rows a card shows inline are the worst case
// for height (two-line titles, a two-line secondary line on a narrow phone).
const longTitles = [titles[4], titles[9], titles[1], titles[2]];

export const bigTrash = {
  items: range(0, 30).map((n) => ({
    kind: n % 2 ? "task" : "contact",
    id: uid(1, n),
    label: `${longTitles[n % longTitles.length]}`,
    trashed_at: iso(-(n % 6)),
    version: 3,
  })),
  has_more: true,
  next_cursor: "page-2",
};
export const bigChanges = {
  changes: range(0, 20).map((n) => ({
    kind: n % 2 ? "shopping_item" : "task",
    id: uid(1, n),
    title: longTitles[n % longTitles.length],
    version: 2,
    action: n % 2 ? "purchased" : "created",
    state: "active",
    occurred_at: iso(-(n % 5)),
    related_id: null,
    undo_tool: n % 2 ? "set_shopping_item_purchased" : null,
  })),
};
export const bigActivity = {
  items: range(0, 25).map((n) => ({
    id: uid(1, n),
    category: "task",
    source: (["user", "assistant", "worker", "system"] as const)[n % 4],
    operation: "update",
    state: "applied",
    aggregate_type: "task",
    summary: `Uppdaterade uppgiften ${longTitles[n % longTitles.length]}`,
    occurred_at: iso(-(n % 5)),
  })),
  next_cursor: null,
};
export const memoryStatus = {
  settings: {
    journal: true,
    contacts: true,
    projects: false,
    tasks: false,
    paused: false,
    version: 2,
  },
  provider: "hindsight",
  sources: [
    {
      kind: "journal_entry",
      retained: 12,
      pending: 1,
      failed: 0,
      parked: 0,
      excluded: 0,
    },
    {
      kind: "contact",
      retained: 30,
      pending: 0,
      failed: 2,
      parked: 0,
      excluded: 0,
    },
    {
      kind: "project",
      retained: 0,
      pending: 0,
      failed: 0,
      parked: 0,
      excluded: 0,
    },
    {
      kind: "task",
      retained: 0,
      pending: 0,
      failed: 0,
      parked: 0,
      excluded: 0,
    },
  ],
};
export const controlReplies: Record<string, unknown> = {
  list_trash: { structuredContent: bigTrash },
  list_recent_changes: { structuredContent: bigChanges },
  list_assistant_activity: { structuredContent: bigActivity },
  get_memory_status: { structuredContent: memoryStatus },
};

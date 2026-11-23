/**
 * Texts of the automations in the Start room (sv and en with equal keys): the list, one automation in full, its
 * approval and the confirmation that lets it apply suggestions without a click. Every word is put together from the
 * server's closed codes and the automation's own fields; nothing here comes from what a run read.
 */
type Source = "mail" | "calendar" | "chat" | "web" | "sidekick" | "manual";
type Runner = "claude" | "claude_code" | "server" | "any";
type Effect = "create_task" | "create_contact";
type Outcome =
  | "ok"
  | "nothing_found"
  | "failed"
  | "budget"
  | "invalid_output"
  | "provider"
  | "refused";

const automationsEn = {
  dateLocale: "en-GB",
  title: "Automations",
  kicker: "Automation",
  moreActions: "More actions for Automations",
  refresh: "Refresh",
  /** The inbox's way here: its lead row and its ⋯ entry. */
  entry: "Automations",
  entryCount: (count: number) =>
    count === 1 ? "1 automation" : `${count} automations`,
  entryWaiting: (count: number) =>
    count === 1
      ? "1 waits for your approval"
      : `${count} wait for your approval`,
  empty: "No automations yet.",
  emptyHint:
    "You make an automation together with Claude. It proposes; you decide.",
  emptyAsk: "Read my e-mail every morning and suggest tasks",
  /** The state of an automation, as its row and its detail say it. */
  states: {
    waiting: "Waits for your approval",
    changed: "Changed since you approved it",
    on: "On",
    paused: "Paused",
    archived: "Archived",
  },
  pending: (count: number) =>
    count === 1 ? "1 suggestion waits" : `${count} suggestions wait`,
  lastRun: (when: string) => `last run ${when}`,
  neverRun: "Has not run yet",
  /** The facts of one automation, in the order a person reads them. */
  facts: {
    schedule: "When",
    runner: "Run by",
    sources: "Reads",
    effects: "May propose",
    handling: "Suggestions",
    limits: "Limits",
    model: "Model",
  },
  manualOnly: "Only when you start it",
  /** A cadence's rule in words ("daily") and the local time. */
  at: (every: string, time: string) => `${every} at ${time}`,
  runners: {
    claude: "Claude",
    claude_code: "Claude Code",
    server: "Sidekick on the server",
    any: "Claude, Claude Code or Sidekick on the server",
  } satisfies Record<Runner, string>,
  sources: {
    mail: "E-mail",
    calendar: "Calendar",
    chat: "Chat",
    web: "The web",
    sidekick: "Sidekick's own records",
    manual: "What you give it",
  } satisfies Record<Source, string>,
  /** What a suggestion may create, in a sentence ("new tasks and new contacts"). */
  effects: {
    create_task: "new tasks",
    create_contact: "new contacts",
  } satisfies Record<Effect, string>,
  and: "and",
  nothing: "Nothing yet",
  decideEach: "You decide on each one",
  groupedFrom: (percent: number) =>
    `safe ones can be approved together from ${percent} % sure`,
  appliesDirectly: (effects: string, percent: number) =>
    `Adds ${effects} without asking when the check is at least ${percent} % sure`,
  appliesNothingYet:
    "Set to add suggestions without asking, but no kind is chosen",
  restWait: "everything else waits for you",
  limits: (count: number, budget: string) =>
    `At most ${count} ${count === 1 ? "suggestion" : "suggestions"} and ${budget} per run`,
  usd: (amount: number) => `${amount.toFixed(2)} USD`,
  models: { standard: "Standard (low cost)", strong: "Strong" },
  instruction: "Instruction",
  showAll: "Show all",
  showLess: "Show less",
  /** The runs since the owner last looked (get_automation_report). */
  runsHeading: "Recent runs",
  since: (day: string) => `counted since ${day}`,
  noRuns: "No runs",
  runs: (count: number) => (count === 1 ? "1 run" : `${count} runs`),
  failed: (count: number) => `${count} failed`,
  made: (count: number) =>
    count === 1 ? "1 suggestion" : `${count} suggestions`,
  waitingNow: (count: number) => `${count} waiting`,
  autoApplied: (count: number) => `${count} added without asking`,
  highlights: {
    run_failed: "The run failed",
    suggestion_flagged: "A suggestion was flagged",
    suggestion_auto_applied: "Added without asking",
  } as Record<string, string>,
  outcomes: {
    ok: "done",
    nothing_found: "found nothing",
    failed: "an error",
    budget: "the budget ran out",
    invalid_output: "the answer could not be read",
    provider: "the model service did not answer",
    refused: "the model declined",
  } satisfies Record<Outcome, string>,
  reportFailed: "Couldn’t load the runs",
  /** The approval. */
  approveKicker: "Approval",
  approveTitle: "Approve this automation?",
  approveBody:
    "You approve exactly what is shown here: the instruction, what it reads, when it runs and its limits. If anything changes afterwards, it does not run until you approve it again.",
  approve: "Approve",
  approveStep: "Approve…",
  approving: "Approving…",
  approveFailed: "Couldn’t approve it. Try again.",
  changedWhileOpen:
    "The automation changed while you were looking. Read it through again.",
  changedTitle: "Changed since you approved it",
  changedBody: "It does not run until you have approved the new version.",
  approvedTitle: (day: string) => `Approved ${day}`,
  approvedAuto: "It may add suggestions without asking.",
  approvedNote:
    "If anything changes, it does not run until you approve it again.",
  pausedNote: "It is paused, so it does not run now.",
  approvedReceipt: (title: string) => `Approved: ${title}`,
  cannotTitle: "Can’t be approved yet",
  needsSources: "it reads nothing",
  needsEffects: "it may not propose anything",
  askClaude: "Ask Claude to complete it.",
  archivedNote: "Archived. Ask Claude to restore it before you approve it.",
  /** The separate confirmation of a spec that applies suggestions without a click; `effects` starts the first line. */
  confirmHeading: "It adds suggestions without asking you",
  confirmLines: (
    effects: string,
    percent: number,
    perRun: number,
    perDay: number,
  ) => [
    `${effects} are added at once, without your click, when the independent check is at least ${percent} % sure and nothing was flagged.`,
    `At most ${perRun} per run and ${perDay} a day. Everything else waits for you as usual.`,
    "You see them afterwards in Suggestions and can undo them.",
  ],
  confirmNoKinds:
    "No kind is chosen yet, so for now every suggestion waits for you.",
  confirmCheck: "I want it to add these suggestions without asking me",
  confirmRequired:
    "Without this confirmation it can’t be approved. To decide on every suggestion yourself, ask Claude to change it.",
  tickFirst: "Tick the box first",
  cancel: "Cancel",
};

export type AutomationLabels = typeof automationsEn;

const automationsSv: AutomationLabels = {
  dateLocale: "sv-SE",
  title: "Automationer",
  kicker: "Automation",
  moreActions: "Fler val för Automationer",
  refresh: "Uppdatera",
  entry: "Automationer",
  entryCount: (count) =>
    count === 1 ? "1 automation" : `${count} automationer`,
  entryWaiting: (count) =>
    count === 1
      ? "1 väntar på ditt godkännande"
      : `${count} väntar på ditt godkännande`,
  empty: "Inga automationer än.",
  emptyHint:
    "En automation gör du tillsammans med Claude. Den föreslår, du bestämmer.",
  emptyAsk: "Läs min mejl varje morgon och föreslå uppgifter",
  states: {
    waiting: "Väntar på ditt godkännande",
    changed: "Ändrad sedan du godkände den",
    on: "På",
    paused: "Pausad",
    archived: "Arkiverad",
  },
  pending: (count) =>
    count === 1 ? "1 förslag väntar" : `${count} förslag väntar`,
  lastRun: (when) => `senast körd ${when}`,
  neverRun: "Har inte körts än",
  facts: {
    schedule: "När",
    runner: "Körs av",
    sources: "Läser",
    effects: "Får föreslå",
    handling: "Förslagen",
    limits: "Gränser",
    model: "Modell",
  },
  manualOnly: "Bara när du startar den",
  at: (every, time) => `${every} kl. ${time}`,
  runners: {
    claude: "Claude",
    claude_code: "Claude Code",
    server: "Sidekick på servern",
    any: "Claude, Claude Code eller Sidekick på servern",
  },
  sources: {
    mail: "Mejl",
    calendar: "Kalender",
    chat: "Chatt",
    web: "Webben",
    sidekick: "Sidekicks egna uppgifter",
    manual: "Det du ger den",
  },
  effects: {
    create_task: "nya uppgifter",
    create_contact: "nya kontakter",
  },
  and: "och",
  nothing: "Inget än",
  decideEach: "Du beslutar om vart och ett",
  groupedFrom: (percent) =>
    `säkra kan godkännas tillsammans från ${percent} % säkerhet`,
  appliesDirectly: (effects, percent) =>
    `Lägger in ${effects} utan att fråga när kontrollen är minst ${percent} % säker`,
  appliesNothingYet:
    "Inställd på att lägga in förslag utan att fråga, men ingen typ är vald",
  restWait: "allt annat väntar på dig",
  limits: (count, budget) => `Högst ${count} förslag och ${budget} per körning`,
  usd: (amount) => `${amount.toFixed(2).replace(".", ",")} USD`,
  models: { standard: "Standard (billig)", strong: "Stark" },
  instruction: "Instruktion",
  showAll: "Visa allt",
  showLess: "Visa mindre",
  runsHeading: "Senaste körningar",
  since: (day) => `räknat sedan ${day}`,
  noRuns: "Inga körningar",
  runs: (count) => (count === 1 ? "1 körning" : `${count} körningar`),
  failed: (count) => `${count} misslyckades`,
  made: (count) => `${count} förslag`,
  waitingNow: (count) => `${count} väntar`,
  autoApplied: (count) => `${count} inlagda utan att fråga`,
  highlights: {
    run_failed: "Körningen misslyckades",
    suggestion_flagged: "Ett förslag flaggades",
    suggestion_auto_applied: "Inlagt utan att fråga",
  },
  outcomes: {
    ok: "klar",
    nothing_found: "hittade inget",
    failed: "ett fel",
    budget: "budgeten tog slut",
    invalid_output: "svaret gick inte att läsa",
    provider: "modelltjänsten svarade inte",
    refused: "modellen avböjde",
  },
  reportFailed: "Körningarna kunde inte hämtas",
  approveKicker: "Godkännande",
  approveTitle: "Godkänna den här automationen?",
  approveBody:
    "Du godkänner exakt det som står här: instruktionen, vad den läser, när den körs och dess gränser. Ändras något efteråt körs den inte förrän du godkänner igen.",
  approve: "Godkänn",
  approveStep: "Godkänn…",
  approving: "Godkänner…",
  approveFailed: "Det gick inte att godkänna. Försök igen.",
  changedWhileOpen:
    "Automationen ändrades medan du tittade. Läs igenom den igen.",
  changedTitle: "Ändrad sedan du godkände den",
  changedBody: "Den körs inte förrän du har godkänt den nya versionen.",
  approvedTitle: (day) => `Godkänd ${day}`,
  approvedAuto: "Den får lägga in förslag utan att fråga.",
  approvedNote: "Ändras något körs den inte förrän du godkänner igen.",
  pausedNote: "Den är pausad, så den körs inte nu.",
  approvedReceipt: (title) => `Godkänd: ${title}`,
  cannotTitle: "Kan inte godkännas än",
  needsSources: "den läser ingenting",
  needsEffects: "den får inte föreslå något",
  askClaude: "Be Claude komplettera den.",
  archivedNote: "Arkiverad. Be Claude återställa den innan du godkänner.",
  confirmHeading: "Den lägger in förslag utan att fråga dig",
  confirmLines: (effects, percent, perRun, perDay) => [
    `${effects} läggs in direkt, utan ditt klick, när den oberoende kontrollen är minst ${percent} % säker och inget har flaggats.`,
    `Högst ${perRun} per körning och ${perDay} per dag. Allt annat väntar på dig som vanligt.`,
    "Du ser dem efteråt i Förslag och kan ångra dem.",
  ],
  confirmNoKinds:
    "Ingen typ är vald än, så tills vidare väntar alla förslag på dig.",
  confirmCheck:
    "Jag vill att den lägger in de här förslagen utan att fråga mig",
  confirmRequired:
    "Utan den här bekräftelsen kan den inte godkännas. Vill du besluta om varje förslag själv, be Claude ändra det.",
  tickFirst: "Kryssa i rutan först",
  cancel: "Avbryt",
};

/** The automations' texts for a room's locale; Swedish unless the locale is English. */
export function automationLabelsFor(locale: string): AutomationLabels {
  return locale.startsWith("en") ? automationsEn : automationsSv;
}

export { automationsEn, automationsSv };

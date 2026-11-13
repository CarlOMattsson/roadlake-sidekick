import type { ChangeRecord, MemoryDomain } from "./transport";

/** How a memory domain reads inside a sentence. Swedish has an indefinite and a definite form. */
type DomainForms = Record<
  MemoryDomain,
  { indefinite: string; definite: string }
>;

const SV_DOMAIN_FORMS: DomainForms = {
  journal: { indefinite: "dagbok", definite: "dagboken" },
  contacts: { indefinite: "kontakter", definite: "kontakterna" },
  projects: { indefinite: "projekt", definite: "projekten" },
  tasks: { indefinite: "uppgifter", definite: "uppgifterna" },
};

const EN_DOMAIN_FORMS: DomainForms = {
  journal: { indefinite: "journal", definite: "journal" },
  contacts: { indefinite: "contacts", definite: "contacts" },
  projects: { indefinite: "projects", definite: "projects" },
  tasks: { indefinite: "tasks", definite: "tasks" },
};

/** One record of a memory source, singular and plural: what a row of `memory_sources` is for the domain. */
const SV_RECORD_NOUNS: Record<MemoryDomain, readonly [string, string]> = {
  journal: ["anteckning", "anteckningar"],
  contacts: ["kontakt", "kontakter"],
  projects: ["projekt", "projekt"],
  tasks: ["uppgift", "uppgifter"],
};

const EN_RECORD_NOUNS: Record<MemoryDomain, readonly [string, string]> = {
  journal: ["entry", "entries"],
  contacts: ["contact", "contacts"],
  projects: ["project", "projects"],
  tasks: ["task", "tasks"],
};

/** The definite singular of one record of a memory source, for the text of "Forget …". */
const SV_RECORD_DEFINITE: Record<MemoryDomain, string> = {
  journal: "anteckningen",
  contacts: "kontakten",
  projects: "projektet",
  tasks: "uppgiften",
};

/** Capitalises the first letter, for a sentence that starts with the noun. */
function upperFirst(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Texts of the Control app. English is the type; Swedish is the default (app language setting). */
export const controlEn = {
  title: "Memory and control",
  locale: "en" as const,
  loading: "Loading…",
  retry: "Try again",
  /** `more`: the server holds rows beyond the ones read, so the count is "at least". */
  showAll: (count: number, more = false) =>
    `Show all (${count}${more ? "+" : ""})`,
  showFewer: "Show fewer",
  views: {
    trash: "Deleted",
    history: "History",
    memory: "Sidekick’s memory",
  },
  /**
   * The first content of a tab in the full view, one meta line (the sentences under the tabs became
   * a meta line or went). No retention period exists, so none is named.
   */
  trashMeta: (count: number, more = false) =>
    `${more ? `${count}+ deleted` : count === 1 ? "1 deleted" : `${count} deleted`} · can be restored`,
  historyMeta: "What you and Claude have done, newest first",
  /** The meta of "Memory is on": how many of the sources are on. */
  sourcesOn: (on: number, all: number) => `${on} of ${all} sources on`,
  sourcesTitle: "Sources",
  // Trash
  trashTitle: "Deleted",
  trashEmpty: "Nothing deleted.",
  trashEmptyHint: "What you delete lands here first and can be restored.",
  trashMore: "Show more",
  trashMoreFailed: "Couldn’t load more.",
  hiddenTitle: "Title hidden",
  restore: "Restore",
  restoreLabel: (title: string) => `Restore ${title}`,
  restoring: "Restoring…",
  /** The history row's receipt after a restore; a trash row's receipt is its kind and `actions.restored`. */
  restored: "Restored",
  /** Opens a restored record in its room; the label names the record for a screen reader. */
  open: "Open",
  openLabel: (title: string) => `Open ${title}`,
  restoreConflict: (title: string | null) =>
    `${title ? `“${title}”` : "This item"} was changed elsewhere. The list is up to date. Choose Restore again.`,
  restoreGone: "That item is no longer in Deleted. Refreshing the list.",
  restoreForbidden: "You don’t have permission to restore this.",
  restoreFailed: "Couldn’t restore.",
  // History: changes (with Undo/Restore) and activity (read only) in one list
  historyEmpty: "No history yet.",
  historyEmptyHint: "Changes made by you or Claude show up here.",
  /** The empty History's example for Claude (a change made now shows up here). */
  historyAskExample: "Add milk to my shopping list",
  nowTrashed: "now in Deleted",
  undo: "Undo",
  undoLabel: (verb: string, title: string) => `${verb} ${title}`,
  undoing: "Saving…",
  /** The history row's receipt after an Undo of a purchase / of a put-back. */
  undoneUnbought: "No longer bought",
  undoneBought: "Bought again",
  undoConflict: (title: string | null) =>
    `${title ? `“${title}”` : "This item"} was changed elsewhere. The list is up to date. Try again.`,
  undoForbidden: "You don’t have permission to undo this.",
  undoFailed: (title: string) => `Couldn’t undo “${title}”.`,
  activityTruncated:
    "This list is shortened. Only the most recent items are shown.",
  // Memory
  memoryOn: "Memory is on",
  memoryPaused: "Memory is paused",
  memoryOff: "Memory is off",
  memoryOnProviderOff: "Memory is on, but the service is off",
  memoryFakeProvider: "Memory is using a test service",
  providerOff: "The memory service is off, so nothing is being saved.",
  providerFake: "Test memory: no real memory is in use.",
  pause: "Pause memory",
  resume: "Resume memory",
  domainOn: "On",
  domainOnPaused: "On · paused",
  domainOff: "Off",
  domainLabel: (name: string, on: boolean) => `${name}: ${on ? "on" : "off"}`,
  /** "214 entries in memory": the count with the source's own noun. A journal source's record is an
   * entry (`memory_sources.source_kind` "journal_entry"), the others a contact, project or task. */
  countStored: (count: number, domain: MemoryDomain) =>
    `${count} ${count === 1 ? EN_RECORD_NOUNS[domain][0] : EN_RECORD_NOUNS[domain][1]} in memory`,
  countWaiting: (count: number, held = false) =>
    held ? `${count} waiting` : `${count} being added`,
  countStuck: (count: number) => `${count} waiting for memory`,
  countUnknown: "Count unknown",
  countOff: "not in memory",
  countDeleting: "deleting…",
  deletionStarted: (domain: MemoryDomain) =>
    `Memory is off for your ${EN_DOMAIN_FORMS[domain].definite}. What Sidekick remembered will be deleted within a few minutes.`,
  confirmTitle: (domain: MemoryDomain) =>
    `Turn off memory for your ${EN_DOMAIN_FORMS[domain].definite}?`,
  confirmCount: (domain: MemoryDomain, count: number | null) => {
    const noun = EN_DOMAIN_FORMS[domain].definite;
    return count === null
      ? `This deletes only what Sidekick remembers about your ${noun}. Your ${noun} won’t change.`
      : `This deletes only what Sidekick remembers about your ${noun} (${count === 1 ? "1 record" : `${count} records`}). Your ${noun} won’t change.`;
  },
  confirmCost: "To get it back, the memory has to be rebuilt from scratch.",
  confirmYes: (domain: MemoryDomain) =>
    `Yes, delete what Sidekick remembers about your ${EN_DOMAIN_FORMS[domain].definite}`,
  confirmNo: "Cancel",
  memoryBusy: "Saving…",
  memorySaved: "Saved.",
  memoryConflict: "Memory settings were changed elsewhere. Refreshing.",
  memoryForbidden: "You don’t have permission to change this.",
  memoryFailed: "Couldn’t save.",
  /** Where memory text goes: to the model the owner connected (Hindsight's LLM), the facts stay on the owner's server. */
  memoryExplain:
    "Sidekick remembers context between your conversations, and Claude can ask Sidekick about it. The text of records that are included goes to the language model you connected to memory, which picks out facts. The facts are stored on your Sidekick server.",
  // What Sidekick remembers: a read only sample per source, a free text search and "Forget the <record>"
  recallShow: "Show what Sidekick remembers",
  recallHide: "Hide",
  recallShowLabel: (name: string) =>
    `Show what Sidekick remembers from ${name}`,
  recallHideLabel: (name: string) =>
    `Hide what Sidekick remembers from ${name}`,
  /** The words sent to recall_memory for a source sample; the tool has no list mode, so this is a broad question. */
  recallProbe: "latest and most important",
  recallSample: "A sample of what Sidekick remembers, not everything.",
  recallLooking: "Looking…",
  recallEmpty: "Sidekick remembers nothing from here yet.",
  recallNothing: "Nothing found in memory for that.",
  recallPaused: "Memory is paused, so nothing can be looked up.",
  recallOff: "Memory is off, so nothing can be looked up.",
  recallUnavailableHeading: "Couldn’t look in memory",
  recallForbidden: "You don’t have permission to look in memory.",
  searchTitle: "Search memory",
  searchHint: "What do you want to know?",
  searchButton: "Search",
  searchTooShort: "Type at least two characters.",
  resultsLabel: "What Sidekick remembers",
  /** "Forget" removes everything remembered from the whole source record, so the button names the record. */
  forget: (domain: MemoryDomain) => `Forget the ${EN_RECORD_NOUNS[domain][0]}`,
  forgetLabel: (domain: MemoryDomain, title: string | null) =>
    `Forget the ${EN_RECORD_NOUNS[domain][0]}${title ? `: ${title}` : ""}`,
  forgetTitle: (domain: MemoryDomain, title: string | null) =>
    `Forget the ${EN_RECORD_NOUNS[domain][0]}${title ? ` “${title}”` : ""}?`,
  forgetBody: (domain: MemoryDomain) =>
    `Everything Sidekick remembers from this ${EN_RECORD_NOUNS[domain][0]}, not just this fact, is removed from Sidekick’s memory. The ${EN_RECORD_NOUNS[domain][0]} itself won’t change.`,
  forgetYes: (domain: MemoryDomain) =>
    `Yes, forget the ${EN_RECORD_NOUNS[domain][0]}`,
  forgetNo: "Cancel",
  forgetting: "Forgetting…",
  forgotten: (domain: MemoryDomain, title: string | null) =>
    `Sidekick has forgotten ${title ? `“${title}”` : `the ${EN_RECORD_NOUNS[domain][0]}`}. The ${EN_RECORD_NOUNS[domain][0]} itself won’t change. It can take a few minutes before it stops showing up in search.`,
  forgetForbidden: "You don’t have permission to change memory.",
  forgetFailed: "Couldn’t forget it.",
  domains: {
    journal: "Journal",
    contacts: "Contacts",
    projects: "Projects",
    tasks: "Tasks",
  } satisfies Record<MemoryDomain, string>,
  /** Who made an activity entry: the owner, the assistant, a background job or the system. */
  sources: {
    user: "You",
    assistant: "Claude",
    worker: "Background",
    system: "System",
  } as Record<string, string>,
  /** The state of an activity entry, in a few words. */
  states: {
    applied: "applied",
    review: "to review",
    failed: "failed",
    reverted: "undone",
  } as Record<string, string>,
  /**
   * Sentences sent to the host model (updateModelContext) after an owner change in the card. Generic:
   * no titles, no ids, no content, per docs/decisions/log.md D-058 (logs and telemetry never carry user content).
   */
  modelNote: {
    restored: "The owner restored an item from the trash in the card.",
    undone: "The owner undid a change in the card.",
    paused: "The owner paused memory in the card.",
    resumed: "The owner resumed memory in the card.",
    memoryChanged: "The owner changed the memory settings in the card.",
    forgotten: "The owner removed an item from memory in the card.",
  },
  /** Spoken name of a storage kind, for trash and change rows. */
  kinds: {
    domain: "Area",
    process: "Process",
    project: "Project",
    task: "Task",
    step: "Step",
    action: "Action",
    contact: "Contact",
    journal_entry: "Journal entry",
    shopping_item: "Shopping item",
    shopping_list: "Shopping list",
    contact_alias: "Contact nickname",
    contact_alias_removed: "Contact nickname",
    contact_link: "Contact link",
    contact_task_link: "Contact–task link",
    contact_project_link: "Contact–project link",
    external_reference: "Reference",
    external_reference_link: "Reference link",
  } as Record<string, string>,
  /** Kinds whose Swedish noun is neuter, so a participle after them takes its neuter form. Never any in English. */
  neuterKinds: [] as readonly string[],
  actions: {
    created: "created",
    updated: "updated",
    completed: "done",
    archived: "archived",
    restored: "restored",
    trashed: "deleted",
    purchased: "bought",
    reopened: "back on the list",
  } as Record<string, string>,
  neuterActions: {} as Record<string, string>,
};
export type ControlLabels = Omit<typeof controlEn, "locale"> & {
  locale: "sv" | "en";
};

export const controlSv: ControlLabels = {
  title: "Minne och kontroll",
  locale: "sv",
  loading: "Laddar…",
  retry: "Försök igen",
  showAll: (count, more = false) => `Visa alla (${count}${more ? "+" : ""})`,
  showFewer: "Visa färre",
  views: {
    trash: "Borttaget",
    history: "Historik",
    memory: "Sidekicks minne",
  },
  trashMeta: (count, more = false) =>
    `${more ? `${count}+ borttagna` : count === 1 ? "1 borttagen" : `${count} borttagna`} · kan återställas`,
  historyMeta: "Det du och Claude har gjort, senaste först",
  sourcesOn: (on, all) => `${on} av ${all} källor på`,
  sourcesTitle: "Källor",
  trashTitle: "Borttaget",
  trashEmpty: "Inget borttaget.",
  trashEmptyHint: "Det du tar bort hamnar här först och kan återställas.",
  trashMore: "Visa fler",
  trashMoreFailed: "Det gick inte att hämta fler.",
  hiddenTitle: "Titeln är dold",
  restore: "Återställ",
  restoreLabel: (title) => `Återställ ${title}`,
  restoring: "Återställer…",
  restored: "Återställd",
  open: "Öppna",
  openLabel: (title) => `Öppna ${title}`,
  restoreConflict: (title) =>
    `${title ? `”${title}”` : "Posten"} har ändrats på annat håll. Listan är uppdaterad – tryck Återställ igen.`,
  restoreGone: "Posten ligger inte längre i Borttaget. Listan uppdateras.",
  restoreForbidden: "Du saknar behörighet att återställa den.",
  restoreFailed: "Det gick inte att återställa.",
  historyEmpty: "Ingen historik ännu.",
  historyEmptyHint: "Det du eller Claude ändrar visas här.",
  historyAskExample: "Lägg till mjölk på inköpslistan",
  nowTrashed: "ligger nu i Borttaget",
  undo: "Ångra",
  undoLabel: (verb, title) => `${verb} ${title}`,
  undoing: "Sparar…",
  undoneUnbought: "Inte längre köpt",
  undoneBought: "Köpt igen",
  undoConflict: (title) =>
    `${title ? `”${title}”` : "Posten"} har ändrats på annat håll. Listan är uppdaterad – tryck igen.`,
  undoForbidden: "Du saknar behörighet att ångra det.",
  undoFailed: (title) => `Det gick inte att ångra ”${title}”.`,
  activityTruncated: "Listan är avkortad. Bara de senaste posterna visas.",
  memoryOn: "Minnet är på",
  memoryPaused: "Minnet är pausat",
  memoryOff: "Minnet är av",
  memoryOnProviderOff: "Minnet är på, men tjänsten är avstängd",
  memoryFakeProvider: "Minnet använder en testtjänst",
  providerOff: "Minnestjänsten är avstängd, så ingenting sparas.",
  providerFake: "Testminne: inget riktigt minne används.",
  pause: "Pausa minnet",
  resume: "Återuppta minnet",
  domainOn: "På",
  domainOnPaused: "På · pausad",
  domainOff: "Av",
  domainLabel: (name, on) => `${name}: ${on ? "på" : "av"}`,
  countStored: (count, domain) =>
    `${count} ${count === 1 ? SV_RECORD_NOUNS[domain][0] : SV_RECORD_NOUNS[domain][1]} i minnet`,
  countWaiting: (count, held = false) =>
    held ? `${count} väntar` : `${count} på väg`,
  countStuck: (count) => `${count} väntar på minnet`,
  countUnknown: "Antal okänt",
  countOff: "inte med i minnet",
  countDeleting: "raderas…",
  deletionStarted: (domain: MemoryDomain) =>
    `Minnet av ${SV_DOMAIN_FORMS[domain].definite} är avslaget. Det Sidekick mindes raderas inom några minuter.`,
  confirmTitle: (domain: MemoryDomain) =>
    `Slå av minnet av ${SV_DOMAIN_FORMS[domain].definite}?`,
  confirmCount: (domain: MemoryDomain, count: number | null) => {
    const noun = SV_DOMAIN_FORMS[domain].definite;
    return count === null
      ? `Bara Sidekicks minne av ${noun} raderas. ${upperFirst(noun)} ändras inte.`
      : `Bara Sidekicks minne av ${noun} raderas (${count === 1 ? "1 post" : `${count} poster`}). ${upperFirst(noun)} ändras inte.`;
  },
  confirmCost: "Vill du ha minnet tillbaka måste det byggas upp igen.",
  confirmYes: (domain: MemoryDomain) =>
    `Ja, radera minnet av ${SV_DOMAIN_FORMS[domain].definite}`,
  confirmNo: "Avbryt",
  memoryBusy: "Sparar…",
  memorySaved: "Sparat.",
  memoryConflict:
    "Minnesinställningarna har ändrats på annat håll. De uppdateras.",
  memoryForbidden: "Du saknar behörighet att ändra det.",
  memoryFailed: "Det gick inte att spara.",
  memoryExplain:
    "Sidekick minns sammanhang mellan dina samtal, och Claude kan fråga Sidekick om det. Texten i poster som är med skickas till den språkmodell du har kopplat till minnet, som plockar ut fakta. Fakta sparas på din Sidekick-server.",
  recallShow: "Visa vad Sidekick minns",
  recallHide: "Dölj",
  recallShowLabel: (name) => `Visa vad Sidekick minns från ${name}`,
  recallHideLabel: (name) => `Dölj vad Sidekick minns från ${name}`,
  recallProbe: "senaste och viktigaste",
  recallSample: "Ett urval av vad Sidekick minns, inte allt.",
  recallLooking: "Letar…",
  recallEmpty: "Sidekick minns inget härifrån ännu.",
  recallNothing: "Hittade inget i minnet om det.",
  recallPaused: "Minnet är pausat, så det går inte att slå upp något.",
  recallOff: "Minnet är av, så det går inte att slå upp något.",
  recallUnavailableHeading: "Det gick inte att titta i minnet",
  recallForbidden: "Du saknar behörighet att titta i minnet.",
  searchTitle: "Sök i minnet",
  searchHint: "Vad vill du veta?",
  searchButton: "Sök",
  searchTooShort: "Skriv minst två tecken.",
  resultsLabel: "Vad Sidekick minns",
  forget: (domain) => `Glöm ${SV_RECORD_DEFINITE[domain]}`,
  forgetLabel: (domain, title) =>
    `Glöm ${SV_RECORD_DEFINITE[domain]}${title ? `: ${title}` : ""}`,
  forgetTitle: (domain, title) =>
    `Glöm ${SV_RECORD_DEFINITE[domain]}${title ? ` ”${title}”` : ""}?`,
  forgetBody: (domain: MemoryDomain) =>
    `Allt Sidekick minns från ${SV_RECORD_DEFINITE[domain]}, inte bara det här faktumet, tas bort ur Sidekicks minne. Själva ${SV_RECORD_DEFINITE[domain]} ändras inte.`,
  forgetYes: (domain: MemoryDomain) => `Ja, glöm ${SV_RECORD_DEFINITE[domain]}`,
  forgetNo: "Avbryt",
  forgetting: "Glömmer…",
  forgotten: (domain, title) =>
    `Sidekick har glömt ${title ? `”${title}”` : SV_RECORD_DEFINITE[domain]}. Själva ${SV_RECORD_DEFINITE[domain]} ändras inte. Det kan ta några minuter innan det försvinner ur sökningen.`,
  forgetForbidden: "Du saknar behörighet att ändra minnet.",
  forgetFailed: "Det gick inte att glömma den.",
  domains: {
    journal: "Dagbok",
    contacts: "Kontakter",
    projects: "Projekt",
    tasks: "Uppgifter",
  },
  sources: {
    user: "Du",
    assistant: "Claude",
    worker: "Bakgrund",
    system: "System",
  },
  states: {
    applied: "tillämpad",
    review: "att granska",
    failed: "misslyckades",
    reverted: "ångrad",
  },
  modelNote: {
    restored: "Användaren återställde en post ur papperskorgen i kortet.",
    undone: "Användaren ångrade en ändring i kortet.",
    paused: "Användaren pausade minnet i kortet.",
    resumed: "Användaren återupptog minnet i kortet.",
    memoryChanged: "Användaren ändrade minnesinställningarna i kortet.",
    forgotten: "Användaren tog bort en post ur minnet i kortet.",
  },
  kinds: {
    domain: "Område",
    process: "Process",
    project: "Projekt",
    task: "Uppgift",
    step: "Steg",
    action: "Åtgärd",
    contact: "Kontakt",
    journal_entry: "Dagboksanteckning",
    shopping_item: "Inköpsvara",
    shopping_list: "Inköpslista",
    contact_alias: "Annat namn (kontakt)",
    contact_alias_removed: "Annat namn (kontakt)",
    contact_link: "Kontaktkoppling",
    contact_task_link: "Koppling kontakt–uppgift",
    contact_project_link: "Koppling kontakt–projekt",
    external_reference: "Referens",
    external_reference_link: "Referenskoppling",
  },
  actions: {
    created: "skapad",
    updated: "ändrad",
    completed: "klar",
    archived: "arkiverad",
    restored: "återställd",
    trashed: "borttagen",
    purchased: "köpt",
    reopened: "lagd tillbaka",
  },
  neuterKinds: [
    "domain",
    "project",
    "step",
    "contact_alias",
    "contact_alias_removed",
  ],
  neuterActions: {
    created: "skapat",
    updated: "ändrat",
    completed: "klart",
    archived: "arkiverat",
    restored: "återställt",
    trashed: "borttaget",
    reopened: "lagt tillbaka",
  },
};

export const controlLabels = {
  sv: controlSv,
  en: controlEn as ControlLabels,
};

/** The spoken name of a storage kind; an unknown kind reads as its name with spaces. */
export function kindName(labels: ControlLabels, kind: string): string {
  return labels.kinds[kind] ?? kind.replace(/_/g, " ");
}

/** Whether the spoken name of a storage kind is a neuter noun (Swedish "projekt", "steg", "område"). */
export function isNeuterKind(labels: ControlLabels, kind: string): boolean {
  return labels.neuterKinds.includes(kind);
}

/** "borttaget igår 14:30" / "deleted yesterday at 14:30": the deletion of a kind of record, with its time when known. */
export function trashedWhen(
  labels: ControlLabels,
  when: string,
  kind: string,
): string {
  const word = actionName(labels, "trashed", kind);
  return when ? `${word} ${when}` : word;
}

/** The spoken verb of a change action; an unknown action is shown as it arrived. */
export function actionName(
  labels: ControlLabels,
  action: string,
  kind: string,
): string {
  const neuter = isNeuterKind(labels, kind) && action in labels.neuterActions;
  return (
    (neuter ? labels.neuterActions[action] : labels.actions[action]) ?? action
  );
}

/** Who made an activity entry, in a word; an unknown source is shown as it arrived. */
export function sourceName(labels: ControlLabels, source: string): string {
  return labels.sources[source] ?? source;
}

/**
 * Who made a change, in a word: "You" or "Claude". An unknown or missing actor says nothing, so a row
 * written before the server recorded it (or by a background job) shows no name.
 */
export function actorName(
  labels: ControlLabels,
  actor: ChangeRecord["actor"],
): string {
  if (actor === "you") return sourceName(labels, "user");
  if (actor === "claude") return sourceName(labels, "assistant");
  return "";
}

/** The state of an activity entry, in a word; an unknown state is shown as it arrived. */
export function stateName(labels: ControlLabels, state: string): string {
  return labels.states[state] ?? state;
}

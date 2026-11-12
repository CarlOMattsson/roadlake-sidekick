import type {
  WorkFilters,
  WorkSavedView,
  WorkSavedViewDefinition,
} from "../transport/transport";

/** The two Work views a saved view can open: the Agenda and the Board. */
export type SavedViewTab = "agenda" | "board";

/** The longest view name, in characters (code points). */
export const SAVED_VIEW_NAME_MAX = 120;
const QUERY_MAX = 200;
const TAG_MAX_COUNT = 5;
const TAG_MAX_LENGTH = 80;
const PRIORITY_MAX_COUNT = 4;

/**
 * The closed value sets a saved view may name (the Work tool schemas). A value outside its set is
 * never saved and never opened.
 */
const CHOICES = {
  actionable: ["all", "now", "later"],
  archive: ["active", "archived", "all"],
  attention: ["all", "requested"],
  estimate: ["all", "estimated", "unestimated"],
  group: ["none", "kind", "status", "context"],
  kind: ["all", "domain", "process", "project", "task", "step", "action"],
  priority: ["low", "normal", "high", "urgent"],
  sort: [
    "updated_desc",
    "due_asc",
    "title_asc",
    "priority_desc",
    "not_before_asc",
    "estimate_asc",
  ],
  status: ["todo", "in_progress", "blocked", "completed"],
  tag_match: ["any", "all"],
  waiting: ["all", "waiting", "not_waiting"],
} as const;

type ChoiceKey = keyof typeof CHOICES;
/** The single-value choice filters; priority is apart because a saved view may hold a list of it. */
type PlainChoiceKey = Exclude<ChoiceKey, "priority">;
const PLAIN_CHOICE_KEYS: readonly PlainChoiceKey[] = [
  "actionable",
  "archive",
  "attention",
  "estimate",
  "group",
  "kind",
  "sort",
  "status",
  "tag_match",
  "waiting",
];

/** The filter keys both boards and agendas take. */
const SHARED_KEYS: readonly string[] = [
  "q",
  "status",
  "priority",
  "tags",
  "tag_match",
  "archive",
  "actionable",
  "attention",
  "estimate",
  "waiting",
];
/** The agenda also takes kind, sort and group; the board does not. */
const AGENDA_KEYS: readonly string[] = [
  ...SHARED_KEYS,
  "kind",
  "sort",
  "group",
];

function keysOf(tab: SavedViewTab): readonly string[] {
  return tab === "agenda" ? AGENDA_KEYS : SHARED_KEYS;
}

function isChoice(key: ChoiceKey, value: unknown): value is string {
  return (
    typeof value === "string" &&
    (CHOICES[key] as readonly string[]).includes(value)
  );
}

/** A tag trimmed, or undefined when it is not text, empty, or longer than 80 characters. */
function cleanTag(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  const tag = value.trim();
  return tag.length > 0 && [...tag].length <= TAG_MAX_LENGTH ? tag : undefined;
}

export type SavedViewDraft = {
  /** The definition to save; it names the tab and the context "all". */
  definition: WorkSavedViewDefinition;
  /**
   * The filter keys that were left out: keys this tab does not take (project_id on either tab),
   * empty values, and values outside their set. A key is listed once.
   */
  dropped: string[];
};

/**
 * The filters of the open tab as a saved view definition. Only keys the tab takes, with values in
 * their sets, are kept; a list of priorities is kept as priorities (at most four). Context is always
 * "all", since the Work app never saves a single Project, Domain, Process or Contact list.
 */
export function filtersToDefinition(
  tab: SavedViewTab,
  filters: WorkFilters,
): SavedViewDraft {
  const definition: WorkSavedViewDefinition = { view: tab, context: "all" };
  const dropped = new Set<string>();
  const allowed = keysOf(tab);
  for (const key of Object.keys(filters)) {
    const value = filters[key];
    if (value === undefined) continue;
    if (!allowed.includes(key)) {
      dropped.add(key);
      continue;
    }
    if (key === "q") {
      const q = typeof value === "string" ? value.trim() : "";
      if (q.length > 0 && [...q].length <= QUERY_MAX) definition.q = q;
      else dropped.add(key);
    } else if (key === "priority") {
      if (typeof value === "string") {
        if (isChoice("priority", value)) definition.priority = value;
        else dropped.add(key);
      } else {
        const valid = value.filter((item) => isChoice("priority", item));
        if (valid.length > 0)
          definition.priorities = valid.slice(0, PRIORITY_MAX_COUNT);
        if (
          valid.length === 0 ||
          valid.length !== value.length ||
          valid.length > PRIORITY_MAX_COUNT
        )
          dropped.add(key);
      }
    } else if (key === "tags") {
      const items = typeof value === "string" ? [value] : value;
      const tags: string[] = [];
      let refused = false;
      for (const item of items) {
        const tag = cleanTag(item);
        if (tag === undefined) refused = true;
        else tags.push(tag);
      }
      if (tags.length > TAG_MAX_COUNT) refused = true;
      const kept = tags.slice(0, TAG_MAX_COUNT);
      if (kept.length > 0) definition.tags = kept;
      if (refused || kept.length === 0) dropped.add(key);
    } else if ((PLAIN_CHOICE_KEYS as readonly string[]).includes(key)) {
      const choice = key as PlainChoiceKey;
      if (typeof value === "string" && isChoice(choice, value))
        definition[choice] = value;
      else dropped.add(key);
    }
  }
  return { definition, dropped: [...dropped] };
}

/**
 * The one priority a saved view opens with: its priority field, or its list when the list holds
 * exactly one value; undefined when that value is outside the set.
 */
function appliedPriority(
  definition: WorkSavedViewDefinition,
): string | undefined {
  const single =
    definition.priority ??
    (definition.priorities?.length === 1
      ? definition.priorities[0]
      : undefined);
  return isChoice("priority", single) ? single : undefined;
}

/**
 * True when a saved view names several priorities, so it opens without a priority filter: the Work
 * tools take one priority, so the view shows every priority and the tab says so.
 */
export function namesSeveralPriorities(
  definition: WorkSavedViewDefinition,
): boolean {
  return (
    appliedPriority(definition) === undefined &&
    (definition.priorities?.length ?? 0) > 1
  );
}

/**
 * The filters a saved view opens with: the inverse of filtersToDefinition. A null or absent key is
 * left out; a value outside its set is skipped; priorities become priority only when they hold
 * exactly one value.
 */
export function definitionToFilters(
  definition: WorkSavedViewDefinition,
): WorkFilters {
  const filters: WorkFilters = {};
  if (typeof definition.q === "string") {
    const q = definition.q.trim();
    if (q.length > 0 && [...q].length <= QUERY_MAX) filters.q = q;
  }
  for (const key of PLAIN_CHOICE_KEYS) {
    const value = definition[key];
    if (isChoice(key, value)) filters[key] = value;
  }
  const priority = appliedPriority(definition);
  if (priority !== undefined) filters.priority = priority;
  if (Array.isArray(definition.tags)) {
    const tags = definition.tags
      .map(cleanTag)
      .filter((tag): tag is string => tag !== undefined)
      .slice(0, TAG_MAX_COUNT);
    if (tags.length > 0) filters.tags = tags;
  }
  return filters;
}

/** Why a view name is refused, or undefined when it is a name of 1 to 120 characters once trimmed. */
export type ViewNameProblem = "required" | "tooLong";
export function viewNameProblem(raw: string): ViewNameProblem | undefined {
  const name = raw.trim();
  if (name.length === 0) return "required";
  if ([...name].length > SAVED_VIEW_NAME_MAX) return "tooLong";
  return undefined;
}

/**
 * A single Project's board cannot be saved as a view: the saved set has no Project. The save is
 * refused, not saved as an all-Projects view.
 */
export function isSaveBlocked(dropped: readonly string[]): boolean {
  return dropped.includes("project_id");
}

/** True for a view the owner archived (archived_at set). */
export function isArchivedView(view: WorkSavedView): boolean {
  return view.archived_at !== undefined && view.archived_at !== null;
}

/** The views saved for one tab; the other tab's views are not listed here. */
export function viewsOfTab(
  views: readonly WorkSavedView[],
  tab: SavedViewTab,
): WorkSavedView[] {
  return views.filter((view) => view.definition.view === tab);
}

/** Replaces the view with the same id, or puts a view that is not listed yet at the top. */
export function upsertView(
  views: readonly WorkSavedView[],
  view: WorkSavedView,
): WorkSavedView[] {
  return views.some((item) => item.id === view.id)
    ? views.map((item) => (item.id === view.id ? view : item))
    : [view, ...views];
}

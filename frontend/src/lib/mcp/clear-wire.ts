/**
 * The wire form of "empty this field" for the update tools.
 *
 * The apps keep one editing model: a patch object where `null` means "empty the field". On the MCP
 * wire the server reads `null` in `changes` / `item` as "not sent" (clients fill optional fields
 * with null), and empties a field only when its name is listed in the tool's `clear` parameter.
 * `clearWire` is the one place that translates the two, so call sites keep writing `{ due_at: null }`.
 */
import type { ToolInputs } from "./tool-results.generated";

type ClearName<T extends keyof ToolInputs> = ToolInputs[T] extends {
  clear?: infer C;
}
  ? NonNullable<C> extends ReadonlyArray<infer N>
    ? N
    : never
  : never;

type ClearSpec = {
  /** The patch parameter that carries the fields. */
  key: string;
  /** Every field the server accepts in `clear`. */
  clearable: Readonly<Record<string, true>>;
};

/**
 * Typed per tool: the patch parameter must exist on the tool's input and the clearable names must
 * be exactly the server's `clear` values, so a contract change breaks `npm run typecheck` here.
 */
const spec = <T extends keyof ToolInputs>(
  _tool: T,
  key: keyof ToolInputs[T] & string,
  clearable: { [F in ClearName<T>]: true },
): ClearSpec => ({ key, clearable });

const TOOLS: Readonly<Record<string, ClearSpec>> = {
  update_task: spec("update_task", "changes", {
    description: true,
    project_id: true,
    domain_id: true,
    process_id: true,
    due_at: true,
    not_before: true,
    estimated_minutes: true,
    waiting_since: true,
    follow_up_at: true,
    waiting_on_contact_id: true,
    recurrence: true,
    last_completed_at: true,
  }),
  update_project: spec("update_project", "changes", {
    description: true,
    start_date: true,
    target_date: true,
    definition_of_done: true,
  }),
  update_domain: spec("update_domain", "changes", {
    description: true,
    review_cadence: true,
    last_reviewed_at: true,
    accent: true,
  }),
  update_process: spec("update_process", "changes", {
    description: true,
    cadence: true,
  }),
  update_task_step: spec("update_task_step", "changes", {
    due_at: true,
    instruction: true,
  }),
  update_step_action: spec("update_step_action", "changes", {
    due_at: true,
    note: true,
  }),
  update_contact: spec("update_contact", "changes", {
    context_note: true,
    email: true,
    phone: true,
    relationship: true,
    organization: true,
    role: true,
    address: true,
  }),
  update_shopping_item: spec("update_shopping_item", "item", {
    unit: true,
    note: true,
    store: true,
    product_url: true,
    recipient_contact_id: true,
    occasion: true,
    target_date: true,
    offer: true,
  }),
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

/**
 * Moves every clearable field whose value is `null` out of `changes` / `item` into `clear` (order
 * kept, merged with a `clear` already present, omitted when empty). A `null` on a field the server
 * cannot empty (title, status) stays in place, where the server reads it as "not sent". `tags` are
 * emptied with `[]` and never touched. Other tools pass through unchanged.
 */
export function clearWire<A extends object>(tool: string, args: A): A {
  const entry = Object.hasOwn(TOOLS, tool) ? TOOLS[tool] : undefined;
  if (entry === undefined) return args;
  const patch = (args as Record<string, unknown>)[entry.key];
  if (!isRecord(patch)) return args;
  const kept: Record<string, unknown> = {};
  const moved: string[] = [];
  for (const [field, value] of Object.entries(patch)) {
    if (value === null && Object.hasOwn(entry.clearable, field))
      moved.push(field);
    else kept[field] = value;
  }
  if (moved.length === 0) return args;
  const existing: unknown = (args as { clear?: unknown }).clear;
  const clear = [
    ...new Set([
      ...(Array.isArray(existing) ? (existing as string[]) : []),
      ...moved,
    ]),
  ];
  return { ...args, [entry.key]: kept, clear };
}

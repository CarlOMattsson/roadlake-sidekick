// Canned tool answers of every Sidekick domain (Work, Journal, Contacts, Shopping) for the simulated
// host in mcp-host-fixture.ts. One fixed world: Anna Andersson and Bo Berg, the task "Ring Anna om
// offerten", one journal entry on 2026-10-24 that links to Anna, and an IKEA shopping list. A read
// that changes after a write is a { __sequence } answer (see SimulatedHostConfig.replies).

export const ids = {
  task: "019f0000-0000-7000-8000-000000000001",
  anna: "019f0000-0000-7000-8000-000000000003",
  bo: "019f0000-0000-7000-8000-000000000004",
  entry: "019f0000-0000-7000-8000-0000000000e1",
  source: "019f0000-0000-7000-8000-0000000000e2",
  list: "019f0000-0000-7000-8000-0000000000a1",
  item: "019f0000-0000-7000-8000-0000000000a2",
};

const stamp = "2026-10-24T12:00:00Z";

export const task = {
  id: ids.task,
  project_id: null,
  domain_id: null,
  process_id: null,
  derived_domain_id: null,
  title: "Ring Anna om offerten",
  description: null,
  status: "todo",
  priority: "normal",
  due_at: "2026-10-30T09:00:00Z",
  completed_at: null,
  created_at: stamp,
  updated_at: stamp,
  version: 1,
};
export const editedTask = {
  ...task,
  title: "Ring Anna idag",
  version: 2,
};

export const workItem = (item: typeof task, group = "overdue") => ({
  kind: "task",
  id: item.id,
  title: item.title,
  status: item.status,
  due_at: item.due_at,
  priority: item.priority,
  version: item.version,
  agenda_group: group,
});

const summary = (id: string, display_name: string) => ({
  id,
  display_name,
  archived: false,
  updated_at: stamp,
  version: 1,
});
export const anna = summary(ids.anna, "Anna Andersson");
export const bo = summary(ids.bo, "Bo Berg");
const record = (item: ReturnType<typeof summary>) => ({
  ...item,
  email: null,
  phone: null,
  context_note: null,
  aliases: [],
  archived_at: null,
  created_at: stamp,
});

type TaskLike = Pick<
  typeof task,
  "id" | "title" | "status" | "priority" | "due_at" | "version"
>;

const taskSummary = (item: TaskLike) => ({
  id: item.id,
  title: item.title,
  status: item.status,
  priority: item.priority,
  due_at: item.due_at,
  project_id: null,
  updated_at: stamp,
  version: item.version,
});

export const entry = {
  id: ids.entry,
  source_id: ids.source,
  journal_date: "2026-10-24",
  occurred_at: "2026-10-24T12:30:00Z",
  title: "Lunch med Anna",
  summary: "Vi planerade flytten.",
  key_points: [],
  project_ids: [],
  task_ids: [ids.task],
  contact_ids: [ids.anna],
  links: [{ kind: "contact", id: ids.anna, label: "Anna Andersson" }],
  archived: false,
  version: 1,
};
export const journalDay = {
  journal_date: "2026-10-24",
  entries: [entry],
  next_cursor: null,
  summary: {
    journal_date: "2026-10-24",
    exists: true,
    origin: "manual",
    status: "current",
    content: { overview: "Lunch och planering." },
  },
};

export const shoppingList = {
  id: ids.list,
  name: "IKEA someday",
  version: 1,
  archived: false,
  created_at: stamp,
  updated_at: stamp,
};
const shoppingItem = {
  id: ids.item,
  list_id: ids.list,
  name: "Lampa",
  quantity: "1",
  unit: null,
  store: "IKEA",
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
  created_at: stamp,
  updated_at: stamp,
};
const shoppingDetail = (purchased: boolean) => ({
  shopping_list: shoppingList,
  items: [
    purchased
      ? { ...shoppingItem, purchased: true, version: 2, purchased_at: stamp }
      : shoppingItem,
  ],
  next_offset: null,
  evaluated_on: "2026-10-24",
});

export const ok = (structuredContent: unknown) => ({ structuredContent });

/** Results the host delivers to open each room, as structuredContent. */
export const opening = {
  journalEntry: { entry },
  journalDay,
  workBoard: {
    columns: {
      todo: [workItem(task)],
      in_progress: [
        {
          ...workItem({
            ...task,
            id: "019f0000-0000-7000-8000-000000000002",
            title: "Skicka faktura",
            status: "in_progress",
          }),
        },
      ],
      blocked: [],
      completed: [],
    },
    next_cursor: null,
  },
  contactList: { contacts: [anna, bo], next_cursor: null },
  shoppingList: shoppingDetail(false),
};

/** What the Contact page answers: Anna lists the task `forTask` and the journal entry that links her. */
export function contactContext(
  who: ReturnType<typeof summary>,
  forTask: TaskLike = task,
) {
  return ok({
    contact: record(who),
    projects: { items: [], next_cursor: null },
    tasks: {
      items: who.id === ids.anna ? [taskSummary(forTask)] : [],
      next_cursor: null,
    },
    journal_entries: {
      items:
        who.id === ids.anna
          ? [{ id: ids.entry, journal_date: "2026-10-24", title: entry.title }]
          : [],
      has_more: false,
      readable: true,
    },
  });
}

/**
 * Answers for every read and write the rooms make. After the task is edited the agenda and the task
 * answer with the edited task; after an item is bought the list answers with it bought.
 */
/**
 * get_task for a run that opens on the journal entry: the entry reads its Task's title first (its Task chip), then the
 * Task view reads the Task, and a read after the edit gets the edited one.
 */
export const getTaskFromEntry = {
  __sequence: [ok({ task }), ok({ task }), ok({ task: editedTask })],
};

export function domainReplies(): Record<string, unknown> {
  return {
    get_work_agenda: {
      __sequence: [
        ok({ items: [workItem(task)], filters: {}, next_cursor: null }),
        ok({ items: [workItem(editedTask)], filters: {}, next_cursor: null }),
      ],
    },
    get_work_board: ok(opening.workBoard),
    get_task: { __sequence: [ok({ task }), ok({ task: editedTask })] },
    update_task: ok({ task: editedTask }),
    list_tasks: ok({ items: [], next_cursor: null }),
    list_task_contacts: ok({ items: [anna], next_cursor: null }),
    list_task_steps: ok({ items: [], next_cursor: null }),
    list_contacts: ok(opening.contactList),
    get_contact_context: {
      __byArgument: {
        key: "contact_id",
        answers: {
          [ids.anna]: contactContext(anna),
          [ids.bo]: contactContext(bo),
        },
      },
    },
    get_journal_day: ok(journalDay),
    get_journal_entry: ok({ entry }),
    list_pending_journal: ok({ items: [] }),
    list_shopping_lists: ok({ lists: [shoppingList], next_offset: null }),
    get_shopping_list: {
      __sequence: [ok(shoppingDetail(false)), ok(shoppingDetail(true))],
    },
    set_shopping_item_purchased: ok({
      item: { ...shoppingItem, purchased: true, version: 2 },
      evaluated_on: "2026-10-24",
    }),
  };
}

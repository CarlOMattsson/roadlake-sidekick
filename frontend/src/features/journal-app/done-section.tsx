import { useId } from "react";
import { Fold } from "../mcp-apps/ui/fold";
import { formatTime } from "./dates";
import type { JournalLabels } from "./labels";
import type { JournalDone, JournalDonePurchase } from "./transport";
import "./journal.css";

/** The real totals: `counts` from the server (transport.ts doneFrom never gives fewer than the lists hold). */
export function doneCounts(done: JournalDone): JournalDone["counts"] {
  return done.counts;
}

/**
 * The fold row's meta, «6 uppgifter · 3 steg · 12 varor köpta»: the nonzero parts only. A part never breaks inside
 * (no-break spaces), and a line breaks before «·» (designsystem §3, Inline-kort 5: «bryts före ·»), so 360 px at 200 %
 * text reads «6 uppgifter · 3 steg» / «· 12 varor köpta». Empty when every count is zero.
 */
export function doneCountLine(done: JournalDone, t: JournalLabels): string {
  const n = doneCounts(done);
  return [
    n.tasks > 0 ? t.doneTaskCount(n.tasks) : "",
    n.steps > 0 ? t.doneStepCount(n.steps) : "",
    n.purchases > 0 ? t.donePurchaseCount(n.purchases) : "",
  ]
    .filter(Boolean)
    .map((part) => part.replace(/ /g, "\u00a0"))
    .join(" ·\u00a0");
}

/** The bought items per list, in the order the lists first appear (the answer is in time order). */
function byList(purchases: JournalDonePurchase[]) {
  const lists = new Map<
    string,
    { title: string; items: JournalDonePurchase[] }
  >();
  for (const item of purchases) {
    const list = lists.get(item.list_id);
    if (list) list.items.push(item);
    else lists.set(item.list_id, { title: item.list_title, items: [item] });
  }
  return [...lists.entries()].map(([id, list]) => ({ id, ...list }));
}

/**
 * «Gjort»: what was done on the day, read-only. The fold row
 * (`Fold`, as «Kontaktvägar») in the section's place: «Gjort ⌄» with the count line as its meta, folded by default.
 * Open: a muted label per kind («Uppgifter», «Steg», «Köpta varor»), then rows of the row template without a button
 * (title, one meta line «14:20 · project»), the bought items as one row per list with the items as its text. A list
 * the server cut says how many more there are. Nothing when every count is zero.
 */
export function DoneSection({
  done,
  labels: t,
  open,
  onToggle,
}: {
  done: JournalDone;
  labels: JournalLabels;
  open: boolean;
  onToggle: () => void;
}) {
  const ids = useId();
  const counts = doneCounts(done);
  const line = doneCountLine(done, t);
  if (!line) return null;
  const time = (value: string) => (
    <time dateTime={value}>{formatTime(value, t.dateLocale)}</time>
  );
  const more = (count: number, shown: number) =>
    count > shown ? (
      <p className="journal-done-more">{t.doneMore(count - shown)}</p>
    ) : null;
  return (
    <section className="journal-done" aria-label={t.done}>
      <h3>
        <Fold text={t.done} meta={line} open={open} onToggle={onToggle} />
      </h3>
      {open && (
        <>
          {done.tasks.length > 0 && (
            <>
              <p className="journal-done-label" id={`${ids}t`}>
                {t.doneTasks}
              </p>
              <ul className="journal-done-list" aria-labelledby={`${ids}t`}>
                {done.tasks.map((task) => (
                  <li key={task.id} className="journal-done-row">
                    <div className="journal-entry-card">
                      <span className="sk-row-primary">{task.title}</span>
                      <span className="journal-entry-meta">
                        {time(task.completed_at)}
                        {task.recurring ? ` · ${t.doneRecurring}` : null}
                        {task.project_title ? ` · ${task.project_title}` : null}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
              {more(counts.tasks, done.tasks.length)}
            </>
          )}
          {done.steps.length > 0 && (
            <>
              <p className="journal-done-label" id={`${ids}s`}>
                {t.doneSteps}
              </p>
              <ul className="journal-done-list" aria-labelledby={`${ids}s`}>
                {done.steps.map((step) => (
                  <li key={step.id} className="journal-done-row">
                    <div className="journal-entry-card">
                      <span className="sk-row-primary">{step.title}</span>
                      <span className="journal-entry-meta">
                        {time(step.completed_at)}
                        {` · ${step.task_title}`}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
              {more(counts.steps, done.steps.length)}
            </>
          )}
          {done.purchases.length > 0 && (
            <>
              <p className="journal-done-label" id={`${ids}p`}>
                {t.donePurchases}
              </p>
              <ul className="journal-done-list" aria-labelledby={`${ids}p`}>
                {byList(done.purchases).map((list) => (
                  <li key={list.id} className="journal-done-row">
                    <div className="journal-entry-card">
                      <span className="sk-row-primary">{list.title}</span>
                      <span className="journal-entry-meta">
                        {t.doneItemCount(list.items.length)}
                        {" · "}
                        {time(list.items[list.items.length - 1]!.purchased_at)}
                      </span>
                      <span className="journal-entry-excerpt journal-done-items">
                        {list.items.map((item) => item.title).join(", ")}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
              {more(counts.purchases, done.purchases.length)}
            </>
          )}
        </>
      )}
    </section>
  );
}

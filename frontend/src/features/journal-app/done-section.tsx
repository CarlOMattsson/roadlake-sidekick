import { useId, useState } from "react";
import type { ReactNode } from "react";
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
    .map((part) => part.replace(/ /g, " "))
    .join(" · ");
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

/** Open, each kind shows this many rows; "+N fler · Visa alla" opens the rest of that kind in place. */
const doneRowLimit = 3;

type DoneKind = "tasks" | "steps" | "purchases";

/** One kind in the open section: its label, its rows (at most three until the owner asks for all) and the server's cut. */
function DoneGroup({
  id,
  label,
  rows,
  unsent,
  whole,
  onWhole,
  labels: t,
}: {
  id: string;
  label: string;
  rows: { key: string; row: ReactNode }[];
  /** How many the server counted but did not send (it sends at most 50 per kind). */
  unsent: number;
  whole: boolean;
  onWhole: () => void;
  labels: JournalLabels;
}) {
  if (rows.length === 0) return null;
  const hidden = rows.length - doneRowLimit;
  const shown = whole ? rows : rows.slice(0, doneRowLimit);
  return (
    <>
      <p className="journal-done-label" id={`${id}-label`}>
        {label}
      </p>
      <ul id={id} className="journal-done-list" aria-labelledby={`${id}-label`}>
        {shown.map(({ key, row }) => (
          <li key={key} className="journal-done-row">
            <div className="journal-entry-card">{row}</div>
          </li>
        ))}
      </ul>
      {hidden > 0 && (
        <p className="journal-list-more">
          <button
            type="button"
            className="sk-btn--quiet"
            aria-expanded={whole}
            aria-controls={id}
            onClick={onWhole}
          >
            {whole
              ? t.showFewer
              : unsent > 0
                ? t.moreShowMore(hidden)
                : t.moreShowAll(hidden)}
          </button>
        </p>
      )}
      {(whole || hidden <= 0) && unsent > 0 && (
        <p className="journal-done-more">{t.doneMore(unsent)}</p>
      )}
    </>
  );
}

/**
 * «Gjort»: what was done on the day, read-only. The fold row
 * (`Fold`, as «Kontaktvägar») in the section's place: «Gjort ⌄» with the count line as its meta, folded by default.
 * Open: a muted label per kind («Uppgifter», «Steg», «Köpta varor»), then rows of the row template without a button
 * (title, one meta line «14:20 · project»), the bought items as one row per list with the items as its text. Each
 * kind shows its first three rows and "+N fler · Visa alla" for the rest, so an open section on a busy day does not
 * push «Anteckningar» far under the first screen. A list the server cut says how many more there are. Nothing when
 * every count is zero. The day view mounts it per day, so a kind shown in full is back to three on the next day.
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
  const [whole, setWhole] = useState<ReadonlySet<DoneKind>>(new Set());
  const counts = doneCounts(done);
  const line = doneCountLine(done, t);
  if (!line) return null;
  const time = (value: string) => (
    <time dateTime={value}>{formatTime(value, t.dateLocale)}</time>
  );
  const groupProps = (kind: DoneKind) => ({
    id: `${ids}${kind}`,
    whole: whole.has(kind),
    onWhole: () =>
      setWhole((current) => {
        const next = new Set(current);
        if (!next.delete(kind)) next.add(kind);
        return next;
      }),
    labels: t,
  });
  return (
    <section className="journal-done" aria-label={t.done}>
      <h3>
        <Fold text={t.done} meta={line} open={open} onToggle={onToggle} />
      </h3>
      {open && (
        <>
          <DoneGroup
            {...groupProps("tasks")}
            label={t.doneTasks}
            unsent={counts.tasks - done.tasks.length}
            rows={done.tasks.map((task) => ({
              key: task.id,
              row: (
                <>
                  <span className="sk-row-primary">{task.title}</span>
                  <span className="journal-entry-meta">
                    {time(task.completed_at)}
                    {task.recurring ? ` · ${t.doneRecurring}` : null}
                    {task.project_title ? ` · ${task.project_title}` : null}
                  </span>
                </>
              ),
            }))}
          />
          <DoneGroup
            {...groupProps("steps")}
            label={t.doneSteps}
            unsent={counts.steps - done.steps.length}
            rows={done.steps.map((step) => ({
              key: step.id,
              row: (
                <>
                  <span className="sk-row-primary">{step.title}</span>
                  <span className="journal-entry-meta">
                    {time(step.completed_at)}
                    {` · ${step.task_title}`}
                  </span>
                </>
              ),
            }))}
          />
          {/* One row per list; the server's cut is counted in items. */}
          <DoneGroup
            {...groupProps("purchases")}
            label={t.donePurchases}
            unsent={counts.purchases - done.purchases.length}
            rows={byList(done.purchases).map((list) => ({
              key: list.id,
              row: (
                <>
                  <span className="sk-row-primary">{list.title}</span>
                  <span className="journal-entry-meta">
                    {t.doneItemCount(list.items.length)}
                    {" · "}
                    {time(list.items[list.items.length - 1]!.purchased_at)}
                  </span>
                  <span className="journal-entry-excerpt journal-done-items">
                    {list.items.map((item) => item.title).join(", ")}
                  </span>
                </>
              ),
            }))}
          />
        </>
      )}
    </section>
  );
}

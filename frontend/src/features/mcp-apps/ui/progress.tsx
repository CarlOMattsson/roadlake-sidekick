import "./progress.css";

/**
 * The one progress bar (helhet rule 8, design language section 4) for tasks, projects, hierarchy rows and shopping
 * lists. The text ("done/total", or `label` such as "1 av 8 köpta") is always shown and is the information; the thin
 * bar is decoration, hidden from assistive technology, in one colour (the text colour) on a hairline track. With
 * `total` 0 the bar is left out, since an empty bar says nothing. Out-of-range values are clamped.
 *
 * `layout="inline"` (default) puts a short bar after the text, for a meta line or a row. `layout="bar"` puts the text
 * first and the bar over the rest of the row's full width, for a view's head ("Kundupdrag · 1 av 8 klara", a shopping
 * list's "1 av 8 köpta"). The status board's distribution bar is not progress and is not this component.
 */
export type ProgressProps = {
  done: number;
  total: number;
  label?: string;
  layout?: "inline" | "bar";
};

function toCount(value: number): number {
  return Number.isFinite(value) ? Math.max(0, Math.floor(value)) : 0;
}

export function Progress({
  done,
  total,
  label,
  layout = "inline",
}: ProgressProps) {
  const safeTotal = toCount(total);
  const safeDone = Math.min(toCount(done), safeTotal);
  const percent = safeTotal === 0 ? 0 : (safeDone / safeTotal) * 100;

  return (
    <span
      className={
        layout === "bar" ? "sk-progress sk-progress--bar" : "sk-progress"
      }
    >
      <span className="sk-progress__text">
        {label ?? `${safeDone}/${safeTotal}`}
      </span>
      {safeTotal > 0 ? (
        <span className="sk-progress__track" aria-hidden="true">
          <span
            className="sk-progress__fill"
            style={{ width: `${percent}%` }}
          />
        </span>
      ) : null}
    </span>
  );
}

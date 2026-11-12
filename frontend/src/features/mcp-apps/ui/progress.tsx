import "./progress.css";

/**
 * Progress for tasks, projects and hierarchy rows (design language section 4). The text "done/total"
 * is always shown and is the information; the thin bar beside it is decoration and hidden from
 * assistive technology. Numbers are the only text, so the component needs no labels and works in
 * sv and en alike. With `total` 0 the bar is left out, since an empty bar says nothing. Out-of-range
 * values are clamped so a bad count never draws past the track. A caller that needs a unit passes
 * `label` (e.g. "1 of 5 done"); it replaces the numbers as the visible text, and the bar stays.
 */
export type ProgressProps = {
  done: number;
  total: number;
  label?: string;
};

function toCount(value: number): number {
  return Number.isFinite(value) ? Math.max(0, Math.floor(value)) : 0;
}

export function Progress({ done, total, label }: ProgressProps) {
  const safeTotal = toCount(total);
  const safeDone = Math.min(toCount(done), safeTotal);
  const percent = safeTotal === 0 ? 0 : (safeDone / safeTotal) * 100;

  return (
    <span className="sk-progress">
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

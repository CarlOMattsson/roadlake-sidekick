import "./counts-bar.css";

/**
 * A proportional bar with one segment per status, plus a text legend that names every count. The
 * words and numbers carry the meaning; colour only supports them, so nothing depends on it. The bar
 * itself is hidden from assistive technology because the legend says the same thing in text. When
 * every count is zero there is no bar, but the legend still shows the zeros. Labels arrive as props
 * (the surface's own label file), so this file holds no text of its own.
 */
export type CountsTone = "neutral" | "info" | "warning";

export type CountsSegment = {
  key: string;
  /** Status name in the caller's language, e.g. `todo`. */
  label: string;
  count: number;
  tone?: CountsTone;
};

export type CountsBarProps = {
  /** Accessible name of the group, in the caller's language. */
  label: string;
  segments: readonly CountsSegment[];
};

/** Negative, NaN and infinite counts become zero; fractions are floored. */
function safeCount(count: number): number {
  return Number.isFinite(count) && count > 0 ? Math.floor(count) : 0;
}

export function CountsBar({ label, segments }: CountsBarProps) {
  // A segment without a tone is drawn neutral (the CSS default).
  const counted = segments.map((segment) => ({
    ...segment,
    count: safeCount(segment.count),
  }));
  const barSegments = counted.filter((segment) => segment.count > 0);

  return (
    <div role="group" aria-label={label} className="sk-counts-bar">
      {barSegments.length ? (
        <div className="sk-counts-bar__bar" aria-hidden="true">
          {barSegments.map((segment) => (
            <span
              key={segment.key}
              className="sk-counts-bar__segment"
              data-tone={segment.tone}
              style={{ flexGrow: segment.count }}
            />
          ))}
        </div>
      ) : null}
      <ul className="sk-counts-bar__legend">
        {counted.map((segment) => (
          <li
            key={segment.key}
            className="sk-counts-bar__item"
            data-tone={segment.tone}
          >
            <span className="sk-counts-bar__label">{segment.label}</span>
            <span className="sk-counts-bar__count">{segment.count}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

import type { ReactNode } from "react";
import "./frame-meta.css";

/**
 * The quiet line under the title of a Project or Process page: the Area with the progress or the cadence. `area` is
 * the Area's name, which arrives after the page and may never come; `detail` is the progress or the cadence. The parts
 * that exist are separated with "·"; with none, nothing is drawn. Each part keeps its own key, so the progress is not
 * drawn again when the Area name arrives in front of it.
 */
export function FrameMeta({
  area,
  detail,
}: {
  area?: string;
  detail?: ReactNode;
}) {
  if (!area && !detail) return null;
  return (
    <p className="work-frame-meta">
      {area ? (
        <span key="area" className="work-frame-meta__part">
          {area}
        </span>
      ) : null}
      {detail ? (
        <span key="detail" className="work-frame-meta__part">
          {detail}
        </span>
      ) : null}
    </p>
  );
}

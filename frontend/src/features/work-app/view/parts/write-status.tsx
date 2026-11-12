import type { RefObject } from "react";
import type { WorkLabels } from "../../shared/labels";
import type { WriteState } from "./frame-types";

/** Feedback of the last Task or Project write, or of a reload that failed. */
export function WriteStatus({
  write,
  conflict,
  onReload,
  banner,
  labels: t,
}: {
  write: WriteState;
  conflict: string;
  onReload: () => void;
  banner: RefObject<HTMLDivElement | null>;
  labels: WorkLabels;
}) {
  return (
    <>
      {write.kind === "conflict" && (
        <div role="alert" tabIndex={-1} ref={banner} className="work-banner">
          <p>{conflict}</p>
          <button type="button" onClick={onReload}>
            {t.reload}
          </button>
        </div>
      )}
      {write.kind === "forbidden" && <p>{t.forbiddenWrite}</p>}
      {write.kind === "invalid" && <p role="alert">{t.invalidChange}</p>}
      {write.kind === "notFound" && <p role="alert">{t.notFound}</p>}
      {write.kind === "failed" && write.action === "reload" && (
        <p role="alert">
          {t.failed}{" "}
          <button type="button" onClick={onReload}>
            {t.retry}
          </button>
        </p>
      )}
      {write.kind === "saved" && <p role="status">{t.saved}</p>}
    </>
  );
}

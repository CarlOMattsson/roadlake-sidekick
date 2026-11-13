import type { RefObject } from "react";
import { ErrorNotice } from "../../../mcp-apps/ui/states";
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
      {(write.kind === "invalid" || write.kind === "notFound") && (
        <ErrorNotice
          placement="row"
          locale={t.dateLocale}
          message={write.kind === "invalid" ? t.invalidChange : t.notFound}
        />
      )}
      {write.kind === "failed" && write.action === "reload" && (
        <ErrorNotice placement="row" locale={t.dateLocale} onRetry={onReload} />
      )}
      {write.kind === "saved" && <p role="status">{t.saved}</p>}
    </>
  );
}

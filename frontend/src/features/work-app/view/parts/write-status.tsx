import type { RefObject } from "react";
import { MessageBox } from "../../../mcp-apps/ui/message-box";
import { ErrorNotice } from "../../../mcp-apps/ui/states";
import type { WorkLabels } from "../../shared/labels";
import type { WriteState } from "./frame-types";

/**
 * Feedback of the last Task or Project write, or of a reload that failed. A write refused because the record changed
 * elsewhere is a warning `MessageBox` with the refresh that fixes it; the box sits in a wrapper that takes focus, since
 * the box itself takes no ref. A refused permission is an `info` box: nothing is wrong that a retry would mend.
 * `savedLine` (default) draws "Saved" as a line; a frame that confirms its saves in the receipt bar turns it off.
 */
export function WriteStatus({
  write,
  conflict,
  onReload,
  banner,
  labels: t,
  savedLine = true,
}: {
  write: WriteState;
  conflict: string;
  onReload: () => void;
  banner: RefObject<HTMLDivElement | null>;
  labels: WorkLabels;
  savedLine?: boolean;
}) {
  return (
    <>
      {write.kind === "conflict" && (
        <div tabIndex={-1} ref={banner}>
          <MessageBox
            severity="warning"
            title={conflict}
            action={{ label: t.reload, onClick: onReload }}
          />
        </div>
      )}
      {write.kind === "forbidden" && (
        <MessageBox severity="info" title={t.forbiddenWrite} />
      )}
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
      {savedLine && write.kind === "saved" && <p role="status">{t.saved}</p>}
    </>
  );
}

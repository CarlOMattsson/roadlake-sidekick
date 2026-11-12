import type { RefObject } from "react";
import { ErrorNotice } from "../../mcp-apps/ui/states";
import type { JournalLabels } from "../labels";
import type { WriteState } from "./use-draft-writes";

export type Notices = {
  proposalChanged: boolean;
  editClosed: boolean;
  keyPointFixed: boolean;
};

/** The write status of the frame: conflict banner, write failures, saved/working, and the one-off notices. */
export function DraftNotices({
  write,
  busy,
  pending,
  notices,
  onReload,
  bannerRef,
  labels: t,
}: {
  write: WriteState;
  busy: boolean;
  pending: boolean;
  notices: Notices;
  onReload: () => void;
  bannerRef: RefObject<HTMLDivElement | null>;
  labels: JournalLabels;
}) {
  return (
    <>
      {write.kind === "conflict" && (
        <div
          role="alert"
          tabIndex={-1}
          ref={bannerRef}
          className="journal-banner"
        >
          <p>{t.conflict}</p>
          <button type="button" onClick={onReload}>
            {t.reload}
          </button>
        </div>
      )}
      {write.kind === "forbidden" && <p>{t.forbiddenWrite}</p>}
      {write.kind === "invalid" && <p role="alert">{t.invalidChange}</p>}
      {write.kind === "failed" && write.action === "reload" && (
        <ErrorNotice locale={t.dateLocale} onRetry={onReload} />
      )}
      {write.kind === "saved" && pending && <p role="status">{t.saved}</p>}
      {busy && <p role="status">{t.working}</p>}
      {notices.proposalChanged && <p role="status">{t.proposalChanged}</p>}
      {notices.editClosed && <p role="status">{t.editClosedHidden}</p>}
      {notices.keyPointFixed && <p role="status">{t.keyPointFixed}</p>}
    </>
  );
}

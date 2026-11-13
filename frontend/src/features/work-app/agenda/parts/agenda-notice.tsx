import { useEffect, useRef } from "react";
import {
  NoticeView,
  noticeSpot,
  type BoardAction,
  type BoardNotice,
} from "../../board/board-notice";
import type { WorkLabels } from "../../shared/labels";

/** The agenda's last notice and what its buttons do; every `AgendaNotice` reads it and shows it only on its own spot. */
export type NoticeSource = {
  notice: BoardNotice | undefined;
  onReload: () => void;
  onRetry: (action: BoardAction) => void;
};

/** The spot of a row's notice: inside that row, below its line. */
export const rowSpot = (key: string) => `row:${key}`;

/**
 * The agenda's notice on the spot where its write or read was made (`noticeSpot`): in the row that was written, at
 * "Flytta alla", below "Visa fler", else above the list. A notice that sits away from the top takes focus on its
 * "Försök igen" when it shows, so a keyboard or screen reader user lands on it and not on the page.
 */
export function AgendaNotice({
  spot,
  source,
  labels,
}: {
  spot: string;
  source: NoticeSource;
  labels: WorkLabels;
}) {
  const box = useRef<HTMLDivElement>(null);
  const { notice } = source;
  const here = noticeSpot(notice) === spot;
  useEffect(() => {
    if (here && spot !== "top")
      box.current?.querySelector<HTMLElement>("button")?.focus();
  }, [here, spot, notice]);
  if (!here) return null;
  return (
    <div ref={box} className="work-agenda-notice">
      <NoticeView
        notice={notice}
        labels={labels}
        onReload={source.onReload}
        onRetry={source.onRetry}
      />
    </div>
  );
}

import { useEffect, type ReactNode } from "react";

import { ErrorNotice, Skeleton } from "../../../mcp-apps/ui/states";
import type { WorkTab } from "../../shell/work-shell";
import type { TabEntry, WorkTabFrame } from "./tab-data";

/**
 * The body of one tab. It mounts when the tab is pressed and asks for its first read then. While
 * the read runs it shows a skeleton; on failure, an error notice with a retry.
 */
export function TabPanel({
  tab,
  entry,
  active,
  shown,
  onLoad,
  onRetry,
  locale,
  children,
}: {
  tab: WorkTab;
  entry: TabEntry | undefined;
  /** True while this tab is the visible one; only then its views take keyboard shortcuts. */
  active: boolean;
  /** False while the whole room is hidden (behind a Task or Project): the first read waits until it is shown. */
  shown: boolean;
  onLoad: (tab: WorkTab) => void;
  onRetry: (tab: WorkTab) => void;
  locale: string;
  children: (frame: WorkTabFrame, active: boolean) => ReactNode;
}) {
  useEffect(() => {
    if (shown) onLoad(tab);
  }, [onLoad, tab, shown]);
  if (entry?.status === "ready") return children(entry.frame, active);
  if (entry?.status === "error")
    return (
      <ErrorNotice
        locale={locale}
        // The tab names what could not be read, whichever tool opened the room.
        subject={`work:${tab}`}
        cause={entry.cause}
        retrying={entry.retrying}
        onRetry={() => onRetry(tab)}
      />
    );
  return <Skeleton heading glyph />;
}

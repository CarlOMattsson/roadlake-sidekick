import { useContext, type ReactNode } from "react";

import "./layout.css";
import { RoomSurfaceContext } from "./room-context";

/**
 * Root for every MCP App surface. `inline` is the compact Glance inside the conversation, `full`
 * is the fullscreen View. The mode sets `data-mode`; density follows from the mode and from the
 * container width (container queries), not from separate views.
 *
 * The host draws the outer edge of an inline app (`prefersBorder: false`), so inline adds only the
 * host safe area. Fullscreen adds 16 px, or 24 px from a 640 px container width, and caps the
 * content width at 72rem. The safe-area values come from `applyHostStyle` as `--host-safe-*`.
 */
export type AppFrameMode = "inline" | "full";

export function AppFrame({
  mode,
  children,
}: {
  mode: AppFrameMode;
  children: ReactNode;
}) {
  // Inside the Sidekick shell's full frame a room draws no second frame.
  const { framed } = useContext(RoomSurfaceContext);
  if (framed && mode === "full") return <>{children}</>;
  return (
    <div className="sk-frame" data-mode={mode}>
      <div className="sk-frame__body">{children}</div>
    </div>
  );
}

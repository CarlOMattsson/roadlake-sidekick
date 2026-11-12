import type { ReactNode } from "react";
import {
  BackHeader,
  BackHeaderActions,
  useBackHeaderSlot,
} from "../../mcp-apps/ui/back-header";
import type { BackTarget } from "./frame-types";

/**
 * The top row of a Task, Contact or Project (design system §3, Tillbakarad): "‹ Parent" on the left and the view's
 * icon buttons (pen, then ⋯) on the right, 44 px high. In fullscreen the shell draws that Back row, and the actions
 * go into its slot (BackHeaderActions). A Back inside the view (a deeper frame of this view) is drawn here with the
 * actions. A root frame with no Back at all shows the kind as a muted kicker ("Uppgift") in the row instead, with the
 * same actions, so the actions never sit on the title's line.
 */
export function DetailBar({
  back,
  kicker,
  actions,
}: {
  back?: BackTarget;
  kicker?: string;
  actions?: ReactNode;
}) {
  const shellBack = useBackHeaderSlot();
  if (back)
    return (
      <BackHeader label={back.label} onBack={back.onBack} actions={actions} />
    );
  if (shellBack)
    return actions ? <BackHeaderActions>{actions}</BackHeaderActions> : null;
  if (!kicker && !actions) return null;
  return (
    <div className="sk-back-header work-detail-bar">
      <div className="sk-back-header__bar">
        {kicker ? <p className="sk-eyebrow">{kicker}</p> : <span />}
        {actions ? (
          <div className="sk-back-header__actions">{actions}</div>
        ) : null}
      </div>
    </div>
  );
}

import type { ReactNode } from "react";
import { SplitLayout } from "../../mcp-apps/ui/split-layout";

/**
 * The view's body under its head. Split (a wide frame, useWideLists): the lists on the left and the chosen list on the
 * right, under its name in the detail's display size (ui/split-layout.tsx, desktop spec 3.4); there is no way back, so
 * the name is the detail's own heading. Otherwise one column: the notices, the picker while no list is chosen, and the
 * list, as on a phone.
 */
export function ShoppingPanes({
  split,
  id,
  title,
  notices,
  picker,
  body,
}: {
  split: boolean;
  /** The chosen list, or "" for the picker. */
  id: string;
  /** The chosen list's name (or its shop view's), when it has been read. */
  title?: string;
  notices: ReactNode;
  picker: ReactNode;
  body: ReactNode;
}) {
  if (!split)
    return (
      <>
        {notices}
        {!id && picker}
        {body}
      </>
    );
  return (
    <SplitLayout split="split" shown={id}>
      <div data-pane="list" className="shopping-rail">
        {picker}
      </div>
      <div data-pane="detail" className="shopping-detail">
        {title && <h2 className="shopping-detail-title">{title}</h2>}
        {notices}
        {body}
      </div>
    </SplitLayout>
  );
}

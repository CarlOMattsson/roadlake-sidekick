import { useEffect, type ReactNode } from "react";
import { scrollBoxOf, useNearest } from "../agenda-undo";

/**
 * The quick choices of an open Task, under its row. It scrolls itself into view when it mounts, which is when the menu
 * opens, so a menu opened low on the screen ends above the host's reply field (its scroll margin is the foot reserve).
 */
export function RowMenu({
  children,
  scrollKey,
  large,
}: {
  children: ReactNode;
  /** What the menu shows besides its row: a change scrolls it into view again (a group opened). */
  scrollKey: string;
  /** Large text (≥ 150 %): the open row is put right under its group's heading. */
  large: boolean;
}) {
  const menu = useNearest<HTMLDivElement>(scrollKey);
  // At large text the open row with its menu (≤ 442 at 200 %) is put 6 under its group's heading,
  // where the heading sticks under the tab row: its title and × stand whole under the heading, and between them lies
  // only the 6 under the row above (no cut stump of another row). A first row stands under its heading in the flow.
  useEffect(() => {
    const row = menu.current?.closest("li");
    if (!large || !row?.isConnected) return;
    const head = row
      .closest("section")
      ?.querySelector<HTMLElement>(".work-agenda-group-head");
    if (!head) return;
    const scroller = scrollBoxOf(row);
    for (let pass = 0; pass < 2; pass += 1) {
      const line = parseFloat(getComputedStyle(head).top);
      if (!Number.isFinite(line)) return;
      const target = line + head.getBoundingClientRect().height + 6;
      const delta = row.getBoundingClientRect().top - target;
      if (Math.abs(delta) < 0.5) return;
      scroller.scrollBy(0, delta);
    }
  }, [scrollKey, large, menu]);
  return (
    <div ref={menu} className="work-agenda-menu">
      {children}
    </div>
  );
}

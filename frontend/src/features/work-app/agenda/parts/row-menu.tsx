import { useEffect, type ReactNode } from "react";
import { Menu, useMenuPopover } from "../../../mcp-apps/ui/menu";
import { scrollBoxOf, useNearest } from "../agenda-undo";
import type { MenuPoint } from "../../shared/row-menu";
import "./row-menu.css";

/**
 * The quick choices of an open Task. With a mouse or in a wide frame they are a popover menu (`Menu`): at the pointer
 * that asked for them, or under the row's title when the keys did (Shift+F10, the menu key), so the list under it
 * does not move. On a phone they are today's panel under the row (`RowMenuPanel`'s chips in the flow).
 */
export function RowMenu({
  children,
  scrollKey,
  large,
  at,
  onClose,
}: {
  children: ReactNode;
  /** What the menu shows besides its row: a change scrolls it into view again (a group opened). */
  scrollKey: string;
  /** Large text (≥ 150 %): the open row is put right under its group's heading. */
  large: boolean;
  /** Where a pointer opened it; absent when the keys did. */
  at?: MenuPoint;
  /** Escape, Tab or a press outside the popover. */
  onClose: () => void;
}) {
  const popover = useMenuPopover();
  if (popover)
    return (
      <RowPopover at={at} onClose={onClose}>
        {children}
      </RowPopover>
    );
  return (
    <RowPanel scrollKey={scrollKey} large={large}>
      {children}
    </RowPanel>
  );
}

/**
 * The popover of a row: it stands in the row's DOM (its keys bubble to the row as before) and in the top layer on
 * screen. Its anchor is the row's title, found from the menu itself (`rowTitleOf`), so it needs no ref through the row.
 */
function RowPopover({
  at,
  onClose,
  children,
}: {
  at?: MenuPoint;
  onClose: () => void;
  children: ReactNode;
}) {
  return (
    <Menu
      anchor={rowTitleOf}
      align="start"
      point={at}
      popoverClassName="sk-menu-popover work-agenda-popmenu"
      onClose={onClose}
    >
      {children}
    </Menu>
  );
}

/** The title of the row a menu lives in: the popover stands under it, and the focus goes back to it. */
function rowTitleOf(menu: HTMLElement): HTMLElement | null {
  return (
    menu
      .closest("li")
      ?.querySelector<HTMLElement>(".work-agenda-body > button") ?? null
  );
}

/**
 * The phone's panel under the row. It scrolls itself into view when it mounts, which is when the menu opens, so a
 * menu opened low on the screen ends above the host's reply field (its scroll margin is the foot reserve).
 */
function RowPanel({
  children,
  scrollKey,
  large,
}: {
  children: ReactNode;
  scrollKey: string;
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

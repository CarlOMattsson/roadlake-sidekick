import { useState, type RefObject } from "react";
import { menuButtonOf } from "../../board/board-card";
import { useLargeText } from "../../../mcp-apps/ui/large-text";

/** The groups of the row menu that fold at large text. */
export type MenuGroup = "status" | "due";

/** The row whose quick choices are open (one at a time) and, at large text, the group of its menu that is open. */
export function useRowMenu(root: RefObject<HTMLElement | null>) {
  // The row whose quick choices are open; one at a time.
  const [menu, setMenu] = useState<string>();
  // At large text the row menu shows one group at a time: Status first, the shorter of the two.
  const largeText = useLargeText();
  const [menuGroup, setMenuGroup] = useState<MenuGroup | undefined>("status");

  return {
    menu,
    menuGroup,
    largeText,
    /** Closes the quick choices of whichever row has them open. */
    closeMenu: () => setMenu(undefined),
    /** At large text one group is open at a time: opening one folds the other. */
    foldGroup: (group: MenuGroup) => {
      setMenuGroup(menuGroup === group ? undefined : group);
    },
    /** Opens or closes the quick choices of a row. Closing hands focus back to the title, where the keys opened them. */
    setOpen: (key: string, next: boolean) => {
      setMenu(next ? key : undefined);
      setMenuGroup("status");
      if (!next) {
        const row = root.current?.querySelector<HTMLElement>(
          `li[data-agenda-key="${key}"]`,
        );
        // Back on the hidden menu button when that opened the menu, else on the title.
        (
          menuButtonOf(row) ??
          row?.querySelector<HTMLElement>(".work-agenda-body > button")
        )?.focus();
      }
    },
  };
}

/** The row menu state: see `useRowMenu`. */
export type RowMenuState = ReturnType<typeof useRowMenu>;

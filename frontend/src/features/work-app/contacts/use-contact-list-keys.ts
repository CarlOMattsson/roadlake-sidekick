import type { KeyboardEvent, RefObject } from "react";
import { useRoomShortcuts } from "../../mcp-apps/ui/shortcut-registry";
import { shellLabelsForDateLocale } from "../../mcp-apps/sidekick-shell-labels";

/** A Contact row's open control (ui/row.tsx). */
const ROW = "[data-sk-open]";

/** The Contact a row opens, from the record key its `li` carries ("contacts:contact:<id>"). */
function contactOf(row: HTMLElement): string | undefined {
  return row
    .closest<HTMLElement>("[data-sk-record]")
    ?.dataset.skRecord?.split(":")[2];
}

/**
 * The keys of the Contact list (desktop spec 2.6). ↓ or Enter in the search field moves to the first row; ↓ and ↑, or
 * j and k, move between rows, and ↑ on the first row goes back to the field. Beside its Contact (a split list), stepping
 * with j, k or an arrow also opens the Contact it lands on there (`follow`), so the detail follows. Returns the
 * `onKeyDown` for the list's root; j and k are listed in the keyboard help under `title`. Only a fullscreen caller turns
 * the single keys on (`shortcuts`).
 */
export function useContactListKeys({
  root,
  search,
  shortcuts,
  locale,
  title,
  follow,
}: {
  root: RefObject<HTMLElement | null>;
  search: RefObject<HTMLInputElement | null>;
  shortcuts: boolean;
  locale: string;
  title: string;
  follow?: (id: string) => void;
}) {
  const rowsOf = () =>
    Array.from(root.current?.querySelectorAll<HTMLElement>(ROW) ?? []);

  function step(delta: number) {
    const rows = rowsOf();
    if (rows.length === 0) return;
    const at = rows.findIndex((row) => row === document.activeElement);
    const next = Math.min(Math.max(at + delta, 0), rows.length - 1);
    const row = rows[next];
    if (!row || next === at) return;
    row.focus();
    const id = contactOf(row);
    if (id) follow?.(id);
  }

  const keys = shellLabelsForDateLocale(locale).shortcuts;
  useRoomShortcuts(
    { j: () => step(1), k: () => step(-1) },
    {
      id: "contacts-rows",
      title,
      labels: { j: keys.nextRow, k: keys.previousRow },
    },
    { enabled: shortcuts },
  );

  return function onKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.defaultPrevented || event.nativeEvent.isComposing) return;
    const target = event.target as HTMLElement;
    if (target === search.current) {
      if (event.key !== "ArrowDown" && event.key !== "Enter") return;
      const first = rowsOf()[0];
      if (!first) return;
      event.preventDefault();
      first.focus();
      return;
    }
    if (!target.matches(ROW)) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      step(1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      if (rowsOf()[0] === target) search.current?.focus();
      else step(-1);
    }
  };
}

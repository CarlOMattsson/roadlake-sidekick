import { createContext, useContext, useEffect, useId } from "react";

import { Notice } from "@/features/mcp-apps/ui/notice";
import { buttonClass } from "@/features/mcp-apps/ui/button";
import type { SidekickShellLabels } from "@/features/mcp-apps/sidekick-shell-labels";

/**
 * Unsaved work, one mechanism for every form. A form that holds edits the user has not saved calls
 * `useUnsavedGuard(dirty)`; the shell then asks "Släng ändringarna?" before a Back (the Back row or the
 * system Back of the phone) or a press on the active room tab would take the layer away. With no unsaved
 * form there is no question. Outside the shell (a card, a test) the hook does nothing.
 */
export type UnsavedRegistry = {
  /** A form (`token`) in layer `layer` has, or no longer has, unsaved edits. */
  set: (layer: string, token: string, dirty: boolean) => void;
  /** True when any of these layers holds a form with unsaved edits. */
  isDirty: (layers: readonly string[]) => boolean;
};

export function createUnsavedRegistry(): UnsavedRegistry {
  const dirty = new Map<string, Set<string>>();
  return {
    set(layer, token, on) {
      const tokens = dirty.get(layer) ?? new Set<string>();
      if (on) tokens.add(token);
      else tokens.delete(token);
      if (tokens.size > 0) dirty.set(layer, tokens);
      else dirty.delete(layer);
    },
    isDirty: (layers) => layers.some((layer) => dirty.has(layer)),
  };
}

/** What the shell gives each layer: its id and the registry function the forms in it report to. */
export type UnsavedGuard = Pick<UnsavedRegistry, "set"> & { layer: string };

export const UnsavedGuardContext = createContext<UnsavedGuard>({
  layer: "",
  set: () => undefined,
});

/** Call with true while the form holds edits that are not saved; false (or unmounted) when there are none. */
export function useUnsavedGuard(dirty: boolean): void {
  const { layer, set } = useContext(UnsavedGuardContext);
  const token = useId();
  useEffect(() => {
    if (!dirty) return undefined;
    set(layer, token, true);
    return () => set(layer, token, false);
  }, [dirty, layer, set, token]);
}

/** "Släng ändringarna? [Släng] [Fortsätt redigera]": a small inline card under the Back row, never a dialog. */
export function UnsavedAsk({
  labels,
  onDiscard,
  onKeep,
  keepRef,
}: {
  labels: Pick<
    SidekickShellLabels,
    "unsavedAsk" | "unsavedDiscard" | "unsavedKeep"
  >;
  onDiscard: () => void;
  onKeep: () => void;
  /** The safe choice takes the focus when the question opens. */
  keepRef?: (element: HTMLButtonElement | null) => void;
}) {
  return (
    <Notice
      tone="warning"
      action={
        <span className="sk-unsaved__actions">
          <button
            type="button"
            className={buttonClass("danger")}
            onClick={onDiscard}
          >
            {labels.unsavedDiscard}
          </button>
          <button
            type="button"
            ref={keepRef}
            className={buttonClass("secondary")}
            onClick={onKeep}
          >
            {labels.unsavedKeep}
          </button>
        </span>
      }
    >
      {labels.unsavedAsk}
    </Notice>
  );
}

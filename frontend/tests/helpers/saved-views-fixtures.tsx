import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi, type Mock } from "vitest";
import { manageLabelsSv } from "@/features/work-app/manage-labels";
import { SavedViewsBar } from "@/features/work-app/saved-views-bar";
import { savedViewsLabelsSv } from "@/features/work-app/saved-views-labels";
import type {
  WorkFilters,
  WorkSavedView,
  WorkTransport,
} from "@/features/work-app/transport";

export const meetings: WorkSavedView = {
  id: "019f0000-0000-7000-8000-0000000000v1",
  name: "Möten",
  definition: { view: "agenda", context: "all", status: "todo" },
  version: 2,
  archived_at: null,
};
export const boardView: WorkSavedView = {
  id: "019f0000-0000-7000-8000-0000000000v2",
  name: "Bräde",
  definition: { view: "board", context: "all" },
  version: 1,
  archived_at: null,
};

/** A transport with the saved-view methods; each write answers with the given view. */
export function fakeTransport(views: WorkSavedView[] = []) {
  const listSavedWorkViews = vi.fn().mockResolvedValue(views);
  const createSavedWorkView = vi.fn();
  const updateSavedWorkView = vi.fn();
  const archiveSavedWorkView = vi.fn();
  const restoreSavedWorkView = vi.fn();
  const transport = {
    listSavedWorkViews,
    createSavedWorkView,
    updateSavedWorkView,
    archiveSavedWorkView,
    restoreSavedWorkView,
  } as unknown as WorkTransport;
  return {
    transport,
    listSavedWorkViews,
    createSavedWorkView,
    updateSavedWorkView,
    archiveSavedWorkView,
    restoreSavedWorkView,
  };
}

export function renderBar(options: {
  transport: WorkTransport;
  tab?: "agenda" | "board";
  filters?: WorkFilters;
  onOpen?: Mock;
}) {
  const onOpen = options.onOpen ?? vi.fn().mockResolvedValue(true);
  render(
    <SavedViewsBar
      tab={options.tab ?? "agenda"}
      transport={options.transport}
      labels={savedViewsLabelsSv}
      manage={manageLabelsSv}
      filters={options.filters ?? {}}
      onOpen={onOpen}
    />,
  );
  return { onOpen };
}

export async function openPanel(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "Sparade vyer" }));
}

export function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

import type { WorkContactsPage } from "../transport/transport";

export type MorePhase = "idle" | "busy" | "failed";

/** What the list read and Show more last did, apart from the page itself (that lives in the frame). */
export type ContactsListState = {
  error: "forbidden" | "error" | undefined;
  /** What the failed read threw, for the error notice's second line. */
  cause: unknown;
  more: MorePhase;
};

export type ContactsListAction =
  /** A new search, archive switch or read starts: the earlier error and Show more are old. */
  | { type: "reset" }
  | { type: "failed"; cause: unknown; forbidden: boolean }
  | { type: "moreStarted" }
  | { type: "moreDone" }
  | { type: "moreFailed" };

export const initialContactsListState: ContactsListState = {
  error: undefined,
  cause: undefined,
  more: "idle",
};

export function contactsListReducer(
  state: ContactsListState,
  action: ContactsListAction,
): ContactsListState {
  switch (action.type) {
    case "reset":
      return { ...state, error: undefined, more: "idle" };
    case "failed":
      return {
        ...state,
        cause: action.cause,
        error: action.forbidden ? "forbidden" : "error",
      };
    case "moreStarted":
      return { ...state, more: "busy" };
    case "moreDone":
      return { ...state, more: "idle" };
    case "moreFailed":
      return { ...state, more: "failed" };
  }
}

/** True when `page` answers this search, archive switch and tag filter. */
export function pageMatches(
  page: WorkContactsPage | undefined,
  q: string,
  includeArchived: boolean,
  tags: readonly string[] = [],
): page is WorkContactsPage {
  return (
    page?.q === q &&
    page.includeArchived === includeArchived &&
    sameTags(page.tags ?? [], tags)
  );
}

function sameTags(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((tag, index) => tag === b[index]);
}

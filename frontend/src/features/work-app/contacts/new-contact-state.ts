import type { WorkContactSummary, WriteFailure } from "../transport/transport";

/** A request to open the create field with a name in it; `n` makes a repeated request with the same name new. */
export type CreateRequest = { name: string; n: number };

export type NewContactState = {
  open: boolean;
  /** The create field's starting text: the name of a request, else empty. */
  prefill: string;
  /** Bumped to remount the create field with its starting text. */
  fieldKey: number;
  /** The last request seen; a different one reopens the field. */
  seenRequest: CreateRequest | undefined;
  problem: string | undefined;
  busy: boolean;
  failure: WriteFailure | undefined;
  /** The Contacts that already have the typed name; the create waits for the user's choice. */
  sameName: WorkContactSummary[];
  /** The name `sameName` was found for. */
  takenName: string;
};

export type NewContactAction =
  /** A new request opens the field afresh with its name; an absent request only records that it went. */
  | { type: "requested"; request: CreateRequest | undefined }
  | { type: "opened" }
  /** The field closes and forgets its text, problem and failure. */
  | { type: "closed" }
  /** The field was emptied after a successful retry: it remounts empty. */
  | { type: "emptied" }
  | { type: "problem"; text: string }
  | { type: "sameNameFound"; name: string; contacts: WorkContactSummary[] }
  | { type: "submitStarted" }
  | { type: "submitFailed"; failure: WriteFailure }
  | { type: "submitSettled" };

export function initialNewContactState(
  request: CreateRequest | undefined,
): NewContactState {
  return {
    open: false,
    prefill: "",
    fieldKey: 0,
    seenRequest: request,
    problem: undefined,
    busy: false,
    failure: undefined,
    sameName: [],
    takenName: "",
  };
}

export function newContactReducer(
  state: NewContactState,
  action: NewContactAction,
): NewContactState {
  switch (action.type) {
    case "requested":
      return action.request
        ? {
            ...state,
            seenRequest: action.request,
            prefill: action.request.name,
            fieldKey: state.fieldKey + 1,
            open: true,
          }
        : { ...state, seenRequest: action.request };
    case "opened":
      return { ...state, prefill: "", open: true };
    case "closed":
      return {
        ...state,
        prefill: "",
        open: false,
        problem: undefined,
        failure: undefined,
        sameName: [],
      };
    case "emptied":
      return {
        ...state,
        prefill: "",
        fieldKey: state.fieldKey + 1,
        sameName: [],
      };
    case "problem":
      return { ...state, problem: action.text };
    case "sameNameFound":
      return {
        ...state,
        sameName: action.contacts,
        takenName: action.name,
      };
    case "submitStarted":
      return {
        ...state,
        busy: true,
        problem: undefined,
        failure: undefined,
        sameName: [],
      };
    case "submitFailed":
      return { ...state, failure: action.failure };
    case "submitSettled":
      return { ...state, busy: false };
  }
}

/** A name as the server compares it: width and case folded, whitespace collapsed. */
function nameKey(name: string): string {
  return name
    .normalize("NFKC")
    .split(/\s+/u)
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

/** The listed Contacts that carry the typed name (the list also holds near and partial matches). */
export function withSameName(
  name: string,
  contacts: WorkContactSummary[],
): WorkContactSummary[] {
  const wanted = nameKey(name);
  return contacts.filter(
    (contact) => !contact.archived && nameKey(contact.display_name) === wanted,
  );
}

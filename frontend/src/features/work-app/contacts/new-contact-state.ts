import type { WriteFailure } from "../transport/transport";

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
      };
    case "emptied":
      return { ...state, prefill: "", fieldKey: state.fieldKey + 1 };
    case "problem":
      return { ...state, problem: action.text };
    case "submitStarted":
      return { ...state, busy: true, problem: undefined, failure: undefined };
    case "submitFailed":
      return { ...state, failure: action.failure };
    case "submitSettled":
      return { ...state, busy: false };
  }
}

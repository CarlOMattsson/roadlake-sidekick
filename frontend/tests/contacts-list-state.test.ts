import { describe, expect, it } from "vitest";

import {
  contactsListReducer,
  initialContactsListState,
  pageMatches,
} from "@/features/work-app/contacts/contacts-list-state";
import {
  initialNewContactState,
  newContactReducer,
  type CreateRequest,
  type NewContactAction,
  type NewContactState,
} from "@/features/work-app/contacts/new-contact-state";
import type { WorkContactsPage } from "@/features/work-app/transport/transport";

describe("contactsListReducer", () => {
  it("starts idle with no error", () => {
    expect(initialContactsListState).toEqual({
      error: undefined,
      cause: undefined,
      more: "idle",
    });
  });

  it("tells a forbidden read from any other failure and keeps what the read threw", () => {
    const cause = new Error("boom");
    const forbidden = contactsListReducer(initialContactsListState, {
      type: "failed",
      cause,
      forbidden: true,
    });
    expect(forbidden).toMatchObject({ error: "forbidden", cause });
    expect(
      contactsListReducer(initialContactsListState, {
        type: "failed",
        cause,
        forbidden: false,
      }).error,
    ).toBe("error");
  });

  it("a new read clears the error and an earlier Show more", () => {
    const failed = contactsListReducer(
      contactsListReducer(initialContactsListState, {
        type: "failed",
        cause: new Error("x"),
        forbidden: false,
      }),
      { type: "moreFailed" },
    );
    expect(failed).toMatchObject({ error: "error", more: "failed" });
    expect(contactsListReducer(failed, { type: "reset" })).toMatchObject({
      error: undefined,
      more: "idle",
    });
  });

  it("Show more goes busy, then idle or failed", () => {
    const busy = contactsListReducer(initialContactsListState, {
      type: "moreStarted",
    });
    expect(busy.more).toBe("busy");
    expect(contactsListReducer(busy, { type: "moreDone" }).more).toBe("idle");
    expect(contactsListReducer(busy, { type: "moreFailed" }).more).toBe(
      "failed",
    );
  });
});

describe("pageMatches", () => {
  const page: WorkContactsPage = {
    items: [],
    next_cursor: null,
    q: "anna",
    includeArchived: false,
  };

  it("matches only the same search and archive switch", () => {
    expect(pageMatches(page, "anna", false)).toBe(true);
    expect(pageMatches(page, "anna", true)).toBe(false);
    expect(pageMatches(page, "bo", false)).toBe(false);
    expect(pageMatches(undefined, "anna", false)).toBe(false);
  });
});

describe("newContactReducer", () => {
  const run = (state: NewContactState, ...actions: NewContactAction[]) =>
    actions.reduce(newContactReducer, state);
  const request: CreateRequest = { name: "Zlatan", n: 1 };

  it("a request opens the field with its name and remounts it", () => {
    const state = run(initialNewContactState(undefined), {
      type: "requested",
      request,
    });
    expect(state).toMatchObject({
      open: true,
      prefill: "Zlatan",
      fieldKey: 1,
      seenRequest: request,
    });
  });

  it("the same name asked again is a new request and remounts the field again", () => {
    const again: CreateRequest = { name: "Zlatan", n: 2 };
    const state = run(
      initialNewContactState(undefined),
      { type: "requested", request },
      { type: "closed" },
      { type: "requested", request: again },
    );
    expect(state).toMatchObject({ open: true, prefill: "Zlatan", fieldKey: 2 });
  });

  it("a request already seen at mount does not open the field", () => {
    expect(initialNewContactState(request)).toMatchObject({
      open: false,
      seenRequest: request,
    });
  });

  it("an absent request only records that the earlier one went", () => {
    const state = run(initialNewContactState(request), {
      type: "requested",
      request: undefined,
    });
    expect(state).toMatchObject({ open: false, seenRequest: undefined });
  });

  it("opens empty from + and closes forgetting text, problem and failure", () => {
    const opened = run(initialNewContactState(undefined), { type: "opened" });
    expect(opened).toMatchObject({ open: true, prefill: "" });
    const closed = run(
      opened,
      { type: "problem", text: "Too long" },
      { type: "submitFailed", failure: "failed" },
      { type: "closed" },
    );
    expect(closed).toMatchObject({
      open: false,
      prefill: "",
      problem: undefined,
      failure: undefined,
    });
  });

  it("a submit holds busy and clears the earlier problem and failure until it settles", () => {
    const started = run(
      initialNewContactState(undefined),
      { type: "problem", text: "Too long" },
      { type: "submitFailed", failure: "conflict" },
      { type: "submitStarted" },
    );
    expect(started).toMatchObject({
      busy: true,
      problem: undefined,
      failure: undefined,
    });
    expect(run(started, { type: "submitSettled" }).busy).toBe(false);
  });

  it("emptying after a successful retry remounts the field without text", () => {
    const state = run(
      initialNewContactState(undefined),
      { type: "requested", request },
      { type: "emptied" },
    );
    expect(state).toMatchObject({ prefill: "", fieldKey: 2, open: true });
  });
});

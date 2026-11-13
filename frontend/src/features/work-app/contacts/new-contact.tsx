import { useEffect, useReducer, useRef } from "react";
import type { WorkLabels } from "../shared/labels";
import { titleProblem } from "../shared/fields";
import { keyFor, type PendingKey } from "../../mcp-apps/idempotency";
import { PlusIcon } from "../../mcp-apps/ui/icons";
import { CreateField } from "../../mcp-apps/ui/create-field";
import { ErrorNotice } from "../../mcp-apps/ui/states";
import { WriteFailureRow } from "../shared/write-failure-row";
import { hierarchyDetailLabelsFor } from "../hierarchy/hierarchy-detail-labels";
import {
  writeFailure,
  type WorkContactRecord,
  type WorkTransport,
} from "../transport/transport";
import {
  initialNewContactState,
  newContactReducer,
  type CreateRequest,
} from "./new-contact-state";

/**
 * "Ny kontakt" behind + in the room head (design system §3, Skapa): + opens the shared create field under the head,
 * and a new Contact needs only its name. The same name sends one key, so a retry after a lost answer replays the result
 * instead of creating a second Contact. The created Contact is handed to the parent, which opens it. Esc and × close
 * the field and return the focus to +.
 */
export function NewContact({
  transport,
  labels: t,
  request,
  onCreated,
}: {
  transport: WorkTransport;
  labels: WorkLabels;
  /** Opens the field with this name in it (a search with no match); a new request opens it again. */
  request?: CreateRequest;
  onCreated: (contact: WorkContactRecord) => void;
}) {
  const [state, dispatch] = useReducer(
    newContactReducer,
    request,
    initialNewContactState,
  );
  const { open, prefill, fieldKey, problem, busy, failure } = state;
  const openButton = useRef<HTMLButtonElement>(null);
  const lastName = useRef("");
  // Synchronous guard against a second create before React re-renders.
  const writing = useRef(false);
  // The key of each name whose delivery is not settled: the same name again reuses its own key.
  const pendingWrite = useRef(new Map<string, PendingKey>());
  // What the create field holds now: a retry that succeeds empties it only if it still holds the retried name.
  const draft = useRef("");
  const mounted = useRef(true);
  const dl = hierarchyDetailLabelsFor(t.dateLocale);
  // A new request opens the field afresh with its name; derived while rendering, as the room does for a new result.
  if (request !== state.seenRequest) dispatch({ type: "requested", request });
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  // The field holds the prefilled name before any typing, so the draft follows it.
  useEffect(() => {
    draft.current = prefill;
  }, [prefill, fieldKey]);

  function retry() {
    const name = lastName.current;
    void submit(name).then((created) => {
      if (created && mounted.current && draft.current.trim() === name.trim()) {
        draft.current = "";
        dispatch({ type: "emptied" });
      }
    });
  }

  function close() {
    draft.current = "";
    dispatch({ type: "closed" });
    openButton.current?.focus();
  }
  /** true when the Contact was created; false when the write was refused or failed (the create field keeps the name). */
  function submit(name: string): Promise<boolean> {
    if (writing.current) return Promise.resolve(false);
    lastName.current = name;
    if (titleProblem(name) === "tooLong") {
      dispatch({ type: "problem", text: t.nameTooLong });
      return Promise.resolve(false);
    }
    const pendingKey = keyFor(
      pendingWrite.current.get(name),
      JSON.stringify([name]),
    );
    pendingWrite.current.set(name, pendingKey);
    writing.current = true;
    dispatch({ type: "submitStarted" });
    return transport
      .createContact({ display_name: name }, pendingKey.key)
      .then((result) => {
        if (mounted.current) {
          pendingWrite.current.delete(name);
          onCreated(result.contact);
        }
        return true;
      })
      .catch((error: unknown) => {
        if (mounted.current)
          dispatch({ type: "submitFailed", failure: writeFailure(error) });
        return false;
      })
      .finally(() => {
        writing.current = false;
        if (mounted.current) dispatch({ type: "submitSettled" });
      });
  }

  return (
    <>
      <button
        ref={openButton}
        type="button"
        className="sk-iconbtn sk-iconbtn--primary work-contacts-add"
        aria-label={t.newContact}
        title={t.newContact}
        aria-expanded={open}
        onClick={() => {
          if (open) close();
          else dispatch({ type: "opened" });
        }}
      >
        <PlusIcon />
      </button>
      {open && (
        <div
          className="work-contacts-create"
          aria-busy={busy}
          onInput={(event) => {
            draft.current = (event.target as HTMLInputElement).value;
          }}
        >
          <CreateField
            key={fieldKey}
            initialText={prefill}
            label={t.newContact}
            placeholder={dl.newContactExample}
            closeLabel={dl.close}
            addLabel={dl.add}
            onCreate={(text) =>
              submit(text).then((ok) => {
                // The field empties itself on success: the draft follows it.
                if (ok && draft.current.trim() === text.trim())
                  draft.current = "";
                return ok;
              })
            }
            onClose={close}
          />
          {problem && (
            <ErrorNotice
              placement="row"
              locale={t.dateLocale}
              message={problem}
            />
          )}
          {failure && (
            <WriteFailureRow
              failure={failure}
              failedMessage={t.contactCreateFailed}
              labels={t}
              retrying={busy}
              onRetry={retry}
            />
          )}
        </div>
      )}
    </>
  );
}

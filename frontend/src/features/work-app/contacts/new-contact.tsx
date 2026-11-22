import { useEffect, useEffectEvent, useReducer, useRef } from "react";
import type { WorkLabels } from "../shared/labels";
import { titleProblem } from "../shared/fields";
import { keyFor, type PendingKey } from "../../mcp-apps/idempotency";
import { PlusIcon } from "../../mcp-apps/ui/icons";
import { CreateField } from "../../mcp-apps/ui/create-field";
import { ErrorNotice } from "../../mcp-apps/ui/states";
import { WriteFailureRow } from "../shared/write-failure-row";
import { useSingleFlight } from "../shared/use-single-flight";
import { hierarchyDetailLabelsFor } from "../hierarchy/hierarchy-detail-labels";
import {
  writeFailure,
  type WorkContactRecord,
  type WorkTransport,
} from "../transport/transport";
import { contactsRoomLabelsFor } from "./contacts-room-labels";
import {
  initialNewContactState,
  newContactReducer,
  withSameName,
  type CreateRequest,
  type HeadPlus,
} from "./new-contact-state";

/**
 * `newContact` behind + in the room head (design system §3, Create): + (its own, or the room head's in a wide frame:
 * `head`) opens the shared create field under the head,
 * and a new Contact needs only its name. The same name sends one key, so a retry after a lost answer replays the result
 * instead of creating a second Contact. The created Contact is handed to the parent, which opens it. Esc and × close
 * the field and return the focus to +. A name another Contact already has is not created at once: the field says so and offers
 * to open that Contact or to create anyway (two people may share a name). A request marked `immediate` skips the typing:
 * the name is created at once, and the field opens only for that question or for a failure.
 */
export function NewContact({
  transport,
  labels: t,
  request,
  head,
  onCreated,
  onOpenExisting,
}: {
  transport: WorkTransport;
  labels: WorkLabels;
  /** Opens the field with this name in it (a search with no match); a new request opens it again. */
  request?: CreateRequest;
  /** The room head's + in a wide frame: no button of its own is drawn. */
  head?: HeadPlus;
  onCreated: (contact: WorkContactRecord) => void;
  /** Opens a Contact that already has the typed name. */
  onOpenExisting: (id: string, name: string) => void;
}) {
  const [state, dispatch] = useReducer(
    newContactReducer,
    request,
    initialNewContactState,
  );
  const {
    open,
    prefill,
    fieldKey,
    problem,
    busy,
    failure,
    sameName,
    takenName,
  } = state;
  const ownButton = useRef<HTMLButtonElement>(null);
  const openButton = head?.button ?? ownButton;
  const box = useRef<HTMLDivElement>(null);
  const lastName = useRef("");
  // Synchronous guard against a second create before React re-renders.
  const flight = useSingleFlight();
  // The key of each name whose delivery is not settled: the same name again reuses its own key.
  const pendingWrite = useRef(new Map<string, PendingKey>());
  // What the create field holds now: a retry that succeeds empties it only if it still holds the retried name.
  const draft = useRef("");
  const mounted = useRef(true);
  const dl = hierarchyDetailLabelsFor(t.dateLocale);
  const words = contactsRoomLabelsFor(t.dateLocale);
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

  // An immediate request (a search with no match, "Create contact ”X”") creates at once through the same checks and
  // key as the field does; the request mounted with is not one to start.
  const startedRequest = useRef(request);
  const createNow = useEffectEvent((name: string) => void submit(name));
  useEffect(() => {
    if (!request?.immediate || startedRequest.current === request) return;
    startedRequest.current = request;
    createNow(request.name);
  }, [request]);

  // The head's + toggles the field; its key opens it, and an open field takes the focus.
  const seenPress = useRef(head?.press);
  const pressed = useEffectEvent((press: NonNullable<HeadPlus["press"]>) => {
    if (!open) dispatch({ type: "opened" });
    else if (press.key) box.current?.querySelector("input")?.focus();
    else close();
  });
  useEffect(() => {
    const press = head?.press;
    if (!press || press === seenPress.current) return;
    seenPress.current = press;
    pressed(press);
  }, [head?.press]);
  const tellOpen = useEffectEvent((now: boolean) => head?.onOpenChange(now));
  useEffect(() => tellOpen(open), [open]);

  function retry() {
    const name = lastName.current;
    // The name was checked before the first send: a lost answer is replayed, not warned about.
    void submit(name, true).then((created) => {
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
  /**
   * true when the Contact was created; false when the write was refused or failed, or the name is taken (the create
   * field keeps the name). `confirmed`: the user has seen the same-name warning and chose to create anyway.
   */
  async function submit(name: string, confirmed = false): Promise<boolean> {
    if (flight.isRunning()) return false;
    lastName.current = name;
    if (titleProblem(name) === "tooLong") {
      dispatch({ type: "problem", text: t.nameTooLong });
      return false;
    }
    flight.enter();
    dispatch({ type: "submitStarted" });
    try {
      if (!confirmed) {
        // The check is a convenience: when it cannot be read the Contact is created as before.
        const taken = await Promise.resolve()
          .then(() =>
            transport.listContacts({ q: name.trim(), includeArchived: false }),
          )
          .then((page) => withSameName(name, page.items))
          .catch(() => []);
        if (taken.length > 0) {
          if (mounted.current)
            dispatch({ type: "sameNameFound", name, contacts: taken });
          return false;
        }
      }
      return await create(name);
    } finally {
      flight.leave();
      if (mounted.current) dispatch({ type: "submitSettled" });
    }
  }
  /** Sends the create under the key of this name; the caller holds the flight. */
  function create(name: string): Promise<boolean> {
    const pendingKey = keyFor(
      pendingWrite.current.get(name),
      JSON.stringify([name]),
    );
    pendingWrite.current.set(name, pendingKey);
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
      });
  }

  return (
    <>
      {!head && (
        <button
          ref={ownButton}
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
      )}
      {open && (
        <div
          ref={box}
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
          {sameName.length > 0 && (
            <div role="status" className="work-contacts-same-name">
              <p>{words.sameName(takenName.trim())}</p>
              {sameName.map((contact) => (
                <button
                  key={contact.id}
                  type="button"
                  className="sk-btn--secondary sk-btn--compact"
                  onClick={() =>
                    onOpenExisting(contact.id, contact.display_name)
                  }
                >
                  {words.openExisting(
                    [contact.display_name, contact.role, contact.organization]
                      .filter(Boolean)
                      .join(" · "),
                  )}
                </button>
              ))}
              <button
                type="button"
                className="sk-btn--secondary sk-btn--compact"
                disabled={busy}
                onClick={() => {
                  const name = lastName.current;
                  void submit(name, true).then((created) => {
                    if (
                      created &&
                      mounted.current &&
                      draft.current.trim() === name.trim()
                    ) {
                      draft.current = "";
                      dispatch({ type: "emptied" });
                    }
                  });
                }}
              >
                {words.createAnyway}
              </button>
            </div>
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

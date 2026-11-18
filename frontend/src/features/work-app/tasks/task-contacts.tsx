import { useEffect, useRef, useState } from "react";
import type { WorkLabels } from "../shared/labels";
import { keyFor, type PendingKey } from "../../mcp-apps/idempotency";
import { useSingleFlight } from "../shared/use-single-flight";
import { useWorkWrite } from "../shared/use-work-write";
import { PlusIcon } from "../../mcp-apps/ui/icons";
import { WriteFailureRow } from "../shared/write-failure-row";
import {
  writeFailure,
  type WorkContact,
  type WorkTransport,
  type WriteFailure,
} from "../transport/transport";
import {
  ContactHit,
  ContactSearchSheet,
  useContactSearch,
} from "./contact-search";
import "./task-contacts.css";

/** The busy marker of the `createContact` row; a Contact id is never this. */
const CREATE_ROW = "create";

/** A refused write and what it was, so the calm line names it. */
type Failed = { failure: WriteFailure; action: "link" | "create" };

/** A write refused with a notice; retry runs the same action again with the same key. */
function ContactFailure({
  failure,
  message,
  labels: t,
  onReload,
  onRetry,
}: {
  failure: WriteFailure;
  /** The line for a failed write; `retry` is the notice's own button. */
  message: string;
  labels: WorkLabels;
  onReload: () => void;
  onRetry: () => void;
}) {
  const banner = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (failure === "conflict") banner.current?.focus();
  }, [failure]);
  if (failure === "conflict")
    return (
      <div role="alert" tabIndex={-1} ref={banner} className="work-banner">
        <p>{t.contactConflict}</p>
        <button type="button" onClick={onReload}>
          {t.reload}
        </button>
      </div>
    );
  return (
    <WriteFailureRow
      failure={failure}
      failedMessage={message}
      labels={t}
      onRetry={onRetry}
    />
  );
}

/**
 * `linkContact` opens a search sheet over the owner's Contacts for the Task. The sheet sticks to the foot of the
 * visible window above the host's reply field (and the on-screen keyboard, which shrinks that window), with the field
 * at its foot and the hits growing upwards over it, so what is typed and what it finds are always in view. Each
 * change of the query starts a debounced search, and an answer to an older query is ignored. A hit that is not linked
 * yet links on a tap; a linked hit is shown, not offered. When nothing matches, `createContact` with the typed name creates the
 * Contact with that name and links it. After a link the parent reads the contact list again. Esc and × close the
 * sheet and return the focus to `linkContact`.
 */
export function LinkContact({
  taskId,
  transport,
  labels: t,
  linkedIds,
  createOffered,
  onChanged,
}: {
  taskId: string;
  transport: WorkTransport;
  labels: WorkLabels;
  linkedIds: readonly string[];
  /** Whether the host answers create_contact; without it a search with no hit offers no create row. */
  createOffered: boolean;
  onChanged: () => void;
}) {
  const search = useContactSearch(transport);
  const [busyId, setBusyId] = useState<string>();
  const [failed, setFailed] = useState<Failed>();
  // Closed, the section shows one quiet `linkContact` line; opening it puts the focus in the search.
  const [open, setOpen] = useState(false);
  const inputElement = useRef<HTMLInputElement>(null);
  const addButton = useRef<HTMLButtonElement>(null);
  // Set by a close, so the focus goes back to `linkContact` and not on the first render.
  const returnFocus = useRef(false);
  // The last write, run again by Försök igen with the same key.
  const again = useRef<() => void>(undefined);
  // A Contact created here whose link has not gone through yet: a retry links it instead of creating a second one.
  const created = useRef<{ name: string; contact: WorkContact }>(undefined);
  // One link or create at a time, claimed before React re-renders.
  const writes = useSingleFlight();
  const pending = useRef(new Map<string, PendingKey>());
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    if (open) inputElement.current?.focus();
    else if (returnFocus.current) {
      returnFocus.current = false;
      addButton.current?.focus();
    }
  }, [open]);

  function changeQuery(value: string) {
    setFailed(undefined);
    search.change(value);
  }

  function link(contact: WorkContact) {
    if (!writes.enter()) return;
    again.current = () => link(contact);
    const signature = JSON.stringify(["link", taskId, contact.id]);
    const pendingKey = keyFor(pending.current.get(contact.id), signature);
    pending.current.set(contact.id, pendingKey);
    setBusyId(contact.id);
    setFailed(undefined);
    transport
      .linkContactToTask(taskId, contact.id, pendingKey.key)
      .then(() => {
        pending.current.delete(contact.id);
        created.current = undefined;
        if (mounted.current) onChanged();
      })
      .catch((error: unknown) => {
        if (mounted.current)
          setFailed({ failure: writeFailure(error), action: "link" });
      })
      .finally(() => {
        writes.leave();
        if (mounted.current) setBusyId(undefined);
      });
  }

  function createAndLink(name: string) {
    if (writes.isRunning()) return;
    if (created.current?.name === name) {
      link(created.current.contact);
      return;
    }
    again.current = () => createAndLink(name);
    const signature = JSON.stringify(["create", name]);
    const pendingKey = keyFor(pending.current.get(signature), signature);
    pending.current.set(signature, pendingKey);
    writes.enter();
    setBusyId(CREATE_ROW);
    setFailed(undefined);
    transport.createContact({ display_name: name }, pendingKey.key).then(
      ({ contact }) => {
        pending.current.delete(signature);
        created.current = { name, contact };
        writes.leave();
        // Linked even when the view has gone meanwhile, so the new Contact does not end up unlinked.
        link(contact);
      },
      (error: unknown) => {
        writes.leave();
        if (!mounted.current) return;
        setBusyId(undefined);
        setFailed({ failure: writeFailure(error), action: "create" });
      },
    );
  }

  function close() {
    if (writes.isRunning()) return;
    // Closing drops the search, so the next opening starts clean.
    changeQuery("");
    returnFocus.current = true;
    setOpen(false);
  }

  if (!open)
    return (
      <div>
        <button
          ref={addButton}
          type="button"
          className="work-add-row sk-action-row"
          onClick={() => setOpen(true)}
        >
          <PlusIcon />
          {t.linkContact}
        </button>
      </div>
    );
  const linked = new Set(linkedIds);
  const busy = busyId !== undefined;
  return (
    <ContactSearchSheet
      title={t.linkContact}
      labels={t}
      search={search}
      busy={busy}
      inputRef={inputElement}
      onClose={close}
      renderHit={(contact) => (
        <ContactHit
          contact={contact}
          note={linked.has(contact.id) ? t.contactAlreadyLinked : undefined}
          disabled={busy}
          busy={busyId === contact.id}
          onPick={() => link(contact)}
        />
      )}
      empty={(q) =>
        createOffered && (
          <button
            type="button"
            className="sk-action-row work-contact-sheet-create"
            disabled={busy}
            aria-busy={busyId === CREATE_ROW || undefined}
            onClick={() => createAndLink(q)}
          >
            <PlusIcon />
            {t.createAndLinkContact(q)}
          </button>
        )
      }
      footer={
        failed && (
          <ContactFailure
            failure={failed.failure}
            message={
              failed.action === "create"
                ? t.contactCreateFailed
                : t.contactWriteFailed
            }
            labels={t}
            onReload={onChanged}
            onRetry={() => again.current?.()}
          />
        )
      }
    />
  );
}

/**
 * `removeLink` from a detail view's ⋯ (design system §3, Tillbakarad and Ångra): one entry per link, no
 * confirmation. The row stays where it was with `linkRemoved` and Ångra (the agenda's UndoMeta) while Ångra
 * holds; then it leaves (`hidden`). Ångra links it back. `send` writes the link (`link` true) or removes it, with the
 * action's idempotency key.
 */
export function useLinkUndo(
  send: (id: string, link: boolean, key: string) => Promise<unknown>,
) {
  const write = useWorkWrite();
  // "gone": removed, Ångra offered; "hidden": removed and the time to undo is up.
  const [state, setState] = useState<
    Record<string, "gone" | "hidden" | undefined>
  >({});
  const again = useRef<() => void>(undefined);
  function set(id: string, link: boolean) {
    again.current = () => set(id, link);
    void write
      .run(JSON.stringify([id, link]), (key) => send(id, link, key))
      .then((done) => {
        if (done !== undefined)
          setState((all) => ({ ...all, [id]: link ? undefined : "gone" }));
      });
  }
  return {
    ...write,
    state,
    set,
    expire: (id: string) => setState((all) => ({ ...all, [id]: "hidden" })),
    retry: () => again.current?.(),
  };
}

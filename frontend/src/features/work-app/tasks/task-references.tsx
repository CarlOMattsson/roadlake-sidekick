import { useCallback, useEffect, useRef, useState } from "react";
import { workDate } from "../../mcp-apps/ui/due";
import { useToolSupport } from "../../mcp-apps/tool-support";
import { knownLabel, type WorkLabels } from "../shared/labels";
import { linksLabelsFor } from "../shared/links-labels";
import { manageLabelsFor } from "../shared/manage-labels";
import { UndoLine, WriteNotice, focusUndoIn } from "../shared/manage-controls";
import { useSingleFlight } from "../shared/use-single-flight";
import { useWorkWrite } from "../shared/use-work-write";
import type {
  WorkExternalReference,
  WorkTransport,
} from "../transport/transport";

export type TaskReferencesProps = {
  taskId: string;
  transport: WorkTransport;
  labels: WorkLabels;
};

type MorePhase = "idle" | "busy" | "failed";

/** The date a pointer names, in the work date form, as a part of the meta line; undefined when there is none or it is unreadable. */
function shortDate(value: string | null, locale: string): string | undefined {
  return workDate(value, new Date(), locale, { inline: true }) || undefined;
}

/**
 * The external pointers on a Task (mail, calendar event, document) under "Underlag". Titles are shown as
 * plain text: they come from another service. Only the pointer is removed, with a visible Undo; focus
 * goes to that Undo, and after Undo back to the restored row. Nothing is shown while the list is empty,
 * cannot be read, or is forbidden, unless an Undo is pending.
 */
export function TaskReferences({
  taskId,
  transport,
  labels: t,
}: TaskReferencesProps) {
  const write = useWorkWrite();
  // One "Show more" page per read generation, claimed before React re-renders the button.
  const pages = useSingleFlight();
  // Removing a pointer needs the unlink and, for its Undo, the link tool; a host without them shows the pointers only.
  const offers = useToolSupport(transport);
  const removable =
    offers("unlink_external_reference_from_task") &&
    offers("link_external_reference_to_task");
  const [items, setItems] = useState<WorkExternalReference[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [more, setMore] = useState<MorePhase>("idle");
  const [removed, setRemoved] = useState<WorkExternalReference>();
  const heading = useRef<HTMLHeadingElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const undoBox = useRef<HTMLDivElement>(null);
  // Focus after the next render: the Undo button after a removal.
  const focusUndo = useRef(false);
  // The pointer an Undo brings back: its id and title, and the place it had, for the focus after the re-read.
  const removedAt = useRef(0);
  const restoredAt = useRef<
    { id: string; title: string; index: number } | undefined
  >(undefined);
  // Bumped by every read and every removal; an answer to an older read or page is ignored.
  const ticket = useRef(0);
  // Runs the last write again; a failed write keeps its key, so the server replays it instead of writing twice.
  const again = useRef<(() => void) | undefined>(undefined);
  const mounted = useRef(true);
  const manage = manageLabelsFor(t.dateLocale);
  const links = linksLabelsFor(t.dateLocale);

  // Called from the mount effect too, so it sets no state itself; a caller that cancels a page resets `more`.
  const readFirstPage = useCallback(() => {
    const current = ++ticket.current;
    transport
      .listTaskExternalReferences(taskId)
      .then((page) => {
        if (current !== ticket.current) return;
        setItems(page.items);
        setNextCursor(page.next_cursor);
      })
      .catch(() => {
        if (current !== ticket.current) return;
        setItems([]);
        setNextCursor(null);
      });
  }, [transport, taskId]);

  useEffect(() => {
    mounted.current = true;
    const marker = ticket;
    readFirstPage();
    return () => {
      mounted.current = false;
      marker.current++;
    };
  }, [readFirstPage]);
  useEffect(() => {
    if (removed && focusUndo.current) {
      focusUndo.current = false;
      focusUndoIn(undoBox.current);
    }
  }, [removed]);
  useEffect(() => {
    // The list has been read again after an Undo: focus goes to the restored row, else to the row
    // that stands where it was, else to the heading.
    const wish = restoredAt.current;
    if (!wish) return;
    restoredAt.current = undefined;
    const target =
      items.find((item) => item.id === wish.id) ??
      items.find((item) => item.title === wish.title) ??
      items[wish.index];
    if (!target) {
      heading.current?.focus();
      return;
    }
    Array.from(
      list.current?.querySelectorAll<HTMLButtonElement>(
        "button[data-reference]",
      ) ?? [],
    )
      .find((button) => button.dataset.reference === target.id)
      ?.focus();
  }, [items]);

  function loadMore() {
    const current = ticket.current;
    if (!nextCursor || !pages.enter(current)) return;
    setMore("busy");
    transport
      .listTaskExternalReferences(taskId, nextCursor)
      .then((page) => {
        if (current !== ticket.current) return;
        setItems((known) => {
          const seen = new Set(known.map((item) => item.id));
          return [...known, ...page.items.filter((item) => !seen.has(item.id))];
        });
        setNextCursor(page.next_cursor);
        setMore("idle");
      })
      .catch(() => {
        if (current === ticket.current) setMore("failed");
      })
      .finally(() => pages.leave(current));
  }

  function remove(reference: WorkExternalReference) {
    again.current = () => remove(reference);
    const signature = JSON.stringify([
      "unlink-reference",
      taskId,
      reference.id,
    ]);
    const index = items.findIndex((item) => item.id === reference.id);
    void write
      .run(signature, (key) =>
        transport.unlinkExternalReferenceFromTask(taskId, reference.id, key),
      )
      .then((done) => {
        if (done === undefined || !mounted.current) return;
        // A page still in flight may hold the pointer just removed; its answer is dropped.
        ticket.current++;
        removedAt.current = index;
        setMore("idle");
        setItems((known) => known.filter((item) => item.id !== reference.id));
        setRemoved(reference);
        focusUndo.current = true;
      });
  }

  function undo(reference: WorkExternalReference) {
    again.current = () => undo(reference);
    const signature = JSON.stringify([
      "relink-reference",
      taskId,
      reference.id,
    ]);
    void write
      .run(signature, (key) =>
        transport.linkExternalReferenceToTask(taskId, reference, key),
      )
      .then((done) => {
        if (done === undefined || !mounted.current) return;
        // The pointer may have come back under a new id, so the list is read again instead of patched.
        restoredAt.current = {
          id: reference.id,
          title: reference.title,
          index: removedAt.current,
        };
        setRemoved(undefined);
        setMore("idle");
        readFirstPage();
      });
  }

  const visible = items.length > 0 || removed !== undefined;
  if (!visible) return null;
  return (
    <>
      <h3 ref={heading} tabIndex={-1}>
        {links.references}
      </h3>
      {items.length > 0 && (
        <>
          <ul className="work-list" ref={list}>
            {items.map((reference) => {
              const meta = [
                knownLabel(links.kind, reference.kind),
                shortDate(reference.occurs_at, t.dateLocale),
              ]
                .filter(Boolean)
                .join(" · ");
              return (
                <li key={reference.id}>
                  <span>{reference.title}</span>
                  <p>{meta}</p>
                  {removable && (
                    <div className="work-manage-controls">
                      <button
                        type="button"
                        className="work-link-remove"
                        data-reference={reference.id}
                        aria-label={links.removeReferenceFor(reference.title)}
                        disabled={write.busy}
                        onClick={() => remove(reference)}
                      >
                        {manage.removeLink}
                      </button>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
          {removable && <p>{links.keptNote}</p>}
        </>
      )}
      <WriteNotice
        failure={write.failure}
        labels={manage}
        onReload={() => {
          write.clear();
          setMore("idle");
          readFirstPage();
        }}
        onRetry={() => again.current?.()}
      />
      {more === "busy" && <p role="status">{links.loading}</p>}
      {more === "failed" && <p role="alert">{links.readMoreFailed}</p>}
      {nextCursor && (
        <button type="button" disabled={more === "busy"} onClick={loadMore}>
          {links.more}
        </button>
      )}
      {removed && (
        <div ref={undoBox}>
          <UndoLine
            text={links.referenceUnlinked(removed.title)}
            disabled={write.busy}
            labels={manage}
            onUndo={() => undo(removed)}
          />
        </div>
      )}
    </>
  );
}

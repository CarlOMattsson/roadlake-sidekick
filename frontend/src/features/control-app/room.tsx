/**
 * The Control room (room contract: mcp-apps/room-types.ts). It owns the card's state and renders the
 * Control card. Every read and write goes through `props.transport`; the room knows nothing about the
 * host bridge. The entry mounts it with the newest tool result. A room mounted hidden has no result and
 * opens on the view `props.view` names (trash when none), reading it for itself, and it does not count an answer that
 * never came.
 */
import { useMemo, useState } from "react";
import type { RoomProps, RoomTransport } from "../mcp-apps/room-types";
import { appLocale } from "../mcp-apps/app-locale";
import { ErrorNotice, toolResultCause } from "../mcp-apps/ui/states";
import {
  ControlApp,
  controlViewNamed,
  viewOf,
  type ControlData,
  type ControlViewName,
} from "./control-app";
import { controlLabels, type ControlLabels } from "./labels";
import type {
  ActivityList,
  ChangesList,
  ControlTransport,
  MemoryStatus,
  RecallRequest,
  RecallResult,
  RecalledFact,
  TrashList,
} from "./transport";

/** The reads and writes of the card, each one an existing tool called through the room's transport. */
function createControlTransport(
  call: RoomTransport["call"],
  supportsTool?: RoomTransport["supportsTool"],
): ControlTransport {
  // The memory sample and "Forget" are offered only together, and only where the host has both tools.
  const memoryTools =
    supportsTool?.("recall_memory") !== false &&
    supportsTool?.("exclude_from_memory") !== false;
  return {
    trash: (cursor) =>
      call<TrashList>("list_trash", cursor === undefined ? {} : { cursor }),
    restore: (item, key) =>
      call("restore_from_trash", {
        kind: item.kind,
        record_id: item.id,
        version: item.version,
        idempotency_key: key,
      }),
    changes: () => call<ChangesList>("list_recent_changes", { limit: 20 }),
    undoPurchase: (change, key) =>
      call("set_shopping_item_purchased", {
        item_id: change.id,
        // The opposite of what the change did: a purchase is put back, a put-back is bought again.
        purchased: change.action !== "purchased",
        version: change.version,
        idempotency_key: key,
      }),
    memoryStatus: () => call<MemoryStatus>("get_memory_status", {}),
    activity: () =>
      call<ActivityList>("list_assistant_activity", { limit: 25 }),
    ...(memoryTools
      ? {
          recall: (request: RecallRequest) =>
            call<RecallResult>("recall_memory", {
              query: request.query,
              ...(request.kind === undefined ? {} : { kinds: [request.kind] }),
            }),
          forget: (fact: RecalledFact) =>
            call("exclude_from_memory", {
              kind: fact.source.kind,
              id: fact.source.id,
              excluded: true,
            }),
        }
      : {}),
    setMemory: (change) =>
      call("set_memory_settings", {
        expected_version: change.expectedVersion,
        ...(change.paused === undefined ? {} : { paused: change.paused }),
        ...(change.domain === undefined || change.value === undefined
          ? {}
          : { [change.domain]: change.value }),
        ...(change.confirm === true ? { confirm: true } : {}),
      }),
  };
}

/** What the room shows: the card of the newest result, or the failure notice. */
type Shown = {
  /** Set when the first answer is an error: the card shows the shared error notice until Try again. */
  failed: boolean;
  /** What the newest tool result delivered. The other views are read when the owner chooses them. */
  known: ControlData;
  /** The view the newest result opened; the card starts there. */
  current: ControlViewName;
  /** A new result remounts the card, so it shows that result and not what an earlier card held. */
  revision: number;
  /** What the last failed Try again threw, so the notice names the connection only when it may be that. */
  cause?: unknown;
};

/** Nothing has been shown yet: the room starts at the view it was opened on (trash when none is named). */
function nothingShown(view: string | undefined): Shown {
  return {
    failed: false,
    known: {},
    current: controlViewNamed(view) ?? "trash",
    revision: 0,
  };
}

/**
 * The room's state after one tool result. A result that is an error, or not a Control answer, is not
 * for this app: it keeps the card, or shows the failure notice when there is no card yet.
 */
function afterResult(
  prev: Shown,
  initial: unknown,
  initialError: boolean,
): Shown {
  const found = initialError ? undefined : viewOf(initial);
  if (!found) {
    // An error answer for the first call leaves nothing to show; later errors keep the card.
    return {
      ...prev,
      failed: Object.keys(prev.known).length === 0,
      // The error answer's own fields, so the notice says whether Sidekick answered (its closed code) or not.
      ...(initialError ? { cause: toolResultCause(initial) } : {}),
    };
  }
  return {
    failed: false,
    known: found.view === "history" ? found.data : { [found.view]: found.data },
    current: found.view,
    revision: prev.revision + 1,
  };
}

/** The one read error card of Control: the app's name above the shared notice, Try again when a re-read exists. */
function errorCard(
  labels: ControlLabels,
  titled: boolean,
  view: ControlViewName,
  onRetry?: () => void,
  cause?: unknown,
) {
  return (
    <section className="sidekick-control" aria-label={labels.title}>
      <div className="control-card sk-card">
        {titled ? (
          <p className="sk-eyebrow">{labels.title}</p>
        ) : (
          // Fullscreen: the title under the shell's "‹ Arbete", as the loaded view.
          <h2 className="control-title">{labels.title}</h2>
        )}
        <ErrorNotice
          locale={labels.locale}
          subject={`control:${view}`}
          cause={cause}
          onRetry={onRetry}
        />
      </div>
    </section>
  );
}

export function ControlRoom(props: RoomProps) {
  const { initial, initialError, resultId } = props;
  // Without any of the three the room is mounted hidden: no answer came, so none is counted.
  const hasResult =
    initial !== undefined ||
    initialError !== undefined ||
    resultId !== undefined;
  const [seen, setSeen] = useState({ initial, initialError, resultId });
  const [shown, setShown] = useState<Shown>(() =>
    hasResult
      ? afterResult(nothingShown(props.view), initial, initialError === true)
      : nothingShown(props.view),
  );
  // A changed resultId, initial or initialError is a new result (room-types). Derived during render, not in an effect.
  if (
    initial !== seen.initial ||
    initialError !== seen.initialError ||
    resultId !== seen.resultId
  ) {
    setSeen({ initial, initialError, resultId });
    if (hasResult)
      setShown((prev) => afterResult(prev, initial, initialError === true));
  }

  const transport = useMemo(
    () =>
      createControlTransport(
        props.transport.call,
        props.transport.supportsTool,
      ),
    [props.transport.call, props.transport.supportsTool],
  );
  // Set while Try again reads the view again, so a second press does not start another read.
  const [retrying, setRetrying] = useState(false);
  const labels = controlLabels[appLocale()];

  function retry() {
    if (retrying) return;
    setRetrying(true);
    // The error answer does not name its tool, so Try again reads the view the card is on (trash at first).
    const name = shown.current;
    const read: Promise<ControlData> =
      name === "trash"
        ? transport.trash().then((trash) => ({ trash }))
        : name === "memory"
          ? transport.memoryStatus().then((memory) => ({ memory }))
          : Promise.allSettled([
              transport.changes(),
              transport.activity(),
            ]).then(([changes, activity]) => {
              // Either part is enough; only both failing is a failure.
              if (
                changes.status === "rejected" &&
                activity.status === "rejected"
              )
                throw changes.reason;
              return {
                ...(changes.status === "fulfilled"
                  ? { changes: changes.value }
                  : {}),
                ...(activity.status === "fulfilled"
                  ? { activity: activity.value }
                  : {}),
              };
            });
    // A tool result that came while this read was on its way is newer: it keeps the card, and this answer is dropped.
    const asked = shown.revision;
    read
      .then((fresh) => {
        setRetrying(false);
        setShown((prev) =>
          prev.revision === asked
            ? {
                ...prev,
                failed: false,
                known: fresh,
                revision: prev.revision + 1,
              }
            : prev,
        );
      })
      .catch((cause: unknown) => {
        setRetrying(false);
        setShown((prev) =>
          prev.revision === asked ? { ...prev, cause } : prev,
        );
      });
  }

  // Inline the card names itself in its kicker; the full view names it with the title "Kontroll" under the shell's
  // Back ("‹ Arbete"), since Control is a step of the room it was opened from.
  const titled = props.mode === "inline";
  if (shown.failed)
    return errorCard(labels, titled, shown.current, retry, shown.cause);
  return (
    <ControlApp
      key={shown.revision}
      transport={transport}
      labels={labels}
      titled={titled}
      heading={!titled}
      initialView={shown.current}
      initialData={shown.known}
      refreshKey={props.refreshKey}
      sendMessage={props.sendMessage}
      onModelContext={(sentence) =>
        void props.transport.updateModelContext(sentence)
      }
      onOpen={props.onNavigate}
    />
  );
}

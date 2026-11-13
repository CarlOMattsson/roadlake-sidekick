import { useEffect, useMemo, useState } from "react";
import type { RoomProps, RoomTransport } from "../mcp-apps/room-types";
import { appLocale } from "../mcp-apps/app-locale";
import { roomEnabled } from "../mcp-apps/enabled-rooms";
import { AppFrame } from "../mcp-apps/ui/layout";
import { ErrorNotice, toolResultCause } from "../mcp-apps/ui/states";
import { toolOffered } from "../mcp-apps/tool-support";
import { BatchCard, batchSummary, type BatchSummary } from "./batch-card";
import { shoppingEn, shoppingSv } from "./labels";
import { ShoppingCard } from "./shopping-card";
import { ShoppingView } from "./shopping-view";
import {
  localDay,
  type ShoppingDetail,
  type ShoppingItem,
  type ShoppingTransport,
} from "./transport";

/** The shopping room: all state and rendering of the Sidekick shopping app. The entry only mounts it. */

/** Every read and write goes through the host's tools/call; the room holds no credential and no URL. */
function createShoppingTransport(
  call: RoomTransport["call"],
  searchContacts: boolean,
  offline?: RoomTransport["offline"],
): ShoppingTransport {
  return {
    ...(offline ? { offline } : {}),
    // A host without list_contacts (the mobile app) gets no recipient search.
    ...(searchContacts
      ? { contacts: (q: string) => call("list_contacts", { q, limit: 25 }) }
      : {}),
    lists: (offset) =>
      call("list_shopping_lists", {
        include_archived: true,
        limit: 50,
        offset,
      }),
    get: (id, offset, store) =>
      call("get_shopping_list", {
        list_id: id,
        on_date: localDay(),
        limit: 100,
        offset,
        ...(store ? { store } : {}),
      }),
    create: (name, key) =>
      call("create_shopping_list", { name, idempotency_key: key }),
    rename: (list, name, archived, key) =>
      call("update_shopping_list", {
        list_id: list.id,
        name,
        archived,
        version: list.version,
        idempotency_key: key,
      }),
    add: (id, names, key, options) =>
      call("add_shopping_items", {
        list_id: id,
        items: names.map((name, index) => ({
          name,
          client_ref: String(index),
          ...(options?.store ? { store: options.store } : {}),
        })),
        merge_duplicates: options?.mergeDuplicates === true,
        idempotency_key: key,
      }),
    update: (item, input, key) =>
      call("update_shopping_item", {
        item_id: item.id,
        item: input,
        version: item.version,
        idempotency_key: key,
      }),
    purchase: (item, key) =>
      call<{ item: ShoppingItem }>("set_shopping_item_purchased", {
        item_id: item.id,
        purchased: !item.purchased,
        version: item.version,
        idempotency_key: key,
      }),
  };
}

/**
 * What the room shows. `seen*` are the result props this state was derived from: a changed resultId,
 * initial or initialError is a new result, and the state is derived again from the previous one.
 */
type RoomState = {
  seenId?: number;
  seenInitial?: unknown;
  seenError?: boolean;
  /** The last add or update result. It has no shopping_list, so it is not a list detail. */
  batch?: BatchSummary;
  /** Set when the first answer is an error: the list could not be read, so the notice shows, not the empty list. */
  failed: boolean;
  /** The last list detail read from the result that opened the room. */
  detail?: ShoppingDetail;
  /** Bumped on every new result that changes what the view shows; a new revision remounts the view. */
  revision: number;
};

const NO_RESULT: RoomState = { failed: false, revision: 0 };

/** Whether the props carry a result the state has not seen yet. A room mounted hidden carries none. */
function resultChanged(state: RoomState, props: RoomProps): boolean {
  return (
    props.resultId !== state.seenId ||
    props.initial !== state.seenInitial ||
    props.initialError !== state.seenError
  );
}

/** The state after a new result. A pure function of the previous state and the result. */
function applyResult(
  prev: RoomState,
  props: Pick<RoomProps, "initial" | "initialError" | "resultId">,
): RoomState {
  const isError = props.initialError === true;
  const seen = {
    seenId: props.resultId,
    seenInitial: props.initial,
    seenError: props.initialError,
  };
  const hadBatch = prev.batch !== undefined;
  const batch = isError ? undefined : batchSummary(props.initial);
  // An error before any list was read: the list could not be read, so the notice shows.
  const failed = isError && prev.detail === undefined && !hadBatch;
  if (failed) return { ...prev, ...seen, batch, failed: true };
  // A new revision remounts a fullscreen view, which then reloads the list instead of showing a stale one.
  if (batch)
    return {
      ...prev,
      ...seen,
      batch,
      failed: false,
      revision: prev.revision + 1,
    };
  const data = props.initial as ShoppingDetail | undefined;
  // A newer result for the same list or shop replaces the old one too: the view then opens on it and
  // reads nothing, instead of showing the list as it was.
  if (data?.shopping_list?.id && Array.isArray(data.items) && !isError) {
    return {
      ...prev,
      ...seen,
      batch,
      failed: false,
      detail: data,
      revision: prev.revision + 1,
    };
  }
  return { ...prev, ...seen, batch, failed: false };
}

/** A result with the rows this room has confirmed at a newer version than the result carries. */
function newerRows(
  data: ShoppingDetail | undefined,
  own: ReadonlyMap<string, ShoppingItem>,
): ShoppingDetail | undefined {
  if (!data || own.size === 0) return data;
  let changed = false;
  const items = data.items.map((item) => {
    const mine = own.get(item.id);
    if (!mine || mine.version <= item.version) return item;
    changed = true;
    return mine;
  });
  return changed ? { ...data, items } : data;
}

/** The state when the room mounts: from the first result, or none when it is mounted hidden. */
function startState(props: RoomProps): RoomState {
  return resultChanged(NO_RESULT, props)
    ? applyResult(NO_RESULT, props)
    : NO_RESULT;
}

/**
 * Both hosts use the same UI. Inline with fullscreen on offer, the list is a compact card and Open asks
 * the host for fullscreen. Without a result (mounted hidden) the view reads its list through `transport`.
 */
export function ShoppingRoom(props: RoomProps) {
  const [state, setState] = useState(() => startState(props));
  // The rows the view confirmed with a write. A later result for the same list never takes a row back to an older
  // version, also though the view is mounted again for it (the rows are told apart by id, so another list is not held).
  const [written] = useState(() => new Map<string, ShoppingItem>());
  // Raised when a reply is stored in `written`: a view mounted since the write then takes the row from it.
  const [writtenTick, setWrittenTick] = useState(0);
  // A new result re-roots the room. It is derived during render, not in an effect, as WorkView does.
  if (resultChanged(state, props)) {
    setState(applyResult(state, props));
  }
  // The recipient search needs the Contact room on, and a host that offers its tool.
  const searchContacts =
    roomEnabled("contacts") && toolOffered(props.transport, "list_contacts");
  const api = useMemo(
    () =>
      createShoppingTransport(
        props.transport.call,
        searchContacts,
        props.transport.offline,
      ),
    [props.transport.call, searchContacts, props.transport.offline],
  );
  const locale = appLocale();
  const labels = locale.startsWith("sv") ? shoppingSv : shoppingEn;
  const fullscreen = props.mode === "full";
  // Inline with fullscreen on offer: the list is a compact card, and Open asks the host for fullscreen.
  const canOpenFullscreen = props.fullscreenAvailable === true;
  const { batch, failed, detail, revision } = state;
  // An inline card mounted again after a write in the full view (refreshKey above 0) reads its list by id
  // itself, as WorkRoom reads its agenda and board. The result it was given stays on screen until the fresh
  // list arrives, so the card never falls back to the list picker meanwhile.
  const inlineRefresh = !fullscreen && (props.refreshKey ?? 0) > 0;
  const refreshId = inlineRefresh ? detail?.shopping_list.id : undefined;
  const refreshStore = detail?.store ?? undefined;
  useEffect(() => {
    if (refreshId === undefined) return undefined;
    let live = true;
    api
      .get(refreshId, 0, refreshStore)
      .then((fresh) => {
        if (live) setState((prev) => ({ ...prev, detail: fresh }));
      })
      .catch(() => {
        // The card keeps what it shows; the next read corrects it.
      });
    return () => {
      live = false;
    };
  }, [refreshId, refreshStore, api]);
  function requestFullscreen() {
    props.transport.requestDisplayMode("fullscreen").catch(() => undefined);
  }
  /** Try again reads the list again: the view mounts without a list and reads it from the server. */
  function retry() {
    setState((prev) => ({ ...prev, failed: false }));
  }
  if (failed) {
    // The error result as the bridge would throw it (matched by name, with the result's closed code): with Sidekick's
    // code the failure is not the connection, so ErrorNotice leaves out "Check your connection" (§3).
    const notice = (
      <ErrorNotice
        locale={locale}
        onRetry={retry}
        cause={toolResultCause(props.initial)}
      />
    );
    return (
      // In the same frame as the list's card, so it keeps the host's side margin as every inline card does.
      <section
        className={
          fullscreen ? "sidekick-shopping" : "sidekick-shopping shopping-card"
        }
        aria-label={labels.title}
      >
        <AppFrame mode={fullscreen ? "full" : "inline"}>
          {fullscreen ? (
            // Under the room's own chrome (the room strip names the room), as Work shows its read error.
            notice
          ) : (
            <div className="shopping-card-body sk-card">
              <p className="sk-eyebrow">{labels.title}</p>
              {notice}
            </div>
          )}
        </AppFrame>
      </section>
    );
  }
  // An add or update result shows the small card inline; Open asks the host for the full list.
  if (batch && !fullscreen) {
    return (
      <BatchCard
        summary={batch}
        labels={labels}
        onOpen={canOpenFullscreen ? requestFullscreen : undefined}
      />
    );
  }
  // A read with a store filter is the shop view: large rows right in the conversation, no Open step.
  const shop = detail?.store ?? undefined;
  if (detail && canOpenFullscreen && !shop) {
    return (
      <ShoppingCard
        detail={detail}
        labels={labels}
        onOpen={requestFullscreen}
        sendMessage={props.sendMessage}
      />
    );
  }
  // Open after a batch shows the batch's list, selected and read. The last list read is not used
  // then, so the view never shows a stale list while the new one loads.
  const batchList = batch?.listId;
  return (
    <ShoppingView
      key={revision}
      transport={api}
      written={written}
      writtenTick={writtenTick}
      onWritten={() => setWrittenTick((n) => n + 1)}
      initial={
        batchList !== undefined && detail?.shopping_list.id !== batchList
          ? undefined
          : newerRows(detail, written)
      }
      listId={batchList}
      labels={labels}
      fullscreen={fullscreen}
      refreshKey={props.refreshKey}
      store={batchList === undefined ? shop : undefined}
      // Inline, also when fullscreen is on offer: a list chosen from the picker folds to the short card. A shop
      // view and the fullscreen view are not compact.
      compact={!fullscreen && shop === undefined}
      onNavigate={props.onNavigate}
      hostSettings={fullscreen ? props.hostSettings : undefined}
      sendMessage={props.sendMessage}
    />
  );
}

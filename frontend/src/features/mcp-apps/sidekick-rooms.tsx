/**
 * The rooms of the Sidekick app as the shell draws them. The shell speaks ShellRoomProps (an entry to
 * show, `visible`, `refreshKey`, `navigate`, `markDirty`); the five rooms speak the room contract of
 * room-types.ts (a tool result as `initial`, a transport, `onNavigate`, `onDirty`). RoomAdapter is
 * the one thin translation between them, so a room knows nothing about the shell and the shell
 * nothing about a room's state. RoomId has one source, router.ts.
 *
 * What the adapter does for a room:
 * - `initial` is the tool result of the entry, or an id-only result for a cross-link (a Contact, a
 *   Task, an entry reached by id), which the room's own view reads fresh.
 * - A changed `refreshKey` is passed on: a full-view room reads again in place. An inline card is
 *   mounted again without its first result, so it reads its record by id.
 * - Every tool call the room makes passes `dirtyDomains`, so a write marks the other rooms stale.
 * - A fullscreen the host granted (or a room that expands inline) tells the entry through
 *   `RoomHost.onExpand`, so the shell switches to the full view with the strip.
 */
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentType,
} from "react";

import { ControlRoom } from "@/features/control-app/room";
import { JournalRoom } from "@/features/journal-app/room";
import { ShoppingRoom } from "@/features/shopping-app/room";
import { ContactsRoom } from "@/features/work-app/contacts-room";
import { WorkRoom } from "@/features/work-app/room";
import type {
  RoomRegistry,
  ShellRoomProps,
} from "@/features/mcp-apps/sidekick-shell";
import { appLocale } from "@/features/mcp-apps/app-locale";
import { HostToolError } from "@/features/mcp-apps/bridge";
import { sidekickShellLabelsFor } from "@/features/mcp-apps/sidekick-shell-labels";
import { dirtyDomains } from "@/features/mcp-apps/dirty-domains";
import { ROOT_VIEW, type NavEntry } from "@/features/mcp-apps/nav-state";
import { isRoomId, type RoomId } from "@/features/mcp-apps/router";
import type {
  RoomProps,
  RoomTarget,
  RoomTransport,
} from "@/features/mcp-apps/room-types";

/** What the entry offers every room: the host bridge and the host's display-mode facts. */
export type RoomHost = {
  transport: RoomTransport;
  /** True when the host offers fullscreen and the app is not in it. Read at render time. */
  fullscreenAvailable: () => boolean;
  /** A room is now shown in the full view: the host granted fullscreen, or the room expanded inline. */
  onExpand: (target?: NavEntry) => void;
  /** Per room, the views the host can serve. Absent (or a room not listed): every view. */
  availableViews?: Partial<Record<RoomId, readonly string[]>>;
  /**
   * The host's own settings, offered in every room's ⋯ menu in Control's place (RoomProps.hostSettings). `onOpen` is
   * told the room it was opened from, so the settings can lead back there.
   */
  hostSettings?: { label: string; onOpen: (from: RoomId) => void };
};

export const RoomHostContext = createContext<RoomHost | undefined>(undefined);

/** Whether the entry carries a single Journal entry record (a card), and its id. */
function journalEntryId(data: unknown): string | undefined {
  const entry = (data as { entry?: { id?: unknown } } | null | undefined)
    ?.entry;
  return typeof entry?.id === "string" ? entry.id : undefined;
}

/** The id of the record a tool result carries ({task: {id}}, {contact: {id}} ...), for a card's own entry. */
export function idInData(entry: NavEntry): string | undefined {
  const keys: Record<string, string> = {
    "work:task": "task",
    "work:project": "project",
    "work:process": "process",
    "contacts:contact": "contact",
    "contacts:compact": "contact",
    "journal:entry": "entry",
    "journal:card": "entry",
    "journal:draft": "draft",
  };
  const key = keys[`${entry.room}:${entry.view}`];
  if (!key) return undefined;
  const record = (entry.data as Record<string, { id?: unknown } | undefined>)?.[
    key
  ];
  return typeof record?.id === "string" ? record.id : undefined;
}

/**
 * A tool result that names a record by id alone: the room reads the record itself. This is what a
 * cross-link carries. The shapes are the ones the rooms' own parsers already read as id-only roots.
 */
function idOnlyResult(entry: NavEntry): unknown {
  const id = entry.id ?? idInData(entry);
  if (id === undefined) return undefined;
  switch (`${entry.room}:${entry.view}`) {
    case "work:task":
      return { task: { id } };
    case "work:project":
      return { project: { id } };
    case "work:process":
      return { process: { id } };
    case "contacts:contact":
    case "contacts:compact":
      // The room reads the Contact itself; the empty pages make its parser take this as a Contact root.
      return {
        contact: { id },
        projects: { items: [] },
        tasks: { items: [] },
      };
    case "journal:entry":
    case "journal:card":
      return { entry: { id } };
    case "journal:draft":
      return { draft: { id } };
    case "journal:source":
      return { source: { id } };
    default:
      return undefined;
  }
}

/** The trimmed search a Contact list result answered (its q), or "" for the whole list. */
function contactSearch(data: unknown): string {
  const q = (data as { q?: unknown } | null | undefined)?.q;
  return typeof q === "string" ? q.trim() : "";
}

/**
 * The `initial` a room gets for an entry. After a refresh of an inline card the original result is
 * stale and is dropped for an id-only read (a card with no id keeps what it has). A whole Contact list
 * has no id, so a refreshed card drops it too and the room reads the list for itself; a list that
 * answered a search keeps its result, since the room cannot read a search for itself. In the full view a
 * Journal entry card opens the entry view directly (the card's Open has already been pressed, or the
 * host showed the app full); a finalized draft's `notice` is kept, so its entry says what was created.
 */
export function initialFor(
  entry: NavEntry,
  full: boolean,
  refreshed: boolean,
): unknown {
  const fresh = refreshed ? idOnlyResult(entry) : undefined;
  if (fresh !== undefined) return fresh;
  if (
    refreshed &&
    entry.room === "contacts" &&
    entry.view === "list" &&
    contactSearch(entry.data) === ""
  )
    return undefined;
  if (entry.data !== undefined) {
    // In the full view a Contact record is the Contact view with its Tasks and Projects, not a card.
    if (full && entry.room === "contacts" && entry.view === "compact") {
      const id = (entry.data as { contact?: { id?: unknown } } | null)?.contact
        ?.id;
      if (typeof id === "string")
        return idOnlyResult({ ...entry, view: "contact", id });
    }
    if (full && entry.room === "journal") {
      const id = journalEntryId(entry.data);
      if (id !== undefined) {
        const notice = (entry.data as { notice?: unknown }).notice;
        return notice === undefined
          ? { entry: { id } }
          : { entry: { id }, notice };
      }
    }
    return entry.data;
  }
  return idOnlyResult(entry);
}

/** A room target from a room's link, as a stack entry. A missing view is the room's root. */
export function entryOfTarget(target: RoomTarget): NavEntry {
  return {
    room: target.room,
    view: target.view ?? ROOT_VIEW,
    id: target.id,
    label: target.label,
    from: target.from,
    data: target.data,
  };
}

export function RoomAdapter({
  Room,
  shell,
}: {
  Room: ComponentType<RoomProps>;
  shell: ShellRoomProps;
}) {
  const host = useContext(RoomHostContext);
  if (!host) throw new Error("RoomAdapter needs a RoomHostContext");
  const { entry, full, visible, refreshKey, navigate, markDirty, sendMessage } =
    shell;
  // A full-view room reads again in place on a new refreshKey and keeps its initial result. An inline
  // card has no state worth keeping: it is mounted again on a refresh and reads its record by id.
  const inlineRefreshed = !full && refreshKey > 0;

  // The latest markDirty, so the transport below stays the same object across renders.
  const dirty = useRef(markDirty);
  useEffect(() => {
    dirty.current = markDirty;
  });
  // The refresh in which the server refused the room's first read (a missing scope), if any.
  const [blockedAt, setBlockedAt] = useState<number | undefined>();
  const answered = useRef(false);
  const refreshAtCall = useRef(refreshKey);
  useEffect(() => {
    refreshAtCall.current = refreshKey;
  });
  const transport = useMemo<RoomTransport>(
    () => ({
      call: async <T,>(name: string, args: object): Promise<T> => {
        const domains = dirtyDomains(name);
        let result: T;
        try {
          result = await host.transport.call<T>(name, args);
        } catch (error) {
          // A write that failed may still have reached the server (a timeout): the other rooms read again.
          if (domains.length > 0) dirty.current(domains);
          // A refused first read says the connection has no access: the room shows a calm line.
          if (
            domains.length === 0 &&
            !answered.current &&
            error instanceof HostToolError &&
            error.code === "forbidden"
          )
            setBlockedAt(refreshAtCall.current);
          throw error;
        }
        answered.current = true;
        if (domains.length > 0) dirty.current(domains);
        return result;
      },
      requestDisplayMode: async (mode) => {
        const granted = await host.transport.requestDisplayMode(mode);
        if (granted === "fullscreen") host.onExpand();
        return granted;
      },
      updateModelContext: (sentence) =>
        host.transport.updateModelContext(sentence),
      supportsTool: host.transport.supportsTool,
      supportsCall: host.transport.supportsCall,
      offline: host.transport.offline,
    }),
    [host],
  );

  const initial = useMemo(
    () => initialFor(entry, full, inlineRefreshed),
    [entry, full, inlineRefreshed],
  );
  const initialError = !inlineRefreshed && entry.isError === true;
  const hasResult = initial !== undefined || initialError;
  if (blockedAt === refreshKey) {
    const labels = sidekickShellLabelsFor(appLocale());
    return (
      <p className="sk-rooms__no-access" role="status">
        {labels.noAccess(labels.rooms[entry.room])}
      </p>
    );
  }

  return (
    <Room
      // Only an inline card is mounted again by a refresh; a full-view room gets refreshKey and reads in place.
      key={full ? 0 : refreshKey}
      refreshKey={refreshKey}
      initial={initial}
      initialError={initialError || undefined}
      resultId={hasResult ? (entry.resultId ?? 1) : undefined}
      view={entry.view === ROOT_VIEW ? undefined : entry.view}
      mode={full ? "full" : "inline"}
      fullscreenAvailable={!full && host.fullscreenAvailable()}
      transport={transport}
      availableViews={host.availableViews?.[entry.room]}
      hostSettings={
        host.hostSettings && {
          label: host.hostSettings.label,
          onOpen: () => host.hostSettings?.onOpen(entry.room),
        }
      }
      sendMessage={sendMessage}
      onNavigate={
        navigate
          ? (target) =>
              navigate(entryOfTarget(target), { replace: target.replace })
          : undefined
      }
      onDirty={(domains) => markDirty(domains.filter(isRoomId))}
      onModeGranted={(mode, target) => {
        if (mode === "full")
          host.onExpand(target ? entryOfTarget(target) : undefined);
      }}
      active={visible}
    />
  );
}

function adapt(Room: ComponentType<RoomProps>) {
  function Adapted(shell: ShellRoomProps) {
    return <RoomAdapter Room={Room} shell={shell} />;
  }
  Adapted.displayName = `Adapted(${Room.displayName ?? Room.name})`;
  return Adapted;
}

/** The five rooms, each behind its adapter. */
export const SIDEKICK_ROOMS: RoomRegistry = {
  work: adapt(WorkRoom),
  journal: adapt(JournalRoom),
  contacts: adapt(ContactsRoom),
  shopping: adapt(ShoppingRoom),
  control: adapt(ControlRoom),
};

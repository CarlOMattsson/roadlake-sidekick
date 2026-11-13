import {
  useCallback,
  useEffect,
  useEffectEvent,
  useRef,
  useState,
} from "react";
import { ErrorNotice, Skeleton } from "../mcp-apps/ui/states";
import { Segmented } from "../mcp-apps/ui/segmented";
import { LicenseRow } from "../mcp-apps/license-mark";
import { UpdateReminderRow } from "../mcp-apps/update-reminder";
import type { ControlLabels } from "./labels";
import { HistoryView } from "./history-view";
import { MemoryView } from "./memory-view";
import { TrashView } from "./trash-view";
import type {
  ActivityList,
  ChangesList,
  ControlTransport,
  MemoryStatus,
  TrashList,
} from "./transport";
import "../mcp-apps/ui/tokens.css";
import "./control.css";

export type ControlViewName = "trash" | "history" | "memory";
/** The History tab holds two parts, changes and activity; each is read through its own tool. */
export type ControlData = {
  trash?: TrashList;
  changes?: ChangesList;
  memory?: MemoryStatus;
  activity?: ActivityList;
};

const VIEW_ORDER: readonly ControlViewName[] = ["trash", "history", "memory"];

/**
 * The view a room target names: the tab names ("memory", "history", "trash") and the tools' own, where
 * list_recent_changes ("changes") and list_assistant_activity ("activity") both open History. An unknown or missing
 * name gives undefined.
 */
export function controlViewNamed(name: string | undefined) {
  const tab = name === "changes" || name === "activity" ? "history" : name;
  return VIEW_ORDER.find((view) => view === tab);
}

/**
 * Which view a tool result belongs to, from its shape: list_trash has items and has_more,
 * list_recent_changes has changes, get_memory_status has settings and provider, and
 * list_assistant_activity has items and next_cursor whose entries carry source, state and operation.
 * The last two are both the History view; the data says which part arrived.
 * Anything else (an error answer, another tool) is not for this app and gives undefined.
 */
export function viewOf(
  structured: unknown,
):
  | { view: "trash"; data: TrashList }
  | { view: "memory"; data: MemoryStatus }
  | { view: "history"; data: ControlData }
  | undefined {
  if (typeof structured !== "object" || structured === null) return undefined;
  const value = structured as Record<string, unknown>;
  if (
    typeof value.settings === "object" &&
    value.settings !== null &&
    typeof value.provider === "string" &&
    Array.isArray(value.sources)
  )
    return { view: "memory", data: structured as MemoryStatus };
  if (Array.isArray(value.changes))
    return { view: "history", data: { changes: structured as ChangesList } };
  if (Array.isArray(value.items) && typeof value.has_more === "boolean")
    return { view: "trash", data: structured as TrashList };
  if (
    Array.isArray(value.items) &&
    "next_cursor" in value &&
    value.items.every(isActivityEntry)
  )
    return { view: "history", data: { activity: structured as ActivityList } };
  return undefined;
}

/** The data keys a view is made of: History is the changes and the activity. */
export function partsOf(name: ControlViewName): (keyof ControlData)[] {
  return name === "history" ? ["changes", "activity"] : [name];
}

function isActivityEntry(item: unknown): boolean {
  if (typeof item !== "object" || item === null) return false;
  const entry = item as Record<string, unknown>;
  return (
    typeof entry.source === "string" &&
    typeof entry.state === "string" &&
    typeof entry.operation === "string" &&
    typeof entry.summary === "string"
  );
}

/**
 * The Control card: a visible switch between Trash, Changes and Memory, and the chosen view below.
 * The tool that opened the app decides the first view; the other two are read through their own
 * existing tools the first time they are chosen, and kept for the life of the card (each view reads
 * again after its own actions). Reading a view never blocks the others.
 */
export function ControlApp({
  transport,
  labels,
  initialView,
  initialData,
  refreshKey,
  now,
  sendMessage,
  onModelContext,
  titled = true,
  heading = false,
}: {
  transport: ControlTransport;
  labels: ControlLabels;
  initialView: ControlViewName;
  initialData: ControlData;
  /**
   * Draws the app's name above the switch. The full view turns it off: the shell names the room there
   * (its BackHeader title, or the active segment of the strip), so the name is not drawn twice.
   */
  titled?: boolean;
  /**
   * Draws the name as the view's title ("Kontroll", --sk-type-title) under the shell's "‹ Arbete", as a detail view's
   * title, instead of the card's kicker. The full view sets it (designsystem §3).
   */
  heading?: boolean;
  /**
   * Changes when the data should be read again (room-types). The value at mount is not a request.
   * A change reads the view on screen again, in place: the tab and the views' own state stay.
   */
  refreshKey?: number;
  now?: () => Date;
  /** The host's chat function (room-types); absent when the host has none, so an empty state's example is plain text. */
  sendMessage?: (text: string) => Promise<boolean>;
  /**
   * Tells the host model, in one generic sentence, that the owner changed something in the card.
   * Never a title or content (see docs/decisions/log.md D-058: logs and telemetry never carry user content). Without a host that supports it, this does nothing.
   */
  onModelContext?: (summary: string) => void;
}) {
  const [view, setView] = useState(initialView);
  const [data, setData] = useState(initialData);
  const [loading, setLoading] = useState(false);
  // False, or what the failed read threw: the notice names the connection only when it may be that.
  const [failed, setFailed] = useState<false | { cause: unknown }>(false);
  // "Show all" per tab. It lives here, not in the views: a view unmounts when another tab is chosen,
  // and the owner's choice must still hold when they come back.
  const [expanded, setExpanded] = useState<
    Partial<Record<ControlViewName, boolean>>
  >({});
  const expandedOf = (name: ControlViewName) => ({
    expanded: expanded[name] ?? false,
    onExpandedChange: (next: boolean) =>
      setExpanded((current) => ({ ...current, [name]: next })),
  });
  // The newest read wins: choosing another view while one loads drops the older answer.
  const newest = useRef(0);
  const remember = useCallback(
    <K extends keyof ControlData>(name: K, value: ControlData[K]) =>
      setData((current) =>
        current[name] === value ? current : { ...current, [name]: value },
      ),
    [],
  );
  const onTrash = useCallback(
    (v: TrashList) => remember("trash", v),
    [remember],
  );
  const onChanges = useCallback(
    (v: ChangesList) => remember("changes", v),
    [remember],
  );
  const onMemory = useCallback(
    (v: MemoryStatus) => remember("memory", v),
    [remember],
  );

  /** Reads a view; History is two reads in parallel, all of them or only the parts still missing. */
  async function read(name: ControlViewName, all = true) {
    const mine = ++newest.current;
    setLoading(true);
    setFailed(false);
    const readers: Record<keyof ControlData, () => Promise<unknown>> = {
      trash: transport.trash,
      changes: transport.changes,
      memory: transport.memoryStatus,
      activity: transport.activity,
    };
    const parts = partsOf(name).filter((p) => all || data[p] === undefined);
    const results = await Promise.allSettled(
      parts.map(async (p) => [p, await readers[p]()] as const),
    );
    if (mine !== newest.current) return;
    const fresh: Record<string, unknown> = {};
    for (const r of results)
      if (r.status === "fulfilled") fresh[r.value[0]] = r.value[1];
    // One part failing is not an error while the other reads, or is already there: the view shows what it has.
    const held = !all && partsOf(name).some((p) => data[p] !== undefined);
    if (!held && Object.keys(fresh).length === 0)
      setFailed({
        cause: (results[0] as PromiseRejectedResult | undefined)?.reason,
      });
    else setData((current) => ({ ...current, ...fresh }));
    setLoading(false);
  }

  // A card mounted without data (a hidden room) reads its first view for itself.
  const readInitial = useEffectEvent(() => {
    if (partsOf(initialView).some((p) => initialData[p] === undefined))
      void read(initialView, false);
  });
  useEffect(() => {
    readInitial();
  }, []);

  // A changed refreshKey after mount reads the view on screen again. The answer only replaces the data.
  const refreshed = useRef(refreshKey);
  const readCurrent = useEffectEvent(() => void read(view));
  useEffect(() => {
    if (refreshKey === refreshed.current) return;
    refreshed.current = refreshKey;
    readCurrent();
  }, [refreshKey]);

  function choose(next: ControlViewName) {
    if (next === view) return;
    setView(next);
    if (partsOf(next).some((p) => data[p] === undefined))
      void read(next, false);
    else {
      newest.current++;
      setLoading(false);
      setFailed(false);
    }
  }

  const options = VIEW_ORDER.map((value) => ({
    value,
    label: labels.views[value],
  }));
  return (
    <section className="sidekick-control" aria-label={labels.title}>
      <div className="control-card sk-card">
        {/* Fullscreen: the shell's Back row reads "‹ Arbete", where it leads, and the view's title "Kontroll" stands under
            it as a detail view's, then the tabs. */}
        {heading ? (
          <h2 className="control-title">{labels.title}</h2>
        ) : titled ? (
          <p className="sk-eyebrow">{labels.title}</p>
        ) : null}
        <Segmented
          label={labels.title}
          options={options}
          value={view}
          onChange={choose}
        />
        <div className="control-body" aria-busy={loading}>
          {failed ? (
            <ErrorNotice
              locale={labels.locale}
              subject={`control:${view}`}
              cause={failed.cause}
              onRetry={() => void read(view)}
            />
          ) : !partsOf(view).some((p) => data[p] !== undefined) ? (
            <Skeleton loading={loading} />
          ) : view === "trash" && data.trash ? (
            <TrashView
              initial={data.trash}
              transport={transport}
              labels={labels}
              now={now}
              onData={onTrash}
              onModelContext={onModelContext}
              full={heading}
              {...expandedOf("trash")}
            />
          ) : view === "history" ? (
            <HistoryView
              changes={data.changes}
              activity={data.activity}
              transport={transport}
              labels={labels}
              now={now}
              onData={onChanges}
              sendMessage={sendMessage}
              onModelContext={onModelContext}
              full={heading}
              {...expandedOf("history")}
            />
          ) : view === "memory" && data.memory ? (
            <MemoryView
              initial={data.memory}
              transport={transport}
              labels={labels}
              onData={onMemory}
              onModelContext={onModelContext}
              recall={heading}
            />
          ) : null}
        </div>
        {/* The instance's settings live here: the update reminder is a row of the full view. */}
        {heading && <UpdateReminderRow locale={labels.locale} now={now} />}
        {/* The license row comes last, after the update row (see docs/decisions/log.md D-083: license terms): the coin of every room leads here. */}
        {heading && <LicenseRow locale={labels.locale} />}
      </div>
    </section>
  );
}

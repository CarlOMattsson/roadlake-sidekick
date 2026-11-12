import { useEffect, useState } from "react";

import { Segmented } from "./ui/segmented";
import { controlLabels } from "../control-app/labels";
import { ViewTabs } from "../work-app/view-tabs";
import { workShellLabelsFor } from "../work-app/work-shell-labels";
import { sidekickShellLabelsFor } from "./sidekick-shell-labels";
import { CONTROL_PARENT } from "./nav-state";
import { STRIP_ROOM_IDS } from "./router";
import { BackHeader } from "./ui/back-header";
import { MoreIcon, PlusIcon, SearchIcon } from "./ui/icons";
import { SkeletonRows } from "./ui/states";
import "./awaiting.css";

/**
 * The placeholder while the app waits for its first tool result (designsystem §3 Tillstånd, §4 "Skelettets
 * orientering"): the frame is drawn for real, with the same components as the loaded view, and only the
 * rows are a skeleton, so nothing moves when the data arrives.
 *
 * - Before the host has answered the handshake nothing is known: the room strip with no room marked and four rows.
 *   The static placeholder in vite.mcp-app.config.ts is this state, class for class.
 * - After the handshake the host context may name the tool that opened the card (`toolInfo`, optional in MCP Apps
 *   2026-01-26). The entry routes it to `room` and `view`, and the placeholder marks that room in the strip and draws
 *   its real header, inert: Work's tab row (ViewTabs, search and + held off while the list loads, and ⋯); Control's
 *   "‹ Arbete", title and tabs, with no strip (Control applies to every room). The header sits in a
 *   `sk-rooms__pane`, as in the shell, so the rooms' own rules place it exactly as the loaded view.
 * - `full` false (the host said inline): a card has no strip, so only the rows are drawn.
 *
 * What is loading ("Laddar uppgifter…") is read by assistive technology through the status role and never drawn.
 * Rows have the measures of the finished list rows: a 36 px leading column with the glyph at the content edge, the
 * text at x 52, 12 px of padding, 70 px for two lines and no hairlines. The skeleton never guesses the groups
 *: Work's lists open on a heading, so one bar holds its place, and five rows follow (SkeletonRows). The blocks
 * pulse softly and stop with `prefers-reduced-motion`.
 * After `timeoutMs` one sentence says to ask Claude to open the app again.
 *
 * The texts live here and in the shell's and rooms' label files, not in @/i18n, so the MCP App bundle does not pull
 * in the Sidekick app catalogue. Swedish for any `sv*` locale, English otherwise.
 */
const awaitingEn = {
  loading: "Loading…",
  loadingRoom: {
    work: "Loading tasks…",
    journal: "Loading journal…",
    contacts: "Loading contacts…",
    shopping: "Loading list…",
    control: "Loading…",
  } as Record<string, string>,
  timedOut:
    "Still waiting for data from Claude. Ask Claude to open this again.",
};

const awaitingSv: typeof awaitingEn = {
  loading: "Laddar…",
  loadingRoom: {
    work: "Laddar uppgifter…",
    journal: "Laddar anteckningar…",
    contacts: "Laddar kontakter…",
    shopping: "Laddar listan…",
    control: "Laddar…",
  },
  timedOut: "Väntar på data från Claude. Be Claude öppna den igen.",
};

/** The texts of the placeholder by app language. Exported for the locale parity test. */
export function awaitingLabelsFor(locale: string): typeof awaitingEn {
  return locale.startsWith("sv") ? awaitingSv : awaitingEn;
}

const DEFAULT_TIMEOUT_MS = 8000;

/** The work views that show the tab row, in its order. */
const WORK_TABS = ["agenda", "board", "hierarchy"] as const;
const CONTROL_VIEWS = ["trash", "history", "memory"] as const;
/** The header is inert: nothing in it is ever called. */
const nothing = () => undefined;

export function AwaitingResult({
  locale,
  timeoutMs = DEFAULT_TIMEOUT_MS,
  room,
  view,
  full = true,
}: {
  locale: string;
  timeoutMs?: number;
  /** The room the opening tool belongs to, when the host named the tool at the handshake. */
  room?: string;
  view?: string;
  /** False when the host said the card is inline: no strip then. */
  full?: boolean;
}) {
  const labels = awaitingLabelsFor(locale);
  const sv = locale.startsWith("sv");
  const shell = sidekickShellLabelsFor(sv ? "sv" : "en");
  // Stores the timeout that has elapsed, so a changed timeoutMs starts over without a state reset in the effect.
  const [expiredFor, setExpiredFor] = useState<number | null>(null);

  useEffect(() => {
    const timer = setTimeout(() => setExpiredFor(timeoutMs), timeoutMs);
    return () => clearTimeout(timer);
  }, [timeoutMs]);

  const timedOut = expiredFor === timeoutMs;
  const workTab = WORK_TABS.find((tab) => tab === view);
  // The router names a changes or activity result; both are Control's History tab.
  const controlView =
    view === "changes" || view === "activity"
      ? "history"
      : (CONTROL_VIEWS.find((name) => name === view) ?? CONTROL_VIEWS[0]);

  let head = null;
  if (full && room === "work" && workTab) {
    const tabs = workShellLabelsFor(sv ? "sv" : "en");
    head = (
      <div className="sidekick-work">
        <div className="sk-shell-tabs sk-shell-tabs--with-end">
          <ViewTabs
            label={tabs.tabsLabel}
            options={WORK_TABS.map((value) => ({
              value,
              label: tabs.tabs[value],
            }))}
            value={workTab}
            onChange={nothing}
          />
          {/* The loaded row's own markup (work-fullscreen.tsx): the tools in .sk-shell-tabs-end and + as
              .work-tab-create, so search, + and ⋯ get the same boxes and do not move when the list comes. */}
          <div className="sk-shell-tabs-end">
            <span className="sk-iconbtn work-tab-tool" aria-disabled="true">
              <SearchIcon />
            </span>
            <span
              className="sk-iconbtn sk-iconbtn--primary work-tab-tool work-tab-create"
              aria-disabled="true"
            >
              <PlusIcon />
            </span>
            <span className="sk-iconbtn work-tab-tool work-agenda-bar-more">
              <MoreIcon />
            </span>
          </div>
        </div>
      </div>
    );
  } else if (full && room === "control") {
    const control = controlLabels[sv ? "sv" : "en"];
    head = (
      <>
        <BackHeader label={shell.rooms[CONTROL_PARENT]} onBack={nothing} />
        <div className="sidekick-control">
          <h2 className="control-title">{control.title}</h2>
          <Segmented
            label={control.title}
            options={CONTROL_VIEWS.map((value) => ({
              value,
              label: control.views[value],
            }))}
            value={controlView}
            onChange={nothing}
          />
        </div>
      </>
    );
  }
  // Control keeps the strip with no room marked: the way back looks the same everywhere.
  const strip = full;

  return (
    <div
      className="sidekick-wait"
      role="status"
      aria-busy="true"
      data-room={room}
      data-view={view}
      data-frame={full ? "full" : "inline"}
    >
      {strip ? (
        <div aria-hidden="true" className="sidekick-wait-strip">
          {STRIP_ROOM_IDS.map((id) => (
            <span
              key={id}
              className="sidekick-wait-room"
              data-current={id === room ? "true" : undefined}
            >
              {shell.rooms[id]}
            </span>
          ))}
        </div>
      ) : null}
      {head ? (
        <div
          aria-hidden="true"
          inert
          className="sk-rooms__pane sidekick-wait-head"
          data-room={room}
        >
          {head}
        </div>
      ) : null}
      <p className="sidekick-wait-line">
        {(room && labels.loadingRoom[room]) || labels.loading}
      </p>
      <div aria-hidden="true" className="sidekick-wait-rows">
        <SkeletonRows
          rows={room === "work" && full ? 5 : 4}
          heading={room === "work"}
        />
      </div>
      {timedOut ? (
        <p className="sidekick-wait-note">{labels.timedOut}</p>
      ) : null}
    </div>
  );
}

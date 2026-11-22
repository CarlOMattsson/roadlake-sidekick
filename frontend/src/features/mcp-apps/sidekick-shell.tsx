import {
  useContext,
  useEffect,
  useLayoutEffect,
  useReducer,
  useCallback,
  useRef,
  useState,
} from "react";

import { sidekickShellLabelsFor } from "@/features/mcp-apps/sidekick-shell-labels";
import { roomEnabled } from "@/features/mcp-apps/enabled-rooms";
import {
  LicenseFoot,
  LicenseHostContext,
} from "@/features/mcp-apps/license-mark";
import {
  openLicenseMenu,
  requestLicenseFocus,
} from "@/features/mcp-apps/license-state";
import {
  canGoBack,
  ROOT_VIEW,
  topOf,
  type NavEntry,
} from "@/features/mcp-apps/nav-state";
import type { RoomId } from "@/features/mcp-apps/router";
import {
  answerProps,
  createShellNavState,
  shellNavReducer,
} from "@/features/mcp-apps/shell-nav-reducer";
import { createUnsavedRegistry } from "@/features/mcp-apps/unsaved-guard";
import { AppFrame } from "@/features/mcp-apps/ui/layout";
import { RenderErrorBoundary } from "@/features/mcp-apps/ui/error-boundary";
import { controlEntry } from "@/features/mcp-apps/ui/control-entry";
import { RoomSurfaceContext } from "@/features/mcp-apps/ui/room-context";
import {
  ShortcutHelpOpenerContext,
  ShortcutRegistryContext,
} from "@/features/mcp-apps/ui/shortcut-registry";
import { ShortcutHelp } from "@/features/mcp-apps/ui/shortcut-help";
import { useShortcuts } from "@/features/mcp-apps/ui/shortcuts";
import { useViewPicker } from "@/features/mcp-apps/ui/view-picker";
import { ShellBar } from "./shell-parts/shell-bar";
import {
  backName,
  layerKey,
  paneBackName,
  layersOf,
  modelContextLine,
  scrollTop,
  setScrollTop,
} from "./shell-parts/shell-layers";
import { ShellPanes } from "./shell-parts/shell-panes";
import type {
  ShellRoomProps,
  SidekickShellProps,
} from "./shell-parts/shell-types";
import { useLayerFreshness } from "./shell-parts/use-layer-freshness";
import { useShellMeasures } from "./shell-parts/use-shell-measures";
import { useShellKeys } from "./shell-parts/use-shell-keys";
import { useRoomStrip } from "./shell-parts/room-strip";
import { useSplitPane, type SplitAsk } from "./shell-parts/use-split-pane";
import "./sidekick-shell.css";

// The shell's public types and helpers live in shell-parts; rooms and tests import them from here.
export { modelContextLine, STALE_AFTER_MS } from "./shell-parts/shell-layers";
export type {
  RoomRegistry,
  ShellRoomProps,
  SidekickShellProps,
} from "./shell-parts/shell-types";

export function SidekickShell({
  locale,
  rooms,
  start,
  openAt,
  full,
  onCollapse,
  features,
  onModelContext,
  onSendMessage,
  strip: stripAllowed = true,
  primaryRooms,
  moreRooms,
  navIcons,
  registerBack,
  staleTick = 0,
}: SidekickShellProps) {
  const labels = sidekickShellLabelsFor(locale);
  const [shellNav, dispatch] = useReducer(shellNavReducer, undefined, () =>
    createShellNavState(start, full),
  );
  // The props are answered in the render that sees them, so no frame draws the old stacks (the card opening
  // the full view, a new tool result, a record to open at). Only a change dispatches: a render-phase dispatch renders again.
  // Unsaved edits report here (useUnsavedGuard). The registry is made before the props are answered because a
  // new tool result or a record to open at would drop the layers that hold them: it waits until they are saved or discarded.
  const [unsaved] = useState(createUnsavedRegistry);
  const [, setUnsavedTick] = useState(0);
  useEffect(
    () => unsaved.subscribe(() => setUnsavedTick((tick) => tick + 1)),
    [unsaved],
  );
  const holdsUnsaved = unsaved.isDirty(
    (Object.keys(shellNav.nav.stacks) as RoomId[]).flatMap((room) =>
      layersOf(shellNav.nav, room).map((layer) => layer.id),
    ),
  );
  const props = holdsUnsaved
    ? { start: shellNav.seenStart, openAt: shellNav.pushedOpenAt, full }
    : { start, openAt, full };
  if (answerProps(shellNav, props) !== shellNav)
    dispatch({ type: "props", ...props });
  const { nav, inlineKey } = shellNav;
  const [asked, setAsked] = useState<string | undefined>();
  // A Back, a press on the active room tab, a record opened beside a list over another one, or the × of the detail,
  // that would drop unsaved edits asks first; `ask` is that question, tied to the layer it was asked on.
  const [ask, setAsk] = useState<{
    kind: "back" | "root" | SplitAsk["kind"];
    layer: string;
    split?: SplitAsk;
  }>();
  const askFrom = useRef<HTMLElement | null>(null);

  // How navigation works on this host: local needs tools/call; reserve asks Claude with ui/message.
  const mode = !full
    ? "inline"
    : features.serverTools
      ? "local"
      : features.message && onSendMessage
        ? "reserve"
        : "none";
  // Control applies to every room, so no room is marked there: the strip stands as in every room, with no room chosen,
  // and Back under it names the room Control was opened from (designsystem §3 "Rumsremsan": a missing strip read as a jump of the head). Its room in the strip
  // goes back to that room's layer, as Back does.
  const inControl = nav.stacks[nav.active].at(-1)?.room === "control";
  const roomStrip = useRoomStrip({
    primary: primaryRooms,
    more: moreRooms,
    icons: navIcons,
    allowed: stripAllowed,
    active: nav.active,
    inControl,
    labels,
    onChoose: choose,
  });
  const { strip, rooms: stripRooms } = roomStrip;
  const stripVisible = strip && (mode === "local" || mode === "reserve");
  const { narrow, wide, tabsEl, shellEl, barEl } = useShellMeasures(
    full,
    stripVisible,
  );
  // The end of the Back row, where the view on top puts its own pen and ⋯ (BackHeaderActions).
  const [backSlot, setBackSlot] = useState<HTMLSpanElement | null>(null);
  // A wide frame (≥ 64rem) where the shell drives the rooms: the head is one row, the strip and then the room's own head
  // (RoomHead portals there). Elsewhere each room draws its head in its own row under the strip.
  const headOn = wide && mode === "local" && stripVisible;
  const [headSlot, setHeadSlot] = useState<HTMLDivElement | null>(null);

  // The keys of every room and the keyboard help (`?`).
  const keysOn = full && mode === "local";
  const {
    registry: shortcutRegistry,
    helpOpen,
    setHelpOpen,
    charKeys,
    groups,
  } = useShellKeys({
    on: keysOn,
    labels,
    stripRooms,
    // Mer opens from its key only while its cell is drawn (not behind the narrow room picker).
    openMore: stripVisible && !narrow ? roomStrip.openMore : undefined,
    choose,
  });
  // The compiler keeps this stable between renders (React Compiler), so the menus' row does not render again for it.
  const helpOpener = {
    open: () => setHelpOpen(true),
    label: labels.shortcuts.title,
  };

  // The page scroll of each layer that was left, by room and depth: Back returns to where the user was.
  const scrolls = useRef(new Map<string, number>());
  const paneEls = useRef<Partial<Record<RoomId, HTMLElement | null>>>({});
  const focusAfterSwitch = useRef(false);
  const firstRender = useRef(true);
  const picker = useViewPicker({
    label: labels.stripLabel,
    options: roomStrip.pickRooms.map((value) => ({
      value,
      label: labels.rooms[value],
    })),
    // Control applies to every room, so the picker marks none there and says `stripLabel`, as the
    // strip does; its first room takes the focus when it opens.
    value: inControl ? undefined : nav.active,
    placeholder: labels.stripLabel,
    onChange: choose,
    shown: narrow && stripVisible,
    reselect: true,
  });
  const licenseHost = useContext(LicenseHostContext);
  const modelContext = useRef(onModelContext);
  useEffect(() => {
    modelContext.current = onModelContext;
  });
  const activeLayers = layersOf(nav, nav.active);
  const shownId = activeLayers[activeLayers.length - 1]?.id;
  // The same wide frame splits a list and the record opened from it (desktop spec 2.1, nav-state splitOf).
  const splitPane = useSplitPane({
    nav,
    wide: headOn,
    labels,
    keys: keysOn && charKeys,
    bound: new Set(
      groups.flatMap((group) => group.entries.flatMap((entry) => entry.keys)),
    ),
    dispatch,
    isDirty: (ids) => unsaved.isDirty(ids),
    askFirst: (question) => askFirst(question.kind, question),
    clearAsk: () => setAsk(undefined),
    focusAfter: (move) => {
      focusAfterSwitch.current = move;
    },
    push: navigate,
  });
  const { split, besideOpen, shownIds, takeRow } = splitPane;
  const holdsEdits = useCallback(
    (layerId: string) => unsaved.isDirty([layerId]),
    [unsaved],
  );
  const { layerKeys, markDirty } = useLayerFreshness({
    nav,
    full,
    shownIds,
    holdsEdits,
    startRoom: start.room,
    onInlineStale: () => dispatch({ type: "inline-stale" }),
    staleTick,
  });

  /** The user leaves `room`: remember where its page was scrolled. */
  function leave(room: RoomId) {
    scrolls.current.set(`${room}:${splitPane.scrollDepth(room)}`, scrollTop());
  }

  function send(room: RoomId) {
    const name = labels.rooms[room];
    void onSendMessage?.(labels.openRoomMessage(name)).then((sent) => {
      if (sent) setAsked(labels.askedNote(name));
    });
  }

  function choose(room: RoomId) {
    if (mode === "reserve") {
      if (room !== nav.active) send(room);
      return;
    }
    if (room === nav.active) {
      if (inControl) return requestBack();
      // Pressing the active room goes to its root.
      if (canGoBack(nav)) {
        const above = layersOf(nav, room).slice(1);
        if (unsaved.isDirty(above.map((layer) => layer.id))) askFirst("root");
        else toRoot(room);
      }
      return;
    }
    setAsk(undefined);
    leave(nav.active);
    focusAfterSwitch.current = true;
    dispatch({ type: "switch-room", room });
  }

  function toRoot(room: RoomId) {
    for (const key of [...scrolls.current.keys()])
      if (key.startsWith(`${room}:`)) scrolls.current.delete(key);
    focusAfterSwitch.current = true;
    dispatch({ type: "switch-room", room });
  }

  /** Asks `unsavedAsk` on the layer on top, remembering where the focus was to give it back on the keep button. */
  function askFirst(
    kind: "back" | "root" | SplitAsk["kind"],
    split?: SplitAsk,
  ) {
    const layer = layersOf(nav, nav.active).at(-1)?.id;
    if (layer === undefined) return;
    askFrom.current = document.activeElement as HTMLElement | null;
    setAsk({ kind, layer, split });
  }

  /** The Back of the row, the tab and the system: one layer back, after asking when the layer holds unsaved edits. */
  function requestBack() {
    const top = layersOf(nav, nav.active).at(-1);
    if (top && unsaved.isDirty([top.id])) askFirst("back");
    else back();
  }

  function discardAsked() {
    const question = ask;
    setAsk(undefined);
    if (question?.kind === "root") toRoot(nav.active);
    else if (question?.split) splitPane.answer(question.split);
    else back();
  }

  function keepEditing() {
    setAsk(undefined);
    askFrom.current?.focus();
  }

  // The safe answer takes the focus when the question opens (a stable callback: it runs once, on mount).
  const focusKeep = useCallback((element: HTMLButtonElement | null) => {
    element?.focus();
  }, []);

  function navigate(target: NavEntry, options?: { replace?: boolean }) {
    if (!roomEnabled(target.room)) return;
    setAsk(undefined);
    if (!options?.replace) {
      scrolls.current.set(layerKey(nav, nav.active), scrollTop());
      // The new layer starts at its top, whatever an earlier layer at that depth remembered.
      scrolls.current.delete(
        `${nav.active}:${nav.stacks[nav.active].length + 1}`,
      );
    }
    focusAfterSwitch.current = true;
    dispatch({ type: "push", target, replace: options?.replace });
  }

  /**
   * The license coin of the room's foot leads to the license row: the host's own settings (the phone), else Control,
   * else (Control off) the ⋯ panel of the room on screen. The row takes the focus there. False: no place answered,
   * and the foot folds the row out itself.
   */
  function showLicense(): boolean {
    requestLicenseFocus();
    if (licenseHost.openSettings) {
      licenseHost.openSettings(nav.active);
      return true;
    }
    if (roomEnabled("control")) {
      if (mode !== "local") return false;
      const { room, view = ROOT_VIEW } = controlEntry(locale).target;
      navigate({ room, view });
      return true;
    }
    return openLicenseMenu();
  }

  function back() {
    scrolls.current.delete(layerKey(nav, nav.active));
    // The first record beside a list closes: the focus goes back to its row, as the × does.
    splitPane.beforeBack();
    focusAfterSwitch.current = true;
    dispatch({ type: "back" });
  }

  // System Back (a host that registers it) goes one layer back, as the Back row does; at the root it is the host's.
  const systemBack = useRef<() => boolean>(() => false);
  useEffect(() => {
    systemBack.current = () => {
      if (mode !== "local" || !canGoBack(nav)) return false;
      // A second Back while the question is open is `unsavedKeep`.
      if (ask) keepEditing();
      else requestBack();
      return true;
    };
  });
  useEffect(() => {
    if (!registerBack) return undefined;
    registerBack(() => systemBack.current());
    return () => registerBack(undefined);
  }, [registerBack]);

  // Esc closes the record beside a list, one step at a time, after a menu, a dialog, a field and the room's own Esc had
  // their turn (they handle it first or take it: useShortcuts skips them). With nothing open the shell does not take
  // Esc, so the host may leave fullscreen with it. While the unsaved question is open, Esc keeps editing.
  useShortcuts(
    { Escape: () => (ask ? keepEditing() : requestBack()) },
    { enabled: keysOn && besideOpen && !helpOpen },
  );

  const activeEntry = topOf(nav, nav.active);
  const line = modelContextLine(labels, nav.active, activeEntry);

  // The model learns where the user is on a room change and on a cross-link, not on every render.
  useEffect(() => {
    if (full) modelContext.current?.(line);
  }, [full, line]);

  // Restore the scroll position of the layer that is shown (a room that was left, or the layer Back
  // returns to), and move focus to the heading of the layer on top after a room change, a step in or Back.
  const depth = splitPane.scrollDepth(nav.active);
  useLayoutEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    setScrollTop(scrolls.current.get(`${nav.active}:${depth}`) ?? 0);
  }, [nav.active, depth]);
  useEffect(() => {
    if (!focusAfterSwitch.current) return;
    focusAfterSwitch.current = false;
    const pane = paneEls.current[nav.active];
    const layer =
      pane?.querySelector<HTMLElement>("[data-layer-top='true']") ?? pane;
    // The detail beside a list closed: its row takes the focus back, where the user left the list.
    const row = takeRow(layer);
    if (row) {
      row.focus({ preventScroll: true });
      return;
    }
    const heading = layer?.querySelector<HTMLElement>(
      "h1, h2, [data-room-heading]",
    );
    if (heading) {
      if (!heading.hasAttribute("tabindex")) heading.tabIndex = -1;
      heading.focus({ preventScroll: true });
    } else pane?.focus({ preventScroll: true });
  }, [nav.active, shownId, takeRow]);

  function roomProps(
    room: RoomId,
    layer?: NavEntry,
    layerId?: string,
    shown?: boolean,
  ): ShellRoomProps {
    return {
      entry: layer ?? topOf(nav, room),
      full,
      visible: shown ?? room === nav.active,
      refreshKey: layerId === undefined ? 0 : (layerKeys[layerId] ?? 0),
      navigate: mode === "local" ? splitPane.navigateFrom(layerId) : undefined,
      back: mode === "local" && canGoBack(nav) ? requestBack : undefined,
      markDirty: (domains) => markDirty(layerId ?? room, domains),
      locale,
      sendMessage: features.message ? onSendMessage : undefined,
    };
  }

  if (!full) {
    // Inline always draws the card the tool result gave (the original card), whatever the stack holds.
    const Room = rooms[start.room];
    return (
      <RoomSurfaceContext.Provider
        value={{
          active: true,
          framed: false,
          room: start.room,
          view: start.view,
        }}
      >
        <RenderErrorBoundary locale={locale} scope={start.room}>
          <Room
            {...roomProps(start.room)}
            entry={start}
            refreshKey={inlineKey}
          />
        </RenderErrorBoundary>
      </RoomSurfaceContext.Provider>
    );
  }

  // In a split pane the detail's own head holds the Back (PaneHead), beside the list it leads to.
  const showBack = mode === "local" && canGoBack(nav) && !besideOpen;

  return (
    <ShortcutRegistryContext.Provider value={shortcutRegistry}>
      <ShortcutHelpOpenerContext.Provider
        value={keysOn ? helpOpener : undefined}
      >
        <AppFrame mode="full">
          <div
            ref={shellEl}
            className="sk-rooms-shell"
            data-strip={stripVisible ? "on" : "off"}
            data-back={showBack ? "on" : undefined}
            data-head={headOn ? "on" : undefined}
          >
            {stripVisible || onCollapse || showBack ? (
              <ShellBar
                labels={labels}
                barRef={barEl}
                tabsRef={tabsEl}
                strip={stripVisible}
                roomStrip={roomStrip}
                narrow={narrow}
                onChoose={choose}
                picker={picker}
                back={
                  showBack
                    ? {
                        label: backName(labels, nav),
                        onBack: requestBack,
                        slotRef: setBackSlot,
                      }
                    : undefined
                }
                // Fäll ihop sits in the header row, on the right, when the full view is only our own expansion.
                collapse={
                  onCollapse
                    ? { label: labels.collapse, onCollapse }
                    : undefined
                }
                ask={
                  ask && ask.layer === shownId
                    ? {
                        onDiscard: discardAsked,
                        onKeep: keepEditing,
                        keepRef: focusKeep,
                      }
                    : undefined
                }
                headSlotRef={headOn ? setHeadSlot : undefined}
              />
            ) : null}
            <p className="sk-rooms__note" role="status" aria-live="polite">
              {asked}
            </p>
            <ShellPanes
              nav={nav}
              rooms={rooms}
              labels={labels}
              locale={locale}
              paneEls={paneEls}
              roomProps={roomProps}
              setUnsaved={unsaved.set}
              strip={strip}
              backSlot={showBack ? backSlot : null}
              headSlot={headOn ? headSlot : null}
              split={{
                ...splitPane.panes,
                of: { [nav.active]: split },
                swapped: shellNav.swapped,
                backLabel: paneBackName(labels, nav),
                onBack: requestBack,
                onClose: splitPane.requestClose,
              }}
            />
            {/* The license coin, last in the room (see docs/decisions/log.md D-083: license terms). Control holds the row itself, so the coin is not drawn there. */}
            {inControl ? null : (
              <LicenseFoot
                key={nav.active}
                locale={locale}
                onShow={showLicense}
              />
            )}
          </div>
          {keysOn ? (
            <ShortcutHelp
              open={helpOpen}
              onClose={() => setHelpOpen(false)}
              title={labels.shortcuts.title}
              closeLabel={labels.shortcuts.close}
              groups={groups}
              charKeys={{
                label: labels.shortcuts.charKeys,
                on: charKeys,
                onChange: shortcutRegistry.setCharKeys,
              }}
            />
          ) : null}
        </AppFrame>
      </ShortcutHelpOpenerContext.Provider>
    </ShortcutRegistryContext.Provider>
  );
}

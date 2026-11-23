/**
 * The Start room (room contract: mcp-apps/room-types.ts). Today it holds the suggestion inbox: what the owner's
 * automations propose, decided here without a new turn of the model. Its views:
 *
 * - root and `suggestions`: the inbox (SuggestionsInbox); inline, its card (SuggestionsCard).
 * - `suggestion`: one suggestion in full, the detail beside the inbox in a wide frame; inline, its decision card.
 * - `decided`: the receipt card of what Claude decided or undid in the chat; in the full view, the inbox.
 * - `automations`: the automations (AutomationsList), reached from the inbox's lead row and its ⋯.
 * - `automation`: one automation in full, with its runs and its approval (AutomationDetailView), beside the list in a
 *   wide frame.
 *
 * Every read and write goes through `props.transport` (the host's tools/call): no credential and no request of its
 * own. The room's day view (the start page) will take the root; the inbox then becomes a view under it.
 */
import { useMemo } from "react";

import { appLocale } from "../mcp-apps/app-locale";
import { roomEnabled } from "../mcp-apps/enabled-rooms";
import type {
  HostSettingsEntry,
  RoomProps,
  RoomTarget,
} from "../mcp-apps/room-types";
import { controlEntry } from "../mcp-apps/ui/control-entry";
import { AppFrame } from "../mcp-apps/ui/layout";
import {
  DecidedCard,
  SuggestionInlineCard,
  SuggestionsCard,
} from "./suggestions/inbox-card";
import { SuggestionsInbox } from "./suggestions/inbox";
import { suggestionLabelsFor } from "./suggestions/labels";
import {
  isDecisions,
  isSuggestionDetail,
  isSuggestionPage,
  isUndo,
  suggestionIdOf,
  suggestionTitle,
} from "./suggestions/model";
import { SuggestionDetailView } from "./suggestions/suggestion-detail";
import { createSuggestionTransport } from "./suggestions/transport";
import { AutomationDetailView } from "./automations/automation-detail";
import {
  AutomationsEntry,
  automationsTarget,
} from "./automations/automations-entry";
import { AutomationsList } from "./automations/automations-list";
import { automationLabelsFor } from "./automations/labels";
import {
  automationIdOf,
  isAutomationPage,
  isAutomationResult,
} from "./automations/model";
import { createAutomationTransport } from "./automations/transport";

export function StartRoom(props: RoomProps) {
  const { transport, onNavigate, mode } = props;
  const api = useMemo(() => createSuggestionTransport(transport), [transport]);
  const automations = useMemo(
    () => createAutomationTransport(transport),
    [transport],
  );
  const locale = appLocale();
  const t = suggestionLabelsFor(locale);
  const ta = automationLabelsFor(locale);
  const initial = props.initialError ? undefined : props.initial;
  const full = mode === "full";

  const control: HostSettingsEntry | undefined = useMemo(() => {
    if (props.hostSettings) return props.hostSettings;
    if (!onNavigate || !roomEnabled("control")) return undefined;
    const entry = controlEntry(locale);
    return { label: entry.label, onOpen: () => onNavigate(entry.target) };
  }, [props.hostSettings, onNavigate, locale]);

  /** The full view, from an inline card: fullscreen where the host offers it, else the shell expands in place. */
  const canOpenFull =
    props.fullscreenAvailable === true || props.onModeGranted !== undefined;
  const openFull = (target?: RoomTarget) => {
    if (props.fullscreenAvailable === true)
      transport
        .requestDisplayMode("fullscreen")
        .then((granted) => {
          if (granted === "fullscreen") props.onModeGranted?.("full", target);
        })
        .catch(() => undefined);
    else props.onModeGranted?.("full", target);
  };
  const openRecord = onNavigate;

  const view = props.view;
  const frameMode = full ? "full" : "inline";

  if (view === "automations")
    return (
      <AppFrame mode={frameMode}>
        <AutomationsList
          api={automations}
          t={ta}
          initial={isAutomationPage(initial) ? initial : undefined}
          refreshKey={props.refreshKey}
          onOpen={onNavigate}
          sendMessage={props.sendMessage}
        />
      </AppFrame>
    );
  const automationId =
    view === "automation" ? automationIdOf(initial) : undefined;
  if (automationId !== undefined)
    return (
      <section className="sidekick-start start-detail" aria-label={ta.kicker}>
        <AppFrame mode={frameMode}>
          <AutomationDetailView
            key={automationId}
            api={automations}
            t={ta}
            id={automationId}
            initial={
              isAutomationResult(initial) ? initial.automation : undefined
            }
            refreshKey={props.refreshKey}
          />
        </AppFrame>
      </section>
    );

  const id = view === "suggestion" ? suggestionIdOf(initial) : undefined;

  if (view === "suggestion" && id !== undefined) {
    const detail = isSuggestionDetail(initial) ? initial.suggestion : undefined;
    if (!full && detail)
      return (
        <SuggestionInlineCard
          api={api}
          t={t}
          detail={detail}
          onOpenFull={canOpenFull ? openFull : undefined}
          onOpenRecord={openRecord}
        />
      );
    return (
      <section className="sidekick-start start-detail" aria-label={t.kicker}>
        <AppFrame mode={full ? "full" : "inline"}>
          <SuggestionDetailView
            key={id}
            api={api}
            t={t}
            id={id}
            initial={detail}
            refreshKey={props.refreshKey}
            onOpenRecord={openRecord}
          />
        </AppFrame>
      </section>
    );
  }

  const decided = isUndo(initial)
    ? ({ undone: true } as const)
    : isDecisions(initial)
      ? initial
      : undefined;
  if (!full && view === "decided" && decided)
    return (
      <DecidedCard
        t={t}
        result={decided}
        onOpenFull={canOpenFull ? () => openFull() : undefined}
      />
    );

  const page = isSuggestionPage(initial) ? initial : undefined;
  if (!full)
    return (
      <SuggestionsCard
        api={api}
        t={t}
        initial={page}
        onOpenFull={canOpenFull ? openFull : undefined}
        onOpenRecord={openRecord}
      />
    );
  return (
    <AppFrame mode="full">
      <SuggestionsInbox
        api={api}
        t={t}
        initial={page}
        refreshKey={props.refreshKey}
        control={control}
        automations={
          automations.offered && onNavigate
            ? {
                label: ta.entry,
                onOpen: () => onNavigate(automationsTarget(ta)),
              }
            : undefined
        }
        lead={
          automations.offered && onNavigate ? (
            <AutomationsEntry
              api={automations}
              t={ta}
              refreshKey={props.refreshKey}
              onOpen={onNavigate}
            />
          ) : undefined
        }
        onOpenSuggestion={
          onNavigate
            ? (item) =>
                onNavigate({
                  room: "start",
                  view: "suggestion",
                  id: item.id,
                  label: suggestionTitle(item.effect, item.summary, t),
                })
            : undefined
        }
        onOpenRecord={openRecord}
      />
    </AppFrame>
  );
}

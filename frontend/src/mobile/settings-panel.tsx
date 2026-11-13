/**
 * The phone's settings (ADR-005): one screen above the rooms, opened from "Inställningar" at the end of every room's
 * ⋯ menu, where Control stands in Claude. It exists only in the mobile app: Claude has no phone to set.
 *
 * First "Språk": Svenska | English, the app's language (app-language.ts; the widget follows it). Then two sections,
 * each read on its own from the native side, each with its own reading line, failure and retry:
 * - Aviseringar: the push state in plain words (or that the server sends none, and then no fix and no test), "Skicka testavisering" with one calm line per outcome, and one sentence
 *   on the lock screen (see docs/decisions/log.md D-079: it follows the phone's own setting).
 * - "Den här telefonen": the device label, the server it is paired to, when it was paired, that the sign-in renews itself and until when it holds,
 *   and "Koppla från den här telefonen", which asks first (it clears the phone). After it, the pairing gate takes over.
 *
 * It fits one phone screen at 320 px and 110 % text: no list, no scroll. Nothing here reaches the network but through
 * the plugin.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import type { AppLocale } from "@/features/mcp-apps/app-locale";
import type { RoomId } from "@/features/mcp-apps/router";
import { sidekickShellLabelsFor } from "@/features/mcp-apps/sidekick-shell-labels";
import { LicenseRow } from "@/features/mcp-apps/license-mark";
import { BackHeader } from "@/features/mcp-apps/ui/back-header";
import { Button } from "@/features/mcp-apps/ui/button";
import { workDate } from "@/features/mcp-apps/ui/due";
import { AppFrame } from "@/features/mcp-apps/ui/layout";
import { Notice } from "@/features/mcp-apps/ui/notice";
import { ErrorNotice } from "@/features/mcp-apps/ui/states";
import type {
  SidekickNativePlugin,
  DeviceStatus,
  PushStatus,
  TestPushResult,
} from "./sidekick-native";
import { LanguageSwitch } from "./language-switch";
import { settingsLabelsFor, type SettingsLabels } from "./settings-labels";
import "./settings-panel.css";

export type SettingsNative = Pick<
  SidekickNativePlugin,
  | "pushStatus"
  | "deviceStatus"
  | "status"
  | "sendTestPush"
  | "unpair"
  | "openNotificationSettings"
  | "requestNotificationPermission"
  | "openNtfyInstall"
>;

export type SettingsPanelProps = {
  native: SettingsNative;
  locale: AppLocale;
  /** The room the settings were opened from: the Back row is named after it. */
  from: RoomId;
  /** Changes when the app comes back to the foreground: the owner may have changed the phone's settings meanwhile. */
  refreshKey: number;
  /** "‹ {room}" and system Back. */
  onBack: () => void;
  /** `unpair` resolved: the phone is cleared. The caller hands over to the pairing gate. */
  onUnpaired: (serverRevoked: boolean) => void;
  /** The clock of the dates; tests pass a fixed one. */
  now?: Date;
  /** Chooses the app's language: Svenska | English first in the settings. Absent: no such section. */
  onLocale?: (locale: AppLocale) => void;
};

/** A native read: reading, read, or failed (with a retry). `read` must be stable (useCallback). */
type Read<T> =
  | { phase: "reading" }
  | { phase: "ready"; value: T }
  | { phase: "failed" };

function useNativeRead<T>(
  read: () => Promise<T>,
  refreshKey: number,
): [Read<T>, () => void] {
  const [state, setState] = useState<Read<T>>({ phase: "reading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    read().then(
      (value) => {
        if (live) setState({ phase: "ready", value });
      },
      () => {
        if (live) setState({ phase: "failed" });
      },
    );
    return () => {
      live = false;
    };
  }, [read, refreshKey, attempt]);
  return [
    state,
    () => {
      setState({ phase: "reading" });
      setAttempt((value) => value + 1);
    },
  ];
}

export function SettingsPanel({
  native,
  locale,
  from,
  refreshKey,
  onBack,
  onUnpaired,
  now,
  onLocale,
}: SettingsPanelProps) {
  const labels = settingsLabelsFor(locale);
  const root = useRef<HTMLElement>(null);
  // The pairing is read once: its section shows it, and Aviseringar learn from it whether the server sends any.
  const readDevice = useCallback(() => native.deviceStatus(), [native]);
  const [device, retryDevice] = useNativeRead(readDevice, refreshKey);
  // Which server the phone is paired to; a failed read only leaves that line out.
  const readServer = useCallback(() => native.status(), [native]);
  const [pairing] = useNativeRead(readServer, refreshKey);
  const serverHost =
    pairing.phase === "ready" ? pairing.value.serverHost : undefined;
  // The settings replace the room on screen: the focus moves to them, as the shell moves it to a new layer.
  useEffect(() => {
    root.current?.focus();
  }, []);
  return (
    <AppFrame mode="full">
      <section
        ref={root}
        className="mobile-settings"
        aria-label={labels.title}
        tabIndex={-1}
        lang={locale}
      >
        <BackHeader
          label={sidekickShellLabelsFor(locale).rooms[from]}
          onBack={onBack}
          title={labels.title}
        />
        {onLocale ? (
          <>
            <h3 className="mobile-settings__section">
              {labels.languageHeading}
            </h3>
            <LanguageSwitch
              locale={locale}
              onChange={onLocale}
              label={labels.languageHeading}
            />
          </>
        ) : null}
        <h3 className="mobile-settings__section">
          {labels.notificationsHeading}
        </h3>
        <PushSection
          native={native}
          labels={labels}
          locale={locale}
          refreshKey={refreshKey}
          serverOff={
            device.phase === "ready" && device.value.pushEnabled === false
          }
        />
        <h3 className="mobile-settings__section">{labels.phoneHeading}</h3>
        <DeviceSection
          native={native}
          device={device}
          serverHost={serverHost}
          retry={retryDevice}
          labels={labels}
          locale={locale}
          onUnpaired={onUnpaired}
          now={now}
        />
        {/* The license row comes last, after a hairline and without a heading of its own (see docs/decisions/log.md D-083). */}
        <LicenseRow locale={locale} now={now && (() => now)} />
      </section>
    </AppFrame>
  );
}

/** The push state in plain words, in the order the owner fixes them: the app first, then the permission. */
export function pushStateText(labels: SettingsLabels, status: PushStatus) {
  if (!status.distributor) return labels.push.install;
  if (status.permission === "denied") return labels.push.denied;
  if (!status.registered || status.permission === "prompt")
    return labels.push.registering;
  return labels.push.on;
}

/** What the owner can do about the push state, if anything: the one button under the state line. */
export type PushFix = "getNtfy" | "openSettings" | "allow";

export function pushFixFor(status: PushStatus): PushFix | undefined {
  if (!status.distributor) return "getNtfy";
  if (status.permission === "denied") return "openSettings";
  if (status.permission === "prompt") return "allow";
  return undefined;
}

/** "Högst 5 testaviseringar i timmen. Försök igen om N min": whole minutes, at least 1. */
function retryMinutes(seconds: number | undefined): number | undefined {
  if (seconds === undefined || !Number.isFinite(seconds) || seconds < 0)
    return undefined;
  return Math.max(1, Math.ceil(seconds / 60));
}

/** The line under "Skicka testavisering": a sent one is a success, a refusal plain information, no answer a failure. */
type Feedback = { tone: "ok" | "info" | "error"; text: string };

export function testPushFeedback(
  labels: SettingsLabels,
  result: TestPushResult | undefined,
): Feedback {
  if (!result) return { tone: "error", text: labels.outcomes.failed };
  switch (result.outcome) {
    case "queued":
      return { tone: "ok", text: labels.outcomes.queued };
    case "rate_limited":
      return {
        tone: "info",
        text: labels.rateLimited(retryMinutes(result.retryAfterSeconds)),
      };
    case "offline":
      return { tone: "error", text: labels.outcomes.offline };
    case "no_subscription":
    case "disabled":
    case "unpaired":
      return { tone: "info", text: labels.outcomes[result.outcome] };
    default:
      return { tone: "error", text: labels.outcomes.failed };
  }
}

function PushSection({
  native,
  labels,
  locale,
  refreshKey,
  serverOff,
}: {
  native: SettingsNative;
  labels: SettingsLabels;
  locale: AppLocale;
  refreshKey: number;
  /** The pairing says the server sends no notifications: no fix and no test, and the state line says so. */
  serverOff: boolean;
}) {
  const readPush = useCallback(() => native.pushStatus(), [native]);
  const [status, retry] = useNativeRead(readPush, refreshKey);
  const [sending, setSending] = useState(false);
  const [feedback, setFeedback] = useState<Feedback | undefined>();
  const fix =
    status.phase === "ready" && !serverOff
      ? pushFixFor(status.value)
      : undefined;

  /** A fix leaves the app (a store page, the phone's settings) or asks the system: the state is read again after it. */
  function applyFix(which: PushFix) {
    const action =
      which === "getNtfy"
        ? native.openNtfyInstall()
        : which === "openSettings"
          ? native.openNotificationSettings()
          : native.requestNotificationPermission();
    action.then(retry, retry);
  }

  function send() {
    if (sending || serverOff) return;
    setSending(true);
    setFeedback(undefined);
    native.sendTestPush().then(
      (result) => {
        setFeedback(testPushFeedback(labels, result));
        setSending(false);
      },
      () => {
        setFeedback(testPushFeedback(labels, undefined));
        setSending(false);
      },
    );
  }

  return (
    <div className="mobile-settings__block">
      {status.phase === "reading" ? (
        <p role="status" className="mobile-settings__meta">
          {labels.loading}
        </p>
      ) : status.phase === "failed" ? (
        <ErrorNotice
          locale={locale}
          message={labels.pushFailed}
          placement="row"
          onRetry={retry}
        />
      ) : (
        <p className="mobile-settings__text">
          {serverOff
            ? labels.push.serverOff
            : pushStateText(labels, status.value)}
        </p>
      )}
      <p className="mobile-settings__meta">{labels.lockScreen}</p>
      <div className="mobile-settings__actions">
        {fix ? (
          <Button variant="secondary" onClick={() => applyFix(fix)}>
            {labels.push[fix]}
          </Button>
        ) : null}
        <Button
          variant="secondary"
          // With push off on the server there is nothing to test: the button stays, off, and the line above says why.
          aria-disabled={sending || serverOff || undefined}
          aria-busy={sending || undefined}
          onClick={send}
        >
          {sending ? labels.sending : labels.sendTest}
        </Button>
      </div>
      {feedback ? (
        feedback.tone === "error" ? (
          <ErrorNotice
            locale={locale}
            message={feedback.text}
            placement="row"
          />
        ) : (
          <Notice
            tone={feedback.tone === "ok" ? "success" : undefined}
            className="mobile-settings__feedback"
          >
            {feedback.text}
          </Notice>
        )
      ) : null}
    </div>
  );
}

function DeviceSection({
  native,
  device,
  serverHost,
  retry,
  labels,
  locale,
  onUnpaired,
  now,
}: {
  native: SettingsNative;
  device: Read<DeviceStatus>;
  serverHost: string | undefined;
  retry: () => void;
  labels: SettingsLabels;
  locale: AppLocale;
  onUnpaired: (serverRevoked: boolean) => void;
  now: Date | undefined;
}) {
  if (device.phase === "reading")
    return (
      <p role="status" className="mobile-settings__meta">
        {labels.loading}
      </p>
    );
  if (device.phase === "failed")
    return (
      <ErrorNotice
        locale={locale}
        message={labels.deviceFailed}
        placement="row"
        onRetry={retry}
      />
    );
  if (!device.value.paired)
    return <p className="mobile-settings__text">{labels.notPaired}</p>;
  return (
    <div className="mobile-settings__block">
      <DeviceLines
        device={device.value}
        serverHost={serverHost}
        labels={labels}
        now={now}
      />
      <Unpair
        native={native}
        labels={labels}
        locale={locale}
        onUnpaired={onUnpaired}
      />
    </div>
  );
}

function DeviceLines({
  device,
  serverHost,
  labels,
  now = new Date(),
}: {
  device: DeviceStatus;
  serverHost: string | undefined;
  labels: SettingsLabels;
  now?: Date;
}) {
  const date = (value: string | undefined) =>
    workDate(value, now, labels.dateLocale, {
      inline: true,
      relative: false,
    });
  const since = date(device.pairedAt);
  const until = date(device.expiresAt);
  return (
    <>
      <p className="mobile-settings__name">
        {device.name?.trim() || labels.unnamed}
      </p>
      {serverHost ? (
        <p className="mobile-settings__meta">{labels.server(serverHost)}</p>
      ) : null}
      {since ? (
        <p className="mobile-settings__meta">{labels.pairedSince(since)}</p>
      ) : null}
      <p className="mobile-settings__meta">
        {until ? `${labels.renews} ${labels.validUntil(until)}` : labels.renews}
      </p>
    </>
  );
}

/**
 * "Koppla från den här telefonen". The first press asks; the confirm button takes the focus, and Avbryt gives it back
 * to the first button (as ContactArchiveToggle does).
 */
function Unpair({
  native,
  labels,
  locale,
  onUnpaired,
}: {
  native: SettingsNative;
  labels: SettingsLabels;
  locale: AppLocale;
  onUnpaired: (serverRevoked: boolean) => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const actionButton = useRef<HTMLButtonElement>(null);
  const confirmButton = useRef<HTMLButtonElement>(null);
  const restoreFocus = useRef(false);
  useEffect(() => {
    if (confirming) confirmButton.current?.focus();
    else if (restoreFocus.current) {
      restoreFocus.current = false;
      actionButton.current?.focus();
    }
  }, [confirming]);

  function confirm() {
    if (busy) return;
    setBusy(true);
    setFailed(false);
    native.unpair().then(
      (result) => onUnpaired(result.serverRevoked),
      () => {
        setBusy(false);
        setFailed(true);
        restoreFocus.current = true;
        setConfirming(false);
      },
    );
  }

  if (!confirming)
    return (
      <>
        <div className="mobile-settings__actions">
          <button
            ref={actionButton}
            type="button"
            className="sk-btn sk-btn--danger mobile-settings__unpair"
            onClick={() => setConfirming(true)}
          >
            {labels.unpair}
          </button>
        </div>
        {failed ? (
          <ErrorNotice
            locale={locale}
            message={labels.unpairFailed}
            placement="row"
          />
        ) : null}
      </>
    );
  return (
    <div className="mobile-settings__confirm">
      <p className="mobile-settings__text">{labels.unpairQuestion}</p>
      <div className="mobile-settings__actions">
        <button
          ref={confirmButton}
          type="button"
          className="sk-btn sk-btn--danger mobile-settings__unpair"
          aria-disabled={busy || undefined}
          aria-busy={busy || undefined}
          onClick={confirm}
        >
          {busy ? labels.unpairing : labels.unpairConfirm}
        </button>
        <button
          type="button"
          className="sk-btn sk-btn--quiet"
          aria-disabled={busy || undefined}
          onClick={() => {
            if (busy) return;
            restoreFocus.current = true;
            setConfirming(false);
          }}
        >
          {labels.cancel}
        </button>
      </div>
    </div>
  );
}

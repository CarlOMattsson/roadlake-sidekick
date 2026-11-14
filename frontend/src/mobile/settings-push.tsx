/**
 * The Aviseringar section of the phone's settings: the push state in plain words, the one fix the owner can apply,
 * and `sendTest` with one calm line per outcome. It reads the push state from the native side on its own.
 */
import { useCallback, useState } from "react";

import type { AppLocale } from "@/features/mcp-apps/app-locale";
import { Button } from "@/features/mcp-apps/ui/button";
import { Notice } from "@/features/mcp-apps/ui/notice";
import { ErrorNotice } from "@/features/mcp-apps/ui/states";
import type {
  SidekickNativePlugin,
  PushStatus,
  TestPushResult,
} from "./sidekick-native";
import type { SettingsLabels } from "./settings-labels";
import { useRead } from "@/features/mcp-apps/ui/use-read";

/** What the section asks of the native side. */
export type PushNative = Pick<
  SidekickNativePlugin,
  | "pushStatus"
  | "sendTestPush"
  | "openNotificationSettings"
  | "requestNotificationPermission"
  | "openNtfyInstall"
>;

/** The push state in plain words, in the order the owner fixes them: the app first, then the permission. */
function pushStateText(labels: SettingsLabels, status: PushStatus) {
  if (!status.distributor) return labels.push.install;
  if (status.permission === "denied") return labels.push.denied;
  if (!status.registered || status.permission === "prompt")
    return labels.push.registering;
  return labels.push.on;
}

/** Whether notifications reach this phone: the app is there, allowed and registered. */
function pushIsOn(status: PushStatus) {
  return (
    status.distributor && status.permission === "granted" && status.registered
  );
}

/** What the owner can do about the push state, if anything: the one button under the state line. */
type PushFix = "getNtfy" | "openSettings" | "allow";

function pushFixFor(status: PushStatus): PushFix | undefined {
  if (!status.distributor) return "getNtfy";
  if (status.permission === "denied") return "openSettings";
  if (status.permission === "prompt") return "allow";
  return undefined;
}

/** The rate-limit line with the wait: whole minutes, at least 1. */
function retryMinutes(seconds: number | undefined): number | undefined {
  if (seconds === undefined || !Number.isFinite(seconds) || seconds < 0)
    return undefined;
  return Math.max(1, Math.ceil(seconds / 60));
}

/** The line under `sendTest`: a sent one is a success, a refusal plain information, no answer a failure. */
type Feedback = { tone: "ok" | "info" | "error"; text: string };

function testPushFeedback(
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

export function PushSection({
  native,
  labels,
  locale,
  refreshKey,
  serverOff,
}: {
  native: PushNative;
  labels: SettingsLabels;
  locale: AppLocale;
  refreshKey: number;
  /** The pairing says the server sends no notifications: no fix and no test, and the state line says so. */
  serverOff: boolean;
}) {
  const readPush = useCallback(() => native.pushStatus(), [native]);
  const [status, retry] = useRead(readPush, refreshKey);
  const [sending, setSending] = useState(false);
  const [feedback, setFeedback] = useState<Feedback | undefined>();
  const fix =
    status.phase === "ready" && !serverOff
      ? pushFixFor(status.value)
      : undefined;
  // The lock-screen sentence is only about notifications that arrive: it is left out while they are off or not allowed.
  const showLockScreenNote =
    status.phase === "ready" && !serverOff && pushIsOn(status.value);

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
      {showLockScreenNote ? (
        <p className="mobile-settings__meta">{labels.lockScreen}</p>
      ) : null}
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

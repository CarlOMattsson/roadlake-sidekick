/**
 * The pairing form of the mobile app: the server address and the pairing code, or the "Connect to <host>?" question when
 * a pairing link filled them in. It pairs through `SidekickNative.pair`; the credential never reaches the page.
 */
import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import type { AppLocale } from "@/features/mcp-apps/app-locale";
import { Button } from "@/features/mcp-apps/ui/button";
import { ErrorNotice } from "@/features/mcp-apps/ui/states";
import { nativeErrorCode, type SidekickNativePlugin } from "./sidekick-native";
import { pairingErrorMessage, type PairingLabels } from "./pairing-labels";
import type { PairingLink } from "./pairing-link";
import {
  codeProblem,
  hostOf,
  serverProblem,
  withScheme,
  type CodeProblem,
  type ServerProblem,
} from "./pairing-validation";

/**
 * The server address of the last pairing, offered again in the form after a disconnect. Only the address: the
 * code is never kept. In the page's own storage, so it goes with the app's data.
 */
export const LAST_SERVER_KEY = "sidekick.lastServer";

function lastServer(): string {
  try {
    return localStorage.getItem(LAST_SERVER_KEY) ?? "";
  } catch {
    return "";
  }
}

function rememberServer(address: string) {
  try {
    localStorage.setItem(LAST_SERVER_KEY, address);
  } catch {
    // Without storage the field starts empty next time.
  }
}

/** What is wrong with each field, as the text shown by it. */
type FieldErrors = { server?: string; code?: string };

function serverText(labels: PairingLabels, problem: ServerProblem): string {
  return problem === "required"
    ? labels.fieldErrors.serverRequired
    : labels.fieldErrors.serverInvalid;
}

function codeText(labels: PairingLabels, problem: CodeProblem): string {
  return problem === "required"
    ? labels.fieldErrors.codeRequired
    : problem === "short"
      ? labels.fieldErrors.codeShort
      : labels.fieldErrors.codeInvalid;
}

export function PairingForm({
  native,
  labels,
  locale,
  note,
  link,
  onPaired,
}: {
  native: Pick<SidekickNativePlugin, "pair" | "status">;
  labels: PairingLabels;
  locale: AppLocale;
  /** The line over the form, when the form is shown again. */
  note: string | undefined;
  /** A pairing link that filled in the fields; the user is asked before it is used. */
  link: PairingLink | undefined;
  onPaired: () => void;
}) {
  const id = useId();
  const [serverUrl, setServerUrl] = useState(
    () => link?.serverUrl ?? lastServer(),
  );
  const [secret, setSecret] = useState(link?.code ?? "");
  const [secretShown, setSecretShown] = useState(false);
  const [confirming, setConfirming] = useState(link !== undefined);
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [problem, setProblem] = useState<string | undefined>();
  const serverInput = useRef<HTMLInputElement>(null);
  const secretInput = useRef<HTMLInputElement>(null);
  const actions = useRef<HTMLDivElement>(null);

  // The keyboard covers the lower part of the page: keep the button in view while a field has focus and when the
  // keyboard opens or closes.
  useEffect(() => {
    const viewport = window.visualViewport;
    if (!viewport) return undefined;
    const reveal = () => {
      if (document.activeElement instanceof HTMLInputElement)
        actions.current?.scrollIntoView?.({ block: "end" });
    };
    viewport.addEventListener("resize", reveal);
    return () => viewport.removeEventListener("resize", reveal);
  }, []);

  function revealButton() {
    window.setTimeout(
      () => actions.current?.scrollIntoView?.({ block: "end" }),
      250,
    );
  }

  function pair(address: string, code: string) {
    setBusy(true);
    setProblem(undefined);
    native
      .pair({ serverUrl: withScheme(address), pairingSecret: code.trim() })
      .then(
        () => {
          rememberServer(withScheme(address));
          onPaired();
        },
        (error: unknown) => {
          const closed = nativeErrorCode(error);
          const message = pairingErrorMessage(labels, closed);
          if (closed === "already_paired") {
            // The phone is paired after all (a second pairing, a stale screen): read the status again and open the
            // app. The sentence stays as the reserve when the status says the phone is not paired.
            native.status().then(
              (status) => {
                if (status.paired) return onPaired();
                setProblem(message);
                setConfirming(false);
                setBusy(false);
              },
              () => {
                setProblem(message);
                setConfirming(false);
                setBusy(false);
              },
            );
            return;
          }
          // A refusal of one field is shown by that field; the rest (network, timeout, ...) is the form's.
          if (closed === "invalid_server_url") {
            setErrors({ server: message });
            serverInput.current?.focus();
          } else if (
            closed === "invalid_pairing_secret" ||
            closed === "pairing_invalid"
          ) {
            setErrors({ code: message });
            secretInput.current?.focus();
          } else {
            setProblem(message);
          }
          setConfirming(false);
          setBusy(false);
        },
      );
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    const server = serverProblem(serverUrl);
    const code = codeProblem(secret);
    setErrors({
      server: server && serverText(labels, server),
      code: code && codeText(labels, code),
    });
    if (server) return serverInput.current?.focus();
    if (code) return secretInput.current?.focus();
    pair(serverUrl, secret);
  }

  function edit(field: keyof FieldErrors, set: (value: string) => void) {
    return (value: string) => {
      set(value);
      setErrors((current) => ({ ...current, [field]: undefined }));
    };
  }

  function cancelLink() {
    setServerUrl("");
    setSecret("");
    setConfirming(false);
  }

  if (confirming) {
    const host = hostOf(serverUrl);
    return (
      <>
        <h1 className="mobile-pairing__title">
          {labels.confirmTitle.replace("{host}", host)}
        </h1>
        <p className="mobile-pairing__intro">
          {labels.confirmBody.replaceAll("{host}", host)}
        </p>
        <div className="mobile-pairing__form" ref={actions}>
          <Button
            variant="primary"
            aria-disabled={busy || undefined}
            onClick={() => {
              if (!busy) pair(serverUrl, secret);
            }}
          >
            {busy ? labels.submitting : labels.confirm}
          </Button>
          <Button variant="quiet" disabled={busy} onClick={cancelLink}>
            {labels.cancel}
          </Button>
        </div>
      </>
    );
  }

  const serverError = errors.server;
  const codeError = errors.code;
  return (
    <>
      <h1 className="mobile-pairing__title">{labels.title}</h1>
      <p className="mobile-pairing__intro">{labels.intro}</p>
      {note ? (
        <p role="status" className="mobile-pairing__hint">
          {note}
        </p>
      ) : null}
      <details className="mobile-pairing__help">
        <summary>{labels.helpTitle}</summary>
        <p>{labels.helpBody}</p>
        <p>{labels.helpLink}</p>
      </details>
      <form className="mobile-pairing__form" onSubmit={submit} noValidate>
        <div className="mobile-pairing__field">
          <label className="mobile-pairing__label" htmlFor={`${id}-server`}>
            {labels.serverLabel}
          </label>
          <input
            ref={serverInput}
            id={`${id}-server`}
            className="mobile-pairing__input"
            type="url"
            inputMode="url"
            enterKeyHint="next"
            autoComplete="off"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            placeholder={labels.serverPlaceholder}
            aria-invalid={serverError ? true : undefined}
            aria-describedby={serverError ? `${id}-server-error` : undefined}
            value={serverUrl}
            disabled={busy}
            onFocus={revealButton}
            onChange={(event) =>
              edit("server", setServerUrl)(event.target.value)
            }
          />
          {serverError ? (
            <p
              id={`${id}-server-error`}
              role="alert"
              className="mobile-pairing__error"
            >
              {serverError}
            </p>
          ) : null}
        </div>
        <div className="mobile-pairing__field">
          <label className="mobile-pairing__label" htmlFor={`${id}-secret`}>
            {labels.secretLabel}
          </label>
          <div className="mobile-pairing__secret">
            {/* Masked: the code is a credential. Not a one-time-code field, which would offer SMS autofill. */}
            <input
              ref={secretInput}
              id={`${id}-secret`}
              className="mobile-pairing__input"
              type={secretShown ? "text" : "password"}
              enterKeyHint="go"
              autoComplete="off"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              aria-invalid={codeError ? true : undefined}
              aria-describedby={
                codeError ? `${id}-secret-error ${id}-hint` : `${id}-hint`
              }
              value={secret}
              disabled={busy}
              onFocus={revealButton}
              onChange={(event) => edit("code", setSecret)(event.target.value)}
            />
            <button
              type="button"
              className="mobile-pairing__reveal"
              aria-pressed={secretShown}
              disabled={busy}
              onClick={() => setSecretShown((shown) => !shown)}
            >
              {secretShown ? labels.hideSecret : labels.showSecret}
            </button>
          </div>
          {codeError ? (
            <p
              id={`${id}-secret-error`}
              role="alert"
              className="mobile-pairing__error"
            >
              {codeError}
            </p>
          ) : null}
          <p id={`${id}-hint`} className="mobile-pairing__hint">
            {labels.secretHint}
          </p>
        </div>
        {problem ? (
          <ErrorNotice locale={locale} message={problem} placement="row" />
        ) : null}
        <div ref={actions}>
          <Button
            type="submit"
            variant="primary"
            aria-disabled={busy || undefined}
          >
            {busy ? labels.submitting : labels.submit}
          </Button>
        </div>
      </form>
    </>
  );
}

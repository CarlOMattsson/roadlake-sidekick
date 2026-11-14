/**
 * The pairing form of the mobile app: the server address and the pairing code, or the "Connect to <host>?" question when
 * a pairing link filled them in. It pairs through `SidekickNative.pair`; the credential never reaches the page.
 */
import { useId } from "react";

import type { AppLocale } from "@/features/mcp-apps/app-locale";
import { Button } from "@/features/mcp-apps/ui/button";
import { ErrorNotice } from "@/features/mcp-apps/ui/states";
import type { SidekickNativePlugin } from "./sidekick-native";
import type { PairingLabels } from "./pairing-labels";
import type { PairingLink } from "./pairing-link";
import { hostOf } from "./pairing-validation";
import { usePairingForm } from "./use-pairing-form";

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
  const {
    serverUrl,
    secret,
    secretShown,
    setSecretShown,
    confirming,
    check,
    busy,
    errors,
    problem,
    serverInput,
    secretInput,
    actions,
    revealButton,
    pair,
    submit,
    editServer,
    editCode,
    cancelLink,
  } = usePairingForm({ native, labels, link, onPaired });

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
        {check ? (
          <div className="mobile-pairing__check">
            <p className="mobile-pairing__check-code">
              {labels.confirmCheck.replace("{check}", check)}
            </p>
            <p className="mobile-pairing__hint">{labels.confirmCheckHelp}</p>
          </div>
        ) : null}
        {check === null ? (
          <p role="alert" className="mobile-pairing__error">
            {labels.confirmCheckMissing}
          </p>
        ) : null}
        <div className="mobile-pairing__form" ref={actions}>
          <Button
            variant="primary"
            disabled={!check}
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
            onChange={(event) => editServer(event.target.value)}
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
              onChange={(event) => editCode(event.target.value)}
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

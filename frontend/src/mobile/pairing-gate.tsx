/**
 * The pairing gate of the mobile app: until the phone is paired with a Sidekick server, the app shows this form (server
 * address and pairing code) and nothing else; once paired, it mounts the app. It belongs to the shell around the
 * rooms, not to any room. The credential never reaches the page: `SidekickNative.pair` keeps it in the Keystore.
 *
 * A pairing link (`sidekick://pair?server=…&code=…`, printed by the server's pairing command) fills in both fields and
 * asks "Connect to <host>?". It never pairs by itself, because any app or page can open such a link.
 *
 * When the server refuses the stored credential (`pairingLost`), the gate returns to the form with a line saying so.
 * The app inside disconnects the phone itself through `PairingGateContext` (the settings' "Koppla från"): the gate
 * then returns to the form with a line that says the phone is disconnected.
 */
import {
  createContext,
  Fragment,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";

import type { AppLocale } from "@/features/mcp-apps/app-locale";
import { Button } from "@/features/mcp-apps/ui/button";
import { ErrorNotice } from "@/features/mcp-apps/ui/states";
import { nativeErrorCode, type SidekickNativePlugin } from "./sidekick-native";
import { useSafeAreaInsets } from "./insets";
import {
  pairingErrorMessage,
  pairingLabelsFor,
  type PairingLabels,
} from "./pairing-labels";
import type { PairingLink } from "./pairing-link";
import {
  codeProblem,
  hostOf,
  serverProblem,
  withScheme,
  type CodeProblem,
  type ServerProblem,
} from "./pairing-validation";
import { LanguageSwitch } from "./language-switch";
import type { MobilePlatform } from "./platform";
import "./pairing.css";

/**
 * The server address of the last pairing, offered again in the form after a disconnect (ua-17). Only the address: the
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

type Phase = "reading" | "unreadable" | "unpaired" | "paired";

/** Why the form is shown again: the server refused the credential, or the owner disconnected the phone. */
type Note = "lost" | "unpaired" | "unpairedUnconfirmed";

/**
 * Given by the gate to the paired app: `unpaired(serverRevoked)` after `SidekickNative.unpair` resolved. The gate shows
 * the form again. Absent outside a gate.
 */
export const PairingGateContext = createContext<
  | {
      unpaired: (serverRevoked: boolean) => void;
      /**
       * A pairing link reached a phone that is already paired and was dropped: the line the app shows once to say so,
       * with the label of the button that dismisses it. Absent when there is nothing to say.
       */
      linkNotice?: { text: string; dismiss: string };
      dismissLinkNotice: () => void;
    }
  | undefined
>(undefined);

/** The reading of the pairing shows no text before this, so a quick read (a cold start of a paired phone) flashes none. */
export const READING_NOTE_AFTER_MS = 400;

export type PairingGateProps = {
  native: Pick<SidekickNativePlugin, "status" | "pair" | "addListener">;
  platform: MobilePlatform;
  /** The language of the gate's own texts: the app's (Swedish by default), not the phone's. */
  locale: AppLocale;
  /** The app, mounted once the phone is paired. A fresh instance after each pairing. */
  children: ReactNode;
  /** Chooses the app's language (Svenska | English at the top of the form). Absent: no switch. */
  onLocale?: (locale: AppLocale) => void;
};

export function PairingGate({
  native,
  platform,
  locale,
  children,
  onLocale,
}: PairingGateProps) {
  const labels = pairingLabelsFor(locale);
  const [phase, setPhase] = useState<Phase>("reading");
  const [note, setNote] = useState<Note | undefined>();
  const [epoch, setEpoch] = useState(0);
  const [attempt, setAttempt] = useState(0);
  // The server the phone is paired to, as the last status said it, and a link that was dropped because of it.
  const [serverHost, setServerHost] = useState<string | undefined>();
  const [linkDropped, setLinkDropped] = useState(false);
  // The latest link, with a counter so that the same link opened twice asks again.
  const [link, setLink] = useState<
    { link: PairingLink; n: number } | undefined
  >(() => {
    const first = platform.pairingLink?.();
    return first ? { link: first, n: 0 } : undefined;
  });

  const linkNow = useRef(link);
  useEffect(() => {
    linkNow.current = link;
  }, [link]);

  useSafeAreaInsets(platform);

  // A link that arrives on a phone that is already paired is dropped: it must not wait there and ask after a
  // later disconnect.
  const pairedNow = useRef(false);
  useEffect(() => {
    pairedNow.current = phase === "paired";
  }, [phase]);
  useEffect(
    () =>
      platform.onPairingLink?.((next) => {
        if (pairedNow.current) setLinkDropped(true);
        else setLink((current) => ({ link: next, n: (current?.n ?? 0) + 1 }));
      }),
    [platform],
  );

  useEffect(() => {
    let live = true;
    native.status().then(
      (status) => {
        if (!live) return;
        if (status.paired) {
          // A link that opened this cold start on a paired phone is dropped, and the app says so.
          if (linkNow.current) setLinkDropped(true);
          setLink(undefined);
          setServerHost(status.serverHost);
        }
        setPhase(status.paired ? "paired" : "unpaired");
      },
      () => {
        if (live) setPhase("unreadable");
      },
    );
    return () => {
      live = false;
    };
  }, [native, attempt]);

  function retry() {
    setPhase("reading");
    setAttempt((value) => value + 1);
  }

  // The server refused the credential: back to the form.
  useEffect(() => {
    const handle = native.addListener("pairingLost", () => {
      setNote("lost");
      setPhase("unpaired");
    });
    return () => {
      void handle.then((registered) => registered.remove());
    };
  }, [native]);

  // The gate has no layer of its own: Back leaves the app.
  useEffect(
    () => (phase === "paired" ? undefined : platform.onBack(() => false)),
    [platform, phase],
  );

  const gate = useMemo(
    () => ({
      unpaired: (serverRevoked: boolean) => {
        setNote(serverRevoked ? "unpaired" : "unpairedUnconfirmed");
        setLinkDropped(false);
        setPhase("unpaired");
      },
      linkNotice: linkDropped
        ? {
            text: (serverHost
              ? labels.linkIgnored
              : labels.linkIgnoredNoHost
            ).replace("{host}", serverHost ?? ""),
            dismiss: labels.dismiss,
          }
        : undefined,
      dismissLinkNotice: () => setLinkDropped(false),
    }),
    [linkDropped, serverHost, labels],
  );

  if (phase === "paired")
    return (
      <PairingGateContext.Provider value={gate}>
        <Fragment key={epoch}>{children}</Fragment>
      </PairingGateContext.Provider>
    );

  return (
    <main className="mobile-pairing" lang={locale}>
      {onLocale && phase !== "reading" ? (
        <LanguageSwitch
          compact
          locale={locale}
          onChange={onLocale}
          label={labels.language}
        />
      ) : null}
      {phase === "reading" ? (
        <ReadingNote text={labels.loading} />
      ) : phase === "unreadable" ? (
        <ErrorNotice
          locale={locale}
          message={labels.statusFailed}
          onRetry={retry}
        />
      ) : (
        <PairingForm
          key={link?.n ?? "typed"}
          native={native}
          labels={labels}
          locale={locale}
          note={note && labels[note]}
          link={link?.link}
          onPaired={() => {
            setLink(undefined);
            setNote(undefined);
            setEpoch((value) => value + 1);
            setPhase("paired");
          }}
        />
      )}
    </main>
  );
}

/**
 * The pairing is being read. A paired phone passes through here on every cold start and is on its way to the rooms, so
 * there is no heading and, at first, no text: only the calm background. The status line appears if the read is slow.
 */
function ReadingNote({ text }: { text: string }) {
  const [late, setLate] = useState(false);
  useEffect(() => {
    const timer = window.setTimeout(() => setLate(true), READING_NOTE_AFTER_MS);
    return () => window.clearTimeout(timer);
  }, []);
  return (
    <p role="status" className="mobile-pairing__intro">
      {late ? text : null}
    </p>
  );
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

function PairingForm({
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

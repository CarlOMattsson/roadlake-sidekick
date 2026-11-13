/**
 * The state of the pairing form: its fields, their problems, and the pairing itself through `SidekickNative.pair`.
 * The credential never reaches the page.
 */
import { useEffect, useRef, useState, type FormEvent } from "react";

import { nativeErrorCode, type SidekickNativePlugin } from "./sidekick-native";
import { pairingErrorMessage, type PairingLabels } from "./pairing-labels";
import type { PairingLink } from "./pairing-link";
import {
  codeProblem,
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

export function usePairingForm({
  native,
  labels,
  link,
  onPaired,
}: {
  native: Pick<SidekickNativePlugin, "pair" | "status">;
  labels: PairingLabels;
  link: PairingLink | undefined;
  onPaired: () => void;
}) {
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

  return {
    serverUrl,
    secret,
    secretShown,
    setSecretShown,
    confirming,
    busy,
    errors,
    problem,
    serverInput,
    secretInput,
    actions,
    revealButton,
    pair,
    submit,
    editServer: edit("server", setServerUrl),
    editCode: edit("code", setSecret),
    cancelLink,
  };
}

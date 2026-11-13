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
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import type { AppLocale } from "@/features/mcp-apps/app-locale";
import { ErrorNotice } from "@/features/mcp-apps/ui/states";
import type { SidekickNativePlugin } from "./sidekick-native";
import { useSafeAreaInsets } from "./insets";
import { pairingLabelsFor } from "./pairing-labels";
import { PairingForm } from "./pairing-form";
import type { PairingLink } from "./pairing-link";
import { LanguageSwitch } from "./language-switch";
import type { MobilePlatform } from "./platform";
import "./pairing.css";

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

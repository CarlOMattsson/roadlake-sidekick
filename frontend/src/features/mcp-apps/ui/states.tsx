import { useContext, useEffect, useRef, useState, type ReactNode } from "react";

import { RoomSurfaceContext } from "./room-context";
import "./states.css";
import "./family.css";
import "../awaiting.css";

/**
 * Loading, empty and error states for MCP App surfaces. Texts that belong to a surface
 * (empty titles, hints, row errors) come in as props. The read error sentence and the retry label
 * are built in, following the same sv/en-by-locale rule as `AwaitingResult`, so the bundle does not
 * pull in the Sidekick app catalogue. Every app shows a failed read with this same sentence.
 */

const errorEn = {
  message: "Couldn’t load this right now.",
  retry: "Try again",
  /** While a retry runs. */
  retrying: "Trying again…",
  /** The second line of a failed read, only what `maybeConnection(cause)` knows: no answer from Sidekick, */
  silent: "Sidekick didn’t respond.",
  /** then, only when the request itself failed or the device is offline; else nothing more. */
  network: "Check your connection.",
  /** or Sidekick's own error code. */
  answered: "Sidekick responded with an error.",
  /** A list that was shown could not be read again; it stays. */
  refresh: "Couldn’t refresh",
  /** The app could not start (handshake with the host, a missing host or platform). */
  startup: "Sidekick couldn’t start",
  /** A room failed while drawing; the rest of the app keeps working. */
  render: "This view couldn’t be shown",
  /**
   * The heading of a failed read, by what the layer shows: "room:view" first, then "room". Anything else
   * gets `message`. Keep the keys equal in both languages (ui-states test).
   */
  subjects: {
    work: "Couldn’t load your tasks",
    "work:task": "Couldn’t load the task",
    "work:project": "Couldn’t load the project",
    "work:process": "Couldn’t load the process",
    "work:hierarchy": "Couldn’t load your projects",
    journal: "Couldn’t load your journal",
    "journal:entry": "Couldn’t load the entry",
    "journal:card": "Couldn’t load the entry",
    "journal:draft": "Couldn’t load the draft",
    contacts: "Couldn’t load your contacts",
    "contacts:contact": "Couldn’t load the contact",
    "contacts:compact": "Couldn’t load the contact",
    shopping: "Couldn’t load the shopping list",
    "shopping:lists": "Couldn’t load your lists",
    control: "Couldn’t load Memory and control",
    "control:trash": "Couldn’t load deleted items",
    "control:history": "Couldn’t load the history",
    "control:changes": "Couldn’t load the history",
    "control:activity": "Couldn’t load the history",
    "control:memory": "Couldn’t load the memory settings",
  } as Record<string, string>,
};

const errorSv: typeof errorEn = {
  message: "Det gick inte att läsa just nu.",
  retry: "Försök igen",
  retrying: "Försöker igen…",
  silent: "Sidekick svarade inte.",
  network: "Kontrollera anslutningen.",
  answered: "Sidekick svarade med ett fel.",
  refresh: "Kunde inte uppdatera",
  startup: "Sidekick kunde inte startas",
  render: "Den här vyn kunde inte visas",
  subjects: {
    work: "Uppgifterna kunde inte hämtas",
    "work:task": "Uppgiften kunde inte hämtas",
    "work:project": "Projektet kunde inte hämtas",
    "work:process": "Processen kunde inte hämtas",
    "work:hierarchy": "Projekten kunde inte hämtas",
    journal: "Dagboken kunde inte hämtas",
    "journal:entry": "Anteckningen kunde inte hämtas",
    "journal:card": "Anteckningen kunde inte hämtas",
    "journal:draft": "Utkastet kunde inte hämtas",
    contacts: "Kontakterna kunde inte hämtas",
    "contacts:contact": "Kontakten kunde inte hämtas",
    "contacts:compact": "Kontakten kunde inte hämtas",
    shopping: "Inköpslistan kunde inte hämtas",
    "shopping:lists": "Listorna kunde inte hämtas",
    control: "Minne och kontroll kunde inte hämtas",
    "control:trash": "Det borttagna kunde inte hämtas",
    "control:history": "Historiken kunde inte hämtas",
    "control:changes": "Historiken kunde inte hämtas",
    "control:activity": "Historiken kunde inte hämtas",
    "control:memory": "Minnesinställningarna kunde inte hämtas",
  },
};

/** The texts of the read error, by app language. Exported for the locale parity test. */
export function errorLabelsFor(locale: string): typeof errorEn {
  return locale.startsWith("sv") ? errorSv : errorEn;
}

/** The heading of a failed read of `subject` ("room" or "room:view"); the general sentence when unknown. */
export function readErrorHeading(locale: string, subject?: string): string {
  const labels = errorLabelsFor(locale);
  // A heading has no full stop (designsystem §1.6); the general sentence keeps its own in a row.
  const general = labels.message.slice(0, -1);
  if (!subject) return general;
  const room = subject.split(":")[0] ?? "";
  return labels.subjects[subject] ?? labels.subjects[room] ?? general;
}

const DEFAULT_DELAY_MS = 150;
const DEFAULT_MIN_MS = 300;

/**
 * The rows of the one neutral skeleton (designsystem §3 Tillstånd), drawn with the classes of awaiting.css: it
 * never guesses the groups. An optional heading bar, then rows with the measures of the finished rows; the title bars
 * take 72, 56, 84, 64 and 48 % of the text column (awaiting.css), so no two neighbours look alike.
 */
export function SkeletonRows({
  rows,
  heading,
  glyph = true,
}: {
  rows: number;
  heading?: boolean;
  glyph?: boolean;
}) {
  return (
    <>
      {heading ? (
        <span className="sidekick-wait-block sidekick-wait-section" />
      ) : null}
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="sidekick-wait-row">
          {glyph ? (
            <span className="sidekick-wait-block sidekick-wait-glyph" />
          ) : null}
          <span className="sidekick-wait-text">
            <span className="sidekick-wait-block sidekick-wait-row-title" />
            {/* Rows 2 and 4 have a second title line: one and two lines alternate. */}
            {index % 2 === 1 ? (
              <span className="sidekick-wait-block sidekick-wait-row-title" />
            ) : null}
            <span className="sidekick-wait-block sidekick-wait-meta" />
          </span>
        </div>
      ))}
    </>
  );
}

/**
 * The skeleton of a list that loads inside a drawn frame (a tab change, Control): the same neutral rows as the first
 * load (SkeletonRows), five of them. Nothing is rendered until `delayMs` of loading has passed, so a fast read shows no
 * placeholder. Once shown, it stays for at least `minMs` even if loading ends sooner, so it does not flicker.
 * `heading` adds the heading bar of a list that opens on a section heading; `glyph` the ring of the leading column.
 */
export function Skeleton({
  loading = true,
  heading = false,
  glyph = false,
  delayMs = DEFAULT_DELAY_MS,
  minMs = DEFAULT_MIN_MS,
}: {
  loading?: boolean;
  heading?: boolean;
  glyph?: boolean;
  delayMs?: number;
  minMs?: number;
}) {
  const [visible, setVisible] = useState(false);
  // When the skeleton appeared, so the minimum display time can be measured after loading ends.
  const shownAt = useRef<number | null>(null);

  useEffect(() => {
    if (loading) {
      const timer = setTimeout(() => {
        shownAt.current = Date.now();
        setVisible(true);
      }, delayMs);
      return () => clearTimeout(timer);
    }
    if (shownAt.current === null) return undefined;
    const remaining = shownAt.current + minMs - Date.now();
    const timer = setTimeout(
      () => {
        shownAt.current = null;
        setVisible(false);
      },
      Math.max(0, remaining),
    );
    return () => clearTimeout(timer);
  }, [loading, delayMs, minMs]);

  if (!visible) return null;

  return (
    <div
      className="sk-skeleton sidekick-wait-rows"
      role="status"
      aria-busy="true"
      data-glyph={glyph || undefined}
    >
      <SkeletonRows rows={5} heading={heading} glyph={glyph} />
    </div>
  );
}

const askLead = { en: "Tell Claude:", sv: "Säg till Claude:" };
// Where the example cannot be sent (the phone app has no chat), the lead says where to say it.
const askLeadAway = {
  en: "Ask Claude in the Claude app:",
  sv: "Be Claude i Claude-appen:",
};
const askSend = {
  en: (example: string) => `Send to Claude: ${example}`,
  sv: (example: string) => `Skicka till Claude: ${example}`,
};

/** The lead of an empty state's chat example, by app language. Exported for the locale parity test. */
export function emptyAskLabelsFor(locale: string) {
  const sv = locale.startsWith("sv");
  return {
    lead: sv ? askLead.sv : askLead.en,
    leadAway: sv ? askLeadAway.sv : askLeadAway.en,
    send: sv ? askSend.sv : askSend.en,
  };
}

/** What a room says to Claude from its empty state: the example sentence, and the host's message function. */
export type EmptyAsk = {
  locale: string;
  /** One sentence the user could say, without quotes; it is also the message that is sent. */
  example: string;
  /** Sends `example` in the chat (ui/message). Absent: the example is shown as text, with nothing to press. */
  onSend?: () => void;
};

/**
 * The family's one empty state (designsystem §3 Tillstånd), the same in every room: line 1 says what is missing
 * ("Inga listor ännu."), an optional muted line says what the list is for, then "Säg till Claude:" with one example
 * sentence. With a host that offers messages the example is a button that sends it, as "Berätta om dagen" does; a host
 * without one (the phone) shows it as text under "Be Claude i Claude-appen:", still the main thing to learn. `children` adds a secondary way to do it
 * by hand. Start-aligned on the content edge, like the rows that will come.
 */
export function EmptyState({
  title,
  hint,
  ask,
  children,
}: {
  title: string;
  hint?: string;
  ask?: EmptyAsk;
  children?: ReactNode;
}) {
  const labels = ask ? emptyAskLabelsFor(ask.locale) : undefined;
  const quoted = ask
    ? ask.locale.startsWith("sv")
      ? `”${ask.example}”`
      : `“${ask.example}”`
    : "";
  return (
    <div className="sk-empty">
      <p className="sk-empty-title">{title}</p>
      {hint ? <p className="sk-empty-hint">{hint}</p> : null}
      {ask && labels ? (
        <div className="sk-empty-ask">
          <p className="sk-empty-ask-lead">
            {ask.onSend ? labels.lead : labels.leadAway}
          </p>
          {ask.onSend ? (
            <button
              type="button"
              className="sk-empty-example"
              aria-label={labels.send(ask.example)}
              onClick={ask.onSend}
            >
              <span className="sk-empty-example-text">{quoted}</span>
              <svg
                aria-hidden="true"
                className="sk-empty-example-send"
                viewBox="0 0 24 24"
                width="20"
                height="20"
              >
                <path
                  d="M12 19V5M6 11l6-6 6 6"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </button>
          ) : (
            <p className="sk-empty-example sk-empty-example--text">{quoted}</p>
          )}
        </div>
      ) : null}
      {children ? <div className="sk-empty-actions">{children}</div> : null}
    </div>
  );
}

/**
 * Whether a failed read may be the connection: true unless Sidekick itself answered with one of its closed error codes
 * (a HostToolError with a code). A timeout, a host error and an isError result without Sidekick's code (the host could
 * not reach the server) all are. Without a cause nothing tells them apart, so the answer is true (designsystem §3).
 */
export function maybeConnection(cause: unknown): boolean {
  // Matched by name, not instanceof, so test mocks of the bridge need not export the class.
  if (!(cause instanceof Error) || cause.name !== "HostToolError") return true;
  const code = (cause as Error & { code?: unknown }).code;
  return !(typeof code === "string" && code !== "");
}

/**
 * The failure of a tool result that came in as an error: shaped as the bridge throws it (named HostToolError, carrying the
 * result's fields, so Sidekick's closed `code` is there when the result names one). A room that is handed an error result
 * instead of catching a throw passes this as the notice's `cause`, so its second line says what the failure says.
 */
export function toolResultCause(result: unknown): Error {
  const fields = typeof result === "object" && result !== null ? result : {};
  return Object.assign(Error(), fields, { name: "HostToolError" });
}

/**
 * A failure of the connection itself: the device is offline, or the request through the host failed
 * before any answer (anything but the host's tool answer, HostToolError). Only then does the card say "Kontrollera
 * anslutningen."; a tool answer without a code says only "Sidekick svarade inte." and guesses no cause.
 */
export function networkFailure(cause: unknown): boolean {
  if (typeof navigator !== "undefined" && navigator.onLine === false)
    return true;
  return !(cause instanceof Error && cause.name === "HostToolError");
}

/** The 24 px ⚠ of a failed read, in the danger line colour. */
const warning = (
  <svg
    aria-hidden="true"
    className="sk-error__icon"
    viewBox="-2 -2 24 24"
    width="24"
    height="24"
  >
    <path
      d="M10 2.5 18.5 17.5H1.5Z"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinejoin="round"
    />
    <path
      d="M10 8v4.5"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
    />
    <circle cx="10" cy="15" r="1.1" fill="currentColor" />
  </svg>
);

/**
 * The family's one error notice (designsystem §3, Tillstånd).
 *
 * `placement="card"` (default) is a failed read, drawn in the row system with no box: ⚠ in the leading column
 * with its centre on the ring's (x 28), then at x 52 a heading without a full stop that names what could not be
 * read ("Uppgifterna kunde inte hämtas"), a muted line with what the frame knows of the failure: "Sidekick
 * svarade inte." when no answer came from Sidekick (`maybeConnection(cause)`), followed by "Kontrollera anslutningen."
 * only on a failed request or offline and alone otherwise ("Försök igen om en stund." said the
 * button again), "Sidekick svarade med ett fel." when
 * Sidekick answered with its own code; no guessed cause or advice, and no line without a cause. Then the primary button
 * "Försök igen". No sentence repeats the button. The heading comes from `subject` ("room" or
 * "room:view"), else from the layer the shell draws (RoomSurfaceContext), else it is the general sentence.
 *
 * `placement="refresh"` is a list that was shown and could not be read again: the list stays and this is one row
 * on top of it, ⚠, "Kunde inte uppdatera" and a secondary "Försök igen" in the right slot.
 *
 * `placement="row"` is a failed write or a failed part of a view: one line in the danger tone under the
 * control, and "Försök igen" as a text button.
 *
 * `retrying` says a retry is running: the button reads "Försöker igen…", is aria-busy and does nothing (it keeps the
 * focus). `message` replaces the heading or the line; it must never carry backend text, identifiers or another owner's
 * data. `onRetry` may be left out when the failure cannot be repeated; `children` adds further actions beside it.
 */
export function ErrorNotice({
  locale,
  message,
  subject,
  cause,
  onRetry,
  retrying = false,
  placement = "card",
  children,
}: {
  locale: string;
  message?: string;
  subject?: string;
  /** The failure, when the caller has it: decides the card's second line. */
  cause?: unknown;
  onRetry?: () => void;
  retrying?: boolean;
  placement?: "row" | "card" | "refresh";
  children?: ReactNode;
}) {
  const surface = useContext(RoomSurfaceContext);
  const labels = errorLabelsFor(locale);
  const shown =
    subject ??
    (surface.room
      ? surface.view
        ? `${surface.room}:${surface.view}`
        : surface.room
      : undefined);
  const retry = onRetry ? (
    <button
      type="button"
      className={
        placement === "row"
          ? "sk-error-retry sk-error-retry--text"
          : placement === "refresh"
            ? "sk-btn sk-btn--secondary sk-btn--compact"
            : "sk-error-retry sk-btn sk-btn--primary"
      }
      aria-busy={retrying || undefined}
      aria-disabled={retrying || undefined}
      onClick={() => {
        if (!retrying) onRetry();
      }}
    >
      {retrying ? labels.retrying : labels.retry}
    </button>
  ) : null;
  const actions =
    retry || children ? (
      <div className="sk-error__actions">
        {retry}
        {children}
      </div>
    ) : null;
  if (placement === "row")
    return (
      <div role="alert" className="sk-error sk-error--row">
        <p className="sk-error-message">{message ?? labels.message}</p>
        {actions}
      </div>
    );
  if (placement === "refresh")
    return (
      <div role="alert" className="sk-error sk-error--refresh">
        {warning}
        <p className="sk-error-message">{message ?? labels.refresh}</p>
        {retry}
      </div>
    );
  return (
    <div role="alert" className="sk-error sk-error--card">
      {warning}
      <div className="sk-error__body">
        <p className="sk-error-message">
          {message ?? readErrorHeading(locale, shown)}
        </p>
        {/* Only what the failure says, never a guessed cause, and no sentence that repeats the button. */}
        {cause ? (
          <p className="sk-error-hint">
            {maybeConnection(cause)
              ? networkFailure(cause)
                ? `${labels.silent} ${labels.network}`
                : labels.silent
              : labels.answered}
          </p>
        ) : null}
        {actions}
      </div>
    </div>
  );
}

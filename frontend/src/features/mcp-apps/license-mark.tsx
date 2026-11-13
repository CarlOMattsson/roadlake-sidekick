import {
  createContext,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";

import { isPlainObject } from "../../lib/mcp/shape";
import { appLocale, type AppLocale } from "./app-locale";
import { roomEnabled } from "./enabled-rooms";
import type { RoomId } from "./router";
import { licenseLabelsFor, type LicenseLabels } from "./license-labels";
import {
  LICENSE_BUY_URL,
  declareLicense,
  licenseFocusAsked,
  licenseFrom,
  licenseSignals,
  onLicenseMenu,
  takeLicenseFocus,
  useLicense,
  type License,
} from "./license-state";
import { Button, buttonClass } from "./ui/button";
import { workDate } from "./ui/due";
import { KeyScope } from "./ui/key-scope";
import { RoomSurfaceContext } from "./ui/room-context";
import { ErrorNotice } from "./ui/states";
import "./license-mark.css";

/**
 * The license signal's parts (see docs/decisions/log.md D-083: license terms):
 * - `LicenseMark`: a small amber coin with "$", 16 px in a 44 px target, no text, no animation. It stands only in the
 *   free version and after the license ran out, never on ⋯ (the update dot's place).
 * - `LicenseRow`: the one place with words, after the update row: Control's foot, the ⋯ panel when Control is off,
 *   the phone's settings. Licensed it is one muted line and the coin is gone everywhere.
 * - `CardFoot` (ui/card.tsx) puts the coin at the end of an inline card's open row; a tap folds the row out in the card.
 * - `LicenseFoot`: the coin at the end of the full view's room, drawn by the shell, with two words beside it
 *   ("Gratisversion") so it does not stand as a lone symbol.
 */

/**
 * What the host offers the row. `call` is the host's tools/call (Claude's bridge, the phone's companion transport) for
 * the app-only tool set_license_key; absent, there is no key field. `openLink` opens "Köp licens" through the host
 * (ui/open-link); absent, a plain link. `openSettings` is a host whose own settings hold the row (the phone): the coin
 * opens them, and no ⋯ panel holds a second row; it is given the room the coin was tapped in, so the settings can lead back to it.
 */
export type LicenseHost = {
  call?: <T>(name: string, args: object) => Promise<T>;
  openLink?: (url: string) => Promise<boolean>;
  openSettings?: (from: RoomId) => void;
};

export const LicenseHostContext = createContext<LicenseHost>({});

/** One coin seen from the front with "$" drawn as a path (not a font glyph), so every platform draws the same. */
export function CoinIcon() {
  return (
    <svg
      viewBox="0 0 16 16"
      width="16"
      height="16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <circle cx="8" cy="8" r="6.75" className="sk-license-coin__face" />
      <path
        strokeWidth="1.35"
        d="M10.1 6.15C9.8 5.5 9 5.1 8 5.1c-1.2 0-2 .6-2 1.45 0 1.9 4.1 1 4.1 2.9 0 .85-.85 1.45-2.1 1.45-1 0-1.8-.4-2.1-1.05M8 3.6v1.5M8 10.9v1.5"
      />
    </svg>
  );
}

/** The coin as a button. The caller decides where it leads; it is drawn only while `licenseSignals` holds. */
export function LicenseMark({
  locale,
  onPress,
  expanded,
  controls,
  text,
}: {
  locale: AppLocale;
  onPress: () => void;
  /** Inline: the row folds out under the card's open row. */
  expanded?: boolean;
  controls?: string;
  /** Words beside the coin (the full view's foot); without them the coin stands alone in its 44 target. */
  text?: string;
}) {
  return (
    <button
      type="button"
      className={
        text
          ? "sk-btn sk-btn--quiet sk-license-mark sk-license-mark--text"
          : "sk-iconbtn sk-license-mark"
      }
      aria-label={licenseLabelsFor(locale).mark}
      aria-expanded={expanded}
      aria-controls={controls}
      onClick={onPress}
      lang={locale}
    >
      <CoinIcon />
      {text ? <span aria-hidden="true">{text}</span> : null}
    </button>
  );
}

function shown(element: HTMLElement | null): element is HTMLElement {
  return Boolean(element?.isConnected && !element.closest("[hidden]"));
}

/** A date for the row: "9 nov 2027" (the year only when it is not this year, as every date of the apps). */
function dayText(value: string | undefined, labels: LicenseLabels, now: Date) {
  return workDate(value, now, labels.dateLocale, {
    inline: true,
    relative: false,
  });
}

/** What the last Spara came to. */
type Outcome =
  | { kind: "saved" }
  | { kind: "rejected" }
  | { kind: "expired"; date: string }
  | { kind: "failed"; cause: unknown };

/**
 * The license row. Free version or expired: the sentence, "Köp licens" (when LICENSE_BUY_URL is set, otherwise a line that licenses can soon be bought) and "Ange
 * licensnyckel", which folds out a field and Spara. The key goes only to set_license_key, through the host (the tool is
 * app-only: the model never sees it); it is not kept in any state after the answer, and never written to the page.
 * Licensed: one muted line. Nothing without a declared license.
 *
 * When the coin asked for it (`requestLicenseFocus`), the row takes the focus as soon as it is shown.
 */
export function LicenseRow({
  locale,
  menu,
  id,
  now = () => new Date(),
}: {
  locale: AppLocale;
  /** Inside a ⋯ menu card: the row takes the card's padding. */
  menu?: boolean;
  id?: string;
  now?: () => Date;
}) {
  const labels = licenseLabelsFor(locale);
  const license = useLicense(now);
  const host = useContext(LicenseHostContext);
  const [editing, setEditing] = useState(false);
  const [key, setKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [outcome, setOutcome] = useState<Outcome>();
  const lead = useRef<HTMLParagraphElement>(null);
  const enterButton = useRef<HTMLButtonElement>(null);
  const field = useRef<HTMLTextAreaElement>(null);
  const fieldId = useId();
  const keyId = useId();
  const statusId = useId();

  // The coin asked: the row's first line takes the focus once it is shown (after the shell and the settings have moved
  // their own focus, hence the timer).
  useEffect(() => {
    if (!licenseFocusAsked() || !shown(lead.current)) return undefined;
    const timer = window.setTimeout(() => {
      const target = lead.current;
      if (!shown(target) || !takeLicenseFocus()) return;
      target.focus({ preventScroll: true });
      target.scrollIntoView?.({ block: "nearest" });
    }, 0);
    return () => window.clearTimeout(timer);
  });

  // The field takes the focus when it opens; Avbryt and Esc give it back to "Ange licensnyckel".
  const refocusEnter = useRef(false);
  useEffect(() => {
    if (editing) field.current?.focus();
    else if (refocusEnter.current) {
      refocusEnter.current = false;
      enterButton.current?.focus();
    }
  }, [editing]);

  if (!license) return null;
  const rowClass = menu
    ? "sk-update-row sk-update-row--menu sk-license-row"
    : "sk-update-row sk-license-row";
  const today = now();

  function close() {
    refocusEnter.current = true;
    setEditing(false);
    setKey("");
  }

  function save() {
    const value = key.trim();
    if (!value || saving || !host.call) return;
    setSaving(true);
    setOutcome(undefined);
    host.call<unknown>("set_license_key", { key: value }).then(
      (answer) => {
        setSaving(false);
        const body = isPlainObject(answer) ? answer : {};
        const display: License | undefined = licenseFrom(
          isPlainObject(body.license) ? body.license : body,
        );
        if (body.accepted === false) {
          // Calm, by the field; the text stays so the owner can see what went in.
          setOutcome({ kind: "rejected" });
          if (display) declareLicense(display);
          return;
        }
        setKey("");
        setEditing(false);
        if (display?.state === "expired")
          setOutcome({
            kind: "expired",
            date: dayText(display.expires, labels, today),
          });
        else setOutcome({ kind: "saved" });
        if (display) declareLicense(display);
      },
      (cause: unknown) => {
        setSaving(false);
        setOutcome({ kind: "failed", cause });
      },
    );
  }

  const rejected = outcome?.kind === "rejected";
  const status =
    outcome?.kind === "saved"
      ? labels.saved
      : outcome?.kind === "expired"
        ? labels.expiredKey(outcome.date)
        : outcome?.kind === "rejected"
          ? labels.invalidKey
          : undefined;

  if (license.state === "licensed")
    return (
      <div className={rowClass} id={id} lang={locale}>
        <p ref={lead} tabIndex={-1} className="sk-license-row__lead">
          {labels.licensed(
            license.licensee,
            dayText(license.expires, labels, today),
          )}
        </p>
        {status ? <p role="status">{status}</p> : null}
      </div>
    );

  return (
    <div className={rowClass} id={id} lang={locale}>
      <p ref={lead} tabIndex={-1} className="sk-license-row__lead">
        {license.state === "expired"
          ? (LICENSE_BUY_URL ? labels.expired : labels.expiredNoShop)(
              dayText(license.expires, labels, today),
            )
          : LICENSE_BUY_URL
            ? labels.unlicensed
            : labels.unlicensedNoShop}
      </p>
      <div className="sk-license-row__actions">
        {LICENSE_BUY_URL ? (
          <BuyButton url={LICENSE_BUY_URL} label={labels.buy} host={host} />
        ) : (
          <span className="sk-license-row__soon">{labels.buySoon}</span>
        )}
        {host.call && !editing ? (
          <button
            ref={enterButton}
            type="button"
            className={buttonClass("secondary")}
            onClick={() => {
              setOutcome(undefined);
              setEditing(true);
            }}
          >
            {labels.enterKey}
          </button>
        ) : null}
      </div>
      {editing ? (
        <KeyScope
          className="sk-license-row__editor"
          id={fieldId}
          onEscape={close}
        >
          <label htmlFor={keyId} className="sk-license-row__key-label">
            {labels.keyField}
          </label>
          <textarea
            ref={field}
            id={keyId}
            className="sk-license-row__key"
            placeholder={labels.keyPlaceholder}
            rows={3}
            autoComplete="off"
            autoCorrect="off"
            autoCapitalize="off"
            spellCheck="false"
            value={key}
            aria-invalid={rejected || undefined}
            aria-describedby={rejected ? statusId : undefined}
            onChange={(event) => setKey(event.target.value)}
          />
          <div className="sk-license-row__actions">
            <Button
              variant="primary"
              className="sk-btn--compact"
              aria-disabled={saving || !key.trim() || undefined}
              aria-busy={saving || undefined}
              onClick={save}
            >
              {saving ? labels.saving : labels.save}
            </Button>
            <Button variant="quiet" onClick={close}>
              {labels.cancel}
            </Button>
          </div>
        </KeyScope>
      ) : null}
      {outcome?.kind === "failed" ? (
        <ErrorNotice
          locale={locale}
          message={labels.saveFailed}
          cause={outcome.cause}
          placement="row"
          onRetry={editing ? save : undefined}
        />
      ) : status ? (
        <p role="status" id={statusId} className="sk-license-row__status">
          {status}
        </p>
      ) : null}
    </div>
  );
}

function BuyButton({
  url,
  label,
  host,
}: {
  url: string;
  label: string;
  host: LicenseHost;
}) {
  if (host.openLink) {
    const open = host.openLink;
    return (
      <Button variant="quiet" onClick={() => void open(url)}>
        {label}
      </Button>
    );
  }
  return (
    <a
      className="sk-btn sk-btn--quiet sk-license-row__buy"
      href={url}
      target="_blank"
      rel="noopener noreferrer"
    >
      {label}
    </a>
  );
}

/** Whether the ⋯ panels hold the row: Control is off and the host has no settings of its own. */
function menuHoldsRow(host: LicenseHost): boolean {
  return !roomEnabled("control") && !host.openSettings;
}

/** The row inside a room's ⋯ panel, after the update row, when Control is off (SIDEKICK_ENABLED_ROOMS=work). */
export function MenuLicenseRow({ now }: { now?: () => Date }) {
  const host = useContext(LicenseHostContext);
  if (!menuHoldsRow(host)) return null;
  return <LicenseRow locale={appLocale()} now={now} menu />;
}

/**
 * Whether a room needs its ⋯ for the license (a room whose ⋯ exists only for Control): the coin stands and the
 * panel holds the row.
 */
export function useLicenseInMenu(): boolean {
  const host = useContext(LicenseHostContext);
  const license = useLicense();
  return menuHoldsRow(host) && licenseSignals(license);
}

/**
 * For the owner of a ⋯ panel: when the coin asks (Control off), the panel that is on screen opens. `anchor` is the ⋯
 * button; a menu whose button is hidden (another tab, another room) does not answer.
 */
export function useLicenseMenu(
  anchor: RefObject<HTMLElement | null>,
  open: () => void,
): void {
  const latest = useRef(open);
  useEffect(() => {
    latest.current = open;
  });
  useEffect(
    () =>
      onLicenseMenu(() => {
        if (!shown(anchor.current)) return false;
        latest.current();
        return true;
      }),
    [anchor],
  );
}

/**
 * An inline card's open row with the coin at its end (the same 44 row, no extra height). The coin folds the row out
 * under it, in the card. Without the signal (licensed, or no declared license) the children stand as they are. In the
 * full view (a framed surface) the shell's foot holds the coin, so the card draws none.
 */
export function LicenseCardFoot({ children }: { children: ReactNode }) {
  const surface = useContext(RoomSurfaceContext);
  const license = useLicense();
  const [open, setOpen] = useState(false);
  const rowId = useId();
  const signals = licenseSignals(license) && !surface.framed;
  if (!signals && !open) return <>{children}</>;
  const locale = appLocale();
  return (
    <>
      <div className="sk-card__foot">
        {children}
        {signals ? (
          <LicenseMark
            locale={locale}
            expanded={open}
            controls={rowId}
            onPress={() => setOpen(!open)}
          />
        ) : null}
      </div>
      {open ? <LicenseRow locale={locale} id={rowId} /> : null}
    </>
  );
}

/**
 * The coin at the end of the full view's room, drawn by the shell. `onShow` leads to the row (Control, the ⋯ panel,
 * the phone's settings) and returns false when there is none on this host; the row then folds out here.
 */
export function LicenseFoot({
  locale,
  onShow,
}: {
  locale: AppLocale;
  onShow: () => boolean;
}) {
  const license = useLicense();
  const [open, setOpen] = useState(false);
  const rowId = useId();
  const signals = licenseSignals(license);
  if (!signals && !open) return null;
  return (
    <div className="sk-license-foot">
      {signals ? (
        <LicenseMark
          locale={locale}
          text={
            license?.state === "expired"
              ? licenseLabelsFor(locale).footExpired
              : licenseLabelsFor(locale).footFree
          }
          expanded={open ? true : undefined}
          controls={open ? rowId : undefined}
          onPress={() => {
            if (open) setOpen(false);
            else if (!onShow()) setOpen(true);
          }}
        />
      ) : null}
      {open ? <LicenseRow locale={locale} id={rowId} /> : null}
    </div>
  );
}

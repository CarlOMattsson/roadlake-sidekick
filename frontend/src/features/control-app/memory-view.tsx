import { useEffect, useRef, useState } from "react";
import type { ControlLabels } from "./labels";
import {
  ControlRow,
  NoticeLine,
  ViewOpenLink,
  type Notice,
} from "./control-parts";
import { PauseIcon, PlayIcon } from "../mcp-apps/ui/icons";
import { MessageBox } from "../mcp-apps/ui/message-box";
import { ReceiptBar, useReceipt } from "../mcp-apps/ui/receipt";
import { Switch } from "../mcp-apps/ui/switch";
import { MemorySearch, SourceRecall, recallTools } from "./memory-recall";
import {
  DOMAIN_KIND,
  MEMORY_DOMAINS,
  writeFailure,
  type ControlTransport,
  type MemoryChange,
  type MemoryDomain,
  type MemorySettings,
  type MemoryStatus,
} from "./transport";
import { useReportedData } from "./use-reported-data";

/** A domain the owner asked to turn off, waiting for the explicit confirmation. */
type PendingOff = {
  domain: MemoryDomain;
  /** Records that leave memory; null when the server does not show the count. */
  documents: number | null;
  /** The settings version the host answered for; the confirmed call repeats it. */
  version: number;
};

/**
 * Memory as an inline card. A message box leads the view when the provider does not answer (warning, with "Try again",
 * which reads the status once more) or is a test one (info, no button); nothing in the card can turn the service on. Then
 * the first line says on, paused or off, and "on, but the service is not answering" while the warning stands, so the two
 * never disagree. Under it, one row per
 * domain with its stored count and a visible On/Off switch. A saved change says so in the receipt bar. Turning a domain on or pausing is sent at
 * once. Turning a domain off first asks the host (set_memory_settings without confirm), which changes
 * nothing and answers needs_confirmation with what would be deleted. Only the owner's explicit
 * "Delete the memory of ..." sends confirm: true; Cancel sends nothing.
 *
 * Where the host offers recall_memory and exclude_from_memory, every source that is on also has "Show what Claude
 * remembers" (a read only sample with "Forget the <record>" per fact), and a search field asks the whole memory.
 */
export function MemoryView({
  initial,
  transport,
  labels,
  onData,
  onModelContext,
  onOpenFull,
  recall = true,
}: {
  initial: MemoryStatus;
  transport: ControlTransport;
  labels: ControlLabels;
  /** Tells the card what this view holds now, so a switch away and back shows it, not the first read. */
  onData?: (data: MemoryStatus) => void;
  /** Called once a memory change is saved, with a generic sentence for the host model. */
  onModelContext?: (summary: string) => void;
  /** Opens this view in fullscreen (the inline card's main link); absent: the card has no link. */
  onOpenFull?: () => void;
  /**
   * The full view's parts: the sentence on what the memory is, `recallShow` and the search. The full view only: the inline card stays one phone screen of
   * status and switches, and Öppna leads to the rest.
   */
  recall?: boolean;
}) {
  const [status, change] = useReportedData(initial, onData);
  const [busy, setBusy] = useState(false);
  // The status is being read again after "Try again" in the warning about the service.
  const [checking, setChecking] = useState(false);
  const [confirming, setConfirming] = useState<PendingOff | undefined>();
  const [notice, setNotice] = useState<Notice | undefined>();
  const receipt = useReceipt();
  /** Domains switched off with confirm; their count reads "deleting" until a later status read. */
  const [deleting, setDeleting] = useState<MemoryDomain[]>([]);
  const confirmRef = useRef<HTMLDivElement>(null);
  const settings = status.settings;
  const anyOn = MEMORY_DOMAINS.some((domain) => settings[domain]);
  // Nothing can be looked up while the service is off, and a search has nothing to ask when every source is off.
  const tools =
    recall && status.provider !== "off" ? recallTools(transport) : undefined;
  // New text is not added while memory is paused or the service is off, so what is queued is waiting, not on its way.
  const held = settings.paused || status.provider === "off";

  // Move focus to the question, so a screen reader reads it and the buttons are next in order.
  useEffect(() => {
    if (confirming) confirmRef.current?.focus();
  }, [confirming]);

  /**
   * Reads the status again. The read right after a confirmed switch-off may still show the old count,
   * so it keeps the "deleting" marker; any later read replaces it.
   */
  async function readAgain(fallback?: MemorySettings, keepDeleting = false) {
    try {
      const fresh = await transport.memoryStatus();
      change(() => fresh);
      if (!keepDeleting) setDeleting([]);
    } catch {
      if (fallback) change((current) => ({ ...current, settings: fallback }));
    }
  }

  /** "Try again" in the warning about the service: reads the status once more; the warning stays while it does not answer. */
  async function recheck() {
    if (checking) return;
    setChecking(true);
    await readAgain();
    setChecking(false);
  }

  /** A fact was forgotten: the receipt says so (the sentence comes from the list) and the counts are read again. */
  function forgotten(message: string) {
    receipt.show({ message });
    void readAgain();
  }

  async function send(
    change: Omit<MemoryChange, "expectedVersion">,
    version?: number,
  ) {
    if (busy) return;
    setBusy(true);
    setNotice(undefined);
    try {
      const result = await transport.setMemory({
        ...change,
        expectedVersion: version ?? settings.version,
      });
      if (result.status === "needs_confirmation") {
        const domain = change.domain;
        if (domain) {
          setConfirming({
            domain,
            documents:
              result.turning_off.find((row) => row.domain === domain)
                ?.documents ?? null,
            version: result.settings.version,
          });
        }
        return;
      }
      setConfirming(undefined);
      if (result.status === "updated")
        onModelContext?.(memoryNote(change, labels));
      const removed =
        change.confirm && change.value === false ? change.domain : undefined;
      if (removed) {
        setDeleting((current) => [
          ...current.filter((domain) => domain !== removed),
          removed,
        ]);
        receipt.show({ message: labels.deletionStarted(removed) });
      } else {
        receipt.show({ message: labels.memorySaved });
      }
      await readAgain(result.settings, removed !== undefined);
    } catch (error) {
      setConfirming(undefined);
      const failure = writeFailure(error);
      if (failure === "conflict") {
        setNotice({ text: labels.memoryConflict });
        await readAgain();
      } else {
        setNotice({
          text:
            failure === "forbidden"
              ? labels.memoryForbidden
              : labels.memoryFailed,
          retry:
            failure === "forbidden"
              ? undefined
              : () => void send(change, version),
        });
      }
    } finally {
      setBusy(false);
    }
  }

  // "On" while the service does not answer would contradict the warning box above it, so the headline says both at once.
  const headline = !anyOn
    ? labels.memoryOff
    : settings.paused
      ? labels.memoryPaused
      : status.provider === "off"
        ? labels.memoryOnDown
        : labels.memoryOn;

  return (
    <>
      <div className="control-view">
        {/* The view's one message about the service, at its top: a service that does not answer is a warning with one
          action, to read the status again; a test service is for information and has none. The card cannot turn the
          service on. */}
        {status.provider === "off" ? (
          <MessageBox
            severity="warning"
            title={labels.providerOffTitle}
            action={{
              label: labels.retry,
              busyLabel: labels.loading,
              busy: checking,
              onClick: () => void recheck(),
            }}
          >
            {labels.providerOff}
          </MessageBox>
        ) : status.provider === "fake" ? (
          <MessageBox severity="info" title={labels.providerFakeTitle}>
            {labels.providerFake}
          </MessageBox>
        ) : null}
        {/* The memory's own row : `memoryOn` with its meta, how many sources are on, alone on
          its line. Under it `pause` is the list's action row (row.css .sk-action-row, as `moveAllOverdue`
          and `addStep`): a pause glyph in the leading column and the text at 500, a global action and no source;
          the screen has no ink. */}
        <div className="control-headrow">
          <div className="control-headrow-text">
            <h2 className="control-heading sk-card__title">{headline}</h2>
            <p className="control-headrow-meta">
              {labels.sourcesOn(
                MEMORY_DOMAINS.filter((domain) => settings[domain]).length,
                MEMORY_DOMAINS.length,
              )}
            </p>
            {/* What the memory is and where it goes: in the full view, beside what it holds. The inline card stays one
              phone screen of status and switches (owner's rule); Öppna leads here. */}
            {recall && (
              <p className="control-explain">{labels.memoryExplain}</p>
            )}
          </div>
        </div>
        {anyOn ? (
          <button
            type="button"
            className="sk-action-row control-pause"
            disabled={busy || confirming !== undefined}
            onClick={() => void send({ paused: !settings.paused })}
          >
            {settings.paused ? <PlayIcon /> : <PauseIcon />}
            {busy
              ? labels.memoryBusy
              : settings.paused
                ? labels.resume
                : labels.pause}
          </button>
        ) : null}
        <NoticeLine notice={notice} locale={labels.locale} />
        <h3 className="control-section">{labels.sourcesTitle}</h3>
        <ul
          className={
            settings.paused
              ? "control-list control-list-wrap control-list-paused"
              : "control-list control-list-wrap"
          }
          aria-label={labels.views.memory}
        >
          {MEMORY_DOMAINS.map((domain) => {
            const on = settings[domain];
            const name = labels.domains[domain];
            return (
              <ControlRow
                key={domain}
                primary={name}
                secondary={
                  // The state leads the meta line: the switch carries no word of its own.
                  on
                    ? `${settings.paused ? labels.domainOnPaused : labels.domainOn} · ${countText(
                        status,
                        domain,
                        labels,
                        deleting.includes(domain),
                        held,
                      )}`
                    : `${labels.domainOff} · ${countText(status, domain, labels, deleting.includes(domain), held)}`
                }
                below={
                  tools && on ? (
                    <SourceRecall
                      kind={DOMAIN_KIND[domain]}
                      name={name}
                      tools={tools}
                      labels={labels}
                      onForgotten={forgotten}
                      onModelContext={onModelContext}
                    />
                  ) : undefined
                }
                action={
                  <Switch
                    checked={on}
                    label={labels.domainLabel(name, on)}
                    disabled={busy || confirming !== undefined}
                    onChange={(next) => void send({ domain, value: next })}
                  />
                }
              />
            );
          })}
        </ul>
        {confirming ? (
          <div
            ref={confirmRef}
            tabIndex={-1}
            role="group"
            aria-labelledby="control-confirm-title"
            className="control-confirm"
          >
            <p id="control-confirm-title" className="control-confirm-title">
              {labels.confirmTitle(confirming.domain)}
            </p>
            <p>
              {labels.confirmCount(confirming.domain, confirming.documents)}{" "}
              {labels.confirmCost}
            </p>
            <div className="control-confirm-actions">
              {/* Cancel comes first in the DOM, so Tab reaches the safe button before the red one. */}
              <button
                type="button"
                className="sk-btn--quiet"
                disabled={busy}
                onClick={() => setConfirming(undefined)}
              >
                {labels.confirmNo}
              </button>
              <button
                type="button"
                className="sk-btn--danger control-confirm-yes"
                disabled={busy}
                onClick={() =>
                  void send(
                    {
                      domain: confirming.domain,
                      value: false,
                      confirm: true,
                    },
                    confirming.version,
                  )
                }
              >
                {labels.confirmYes(confirming.domain)}
              </button>
            </div>
          </div>
        ) : null}
        {tools && anyOn ? (
          <MemorySearch
            tools={tools}
            labels={labels}
            onForgotten={forgotten}
            onModelContext={onModelContext}
          />
        ) : null}
        <ViewOpenLink
          labels={labels}
          view="memory"
          full={recall}
          onOpenFull={onOpenFull}
        />
      </div>
      <ReceiptBar receipt={receipt} />
    </>
  );
}

/** The generic sentence for a saved memory change: pause, resume, or a domain switched on or off. */
function memoryNote(
  change: Omit<MemoryChange, "expectedVersion">,
  labels: ControlLabels,
): string {
  if (change.paused === true) return labels.modelNote.paused;
  if (change.paused === false) return labels.modelNote.resumed;
  return labels.modelNote.memoryChanged;
}

/**
 * the count line with those on the way (the source's own noun). A domain being deleted reads "deleting…"; a domain
 * that is off reads `countOff` after `domainOff`; an on domain without a count reads "count unknown".
 */
function countText(
  status: MemoryStatus,
  domain: MemoryDomain,
  labels: ControlLabels,
  removing: boolean,
  held: boolean,
): string {
  if (removing) return labels.countDeleting;
  if (!status.settings[domain]) return labels.countOff;
  const source = status.sources.find((row) => row.kind === DOMAIN_KIND[domain]);
  if (!source) return labels.countUnknown;
  const parts = [labels.countStored(source.retained, domain)];
  if (source.pending > 0) parts.push(labels.countWaiting(source.pending, held));
  const stuck = source.failed + source.parked;
  if (stuck > 0) parts.push(labels.countStuck(stuck));
  return parts.join(" · ");
}

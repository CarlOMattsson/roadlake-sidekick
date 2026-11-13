import { useEffect, useRef, useState } from "react";
import type { ControlLabels } from "./labels";
import { ControlRow, NoticeLine, type Notice } from "./control-parts";
import { PauseIcon, PlayIcon } from "../mcp-apps/ui/icons";
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
 * Memory as an inline card. The first line says on, paused or off; when the provider is off or a test
 * one, the headline says so in warning colour and a warning line explains it. Under it, one row per
 * domain with its stored count and a visible On/Off switch. Turning a domain on or pausing is sent at
 * once. Turning a domain off first asks the host (set_memory_settings without confirm), which changes
 * nothing and answers needs_confirmation with what would be deleted. Only the owner's explicit
 * "Delete the memory of ..." sends confirm: true; Cancel sends nothing.
 *
 * Where the host offers recall_memory and exclude_from_memory, every source that is on also has "Show what Claude
 * remembers" (a read only sample with "Forget this" per fact), and a search field asks the whole memory.
 */
export function MemoryView({
  initial,
  transport,
  labels,
  onData,
  onModelContext,
  recall = true,
}: {
  initial: MemoryStatus;
  transport: ControlTransport;
  labels: ControlLabels;
  /** Tells the card what this view holds now, so a switch away and back shows it, not the first read. */
  onData?: (data: MemoryStatus) => void;
  /** Called once a memory change is saved, with a generic sentence for the host model. */
  onModelContext?: (summary: string) => void;
  /**
   * The full view's parts: the sentence on what the memory is, "Visa vad Sidekick minns" and the search. The full view only: the inline card stays one phone screen of
   * status and switches, and Öppna leads to the rest.
   */
  recall?: boolean;
}) {
  const [status, change] = useReportedData(initial, onData);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState<PendingOff | undefined>();
  const [notice, setNotice] = useState<Notice | undefined>();
  /** Domains switched off with confirm; their count reads "deleting" until a later status read. */
  const [deleting, setDeleting] = useState<MemoryDomain[]>([]);
  const confirmRef = useRef<HTMLDivElement>(null);
  const settings = status.settings;
  const tools = recall ? recallTools(transport) : undefined;

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
        setNotice({
          tone: "ok",
          text: labels.deletionStarted(removed),
        });
      } else {
        setNotice({ tone: "ok", text: labels.memorySaved });
      }
      await readAgain(result.settings, removed !== undefined);
    } catch (error) {
      setConfirming(undefined);
      const failure = writeFailure(error);
      if (failure === "conflict") {
        setNotice({ tone: "error", text: labels.memoryConflict });
        await readAgain();
      } else {
        setNotice({
          tone: "error",
          text:
            failure === "forbidden"
              ? labels.memoryForbidden
              : labels.memoryFailed,
        });
      }
    } finally {
      setBusy(false);
    }
  }

  const anyOn = MEMORY_DOMAINS.some((domain) => settings[domain]);
  const providerNote =
    status.provider === "off"
      ? labels.providerOff
      : status.provider === "fake"
        ? labels.providerFake
        : undefined;
  const providerHeadline =
    status.provider === "off"
      ? labels.memoryOnProviderOff
      : status.provider === "fake"
        ? labels.memoryFakeProvider
        : undefined;
  const warningHeadline =
    anyOn && !settings.paused && providerHeadline !== undefined;
  const headline = !anyOn
    ? labels.memoryOff
    : settings.paused
      ? labels.memoryPaused
      : (providerHeadline ?? labels.memoryOn);

  return (
    <div className="control-view">
      {/* The memory's own row : "Minnet är på" with its meta, how many sources are on, alone on
          its line. Under it Pausa minnet is the list's action row (row.css .sk-action-row, as "Flytta …"
          and "+ Lägg till steg"): a pause glyph in the leading column and the text at 500, a global action and no source;
          the screen has no ink. */}
      <div className="control-headrow">
        <div className="control-headrow-text">
          <h2
            className={
              warningHeadline
                ? "control-heading sk-card__title control-heading-warning"
                : "control-heading sk-card__title"
            }
          >
            {headline}
          </h2>
          <p className="control-headrow-meta">
            {labels.sourcesOn(
              MEMORY_DOMAINS.filter((domain) => settings[domain]).length,
              MEMORY_DOMAINS.length,
            )}
          </p>
          {/* What the memory is and where it goes: in the full view, beside what it holds. The inline card stays one
              phone screen of status and switches (owner's rule); Öppna leads here. */}
          {recall && <p className="control-explain">{labels.memoryExplain}</p>}
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
      {providerNote ? (
        <p className="sk-notice sk-notice--warning control-notice control-notice-warning">
          {providerNote}
        </p>
      ) : null}
      <NoticeLine notice={notice} />
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
                    )}`
                  : `${labels.domainOff} · ${countText(status, domain, labels, deleting.includes(domain))}`
              }
              below={
                tools && on ? (
                  <SourceRecall
                    kind={DOMAIN_KIND[domain]}
                    name={name}
                    tools={tools}
                    labels={labels}
                    onForgotten={() => void readAgain()}
                    onModelContext={onModelContext}
                  />
                ) : undefined
              }
              action={
                <button
                  type="button"
                  role="switch"
                  aria-checked={on}
                  aria-label={labels.domainLabel(name, on)}
                  className="control-switch"
                  data-on={on ? "true" : "false"}
                  disabled={busy || confirming !== undefined}
                  onClick={() => void send({ domain, value: !on })}
                >
                  <span className="control-switch-track" aria-hidden="true">
                    <span className="control-switch-knob" />
                  </span>
                </button>
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
      {tools ? (
        <MemorySearch
          tools={tools}
          labels={labels}
          onForgotten={() => void readAgain()}
          onModelContext={onModelContext}
        />
      ) : null}
    </div>
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
 * "214 anteckningar i minnet · 2 på väg" (the source's own noun). A domain being deleted reads "deleting…"; a domain
 * that is off reads "inte med i minnet" after "Av"; an on domain without a count reads "count unknown".
 */
function countText(
  status: MemoryStatus,
  domain: MemoryDomain,
  labels: ControlLabels,
  removing: boolean,
): string {
  if (removing) return labels.countDeleting;
  if (!status.settings[domain]) return labels.countOff;
  const source = status.sources.find((row) => row.kind === DOMAIN_KIND[domain]);
  if (!source) return labels.countUnknown;
  const parts = [labels.countStored(source.retained, domain)];
  if (source.pending > 0) parts.push(labels.countWaiting(source.pending));
  const stuck = source.failed + source.parked;
  if (stuck > 0) parts.push(labels.countStuck(stuck));
  return parts.join(" · ");
}

import {
  useCallback,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";

import type { HostSettingsEntry, RoomTarget } from "../../mcp-apps/room-types";
import { ApproveGroup } from "../../mcp-apps/ui/approve-group";
import { DecisionCard } from "../../mcp-apps/ui/decision-card";
import { MoreIcon } from "../../mcp-apps/ui/icons";
import { Menu, menuButtonKeys } from "../../mcp-apps/ui/menu";
import { ReceiptBar, useReceipt } from "../../mcp-apps/ui/receipt";
import { RoomSurfaceContext } from "../../mcp-apps/ui/room-context";
import { RoomHead } from "../../mcp-apps/ui/room-head";
import { MenuShortcutsRow } from "../../mcp-apps/ui/shortcut-help";
import { useRecordRow, useSplitList } from "../../mcp-apps/ui/split-layout";
import {
  EmptyState,
  ErrorNotice,
  SkeletonRows,
} from "../../mcp-apps/ui/states";
import type { SuggestionLabels } from "./labels";
import {
  appendPage,
  inboxOf,
  MAX_PER_CONFIRMATION,
  suggestionTitle,
  suggestionTrust,
  type InboxGroup,
  type SuggestionItem,
  type SuggestionPage,
} from "./model";
import type { SuggestionTransport } from "./transport";
import { useDecisions } from "./use-decisions";
import "./suggestions.css";

/** The inbox's read: the first page, read again in place; more pages appended. */
type InboxRead =
  | { phase: "reading" }
  | { phase: "failed"; cause: unknown }
  | {
      phase: "ready";
      page: SuggestionPage;
      /** A read again failed: the page stays, with the refresh line over it. */
      stale?: { cause: unknown };
      more?: "loading" | "failed";
    };

/**
 * Reads the inbox: the result that opened the room when there is one, else the first page. `reload` reads the first
 * page again and keeps the page on screen until the answer comes (a refresh in place, never a skeleton); a new
 * `refreshKey` does the same. `loadMore` appends the next page.
 */
export function useInbox(
  api: SuggestionTransport,
  initial: SuggestionPage | undefined,
  refreshKey = 0,
) {
  const [read, setRead] = useState<InboxRead>(
    initial ? { phase: "ready", page: initial } : { phase: "reading" },
  );
  const latest = useRef(0);
  const reload = useCallback(() => {
    const ticket = ++latest.current;
    api.list().then(
      (page) => {
        if (ticket === latest.current) setRead({ phase: "ready", page });
      },
      (cause: unknown) => {
        if (ticket !== latest.current) return;
        setRead((now) =>
          now.phase === "ready"
            ? { ...now, stale: { cause } }
            : { phase: "failed", cause },
        );
      },
    );
  }, [api]);
  const retry = useCallback(() => {
    setRead((now) => (now.phase === "failed" ? { phase: "reading" } : now));
    reload();
  }, [reload]);
  // The first read when nothing came with the room, and a read again on every new refreshKey.
  const seen = useRef(initial ? refreshKey : -1);
  useEffect(() => {
    if (seen.current === refreshKey) return;
    seen.current = refreshKey;
    reload();
  }, [refreshKey, reload]);
  const loadMore = () => {
    if (read.phase !== "ready" || !read.page.next_cursor) return;
    const cursor = read.page.next_cursor;
    const ticket = latest.current;
    setRead({ ...read, more: "loading" });
    api.list(cursor).then(
      (next) => {
        if (ticket !== latest.current) return;
        setRead((now) =>
          now.phase === "ready"
            ? { phase: "ready", page: appendPage(now.page, next) }
            : now,
        );
      },
      () => {
        if (ticket !== latest.current) return;
        setRead((now) =>
          now.phase === "ready" ? { ...now, more: "failed" } : now,
        );
      },
    );
  };
  return { read, reload, retry, loadMore };
}

/**
 * The suggestion inbox in the full view (the Start room's suggestions; a column beside the open suggestion in a wide
 * frame). Its title "Förslag" and ⋯, then each safe group the server made as a card of its own (ApproveGroup, at most
 * three per confirmation), then "Att granska (n)": every other card as a decision card whose title opens its detail.
 * The answers have Ångra in the receipt bar, and a decided card holds its place as its receipt while Ångra is offered.
 *
 * `lead` is the place above the groups for what the automations say about themselves (the latest report, what was
 * applied without the owner); nothing draws there yet.
 */
export function SuggestionsInbox({
  api,
  t,
  initial,
  refreshKey,
  onOpenSuggestion,
  onOpenRecord,
  control,
  lead,
}: {
  api: SuggestionTransport;
  t: SuggestionLabels;
  initial?: SuggestionPage;
  refreshKey?: number;
  onOpenSuggestion?: (item: SuggestionItem) => void;
  onOpenRecord?: (target: RoomTarget) => void;
  /** The last entry of ⋯: the memory and control entry, or the host's own settings. */
  control?: HostSettingsEntry;
  lead?: ReactNode;
}) {
  const locale = t.dateLocale;
  const inbox = useInbox(api, initial, refreshKey);
  const receipt = useReceipt();
  const decisions = useDecisions({
    api,
    t,
    receipt,
    onSettled: inbox.reload,
    onOpen: onOpenRecord,
  });
  const [excluded, setExcluded] = useState<Record<string, Set<string>>>({});
  const inBar = Boolean(useContext(RoomSurfaceContext).headSlot);
  const splitList = useSplitList();
  const { read } = inbox;

  const [moreOpen, setMoreOpen] = useState(false);
  const moreButton = useRef<HTMLButtonElement>(null);
  const panelId = useId();
  const more: InboxMore = { open: moreOpen, setOpen: setMoreOpen, panelId };
  const menu = (
    <InboxMenu
      more={more}
      buttonRef={moreButton}
      t={t}
      onRefresh={inbox.reload}
      control={control}
    />
  );

  let body: ReactNode;
  if (read.phase === "reading")
    body = (
      <div className="start-inbox-wait" aria-busy="true">
        <SkeletonRows rows={3} heading glyph={false} />
      </div>
    );
  else if (read.phase === "failed")
    body = (
      <ErrorNotice
        locale={locale}
        subject="start"
        cause={read.cause}
        onRetry={inbox.retry}
      />
    );
  else {
    const { groups, review } = inboxOf(read.page);
    const empty = groups.length === 0 && review.length === 0;
    body = (
      <>
        {read.stale ? (
          <ErrorNotice
            locale={locale}
            placement="refresh"
            subject="start"
            cause={read.stale.cause}
            onRetry={inbox.reload}
          />
        ) : null}
        {empty ? <EmptyState title={t.empty} hint={t.emptyHint} /> : null}
        {groups.map((group) => (
          <GroupCard
            key={group.group.group_digest}
            group={group}
            t={t}
            state={decisions.group(group.group.group_digest)}
            excluded={excluded[group.group.group_digest] ?? EMPTY}
            onToggle={(id) =>
              setExcluded((all) => {
                const digest = group.group.group_digest;
                const next = new Set(all[digest] ?? EMPTY);
                if (next.has(id)) next.delete(id);
                else next.add(id);
                return { ...all, [digest]: next };
              })
            }
            onApprove={(ids) => decisions.approveGroup(group, ids)}
          />
        ))}
        {review.length > 0 ? (
          <section
            className="start-inbox-review"
            aria-labelledby={`${panelId}-review`}
          >
            <h3 className="start-inbox-section" id={`${panelId}-review`}>
              {t.reviewHeading(review.length)}
            </h3>
            <ul className="start-inbox-cards">
              {review.map((item) => (
                <ReviewItem key={item.id} id={item.id} split={splitList}>
                  <ReviewCard
                    item={item}
                    t={t}
                    state={decisions.card(item.id)}
                    inList
                    onAnswer={(answer, confirmed) =>
                      decisions.answer(item, answer, confirmed)
                    }
                    onOpen={
                      onOpenSuggestion
                        ? () => onOpenSuggestion(item)
                        : undefined
                    }
                    onOpenRecord={onOpenRecord}
                  />
                </ReviewItem>
              ))}
            </ul>
          </section>
        ) : null}
        {read.page.next_cursor ? (
          <div className="start-inbox-more">
            <button
              type="button"
              className="sk-btn sk-btn--secondary sk-btn--compact"
              aria-busy={read.more === "loading" || undefined}
              onClick={inbox.loadMore}
            >
              {read.more === "loading" ? t.loadingMore : t.loadMore}
            </button>
            {read.more === "failed" ? (
              <ErrorNotice
                locale={locale}
                placement="row"
                onRetry={inbox.loadMore}
              />
            ) : null}
          </div>
        ) : null}
        {read.page.hidden > 0 ? (
          <p className="sk-card__meta start-inbox-hidden">
            {t.hidden(read.page.hidden)}
          </p>
        ) : null}
      </>
    );
  }

  return (
    <article className="sidekick-start start-inbox">
      {inBar ? (
        <RoomHead
          scope="sidekick-start"
          keysTitle={t.title}
          tabs={<span className="sk-shell-tabs-fill" aria-hidden="true" />}
          more={
            <>
              <InboxMoreButton more={more} buttonRef={moreButton} t={t} />
              {menu}
            </>
          }
        />
      ) : null}
      <div className="start-inbox-head">
        <h2 className="start-inbox-title">{t.title}</h2>
        {inBar ? null : (
          <InboxMoreButton more={more} buttonRef={moreButton} t={t} />
        )}
      </div>
      {inBar ? null : menu}
      {lead}
      {body}
      <ReceiptBar receipt={receipt} />
    </article>
  );
}

const EMPTY: ReadonlySet<string> = new Set();

/** One safe group as a card: where it comes from, its rows and its one button (at most three per confirmation). */
function GroupCard({
  group,
  t,
  state,
  excluded,
  onToggle,
  onApprove,
}: {
  group: InboxGroup;
  t: SuggestionLabels;
  state: ReturnType<ReturnType<typeof useDecisions>["group"]>;
  excluded: ReadonlySet<string>;
  onToggle: (id: string) => void;
  onApprove: (ids: string[]) => void;
}) {
  if (state.decided)
    return (
      <DecisionCard
        locale={t.dateLocale}
        kicker={t.kicker}
        title={t.safeHeading(group.items.length)}
        actions={{ approve: noop, dismiss: noop }}
        decided={{ message: state.note ?? state.decided }}
      />
    );
  return (
    <section className="sk-card start-group">
      <p className="sk-eyebrow">
        {t.fromAutomation(group.group.automation_title)}
      </p>
      <ApproveGroup
        locale={t.dateLocale}
        title={t.safeHeading(group.items.length)}
        items={group.items.map((item) => ({
          id: item.id,
          label: suggestionTitle(item.effect, item.summary, t),
        }))}
        excluded={excluded}
        onToggle={onToggle}
        onApproveAll={onApprove}
        busy={state.busy}
        failed={state.failed}
        max={MAX_PER_CONFIRMATION}
      />
    </section>
  );
}

const noop = () => undefined;

/**
 * A card's place in the list. Beside its detail in a wide frame it carries the record's mark (useRecordRow): the
 * focus returns to it when the detail closes, and it is drawn chosen while open.
 */
function ReviewItem({
  id,
  split,
  children,
}: {
  id: string;
  split: boolean;
  children: ReactNode;
}) {
  const record = useRecordRow(
    split ? { room: "start", view: "suggestion", id } : undefined,
  );
  return (
    <li className="start-inbox-card" {...record}>
      {children}
    </li>
  );
}

/**
 * One card to review alone: its title opens the detail. In the inbox (`inList`) the kicker is the automation alone,
 * since every card there is a suggestion; on its own in the chat it says "Förslag · från Morgonmejl".
 */
export function ReviewCard({
  item,
  t,
  state,
  inList = false,
  onAnswer,
  onOpen,
  onOpenRecord,
}: {
  item: SuggestionItem;
  inList?: boolean;
  t: SuggestionLabels;
  state: ReturnType<ReturnType<typeof useDecisions>["card"]>;
  onAnswer: (answer: "approve" | "dismiss", confirmed: boolean) => void;
  onOpen?: () => void;
  onOpenRecord?: (target: RoomTarget) => void;
}) {
  const trust = suggestionTrust(item, t.dateLocale);
  const flagged = trust.state === "unsure" || trust.state === "suspicious";
  const target = state.decided?.target;
  return (
    <DecisionCard
      locale={t.dateLocale}
      kicker={inList ? item.automation_title : t.kicker}
      title={suggestionTitle(item.effect, item.summary, t)}
      source={inList ? undefined : { name: item.automation_title }}
      trust={trust}
      edited={item.edited}
      actions={{
        approve: () => onAnswer("approve", flagged),
        dismiss: () => onAnswer("dismiss", false),
        review: onOpen,
        open: onOpen,
      }}
      busy={state.busy}
      failed={state.failed}
      applyError={state.applyError}
      decided={
        state.decided
          ? {
              message: state.decided.message,
              hold: state.decided.hold,
              open:
                target && onOpenRecord
                  ? { label: t.open, onOpen: () => onOpenRecord(target) }
                  : undefined,
            }
          : undefined
      }
    />
  );
}

/** The inbox's ⋯ state: open or not, and the panel's id. The button's ref is the caller's own. */
type InboxMore = {
  open: boolean;
  setOpen: (open: boolean) => void;
  panelId: string;
};

function InboxMoreButton({
  more,
  buttonRef,
  t,
}: {
  more: InboxMore;
  buttonRef: RefObject<HTMLButtonElement | null>;
  t: SuggestionLabels;
}) {
  return (
    <button
      ref={buttonRef}
      type="button"
      className="sk-iconbtn sk-room-head__tool start-inbox-more-button"
      aria-label={t.moreActions}
      aria-expanded={more.open}
      aria-controls={more.panelId}
      onClick={() => more.setOpen(!more.open)}
      onKeyDown={menuButtonKeys(more.open, more.setOpen)}
    >
      <MoreIcon />
    </button>
  );
}

/** The inbox's ⋯: refresh, the keyboard help, and the memory and control entry (or the host's settings). */
function InboxMenu({
  more,
  buttonRef,
  t,
  onRefresh,
  control,
}: {
  more: InboxMore;
  buttonRef: RefObject<HTMLButtonElement | null>;
  t: SuggestionLabels;
  onRefresh: () => void;
  control?: HostSettingsEntry;
}) {
  const close = () => more.setOpen(false);
  return (
    <Menu id={more.panelId} open={more.open} anchor={buttonRef} onClose={close}>
      <button
        type="button"
        className="sk-menu-item"
        onClick={() => {
          close();
          onRefresh();
        }}
      >
        {t.refresh}
      </button>
      <MenuShortcutsRow
        onChosen={() => {
          close();
          buttonRef.current?.focus();
        }}
      />
      {control ? (
        <button
          type="button"
          className="sk-menu-item"
          onClick={() => {
            close();
            control.onOpen();
          }}
        >
          {control.label}
        </button>
      ) : null}
    </Menu>
  );
}

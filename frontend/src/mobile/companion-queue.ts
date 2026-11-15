/**
 * The transport's side of the phone's outbox (companion-transport.ts): keeping a write that got no answer, reading what
 * waits, and answering a read with what waits added to it. The writes are purchases, items added to a shopping list, and
 * record writes (a new or edited Task, Project or journal entry). The stand-ins of the last two are made in
 * companion-queued-adds.ts and companion-queued-records.ts.
 */
import { HostToolError } from "@/features/mcp-apps/bridge";

import type { Planned, Queueable } from "./companion-plan";
import { queuedAddResult, withQueuedAdds } from "./companion-queued-adds";
import {
  KnownRecords,
  queuedTask,
  standInFor,
  withQueuedEntries,
} from "./companion-queued-records";
import type {
  QueuedShoppingAdd,
  SidekickNativePlugin,
} from "./sidekick-native";

/** The plugin as the transport uses it: `request`, and the outbox and its event where the plugin has them. */
export type NativeForTransport = Pick<SidekickNativePlugin, "request"> &
  Partial<
    Pick<
      SidekickNativePlugin,
      | "queuePurchase"
      | "queueShoppingAdd"
      | "queueRecordWrite"
      | "queuedWrites"
      | "addListener"
    >
  >;

const NOTHING_QUEUED = {
  purchases: [],
  adds: [],
  completions: [],
  records: [],
} as const;

/**
 * What the outbox kept: a purchase (`purchased` is the state that will be sent), or a write that is answered with a
 * stand-in (`answer`).
 */
export type Kept = { purchased: boolean } | { answer: unknown };

export class TransportOutbox {
  /** The records the answers held, the base of an edit that has to wait for the network. */
  readonly known = new KnownRecords();
  /** The room's listeners of the outbox, told also when this transport itself put something in it. */
  private readonly listeners = new Set<() => void>();

  constructor(private readonly native: NativeForTransport) {}

  /** The outbox as the phone holds it; nothing when it cannot be read. */
  async writes() {
    if (!this.native.queuedWrites) return NOTHING_QUEUED;
    try {
      // `completions` and `records` are absent from an older phone build.
      const { purchases, adds, completions, records } =
        await this.native.queuedWrites();
      return {
        purchases,
        adds,
        completions: completions ?? [],
        records: records ?? [],
      };
    } catch {
      return NOTHING_QUEUED;
    }
  }

  /** Calls `listener` when a run of the outbox has ended or this transport put something in it; returns the unsubscribe. */
  listen(listener: () => void): () => void {
    this.listeners.add(listener);
    const handle = this.native.addListener?.("queueChanged", listener);
    return () => {
      this.listeners.delete(listener);
      void handle?.then((h) => h.remove()).catch(() => undefined);
    };
  }

  private notify() {
    for (const listener of [...this.listeners]) listener();
  }

  /**
   * Puts the write that got no answer in the outbox with the key it was sent with, bound to the pairing generation the
   * request began under (a late failure after an unpair is refused by the phone). Undefined when it cannot be kept: the
   * caller fails with the connection error. Items added and record writes are answered with stand-ins, and the room's
   * listeners are told before the answer, so it lists them as waiting.
   */
  async keep(
    plan: Planned,
    queue: Queueable,
    generation: number | undefined,
  ): Promise<Kept | undefined> {
    const key = plan.request.idempotencyKey;
    // Without the generation the failed request began under, the phone could not tell a pairing that has since ended.
    if (!key || generation === undefined) return undefined;
    switch (queue.kind) {
      case "purchase":
        return this.keepPurchase(queue, key, generation);
      case "add":
        return this.keepAdd(queue, key, generation);
      case "record":
        return this.keepRecord(queue, key, generation);
    }
  }

  private async keepPurchase(
    queue: Extract<Queueable, { kind: "purchase" }>,
    key: string,
    generation: number,
  ): Promise<Kept | undefined> {
    if (!this.native.queuePurchase) return undefined;
    try {
      const kept = await this.native.queuePurchase({
        itemId: queue.itemId,
        version: queue.version,
        purchased: queue.purchased,
        generation,
        idempotencyKey: key,
      });
      return kept.queued
        ? { purchased: kept.purchased ?? queue.purchased }
        : undefined;
    } catch {
      return undefined;
    }
  }

  private async keepAdd(
    queue: Extract<Queueable, { kind: "add" }>,
    key: string,
    generation: number,
  ): Promise<Kept | undefined> {
    if (!this.native.queueShoppingAdd) return undefined;
    try {
      const kept = await this.native.queueShoppingAdd({
        generation,
        listId: queue.listId,
        idempotencyKey: key,
        body: queue.body,
      });
      if (!kept.queued) return undefined;
    } catch {
      return undefined;
    }
    const add: QueuedShoppingAdd = {
      listId: queue.listId,
      key,
      queuedAt: Date.now(),
      items: queue.body.items,
      mergeDuplicates: queue.body.merge_duplicates === true,
    };
    // Before the answer: the room reads the list next, and must already know which of its rows are waiting.
    this.notify();
    return { answer: queuedAddResult(add) };
  }

  /** An edit with nothing to lay its change over (the record was never read here) is not kept: nothing the room could not show is queued. */
  private async keepRecord(
    queue: Extract<Queueable, { kind: "record" }>,
    key: string,
    generation: number,
  ): Promise<Kept | undefined> {
    if (!this.native.queueRecordWrite) return undefined;
    const standIn = standInFor(
      { kind: queue.write, subjectId: queue.subjectId, body: queue.body },
      key,
      this.known,
      Date.now(),
    );
    if (!standIn) return undefined;
    try {
      const kept = await this.native.queueRecordWrite({
        generation,
        kind: queue.write,
        ...(queue.subjectId ? { subjectId: queue.subjectId } : {}),
        ...(queue.version ? { version: queue.version } : {}),
        idempotencyKey: key,
        body: queue.body,
      });
      if (!kept.queued) return undefined;
    } catch {
      return undefined;
    }
    // The edit stands in for the record from now on, so a second edit lays its change over this one.
    this.known.remember(standIn);
    this.notify();
    return { answer: standIn };
  }

  /** A shopping list page with the items still waiting appended; the page as it is when nothing waits or it is not this list's. */
  async withAdds(
    args: Record<string, unknown>,
    body: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const { list_id: listId, store } = args;
    if (typeof listId !== "string") return body;
    const { adds } = await this.writes();
    return withQueuedAdds(
      body,
      listId.toLowerCase(),
      typeof store === "string" ? store : undefined,
      adds,
    );
  }

  /** A journal day page with the entries still waiting for that day appended. */
  async withEntries(
    args: Record<string, unknown>,
    body: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const { journal_date: day } = args;
    if (typeof day !== "string") return body;
    const { records } = await this.writes();
    return withQueuedEntries(body, day, records, this.known);
  }

  /** The stand-in Task of one made without a network, for the room that opens it; not found once it has been sent. */
  async task(id: string) {
    const { records } = await this.writes();
    const task = queuedTask(records, id, this.known);
    if (!task) throw new HostToolError("not_found");
    return { task };
  }
}

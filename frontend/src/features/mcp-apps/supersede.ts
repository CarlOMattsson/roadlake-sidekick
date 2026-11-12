/**
 * Instance supersession for MCP App cards. Claude mounts a new iframe per tool call and never
 * unmounts the older ones, so copies of the same card stay editable and keep pushing model
 * context. Each card announces its server-issued `issuedAt` and instance id on a
 * BroadcastChannel. An older card is superseded when a younger sibling is heard, and a younger
 * card answers an announcement from an older one so that the older card learns it was replaced.
 *
 * Ranking uses only `issuedAt` values from the server and the instance id as tie-breaker. Client
 * time is never compared with server time. Without BroadcastChannel no sibling can be heard, so
 * the instance is never superseded.
 */

const ANNOUNCE = "sidekick-card-announce";
const MAX_INSTANCE_ID_LENGTH = 200;

export type SupersessionOptions = {
  /** Name of the BroadcastChannel shared by all copies of the same card. */
  channel: string;
  /** Server-issued UTC ISO timestamp for the card (`card.issued_at`). */
  issuedAt: string;
  /** Stable id for this instance. Generated randomly when omitted. */
  instanceId?: string;
  /** Called with `true` once when a younger sibling is heard. */
  onSuperseded: (superseded: boolean) => void;
};

export type Supersession = {
  /** Stops listening and closes the channel. Safe to call more than once. */
  dispose: () => void;
};

type Peer = { issuedAt: string; instanceId: string };

type Announcement = Peer & { type: typeof ANNOUNCE };

export function createSupersession(options: SupersessionOptions): Supersession {
  const noop: Supersession = { dispose: () => undefined };
  if (typeof BroadcastChannel === "undefined") return noop;

  const self: Peer = {
    issuedAt: options.issuedAt,
    instanceId: options.instanceId ?? randomInstanceId(),
  };
  const channel = new BroadcastChannel(options.channel);
  let superseded = false;
  let disposed = false;

  const announce = (): void => {
    const message: Announcement = {
      type: ANNOUNCE,
      issuedAt: self.issuedAt,
      instanceId: self.instanceId,
    };
    channel.postMessage(message);
  };

  const onMessage = (event: MessageEvent<unknown>): void => {
    if (disposed) return;
    const peer = parseAnnouncement(event.data);
    if (!peer || peer.instanceId === self.instanceId) return;
    if (comparePeers(peer, self) > 0) {
      // A younger sibling exists: this instance is replaced. Only notify once.
      if (!superseded) {
        superseded = true;
        options.onSuperseded(true);
      }
      return;
    }
    // An older sibling announced itself: answer so that it learns it has been replaced.
    announce();
  };

  channel.addEventListener("message", onMessage);
  announce();

  return {
    dispose: () => {
      if (disposed) return;
      disposed = true;
      channel.removeEventListener("message", onMessage);
      channel.close();
    },
  };
}

/** Negative when `a` is older than `b`, positive when younger, zero for the same instance. */
function comparePeers(a: Peer, b: Peer): number {
  const timeA = Date.parse(a.issuedAt);
  const timeB = Date.parse(b.issuedAt);
  if (Number.isFinite(timeA) && Number.isFinite(timeB)) {
    if (timeA !== timeB) return timeA < timeB ? -1 : 1;
  } else if (a.issuedAt !== b.issuedAt) {
    return a.issuedAt < b.issuedAt ? -1 : 1;
  }
  if (a.instanceId === b.instanceId) return 0;
  return a.instanceId < b.instanceId ? -1 : 1;
}

function parseAnnouncement(data: unknown): Peer | undefined {
  if (typeof data !== "object" || data === null) return undefined;
  const candidate = data as Record<string, unknown>;
  if (candidate.type !== ANNOUNCE) return undefined;
  const { issuedAt, instanceId } = candidate;
  if (typeof issuedAt !== "string" || typeof instanceId !== "string")
    return undefined;
  if (instanceId.length === 0 || instanceId.length > MAX_INSTANCE_ID_LENGTH)
    return undefined;
  return { issuedAt, instanceId };
}

/** Random hex id from getRandomValues, which also works outside secure contexts. */
function randomInstanceId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(12));
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join(
    "",
  );
}

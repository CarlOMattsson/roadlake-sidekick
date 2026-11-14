import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  createSupersession,
  type Supersession,
} from "@/features/mcp-apps/supersede";

/**
 * Fictional BroadcastChannel: channels with the same name see each other's messages, senders
 * do not receive their own, and delivery is asynchronous like the real API.
 */
type Listener = (event: { data: unknown }) => void;

class FakeBroadcastChannel {
  static groups = new Map<string, Set<FakeBroadcastChannel>>();
  /** Deliveries queued but not yet run. A reply to a message is queued while delivering. */
  static pending = 0;

  private listeners = new Set<Listener>();
  private closed = false;

  constructor(readonly name: string) {
    this.group().add(this);
  }

  addEventListener(type: string, listener: Listener): void {
    if (type === "message") this.listeners.add(listener);
  }

  removeEventListener(type: string, listener: Listener): void {
    if (type === "message") this.listeners.delete(listener);
  }

  postMessage(data: unknown): void {
    if (this.closed) throw new Error("InvalidStateError: channel is closed");
    for (const peer of this.group()) {
      if (peer === this) continue;
      const payload = structuredClone(data);
      FakeBroadcastChannel.pending += 1;
      setTimeout(() => {
        peer.deliver(payload);
        FakeBroadcastChannel.pending -= 1;
      }, 0);
    }
  }

  close(): void {
    this.closed = true;
    this.group().delete(this);
  }

  private deliver(data: unknown): void {
    if (this.closed) return;
    for (const listener of this.listeners) listener({ data });
  }

  private group(): Set<FakeBroadcastChannel> {
    let members = FakeBroadcastChannel.groups.get(this.name);
    if (!members) {
      members = new Set();
      FakeBroadcastChannel.groups.set(this.name, members);
    }
    return members;
  }
}

const CHANNEL = "sidekick-card-test";
const OLDER = "2026-10-25T10:00:00Z";
const YOUNGER = "2026-10-25T10:05:00Z";

/**
 * Lets queued fake-channel deliveries run, including replies sent from within a delivery
 * (an older card's announcement is answered by a younger one, which takes a second hop).
 */
async function flush(): Promise<void> {
  while (FakeBroadcastChannel.pending > 0) {
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
  }
}

let instances: Supersession[];

beforeEach(() => {
  FakeBroadcastChannel.groups.clear();
  FakeBroadcastChannel.pending = 0;
  vi.stubGlobal("BroadcastChannel", FakeBroadcastChannel);
  instances = [];
});

afterEach(() => {
  for (const instance of instances) instance.dispose();
  vi.unstubAllGlobals();
});

function card(
  issuedAt: string,
  instanceId: string | undefined,
  onSuperseded = vi.fn<(superseded: boolean) => void>(),
) {
  const supersession = createSupersession({
    channel: CHANNEL,
    issuedAt,
    instanceId,
    onSuperseded,
  });
  instances.push(supersession);
  return { supersession, onSuperseded };
}

describe("createSupersession", () => {
  it("supersedes the older card when a younger sibling appears", async () => {
    const older = card(OLDER, "a");
    const younger = card(YOUNGER, "b");
    await flush();

    expect(older.onSuperseded).toHaveBeenCalledOnce();
    expect(older.onSuperseded).toHaveBeenCalledWith(true);
    expect(younger.onSuperseded).not.toHaveBeenCalled();
  });

  it("supersedes an older card that announces after a younger one exists", async () => {
    const younger = card(YOUNGER, "b");
    const older = card(OLDER, "a");
    await flush();

    expect(older.onSuperseded).toHaveBeenCalledOnce();
    expect(older.onSuperseded).toHaveBeenCalledWith(true);
    expect(younger.onSuperseded).not.toHaveBeenCalled();
  });

  it("ranks by parsed issuedAt, not by string order", async () => {
    // "…:00.5Z" is later than "…:00Z", but "." sorts before "Z" as a string.
    const plain = card("2026-10-25T10:00:00Z", "a");
    const fractional = card("2026-10-25T10:00:00.5Z", "b");
    await flush();

    expect(plain.onSuperseded).toHaveBeenCalledWith(true);
    expect(fractional.onSuperseded).not.toHaveBeenCalled();
  });

  it("breaks an issuedAt tie with instanceId", async () => {
    const low = card(OLDER, "instance-a");
    const high = card(OLDER, "instance-b");
    await flush();

    expect(low.onSuperseded).toHaveBeenCalledWith(true);
    expect(high.onSuperseded).not.toHaveBeenCalled();
  });

  it("generates an instance id when none is given, so exactly one of two equal cards is superseded", async () => {
    const first = card(OLDER, undefined);
    const second = card(OLDER, undefined);
    await flush();

    const calls =
      first.onSuperseded.mock.calls.length +
      second.onSuperseded.mock.calls.length;
    expect(calls).toBe(1);
  });

  it("calls onSuperseded only once even when several younger siblings appear", async () => {
    const older = card(OLDER, "a");
    card(YOUNGER, "b");
    card(YOUNGER, "c");
    card("2026-10-25T10:10:00Z", "d");
    await flush();

    expect(older.onSuperseded).toHaveBeenCalledOnce();
  });

  it("never supersedes a card when BroadcastChannel is missing", async () => {
    vi.stubGlobal("BroadcastChannel", undefined);
    const alone = card(OLDER, "a");
    await flush();

    expect(alone.onSuperseded).not.toHaveBeenCalled();
  });

  it("stops listening after dispose", async () => {
    const older = card(OLDER, "a");
    older.supersession.dispose();
    card(YOUNGER, "b");
    await flush();

    expect(older.onSuperseded).not.toHaveBeenCalled();
  });

  it("dispose can be called more than once", () => {
    const { supersession } = card(OLDER, "a");
    supersession.dispose();
    expect(() => supersession.dispose()).not.toThrow();
  });

  it("ignores malformed messages on the channel", async () => {
    const older = card(OLDER, "a");
    const intruder = new FakeBroadcastChannel(CHANNEL);
    intruder.postMessage({ type: "other", issuedAt: YOUNGER, instanceId: "b" });
    intruder.postMessage({
      type: "sidekick-card-announce",
      issuedAt: 42,
      instanceId: "b",
    });
    intruder.postMessage({
      type: "sidekick-card-announce",
      issuedAt: YOUNGER,
      instanceId: "",
    });
    intruder.postMessage("not an object");
    await flush();

    expect(older.onSuperseded).not.toHaveBeenCalled();
    intruder.close();
  });
});

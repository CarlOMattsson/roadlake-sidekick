import { vi } from "vitest";

import type {
  FailedWrite,
  SidekickNativePlugin,
  DeviceStatus,
  NativeLocale,
  NativeRequest,
  NativeResponse,
  PairingStatus,
  PairOptions,
  PushStatus,
  QueuePurchaseOptions,
  QueueShoppingAddOptions,
  TestPushResult,
} from "@/mobile/sidekick-native";

export type FakeNative = SidekickNativePlugin & {
  request: ReturnType<
    typeof vi.fn<(request: NativeRequest) => Promise<NativeResponse>>
  >;
  pair: ReturnType<
    typeof vi.fn<(options: PairOptions) => Promise<PairingStatus>>
  >;
  status: ReturnType<typeof vi.fn<() => Promise<PairingStatus>>>;
  unpair: ReturnType<typeof vi.fn<() => Promise<{ serverRevoked: boolean }>>>;
  widgetRefresh: ReturnType<typeof vi.fn<() => Promise<void>>>;
  setLocale: ReturnType<
    typeof vi.fn<(options: { tag: NativeLocale }) => Promise<void>>
  >;
  pushStatus: ReturnType<typeof vi.fn<() => Promise<PushStatus>>>;
  openNotificationSettings: ReturnType<typeof vi.fn<() => Promise<void>>>;
  requestNotificationPermission: ReturnType<typeof vi.fn<() => Promise<void>>>;
  openNtfyInstall: ReturnType<typeof vi.fn<() => Promise<void>>>;
  deviceStatus: ReturnType<typeof vi.fn<() => Promise<DeviceStatus>>>;
  sendTestPush: ReturnType<typeof vi.fn<() => Promise<TestPushResult>>>;
  /** Every request in order. */
  requests: NativeRequest[];
  /** Fires `pairingLost` as the native side does after a 401. */
  losePairing: () => void;
  queuePurchase: ReturnType<
    typeof vi.fn<
      (
        options: QueuePurchaseOptions,
      ) => Promise<{ queued: boolean; purchased?: boolean }>
    >
  >;
  queueShoppingAdd: ReturnType<
    typeof vi.fn<
      (options: QueueShoppingAddOptions) => Promise<{ queued: boolean }>
    >
  >;
  /** The phone's outbox of purchases, by item id. */
  outbox: Map<string, QueuePurchaseOptions>;
  /** The phone's outbox of added items, by the key of the add. */
  addOutbox: Map<string, QueueShoppingAddOptions>;
  /** The Task completions waiting in the phone's outbox (the widget's ticks too), by task id. */
  completions: Map<string, number>;
  /** The writes the phone gave up on (expired or refused), by key; `queueChanged` fires when a test adds one with `runOutbox`. */
  failedWrites: Map<string, FailedWrite>;
  retryQueuedWrite: ReturnType<
    typeof vi.fn<(options: { key: string }) => Promise<{ retried: boolean }>>
  >;
  removeQueuedWrite: ReturnType<
    typeof vi.fn<(options: { key: string }) => Promise<{ removed: boolean }>>
  >;
  /** Ends a run of the outbox: `sent` (item ids, or the keys of adds) leave it, then `queueChanged` fires as the native sync does. */
  runOutbox: (sent?: string[]) => void;
};

export type FakePairing = {
  /** Paired at the start. Default true. */
  paired?: boolean;
  /** Answers `pair`; a thrown error carries the closed code as the plugin's rejections do. */
  pair?: (options: PairOptions) => PairingStatus | Promise<PairingStatus>;
  /** What `deviceStatus` reports as `pushEnabled`; left out (unknown) by default, as for an older server. */
  pushEnabled?: boolean;
};

/**
 * A rejection as Capacitor delivers a native one: an Error with a closed `code`. A connection failure of `request`
 * also carries, in `data`, the pairing `generation` the request began under.
 */
export function nativeError(code: string, generation?: number): Error {
  return Object.assign(
    new Error(code),
    { code },
    generation === undefined ? {} : { data: { generation } },
  );
}

/**
 * A SidekickNative plugin that answers `request` from `handler` (a thrown error is "no answer came") and keeps a small
 * pairing state: `status` reports it, `pair` sets it, `unpair` clears it, `losePairing` fires `pairingLost`.
 */
export function fakeNative(
  handler: (request: NativeRequest) => NativeResponse | Promise<NativeResponse>,
  pairing: FakePairing = {},
): FakeNative {
  const requests: NativeRequest[] = [];
  const listeners = new Set<() => void>();
  const queueListeners = new Set<() => void>();
  const outbox = new Map<string, QueuePurchaseOptions>();
  const addOutbox = new Map<string, QueueShoppingAddOptions>();
  let state: PairingStatus =
    pairing.paired === false
      ? { paired: false }
      : { paired: true, serverHost: "sidekick.example" };

  const request = vi.fn(async (req: NativeRequest) => {
    requests.push(req);
    await Promise.resolve();
    return handler(req);
  });
  const pair = vi.fn(async (options: PairOptions) => {
    await Promise.resolve();
    state = pairing.pair
      ? await pairing.pair(options)
      : { paired: true, serverHost: new URL(options.serverUrl).hostname };
    return state;
  });
  const status = vi.fn(() => Promise.resolve(state));
  const unpair = vi.fn(() => {
    state = { paired: false };
    return Promise.resolve({ serverRevoked: true });
  });

  // A phone with ntfy installed and push working, so the push note is not drawn unless a test asks for it.
  const pushStatus = vi.fn<() => Promise<PushStatus>>(() =>
    Promise.resolve({
      distributor: true,
      registered: true,
      permission: "granted",
    }),
  );
  // The phone of the settings: named, paired a week ago, its credential good for another week.
  const deviceStatus = vi.fn<() => Promise<DeviceStatus>>(() =>
    Promise.resolve(
      state.paired
        ? {
            paired: true,
            name: "Samsung",
            pairedAt: "2026-11-01T09:00:00Z",
            expiresAt: "2026-11-15T09:00:00Z",
            ...(pairing.pushEnabled === undefined
              ? {}
              : { pushEnabled: pairing.pushEnabled }),
          }
        : { paired: false },
    ),
  );
  const sendTestPush = vi.fn<() => Promise<TestPushResult>>(() =>
    Promise.resolve({ outcome: "queued" }),
  );
  const openNotificationSettings = vi.fn(() => Promise.resolve());
  const requestNotificationPermission = vi.fn(() => Promise.resolve());
  const openNtfyInstall = vi.fn(() => Promise.resolve());
  const widgetRefresh = vi.fn(() => Promise.resolve());
  const setLocale = vi.fn<(options: { tag: NativeLocale }) => Promise<void>>(
    () => Promise.resolve(),
  );

  const queuePurchase = vi.fn((options: QueuePurchaseOptions) => {
    const kept = outbox.get(options.itemId) ?? options;
    outbox.set(options.itemId, kept);
    return Promise.resolve({ queued: true, purchased: kept.purchased });
  });

  // The same add queued again (same key) is the same add.
  const queueShoppingAdd = vi.fn((options: QueueShoppingAddOptions) => {
    if (!addOutbox.has(options.idempotencyKey))
      addOutbox.set(options.idempotencyKey, options);
    return Promise.resolve({ queued: true });
  });

  const completions = new Map<string, number>();
  const failedWrites = new Map<string, FailedWrite>();
  const retryQueuedWrite = vi.fn((options: { key: string }) =>
    Promise.resolve({ retried: failedWrites.delete(options.key) }),
  );
  const removeQueuedWrite = vi.fn((options: { key: string }) =>
    Promise.resolve({ removed: failedWrites.delete(options.key) }),
  );

  return {
    request,
    queuePurchase,
    failedWrites,
    completions,
    retryQueuedWrite,
    removeQueuedWrite,
    queueShoppingAdd,
    queuedWrites: () =>
      Promise.resolve({
        purchases: [...outbox.values()].map((entry) => ({
          itemId: entry.itemId,
          purchased: entry.purchased,
        })),
        adds: [...addOutbox.values()].map((entry, index) => ({
          listId: entry.listId,
          key: entry.idempotencyKey,
          queuedAt: Date.UTC(2026, 10, 11, 12, 0, index),
          items: entry.body.items,
          mergeDuplicates: entry.body.merge_duplicates === true,
        })),
        failed: [...failedWrites.values()],
        completions: [...completions].map(([taskId, queuedAt]) => ({
          taskId,
          queuedAt,
        })),
      }),
    outbox,
    addOutbox,
    runOutbox: (sent = [...outbox.keys(), ...addOutbox.keys()]) => {
      for (const id of sent) {
        outbox.delete(id);
        addOutbox.delete(id);
      }
      for (const listener of queueListeners) listener();
    },
    pair,
    status,
    unpair,
    widgetRefresh,
    setLocale,
    pushStatus,
    openNotificationSettings,
    requestNotificationPermission,
    openNtfyInstall,
    deviceStatus,
    sendTestPush,
    addListener: (event, listener) => {
      const set = event === "queueChanged" ? queueListeners : listeners;
      set.add(listener);
      return Promise.resolve({
        remove: () => {
          set.delete(listener);
          return Promise.resolve();
        },
      });
    },
    requests,
    losePairing: () => {
      state = { paired: false };
      for (const listener of listeners) listener();
    },
  };
}

export const ok = (body: unknown): NativeResponse => ({ status: 200, body });

/**
 * The typed Capacitor plugin the mobile app's network goes through (ADR-005, "C: Capacitor mobile shell").
 * JavaScript holds no token, no server address and no fetch: the Kotlin side owns HTTP, the Keystore token and the
 * cache, and answers one closed request shape. This file is only the TypeScript interface and its web stand-in; the
 * Kotlin plugin implements it under the same name ("SidekickNative").
 *
 * Contract with the native side (Kotlin: android/app/src/main/kotlin/com/roadlake/sidekick/companion/):
 * - `request` resolves with the HTTP status and the JSON body for every answer the server gave, 4xx and 5xx included,
 *   so the caller can read the server's closed error code. It rejects only when no answer came (no network, timeout,
 *   no pairing), which a room shows as a retryable failure.
 * - `path` is a companion route chosen by CompanionRoomTransport from its closed list, always under /companion/v1/.
 *   The native side must refuse any other path; it never receives a host or a URL from JavaScript.
 * - `idempotencyKey` becomes the `Idempotency-Key` header, byte for byte.
 * - The server address and the device credential belong to the pairing and stay native: the page chooses neither and
 *   can read neither. A 401 from the server removes the credential and fires `pairingLost`.
 * - Every rejection carries a closed `code` (see `nativeErrorCode`), never text built from request or response.
 */
import { registerPlugin, type PluginListenerHandle } from "@capacitor/core";

/** PUT is the license key's (companion-license.ts); the native side must allow it for that route. */
export type NativeMethod = "GET" | "POST" | "PUT";
/** Query values are strings or lists of strings; the transport has already turned numbers and booleans into text. */
export type NativeQuery = Record<string, string | string[]>;

export type NativeRequest = {
  method: NativeMethod;
  /** A companion route such as /companion/v1/tasks/<uuid>, without scheme, host or query. */
  path: string;
  query?: NativeQuery;
  /** The JSON body of a POST or PUT. */
  body?: Record<string, unknown>;
  /** The Idempotency-Key header of a write. The same action sends the same key again. */
  idempotencyKey?: string;
};

/** The languages the app, and so the widget, has texts for. */
export type NativeLocale = "sv" | "en";

/**
 * The server's answer. `cachedAt` is set only when no answer came and a shopping, Agenda or Task detail read was
 * answered from the phone's offline copy instead: the epoch millis that copy was read from the server.
 */
export type NativeResponse = {
  status: number;
  body: unknown;
  cachedAt?: number;
};

/** A shopping purchase waiting in the phone's outbox: the item and the state that will be sent. */
export type QueuedPurchase = { itemId: string; purchased: boolean };

/** A Task completion waiting in the phone's outbox (ticked in the widget or the app): the Task and when it was queued. */
export type QueuedCompletion = { taskId: string; queuedAt: number };

/**
 * Items added without a network, waiting in the phone's outbox: the list, the key the add was sent with, when it was
 * queued (epoch millis) and the items as the page sent them.
 */
export type QueuedShoppingAdd = {
  listId: string;
  key: string;
  queuedAt: number;
  items: Record<string, unknown>[];
  mergeDuplicates: boolean;
};

/**
 * A shopping write the phone will not send unless the user says so: it waited in the outbox longer than seven days
 * (`expired`) or the server refused it for good (`rejected`: changed elsewhere, gone, not valid). `key` names it for
 * `retryQueuedWrite` and `removeQueuedWrite`. An add (`kind: "add"`) carries its list and the items as the page sent
 * them; a purchase carries the item and the state it asked for.
 */
export type FailedWrite = {
  key: string;
  kind: "add" | "purchase";
  reason: "expired" | "rejected";
  queuedAt: number;
  /**
   * False when the key is older than the server's idempotency window: sending it again would be a new write, so
   * the write can only be removed. Absent (an older app version) reads as retryable.
   */
  retryable?: boolean;
  listId?: string;
  items?: Record<string, unknown>[];
  itemId?: string;
  purchased?: boolean;
};

/**
 * The add that got no answer, to be sent again from the outbox with the same key. `generation` is the pairing the failed
 * request began under, as for [QueuePurchaseOptions]. `body` is the request body the page built.
 */
export type QueueShoppingAddOptions = {
  generation: number;
  listId: string;
  idempotencyKey: string;
  body: { items: Record<string, unknown>[]; merge_duplicates?: boolean };
};

/**
 * The purchase that got no answer, to be sent again from the outbox with the same key and version. `generation` is the
 * pairing the failed request began under, as its rejection carried it (`nativeErrorGeneration`): the phone queues the
 * purchase only while that pairing is still the current one.
 */
export type QueuePurchaseOptions = {
  generation: number;
  itemId: string;
  version: number;
  purchased: boolean;
  idempotencyKey: string;
};

/** Whether the phone is paired, and with which host. Never a token or a secret. */
export type PairingStatus = {
  paired: boolean;
  /** The host name of the paired server ("sidekick.example"). Only when paired. */
  serverHost?: string;
  /** The name the operator gave the device when issuing the pairing ("Samsung"). Only when paired and set. */
  deviceLabel?: string;
  /** The rooms the server last said the instance shows (the stored copy, so it works offline). Absent: it never said. */
  enabledRooms?: string[];
  /** The owner's IANA time zone as the server last said (the stored copy, so it works offline). Absent: it never said. */
  ownerTimeZone?: string;
};

export type PairOptions = {
  /** The server's origin, e.g. "https://sidekick.example". HTTPS only (the debug build also takes http://10.0.2.2:port). */
  serverUrl: string;
  /** The single-use pairing secret the operator issued. The device label is the operator's, set at issue time. */
  pairingSecret: string;
};

/**
 * Whether push (UnifiedPush, with the ntfy app as distributor) can work on this phone. No endpoint, no token.
 * `distributor`: a distributor app is installed. `registered`: the server has this phone's endpoint.
 * `permission`: the notification permission; "prompt" until the one question after pairing has been asked.
 */
export type PushStatus = {
  distributor: boolean;
  registered: boolean;
  permission: "granted" | "denied" | "prompt";
};

/**
 * This phone's pairing as the settings show it. No token, no secret, no server address. `name` is the device label
 * the operator gave at issue time; `pairedAt` and `expiresAt` are ISO instants (the credential renews itself before
 * `expiresAt`); `enabledRooms` is the server's `SIDEKICK_ENABLED_ROOMS`, absent for an older server. `pushEnabled` is
 * whether the server delivers push (`SIDEKICK_PUSH_ENABLED`), as it last said and kept for a cold start offline; absent
 * when unknown (an older server, or it never answered), which is not the same as `false`. Only `paired` when the phone
 * is not paired.
 */
export type DeviceStatus = {
  paired: boolean;
  name?: string;
  pairedAt?: string;
  expiresAt?: string;
  enabledRooms?: string[];
  ownerTimeZone?: string;
  pushEnabled?: boolean;
};

/**
 * The closed answer of a test push. `queued`: the server queued one visible test notification. `rate_limited`: the
 * server allows a few per hour, `retryAfterSeconds` says when the next one is. `no_subscription`: the server has no
 * push endpoint for this phone yet. `disabled`: push is off on the server. `offline`: no answer came. `unpaired`: the
 * phone has no credential.
 */
export type TestPushOutcome =
  | "queued"
  | "rate_limited"
  | "no_subscription"
  | "disabled"
  | "offline"
  | "unpaired";

export type TestPushResult = {
  outcome: TestPushOutcome;
  retryAfterSeconds?: number;
};

export interface SidekickNativePlugin {
  request(request: NativeRequest): Promise<NativeResponse>;
  /** Exchanges the pairing secret for a device credential kept in the Keystore. Rejects with the server's closed code. */
  pair(options: PairOptions): Promise<PairingStatus>;
  status(): Promise<PairingStatus>;
  /**
   * Revokes this device on the server and clears the credential and cache on the phone. The phone is always cleared;
   * `serverRevoked` is false when the server could not confirm (whoever runs the server then revokes the device there).
   */
  unpair(): Promise<{ serverRevoked: boolean }>;
  /**
   * Tells the native side that something the home-screen widget shows may have changed (the page completed or
   * reopened a Task). The native side reads Today again in the background and redraws the widget; it resolves at once
   * and never fails the caller. The native side also notices a successful complete/reopen request by itself, so this
   * is for changes it cannot see.
   */
  widgetRefresh(): Promise<void>;
  /**
   * Tells the native side which language the app is set to ("sv" is the default, "en"), so the home-screen widget
   * draws its texts in it instead of the system language. Saved natively; the widget is redrawn. Rejects with
   * "bad_request" for any other tag.
   */
  setLocale(options: { tag: NativeLocale }): Promise<void>;
  /** Reads the push state. Never fails the caller for want of push: the app works without it (polling, foreground). */
  pushStatus(): Promise<PushStatus>;
  /**
   * Opens Android's notification settings for Sidekick. Where the permission was refused only the owner can turn it
   * on again. Rejects when no screen could open.
   */
  openNotificationSettings(): Promise<void>;
  /** Asks again for the notification permission and the distributor's endpoint, while the question is still open. */
  requestNotificationPermission(): Promise<void>;
  /** Opens the ntfy app's page in the app store (a browser page when no store app answers). Rejects when nothing could open. */
  openNtfyInstall(): Promise<void>;
  /** Reads this phone's pairing for the settings: its name, when it was paired and until when the credential holds. */
  deviceStatus(): Promise<DeviceStatus>;
  /**
   * Asks the server for one visible test notification to this phone. Resolves with a closed outcome for every answer,
   * also when none came (`offline`), so the settings can say what happened.
   */
  sendTestPush(): Promise<TestPushResult>;
  /**
   * Puts a purchase that got no answer in the phone's outbox (the widget's queue), which sends it as soon as a network
   * exists, also with the app closed. `purchased` is the state that will be sent: an entry already queued for the item
   * wins. `queued: false` when it could not be kept (no pairing, a full queue, a disk failure).
   */
  queuePurchase(
    options: QueuePurchaseOptions,
  ): Promise<{ queued: boolean; purchased?: boolean }>;
  /**
   * Puts items that got no answer when they were added in the outbox, to be sent with the same key as soon as a network
   * exists. `queued: false` when they could not be kept (no pairing, a full queue, a disk failure).
   */
  queueShoppingAdd(
    options: QueueShoppingAddOptions,
  ): Promise<{ queued: boolean }>;
  /**
   * The writes waiting in the outbox: purchases, added items and Task completions. `failed` are the ones that will
   * not be sent unless the user retries them; `completions` are the Tasks ticked (also from the widget) and not yet
   * sent. Both are absent from an older phone build: none. No network.
   */
  queuedWrites(): Promise<{
    purchases: QueuedPurchase[];
    adds: QueuedShoppingAdd[];
    failed?: FailedWrite[];
    completions?: QueuedCompletion[];
  }>;
  /** Puts a failed write back in the outbox to be sent again with its own key. `retried: false`: it was not there. */
  retryQueuedWrite(options: { key: string }): Promise<{ retried: boolean }>;
  /** Removes a failed write for good. `removed: false`: it was not there. */
  removeQueuedWrite(options: { key: string }): Promise<{ removed: boolean }>;
  /**
   * `pairingLost`: the server refused the credential (401); it is already removed. `queueChanged`: a run of the
   * outbox ended (it may have sent queued purchases), so a room reads again.
   */
  addListener(
    eventName: "pairingLost" | "queueChanged",
    listener: () => void,
  ): Promise<PluginListenerHandle>;
}

/** The closed codes of a request that got no answer because of the connection: no network, or none in time. */
export function isConnectionCode(code: string): code is "network" | "timeout" {
  return code === "network" || code === "timeout";
}

/** The closed code of a failed plugin call ("not_paired", "pairing_invalid", "timeout", ...), or "unknown". */
export function nativeErrorCode(error: unknown): string {
  if (typeof error === "object" && error !== null && "code" in error) {
    const code = error.code;
    if (typeof code === "string" && /^[a-z][a-z0-9_]{0,63}$/.test(code))
      return code;
  }
  return "unknown";
}

/**
 * The pairing generation a failed `request` began under (its connection failure carries it), or undefined. The page
 * only passes it back to `queuePurchase`; the phone decides whether that pairing is still the current one.
 */
export function nativeErrorGeneration(error: unknown): number | undefined {
  if (typeof error !== "object" || error === null || !("data" in error))
    return undefined;
  const data = error.data;
  if (typeof data !== "object" || data === null || !("generation" in data))
    return undefined;
  const generation = data.generation;
  return typeof generation === "number" &&
    Number.isSafeInteger(generation) &&
    generation >= 0
    ? generation
    : undefined;
}

/**
 * The plugin as the page sees it. In a browser (development, tests that do not inject a fake) the web
 * implementation refuses every request: there is no credential and no server address there.
 */
export const SidekickNative = registerPlugin<SidekickNativePlugin>(
  "SidekickNative",
  {
    web: () =>
      import("./sidekick-native-web").then(
        (module) => new module.SidekickNativeWeb(),
      ),
  },
);

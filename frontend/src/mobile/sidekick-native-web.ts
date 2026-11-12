import type {
  SidekickNativePlugin,
  DeviceStatus,
  NativeResponse,
  PairingStatus,
  PushStatus,
  TestPushResult,
} from "./sidekick-native";

const unavailable = () =>
  Promise.reject(
    Object.assign(new Error("SidekickNative is not available here"), {
      code: "unavailable",
    }),
  );

/**
 * The browser stand-in of the SidekickNative plugin. A browser has no paired device credential, so it is never paired
 * and every request is refused as "no answer came": the room shows its retryable failure. Tests inject their own
 * plugin instead.
 */
export class SidekickNativeWeb implements SidekickNativePlugin {
  request(): Promise<NativeResponse> {
    return unavailable();
  }
  pair(): Promise<PairingStatus> {
    return unavailable();
  }
  status(): Promise<PairingStatus> {
    return Promise.resolve({ paired: false });
  }
  unpair(): Promise<{ serverRevoked: boolean }> {
    return Promise.resolve({ serverRevoked: false });
  }
  widgetRefresh(): Promise<void> {
    return Promise.resolve();
  }
  setLocale(): Promise<void> {
    return Promise.resolve();
  }
  pushStatus(): Promise<PushStatus> {
    return Promise.resolve({
      distributor: false,
      registered: false,
      permission: "prompt",
    });
  }
  openNotificationSettings(): Promise<void> {
    return unavailable();
  }
  requestNotificationPermission(): Promise<void> {
    return Promise.resolve();
  }
  openNtfyInstall(): Promise<void> {
    return unavailable();
  }
  deviceStatus(): Promise<DeviceStatus> {
    return Promise.resolve({ paired: false });
  }
  sendTestPush(): Promise<TestPushResult> {
    return Promise.resolve({ outcome: "unpaired" });
  }
  queuePurchase(): Promise<{ queued: boolean }> {
    return Promise.resolve({ queued: false });
  }
  queueShoppingAdd(): Promise<{ queued: boolean }> {
    return Promise.resolve({ queued: false });
  }
  queuedWrites(): Promise<{
    purchases: [];
    adds: [];
    failed: [];
    completions: [];
  }> {
    return Promise.resolve({
      purchases: [],
      adds: [],
      failed: [],
      completions: [],
    });
  }
  retryQueuedWrite(): Promise<{ retried: boolean }> {
    return Promise.resolve({ retried: false });
  }
  removeQueuedWrite(): Promise<{ removed: boolean }> {
    return Promise.resolve({ removed: false });
  }
  addListener() {
    return Promise.resolve({ remove: () => Promise.resolve() });
  }
}

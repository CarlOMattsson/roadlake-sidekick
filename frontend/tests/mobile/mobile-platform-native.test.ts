import { beforeEach, describe, expect, it, vi } from "vitest";

type Listener = (event: unknown) => void;
const listeners = new Map<string, Listener>();
const exitApp = vi.fn(() => Promise.resolve());
const getLaunchUrl = vi.fn<() => Promise<{ url: string } | undefined>>();

vi.mock("@capacitor/app", () => ({
  App: {
    getLaunchUrl: () => getLaunchUrl(),
    exitApp: () => exitApp(),
    addListener: vi.fn((name: string, listener: Listener) => {
      listeners.set(name, listener);
      return Promise.resolve({ remove: () => listeners.delete(name) });
    }),
  },
}));

const { createNativePlatform, launchSearchOf } =
  await import("@/mobile/platform-native");

beforeEach(() => {
  listeners.clear();
  exitApp.mockClear();
  getLaunchUrl.mockResolvedValue(undefined);
});

const back = () => listeners.get("backButton")?.({ canGoBack: false });

describe("launchSearchOf", () => {
  it("takes the query of a sidekick://open link and nothing else", () => {
    expect(launchSearchOf("sidekick://open?view=today")).toBe("?view=today");
    expect(launchSearchOf("sidekick://open?view=task&id=abc#x")).toBe(
      "?view=task&id=abc",
    );
    expect(launchSearchOf("https://evil.example/?view=task")).toBe("");
    expect(launchSearchOf("sidekick://other?view=task")).toBe("");
    expect(launchSearchOf(undefined)).toBe("");
  });
});

describe("createNativePlatform", () => {
  it("hands the launch intent's hint to the launch search", async () => {
    getLaunchUrl.mockResolvedValue({
      url: "sidekick://open?view=task&id=3f2b8c1e-4d5a-4b6c-9d7e-8f9a0b1c2d3e",
    });
    const platform = await createNativePlatform();
    expect(platform.launchSearch()).toBe(
      "?view=task&id=3f2b8c1e-4d5a-4b6c-9d7e-8f9a0b1c2d3e",
    );
  });

  it("has an empty launch search for an ordinary launch", async () => {
    expect((await createNativePlatform()).launchSearch()).toBe("");
  });

  it("goes one layer back while a handler takes it, and leaves at the root", async () => {
    const platform = await createNativePlatform();
    let layers = 2;
    platform.onBack(() => {
      if (layers === 0) return false;
      layers -= 1;
      return true;
    });

    back();
    back();
    expect(exitApp).not.toHaveBeenCalled();
    back();
    expect(exitApp).toHaveBeenCalledTimes(1);
  });

  it("leaves the app on Back when no screen has registered", async () => {
    await createNativePlatform();
    back();
    expect(exitApp).toHaveBeenCalledTimes(1);
  });

  it("offers Back to the innermost handler, and to the outer one after it is gone", async () => {
    const platform = await createNativePlatform();
    const outer = vi.fn(() => true);
    const inner = vi.fn(() => true);
    platform.onBack(outer);
    const remove = platform.onBack(inner);

    back();
    expect(inner).toHaveBeenCalledTimes(1);
    expect(outer).not.toHaveBeenCalled();
    remove();
    back();
    expect(outer).toHaveBeenCalledTimes(1);
  });

  it("delivers a hint that arrives while the app runs", async () => {
    const platform = await createNativePlatform();
    const heard = vi.fn();
    platform.onLaunchSearch(heard);
    listeners.get("appUrlOpen")?.({ url: "sidekick://open?view=today" });
    expect(heard).toHaveBeenCalledWith("?view=today");
  });

  const pairUrl =
    "sidekick://pair?server=https%3A%2F%2Fsidekick.example&code=rspair_abcdefghijklmnop";
  const pairing = {
    serverUrl: "https://sidekick.example",
    code: "rspair_abcdefghijklmnop",
  };

  it("hands a pairing link the app was launched with to the gate, not to the launch search", async () => {
    getLaunchUrl.mockResolvedValue({ url: pairUrl });
    const platform = await createNativePlatform();
    expect(platform.pairingLink?.()).toEqual(pairing);
    expect(platform.launchSearch()).toBe("");
  });

  it("delivers a pairing link that arrives while the app runs, and only that to the pairing listener", async () => {
    const platform = await createNativePlatform();
    const heard = vi.fn();
    platform.onPairingLink?.(heard);
    listeners.get("appUrlOpen")?.({ url: "sidekick://open?view=today" });
    listeners.get("appUrlOpen")?.({ url: "sidekick://pair?code=x" });
    expect(heard).not.toHaveBeenCalled();
    listeners.get("appUrlOpen")?.({ url: pairUrl });
    expect(heard).toHaveBeenCalledWith(pairing);
  });

  it("does not send a pairing link to Today as a hint", async () => {
    const platform = await createNativePlatform();
    const heard = vi.fn();
    platform.onLaunchSearch(heard);
    listeners.get("appUrlOpen")?.({ url: pairUrl });
    expect(heard).not.toHaveBeenCalled();
  });

  it("leaves the insets to the CSS variables Capacitor publishes", async () => {
    expect((await createNativePlatform()).safeAreaInsets()).toBeUndefined();
  });

  it("tells a resume listener when the app becomes active, not when it goes to the background", async () => {
    const platform = await createNativePlatform();
    const heard = vi.fn();
    const stop = platform.onResume(heard);

    listeners.get("appStateChange")?.({ isActive: false });
    expect(heard).not.toHaveBeenCalled();
    listeners.get("appStateChange")?.({ isActive: true });
    expect(heard).toHaveBeenCalledTimes(1);

    stop();
    await Promise.resolve();
    expect(listeners.has("appStateChange")).toBe(false);
  });
});

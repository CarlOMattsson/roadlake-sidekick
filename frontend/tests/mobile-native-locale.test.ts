import { describe, expect, it } from "vitest";

import { SidekickNativeWeb } from "@/mobile/sidekick-native-web";

import { fakeNative, ok } from "./helpers/fake-native";

describe("SidekickNative.setLocale", () => {
  it("the fake registers each call with its tag", async () => {
    const native = fakeNative(() => ok({}));
    await native.setLocale({ tag: "en" });
    await native.setLocale({ tag: "sv" });
    expect(native.setLocale.mock.calls.map(([options]) => options)).toEqual([
      { tag: "en" },
      { tag: "sv" },
    ]);
  });

  it("the web implementation is a no-op that resolves", async () => {
    await expect(new SidekickNativeWeb().setLocale()).resolves.toBeUndefined();
  });
});

import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  licenseLabelsEn,
  licenseLabelsSv,
} from "@/features/mcp-apps/license-labels";
import { LicenseRow } from "@/features/mcp-apps/license-mark";
import { declareLicense } from "@/features/mcp-apps/license-state";

// With a shop address set the row keeps its invitation and the buy button; without one (the default, tested in
// mcp-license-signal.test.tsx) it states the version and says that licenses can soon be bought.
vi.mock("@/features/mcp-apps/license-state", async (importOriginal) => ({
  ...(await importOriginal<
    typeof import("@/features/mcp-apps/license-state")
  >()),
  LICENSE_BUY_URL: "https://example.test/buy/",
}));

const now = () => new Date("2026-11-09T12:00:00Z");

afterEach(() => {
  cleanup();
  act(() => declareLicense(undefined));
});

describe("the license row with a shop address", () => {
  it("invites a purchase and offers the buy button instead of the soon line", () => {
    act(() => declareLicense({ state: "unlicensed" }));
    render(<LicenseRow locale="sv" now={now} />);
    expect(screen.getByText(licenseLabelsSv.unlicensed)).toBeTruthy();
    expect(screen.getByText(licenseLabelsSv.buy)).toBeTruthy();
    expect(screen.queryByText(licenseLabelsSv.buySoon)).toBeNull();
  });

  it("invites a new purchase after the license ran out", () => {
    act(() => declareLicense({ state: "expired", expires: "2026-11-03" }));
    render(<LicenseRow locale="en" now={now} />);
    expect(
      screen.getByText(
        "Your license expired on Tue 3 Nov. You can buy a new one.",
      ),
    ).toBeTruthy();
    expect(screen.getByText(licenseLabelsEn.buy)).toBeTruthy();
  });
});

import { screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

// The mobile entry loads the native platform before drawing. When that fails, the user gets the short
// translated start-up card with "Försök igen" (not a blank screen), and nothing of the error is shown.

vi.mock("@capacitor/core", () => ({
  Capacitor: { isNativePlatform: () => true },
  registerPlugin: () => ({}),
}));
vi.mock("@/mobile/platform-native", () => {
  throw new Error("secret: Anna's token");
});

afterEach(() => {
  vi.restoreAllMocks();
});

it("shows the start-up error card when the platform cannot be loaded", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  document.body.innerHTML = '<div id="root"></div>';
  await import("@/mobile/main");

  const alert = await waitFor(() => screen.getByRole("alert"));
  expect(alert).toHaveTextContent("Sidekick kunde inte startas");
  expect(screen.getByRole("button", { name: "Försök igen" })).toBeVisible();
  expect(document.body.textContent).not.toContain("Anna");
});

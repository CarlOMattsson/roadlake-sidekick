import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AppFrame } from "@/features/mcp-apps/ui/layout";

describe.each(["inline", "full"] as const)("AppFrame mode=%s", (mode) => {
  it("is the frame root with data-mode and the body wrapper around the children", () => {
    const { container } = render(
      <AppFrame mode={mode}>
        <p>Innehåll</p>
      </AppFrame>,
    );

    const root = container.firstElementChild as HTMLElement;
    expect(root).toHaveClass("sk-frame");
    expect(root).toHaveAttribute("data-mode", mode);
    const body = root.firstElementChild as HTMLElement;
    expect(body).toHaveClass("sk-frame__body");
    expect(body).toContainElement(screen.getByText("Innehåll"));
  });
});

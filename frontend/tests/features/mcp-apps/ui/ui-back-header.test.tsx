import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { BackHeader } from "@/features/mcp-apps/ui/back-header";

describe("BackHeader", () => {
  it("names its Back button after the parent and calls onBack on click", () => {
    const onBack = vi.fn();
    render(<BackHeader label="Tavla" onBack={onBack} />);

    const back = screen.getByRole("button", { name: "Tillbaka till Tavla" });
    expect(back).toHaveTextContent("Tavla");
    expect(onBack).not.toHaveBeenCalled();

    fireEvent.click(back);
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it("shows the actions on the Back row and the title as a heading under that row", () => {
    const onMore = vi.fn();
    const { container } = render(
      <BackHeader
        label="Sidekick"
        title="Kontroll"
        onBack={() => undefined}
        actions={
          <button type="button" aria-label="Fler" onClick={onMore}>
            ⋯
          </button>
        }
      />,
    );

    const heading = screen.getByRole("heading", { level: 2, name: "Kontroll" });
    expect(heading).toBeInTheDocument();
    // The title is not inside the Back row: it comes after the row, as the view's own heading.
    const bar = container.querySelector(".sk-back-header__bar");
    expect(bar).not.toBeNull();
    expect(bar?.contains(heading)).toBe(false);
    expect(bar?.contains(screen.getByRole("button", { name: "Fler" }))).toBe(
      true,
    );
    fireEvent.click(screen.getByRole("button", { name: "Fler" }));
    expect(onMore).toHaveBeenCalledTimes(1);
  });

  it("draws no title and no action row when none is given", () => {
    const { container } = render(
      <BackHeader label="Listor" onBack={() => undefined} />,
    );

    expect(screen.queryByRole("heading")).toBeNull();
    expect(container.querySelector(".sk-back-header__actions")).toBeNull();
    expect(
      screen.getByRole("button", { name: "Tillbaka till Listor" }),
    ).toBeInTheDocument();
  });

  it("has no heading form any more: the text after ‹ always names the parent and the name reads 'Tillbaka till {label}'", () => {
    const { container } = render(
      <BackHeader label="Arbete" onBack={() => undefined} />,
    );

    expect(container.querySelector(".sk-back-header")).not.toHaveClass(
      "sk-back-header--heading",
    );
    const back = screen.getByRole("button", { name: "Tillbaka till Arbete" });
    expect(back).toHaveTextContent("Arbete");
    expect(back.querySelector("svg")).not.toBeNull();
    expect(container.querySelector(".sk-back-header__title")).toBeNull();
  });
});

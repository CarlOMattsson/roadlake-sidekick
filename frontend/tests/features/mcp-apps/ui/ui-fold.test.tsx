import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Fold } from "@/features/mcp-apps/ui/fold";

describe("Fold, the one fold row", () => {
  it("is a button with aria-expanded, the counted text, an optional meta line, and ⌄ last", () => {
    const onToggle = vi.fn();
    render(
      <Fold
        text="Done here (2)"
        meta="Since you opened the agenda"
        open={false}
        onToggle={onToggle}
      />,
    );
    const fold = screen.getByRole("button");
    expect(fold).toHaveClass("sk-fold");
    expect(fold).toHaveAttribute("type", "button");
    expect(fold).toHaveAttribute("aria-expanded", "false");
    expect(fold.querySelector(".sk-count")).toHaveTextContent("(2)");
    expect(fold.querySelector(".sk-fold-meta")).toHaveTextContent(
      "Since you opened the agenda",
    );
    expect(fold.lastElementChild?.tagName.toLowerCase()).toBe("svg");
    fireEvent.click(fold);
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it("has no meta element without a meta, reports open, and takes an extra class", () => {
    render(
      <Fold text="Contact ways" open onToggle={vi.fn()} className="extra" />,
    );
    const fold = screen.getByRole("button", { name: "Contact ways" });
    expect(fold).toHaveClass("sk-fold", "extra");
    expect(fold).toHaveAttribute("aria-expanded", "true");
    expect(fold.querySelector(".sk-fold-meta")).toBeNull();
  });

  it("names the region it opens through aria-controls when given one, and leaves the attribute out otherwise", () => {
    const { rerender } = render(
      <Fold
        text="Links (3)"
        open={false}
        onToggle={vi.fn()}
        controls="body-1"
      />,
    );
    expect(screen.getByRole("button")).toHaveAttribute(
      "aria-controls",
      "body-1",
    );

    rerender(<Fold text="Links (3)" open={false} onToggle={vi.fn()} />);
    expect(screen.getByRole("button")).not.toHaveAttribute("aria-controls");
  });
});

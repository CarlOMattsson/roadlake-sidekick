import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it, vi } from "vitest";

import { Row, type RowProps } from "@/features/mcp-apps/ui/row";

const css = readFileSync(
  path.resolve(import.meta.dirname, "../src/features/mcp-apps/ui/row.css"),
  "utf8",
);

function renderRow(props: Partial<RowProps> & { primary: string }) {
  return render(
    <ul>
      <Row {...props} />
    </ul>,
  );
}

describe("Row DOM structure", () => {
  it("is an li whose leading and open controls are sibling buttons, never nested", () => {
    renderRow({
      primary: "Köp mjölk",
      secondary: "Inköp · 2 st",
      leading: <span>G</span>,
      onLeading: vi.fn(),
      onOpen: vi.fn(),
    });

    const item = screen.getByRole("listitem");
    const buttons = within(item).getAllByRole("button");
    expect(buttons).toHaveLength(2);
    expect(buttons[0]).toHaveClass("sk-row-lead");
    expect(buttons[1]).toHaveClass("sk-row-open");
    for (const button of buttons) {
      expect(button.parentElement).toBe(item);
      expect(button.querySelector("button")).toBeNull();
    }
    expect(buttons[0]).toHaveTextContent("G");
    expect(buttons[0]).not.toHaveTextContent("Köp mjölk");
    expect(buttons[1]).toHaveTextContent("Köp mjölk");
    expect(buttons[1]).toHaveTextContent("Inköp · 2 st");
  });

  it("renders the title as text and puts trailing text in the open control", () => {
    renderRow({
      primary: "Projekt Kök",
      trailing: "Fre 3 nov",
      onOpen: vi.fn(),
    });

    const open = screen.getByRole("button", { name: /Projekt Kök/ });
    expect(open).toHaveClass("sk-row-open");
    expect(within(open).getByText("Fre 3 nov")).toHaveClass("sk-row-trailing");
    expect(within(open).getByText("Projekt Kök")).toHaveClass("sk-row-primary");
  });

  it("shows the chevron only when the row navigates", () => {
    const { unmount } = renderRow({ primary: "Detalj", onOpen: vi.fn() });
    expect(screen.getByRole("listitem").querySelector("svg")).toBeNull();
    expect(screen.getByRole("listitem")).not.toHaveAttribute("data-navigates");
    unmount();

    renderRow({ primary: "Detalj", navigates: true, onOpen: vi.fn() });
    const chevron = screen.getByRole("listitem").querySelector("svg");
    expect(chevron).not.toBeNull();
    expect(chevron).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByRole("listitem")).toHaveAttribute(
      "data-navigates",
      "true",
    );
  });

  it("renders no control for a handler that is not given", () => {
    const { unmount } = renderRow({
      primary: "Enbart öppna",
      onOpen: vi.fn(),
    });
    expect(screen.getAllByRole("button")).toHaveLength(1);
    unmount();

    renderRow({ primary: "Ingen åtgärd" });
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByRole("listitem")).toHaveTextContent("Ingen åtgärd");
  });
});

describe("Row keyboard and pointer", () => {
  it("opens with Enter and Space on the open control", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    const onLeading = vi.fn();
    renderRow({
      primary: "Uppgift",
      leading: <span>G</span>,
      onLeading,
      onOpen,
    });

    const open = screen.getByRole("button", { name: /Uppgift/ });
    open.focus();
    await user.keyboard("{Enter}");
    expect(onOpen).toHaveBeenCalledTimes(1);
    await user.keyboard(" ");
    expect(onOpen).toHaveBeenCalledTimes(2);
    expect(onLeading).not.toHaveBeenCalled();
  });

  it("runs the leading action with Enter and Space and not the open action", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    const onLeading = vi.fn();
    renderRow({
      primary: "Uppgift",
      leading: <span>G</span>,
      onLeading,
      onOpen,
    });

    const lead = screen.getByRole("listitem").querySelector("button");
    expect(lead).not.toBeNull();
    lead?.focus();
    await user.keyboard("{Enter}");
    expect(onLeading).toHaveBeenCalledTimes(1);
    await user.keyboard(" ");
    expect(onLeading).toHaveBeenCalledTimes(2);
    expect(onOpen).not.toHaveBeenCalled();
  });

  it("moves focus leading first, then open, in DOM order", async () => {
    const user = userEvent.setup();
    renderRow({
      primary: "Uppgift",
      leading: <span>G</span>,
      onLeading: vi.fn(),
      onOpen: vi.fn(),
    });

    const [lead, open] = screen.getAllByRole("button");
    await user.tab();
    expect(lead).toHaveFocus();
    await user.tab();
    expect(open).toHaveFocus();
    await user.tab({ shift: true });
    expect(lead).toHaveFocus();
  });

  it("calls onOpen on a click on the title and onLeading on a click on the leading slot", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    const onLeading = vi.fn();
    renderRow({
      primary: "Uppgift",
      leading: <span>G</span>,
      onLeading,
      onOpen,
    });

    await user.click(screen.getByText("Uppgift"));
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onLeading).not.toHaveBeenCalled();

    await user.click(screen.getByText("G"));
    expect(onLeading).toHaveBeenCalledTimes(1);
    expect(onOpen).toHaveBeenCalledTimes(1);
  });
});

describe("row.css", () => {
  it("reads the row template: a --sk-row-min floor, --sk-row-pad of air, no hairline, and a title clamp that only the line-limit token sets", () => {
    const rowRule = css.match(/\.sk-row \{[^}]*\}/)?.[0] ?? "";
    // The floor is the one row token (48 px in tokens.css, ui-tokens.test.ts), not a literal of its own.
    expect(rowRule).toMatch(/min-height:\s*var\(--sk-row-min\)/);
    expect(rowRule).not.toMatch(/border-bottom/);
    // The open area holds the 6 of air over the title line and under the last text line.
    const openRule = css.match(/^\.sk-row-open \{[^}]*\}/m)?.[0] ?? "";
    expect(openRule).toMatch(/padding:\s*var\(--sk-row-pad\) 0;/);

    // The title is cut only by the token: `none` in an inline card, 3 in a full-screen list (layout.css).
    const primaryRule = css.match(/\.sk-row-primary \{[^}]*\}/)?.[0] ?? "";
    expect(primaryRule).toMatch(
      /-webkit-line-clamp:\s*var\(--sk-row-title-lines, none\);/,
    );
    expect(primaryRule).not.toMatch(/-webkit-line-clamp:\s*\d/);
  });

  it("holds the metarad to one line cut with an ellipsis, and sets tabular numbers on the trailing text", () => {
    const secondaryRule = css.match(/\.sk-row-secondary \{[^}]*\}/)?.[0] ?? "";
    expect(secondaryRule).toMatch(/white-space:\s*nowrap/);
    expect(secondaryRule).toMatch(/text-overflow:\s*ellipsis/);
    expect(secondaryRule).toMatch(/overflow:\s*hidden/);
    expect(secondaryRule).not.toMatch(/line-height:\s*1\.4/);

    const trailingRule = css.match(/\.sk-row-trailing \{[^}]*\}/)?.[0] ?? "";
    expect(trailingRule).toMatch(/font-variant-numeric:\s*tabular-nums/);
  });

  it("uses no colour-scheme media query, so the host decides the theme", () => {
    expect(css).not.toContain("prefers-color-scheme");
  });
});

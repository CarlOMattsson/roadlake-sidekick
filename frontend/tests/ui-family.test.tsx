import { readFileSync } from "node:fs";
import path from "node:path";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Button, buttonClass } from "@/features/mcp-apps/ui/button";
import { Card, Eyebrow } from "@/features/mcp-apps/ui/card";
import { Notice, UndoNotice } from "@/features/mcp-apps/ui/notice";
import { ErrorNotice } from "@/features/mcp-apps/ui/states";

const uiDir = path.resolve(import.meta.dirname, "../src/features/mcp-apps/ui");

describe("Card", () => {
  it("renders eyebrow, title, body and actions in the family order", () => {
    render(
      <Card
        eyebrow="Uppgift"
        title="Skicka offert"
        actions={<Button variant="primary">Öppna</Button>}
        aria-label="Uppgiftskort"
      >
        <p>Förfaller fre</p>
      </Card>,
    );
    const card = screen.getByRole("region", { name: "Uppgiftskort" });
    expect(card).toHaveClass("sk-card");
    expect(card.children[0]).toHaveClass("sk-eyebrow");
    expect(card.children[0]).toHaveTextContent("Uppgift");
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(
      "Skicka offert",
    );
    expect(card.lastElementChild).toHaveClass("sk-card__actions");
  });

  it("puts the optional muted line between the body and the actions (designsystem §3)", () => {
    render(
      <Card
        eyebrow="Dagbok · sparad 10:20"
        title="Tisdag"
        meta="Sammanfattad av Claude"
        actions={<Button variant="primary">Öppna anteckningen</Button>}
        aria-label="Dagbokskort"
      >
        <p>Text</p>
      </Card>,
    );
    const card = screen.getByRole("region", { name: "Dagbokskort" });
    const classes = [...card.children].map((child) => child.className);
    expect(classes).toEqual([
      "sk-eyebrow",
      "sk-card__title",
      "",
      "sk-card__meta",
      "sk-card__actions",
    ]);
    expect(card.querySelector(".sk-card__meta")).toHaveTextContent(
      "Sammanfattad av Claude",
    );
  });

  it("leaves out an empty eyebrow and uses the requested element and level", () => {
    const { container } = render(
      <Card as="article" title="Titel" headingLevel={3} aria-label="Post">
        <p>Text</p>
      </Card>,
    );
    expect(container.querySelector(".sk-eyebrow")).toBeNull();
    expect(screen.getByRole("article", { name: "Post" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3 })).toBeInTheDocument();
  });

  it("Eyebrow can be a heading element", () => {
    render(<Eyebrow as="h1">Dagbok</Eyebrow>);
    expect(screen.getByRole("heading", { level: 1 })).toHaveClass("sk-eyebrow");
  });
});

describe("Button", () => {
  it("defaults to a secondary button of type button", () => {
    render(<Button>Avbryt</Button>);
    const button = screen.getByRole("button", { name: "Avbryt" });
    expect(button).toHaveAttribute("type", "button");
    expect(button).toHaveClass("sk-btn", "sk-btn--secondary");
  });

  it("gives each variant its class", () => {
    expect(buttonClass("primary")).toBe("sk-btn sk-btn--primary");
    expect(buttonClass("quiet", "x")).toBe("sk-btn sk-btn--quiet x");
    expect(buttonClass("danger")).toContain("sk-btn--danger");
  });
});

describe("Notice and UndoNotice", () => {
  it("is a polite status region with the message and an action", () => {
    render(
      <Notice tone="success" action={<button>Ok</button>}>
        Sparat
      </Notice>,
    );
    const notice = screen.getByRole("status");
    expect(notice).toHaveClass("sk-notice", "sk-notice--success");
    expect(notice).toHaveTextContent("Sparat");
  });

  it("UndoNotice calls onUndo, sticks by default and disables while busy", () => {
    const onUndo = vi.fn();
    const { rerender } = render(
      <UndoNotice
        message="Flyttad till Klar"
        undoLabel="Ångra"
        onUndo={onUndo}
      />,
    );
    expect(screen.getByRole("status")).toHaveClass("sk-notice--sticky");
    fireEvent.click(screen.getByRole("button", { name: "Ångra" }));
    expect(onUndo).toHaveBeenCalledTimes(1);
    rerender(
      <UndoNotice
        message="Flyttad till Klar"
        undoLabel="Ångra"
        onUndo={onUndo}
        busy
      />,
    );
    expect(screen.getByRole("button", { name: "Ångra" })).toBeDisabled();
  });
});

describe("ErrorNotice placement", () => {
  it("defaults to the card placement and can sit at the row", () => {
    const { rerender } = render(
      <ErrorNotice locale="sv" onRetry={() => undefined} />,
    );
    expect(screen.getByRole("alert")).toHaveClass("sk-error--card");
    rerender(<ErrorNotice locale="sv" placement="row" />);
    expect(screen.getByRole("alert")).toHaveClass("sk-error--row");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("puts extra actions beside the retry", () => {
    render(
      <ErrorNotice locale="sv" onRetry={() => undefined}>
        <button type="button">Läs om</button>
      </ErrorNotice>,
    );
    expect(screen.getByRole("button", { name: "Försök igen" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Läs om" })).toBeVisible();
  });
});

describe("family.css", () => {
  const css = readFileSync(path.join(uiDir, "family.css"), "utf8");
  it("uses tokens only: no hex outside var() or light-dark()", () => {
    const stripped = css
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/var\([^)]*\)/g, "");
    expect(stripped).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    expect(css).not.toMatch(/prefers-color-scheme/);
  });
  it("keeps every button at least 44 px high (the tap token; the phone raises it to 48)", () => {
    expect(css).toMatch(/min-height:\s*var\(--sk-tap\)/);
  });
  it("fullscreen frames lift every sticky notice above the foot reserve", () => {
    expect(css).toMatch(
      /\.sk-frame\[data-mode="full"\] \{[^}]*--sk-notice-bottom: var\(--sk-foot-reserve, 6rem\);/,
    );
  });
});

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { QuoteBlock, quoteText } from "@/features/mcp-apps/ui/quote-block";
import { TrustNote } from "@/features/mcp-apps/ui/trust-note";

describe("TrustNote", () => {
  it("says the level in words beside the glyph, as a note", () => {
    const { rerender } = render(
      <TrustNote state="unsure" reason="Namnet finns redan." locale="sv-SE" />,
    );
    const note = screen.getByRole("note");
    expect(note).toHaveTextContent("Kontrollen var osäker");
    expect(note).toHaveTextContent("Namnet finns redan.");
    expect(note.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    rerender(<TrustNote state="suspicious" locale="en-GB" />);
    expect(screen.getByRole("note")).toHaveTextContent("Suspicious suggestion");
    expect(screen.getByRole("note")).toHaveAttribute(
      "data-trust",
      "suspicious",
    );
  });

  it("takes another heading for what is not a suggestion, and runs heading and reason together on request", () => {
    render(
      <TrustNote
        state="unsure"
        locale="sv-SE"
        title="Rapporten var osäker"
        reason="Två källor angav olika datum."
        flow="run"
      />,
    );
    expect(screen.getByRole("note")).toHaveTextContent(
      "Rapporten var osäker: Två källor angav olika datum.",
    );
  });
});

describe("QuoteBlock", () => {
  it("shows the label and the text as plain text, never as markup or a link", () => {
    render(
      <QuoteBlock
        label="Ur mejlet, inte skrivet av Sidekick"
        text={"Hej <b>Carl</b>!\n[klicka](https://evil.example.com/a?b=1)"}
      />,
    );
    const figure = screen.getByRole("figure");
    expect(figure.querySelector("figcaption")).toHaveTextContent(
      "Ur mejlet, inte skrivet av Sidekick",
    );
    expect(figure.querySelector("b")).toBeNull();
    expect(figure.querySelector("a")).toBeNull();
    expect(figure).toHaveTextContent("Hej <b>Carl</b>!");
    expect(figure).toHaveTextContent("[klicka](evil.example.com)");
  });

  it("turns every web address into its domain name and drops script addresses", () => {
    expect(quoteText("Se https://www.example.com/x?y=1.")).toBe(
      "Se example.com.",
    );
    expect(quoteText("eller www.bank.example.se/login, tack")).toBe(
      "eller bank.example.se, tack",
    );
    expect(quoteText("klicka javascript:alert(1) nu")).toBe("klicka … nu");
    expect(quoteText("data:text/html;base64,PHNjcmlwdD4= här")).toBe("… här");
    expect(quoteText("ftp://files.example.org/a")).toBe("…");
    expect(quoteText("ingen adress här")).toBe("ingen adress här");
  });
});

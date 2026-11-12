import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  EmptyState,
  ErrorNotice,
  Skeleton,
  SkeletonRows,
  errorLabelsFor,
} from "@/features/mcp-apps/ui/states";
import { RoomSurfaceContext } from "@/features/mcp-apps/ui/room-context";
import { HostToolError } from "@/features/mcp-apps/bridge";

import { readStylesheet } from "./helpers/stylesheet";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("Skeleton timing", () => {
  it("renders nothing before the 150 ms delay has passed", () => {
    render(<Skeleton />);

    act(() => {
      vi.advanceTimersByTime(149);
    });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.getByRole("status")).toHaveAttribute("aria-busy", "true");
  });

  it("shows nothing when loading finishes before the delay", () => {
    const { rerender } = render(<Skeleton loading />);

    act(() => {
      vi.advanceTimersByTime(100);
    });
    rerender(<Skeleton loading={false} />);
    act(() => {
      vi.advanceTimersByTime(1000);
    });

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("keeps the skeleton for at least 300 ms after it appeared", () => {
    const { rerender } = render(<Skeleton loading />);

    // Shown at 150 ms, loading ends at 200 ms: it must stay until 450 ms.
    act(() => {
      vi.advanceTimersByTime(200);
    });
    rerender(<Skeleton loading={false} />);

    act(() => {
      vi.advanceTimersByTime(249);
    });
    expect(screen.getByRole("status")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("hides straight away when loading ends after the minimum has passed", () => {
    const { rerender } = render(<Skeleton loading />);

    act(() => {
      vi.advanceTimersByTime(600);
    });
    expect(screen.getByRole("status")).toBeInTheDocument();

    rerender(<Skeleton loading={false} />);
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("waits the delay again on the next load", () => {
    const { rerender } = render(<Skeleton loading />);

    act(() => {
      vi.advanceTimersByTime(150);
    });
    rerender(<Skeleton loading={false} />);
    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();

    rerender(<Skeleton loading />);
    act(() => {
      vi.advanceTimersByTime(149);
    });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});

describe("Skeleton rows", () => {
  it("renders the neutral skeleton: five rows, no heading and no glyph by default", () => {
    const { container } = render(<Skeleton />);
    act(() => {
      vi.advanceTimersByTime(150);
    });

    expect(container.querySelectorAll(".sidekick-wait-row")).toHaveLength(5);
    expect(container.querySelector(".sidekick-wait-section")).toBeNull();
    expect(container.querySelector(".sidekick-wait-glyph")).toBeNull();
    expect(container.textContent).toBe("");
  });

  it("adds one heading bar and the rings on request, never a group guess", () => {
    const { container } = render(<Skeleton heading glyph />);
    act(() => {
      vi.advanceTimersByTime(150);
    });

    expect(container.querySelectorAll(".sidekick-wait-section")).toHaveLength(
      1,
    );
    expect(container.querySelectorAll(".sidekick-wait-glyph")).toHaveLength(5);
  });
});

describe("EmptyState", () => {
  it("shows the title and the hint", () => {
    render(
      <EmptyState
        title="Inget förfaller."
        hint="Säg 'lägg till uppgift…' till Claude."
      />,
    );

    expect(screen.getByText("Inget förfaller.")).toBeInTheDocument();
    expect(
      screen.getByText("Säg 'lägg till uppgift…' till Claude."),
    ).toBeInTheDocument();
  });

  it("renders only the title when no hint is given", () => {
    const { container } = render(<EmptyState title="Inga uppgifter ännu." />);

    expect(screen.getByText("Inga uppgifter ännu.")).toBeInTheDocument();
    expect(container.querySelectorAll("p")).toHaveLength(1);
  });
});

describe("ErrorNotice", () => {
  it("is an alert with a Swedish sentence and retry button for sv", () => {
    render(<ErrorNotice locale="sv" onRetry={vi.fn()} />);

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Det gick inte att läsa just nu",
    );
    expect(screen.getByRole("button", { name: "Försök igen" })).toHaveClass(
      "sk-error-retry",
      "sk-btn",
      "sk-btn--primary",
    );
  });

  it("uses English text for non-sv locales", () => {
    render(<ErrorNotice locale="en-US" onRetry={vi.fn()} />);

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Couldn’t load this right now",
    );
    expect(
      screen.getByRole("button", { name: "Try again" }),
    ).toBeInTheDocument();
  });

  it("calls onRetry when the button is pressed", () => {
    const onRetry = vi.fn();
    render(<ErrorNotice locale="sv" onRetry={onRetry} />);

    fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));

    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("shows a surface-supplied message instead of the generic one", () => {
    render(
      <ErrorNotice
        locale="sv"
        message="Kunde inte läsa agendan."
        onRetry={vi.fn()}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Kunde inte läsa agendan.",
    );
    expect(
      screen.queryByText("Det gick inte att läsa just nu"),
    ).not.toBeInTheDocument();
  });
});

describe("ErrorNotice heading by subject", () => {
  it("names a failed read of a room in its heading, and says Sidekick answered when it gave its own code", () => {
    render(
      <ErrorNotice
        locale="sv"
        subject="work"
        cause={new HostToolError("forbidden")}
        onRetry={vi.fn()}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Uppgifterna kunde inte hämtas",
    );
    expect(screen.getByText("Uppgifterna kunde inte hämtas")).toHaveClass(
      "sk-error-message",
    );
    expect(screen.queryByText("Försök igen om en stund.")).toBeNull();
    // Sidekick's own closed code: the second line says the answer came from Sidekick, not from the connection.
    expect(document.querySelector(".sk-error-hint")).toHaveTextContent(
      "Sidekick svarade med ett fel.",
    );
    expect(
      screen.getByRole("button", { name: "Försök igen" }),
    ).toBeInTheDocument();
  });

  it("takes the heading from the room the surface shows when no subject is given", () => {
    render(
      <RoomSurfaceContext.Provider
        value={{
          active: true,
          framed: true,
          room: "contacts",
          view: "contact",
        }}
      >
        <ErrorNotice locale="sv" onRetry={vi.fn()} />
      </RoomSurfaceContext.Provider>,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Kontakten kunde inte hämtas",
    );
  });

  it("says Sidekick did not answer and, only when the request itself failed, to check the connection; a tool answer without a code says only that Sidekick did not answer; no second line without a cause", () => {
    const onLine = vi
      .spyOn(window.navigator, "onLine", "get")
      .mockReturnValue(true);
    try {
      // A request that failed before any answer (a plain Error): the connection.
      const { container, rerender } = render(
        <ErrorNotice
          locale="sv"
          subject="work"
          cause={new Error("Host request failed")}
          onRetry={vi.fn()}
        />,
      );
      expect(container.querySelector(".sk-error-hint")).toHaveTextContent(
        "Sidekick svarade inte. Kontrollera anslutningen.",
      );
      expect(screen.queryByText(/Försök igen om en stund/)).toBeNull();
      expect(
        screen.getByRole("button", { name: "Försök igen" }),
      ).toBeInTheDocument();
      rerender(
        <ErrorNotice
          locale="en"
          subject="work"
          cause={new Error("Host request failed")}
          onRetry={vi.fn()}
        />,
      );
      expect(container.querySelector(".sk-error-hint")).toHaveTextContent(
        "Sidekick didn’t respond. Check your connection.",
      );
      // isError without Sidekick's closed code (HostToolError): the host answered, so it is not the connection.
      rerender(
        <ErrorNotice
          locale="sv"
          subject="work"
          cause={new HostToolError(undefined)}
          onRetry={vi.fn()}
        />,
      );
      expect(container.querySelector(".sk-error-hint")?.textContent).toBe(
        "Sidekick svarade inte.",
      );
      expect(screen.queryByText(/Kontrollera anslutningen/)).toBeNull();
      expect(screen.queryByText(/Försök igen om en stund/)).toBeNull();
      rerender(
        <ErrorNotice
          locale="en"
          subject="work"
          cause={new HostToolError(undefined)}
          onRetry={vi.fn()}
        />,
      );
      expect(container.querySelector(".sk-error-hint")?.textContent).toBe(
        "Sidekick didn’t respond.",
      );
      expect(screen.queryByText(/Check your connection/)).toBeNull();
      expect(screen.queryByText(/Try again in a moment/)).toBeNull();
      // Without a cause nothing is known about the failure, so there is no second line at all.
      rerender(<ErrorNotice locale="sv" subject="work" onRetry={vi.fn()} />);
      expect(container.querySelector(".sk-error-hint")).toBeNull();
    } finally {
      onLine.mockRestore();
    }
  });

  it("a tool answer without a code says to check the connection when the device is offline", () => {
    const onLine = vi
      .spyOn(window.navigator, "onLine", "get")
      .mockReturnValue(false);
    try {
      const { container, rerender } = render(
        <ErrorNotice
          locale="sv"
          subject="work"
          cause={new HostToolError(undefined)}
          onRetry={vi.fn()}
        />,
      );
      expect(container.querySelector(".sk-error-hint")).toHaveTextContent(
        "Sidekick svarade inte. Kontrollera anslutningen.",
      );
      rerender(
        <ErrorNotice
          locale="en"
          subject="work"
          cause={new HostToolError(undefined)}
          onRetry={vi.fn()}
        />,
      );
      expect(container.querySelector(".sk-error-hint")).toHaveTextContent(
        "Sidekick didn’t respond. Check your connection.",
      );
    } finally {
      onLine.mockRestore();
    }
  });

  it("says Sidekick did not answer, not that the connection is down, when the frame is offline too", () => {
    const onLine = vi
      .spyOn(window.navigator, "onLine", "get")
      .mockReturnValue(false);
    try {
      const { container, rerender } = render(
        <ErrorNotice
          locale="sv"
          subject="work"
          cause={new Error("Host request failed")}
          onRetry={vi.fn()}
        />,
      );
      expect(container.querySelector(".sk-error-hint")).toHaveTextContent(
        "Sidekick svarade inte. Kontrollera anslutningen.",
      );
      expect(screen.queryByText(/Försök igen om en stund/)).toBeNull();
      expect(screen.queryByText(/offline/i)).toBeNull();
      rerender(
        <ErrorNotice
          locale="en"
          subject="work"
          cause={new Error("Host request failed")}
          onRetry={vi.fn()}
        />,
      );
      expect(
        screen.getByText("Sidekick didn’t respond. Check your connection."),
      ).toHaveClass("sk-error-hint");
      expect(screen.queryByText(/offline/i)).toBeNull();
      // Sidekick answered with its own closed code: the second line says so.
      rerender(
        <ErrorNotice
          locale="en"
          subject="work"
          cause={new HostToolError("forbidden")}
          onRetry={vi.fn()}
        />,
      );
      expect(screen.getByText("Sidekick responded with an error.")).toHaveClass(
        "sk-error-hint",
      );
    } finally {
      onLine.mockRestore();
    }
  });

  it("says Försöker igen… while a retry runs, aria-busy, and ignores a second press", () => {
    const onRetry = vi.fn();
    render(<ErrorNotice locale="sv" retrying onRetry={onRetry} />);
    const button = screen.getByRole("button", { name: "Försöker igen…" });
    expect(button).toHaveAttribute("aria-busy", "true");
    expect(button).toHaveAttribute("aria-disabled", "true");
    fireEvent.click(button);
    expect(onRetry).not.toHaveBeenCalled();
  });

  it("draws a failed refresh as one row with a secondary compact Försök igen", () => {
    const onRetry = vi.fn();
    render(<ErrorNotice locale="sv" placement="refresh" onRetry={onRetry} />);
    expect(screen.getByRole("alert")).toHaveClass("sk-error--refresh");
    expect(screen.getByText("Kunde inte uppdatera")).toBeInTheDocument();
    const button = screen.getByRole("button", { name: "Försök igen" });
    expect(button).toHaveClass(
      "sk-btn",
      "sk-btn--secondary",
      "sk-btn--compact",
    );
    expect(button).not.toHaveClass("sk-btn--tonal");
    fireEvent.click(button);
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("has the same keys in Swedish and English", () => {
    expect(Object.keys(errorLabelsFor("sv"))).toEqual(
      Object.keys(errorLabelsFor("en")),
    );
  });

  it("has the same subjects in Swedish and English", () => {
    expect(Object.keys(errorLabelsFor("sv").subjects)).toEqual(
      Object.keys(errorLabelsFor("en").subjects),
    );
  });
});

describe("states styling", () => {
  const css = readStylesheet("features/mcp-apps/ui/states.css");

  it("draws the skeleton with the waiting placeholder's blocks, whose pulse stops under reduced motion", () => {
    const wait = readStylesheet("features/mcp-apps/awaiting.css");
    render(<SkeletonRows rows={1} />);
    const block = document.querySelector(".sidekick-wait-block") as Element;

    expect(
      css.rules.some((rule) =>
        rule.declarations.animation?.includes("sk-skeleton-pulse"),
      ),
    ).toBe(false);
    expect(
      wait.styleOf(block, {
        conditions: ["@media (prefers-reduced-motion: reduce)"],
      }).animation,
    ).toBe("none");
  });

  it("uses no pixel font sizes", () => {
    for (const rule of css.rules) {
      expect(rule.declarations["font-size"] ?? "", rule.selector).not.toMatch(
        /^\d+px$/,
      );
    }
  });
});

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { aiUsageEn, aiUsageSv } from "@/features/control-app/ai-usage-labels";
import { AiUsageRow } from "@/features/control-app/ai-usage-row";
import type { AiUsage } from "@/features/control-app/transport";

// The AI cost row of Control: drawn and read only where the instance switched it on (the app document's meta), in the
// app language. Rendered with a fake transport, not in a real Claude or Android host.

const usage: AiUsage = {
  month_starts_at: "2026-11-01T00:00:00Z",
  spent_usd: 0.42,
  client_estimate_usd: 0,
  monthly_cap_usd: 5,
  starts_today: 3,
  daily_starts_cap: 50,
};

function switchOn() {
  const meta = document.createElement("meta");
  meta.name = "sidekick-ai-usage";
  meta.content = "on";
  document.head.append(meta);
}

afterEach(() => {
  document.head.querySelector('meta[name="sidekick-ai-usage"]')?.remove();
});

describe("the AI cost row", () => {
  it("is off by default: nothing is drawn and get_ai_usage is never called", () => {
    const aiUsage = vi.fn().mockResolvedValue(usage);
    const { container } = render(
      <AiUsageRow transport={{ aiUsage }} locale="sv" />,
    );
    expect(container).toBeEmptyDOMElement();
    expect(aiUsage).not.toHaveBeenCalled();
  });

  it("draws nothing where the host offers no get_ai_usage", () => {
    switchOn();
    const { container } = render(<AiUsageRow transport={{}} locale="sv" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("says what the month cost of the cap and today's starts, in Swedish", async () => {
    switchOn();
    const aiUsage = vi.fn().mockResolvedValue(usage);
    render(<AiUsageRow transport={{ aiUsage }} locale="sv" />);
    expect(screen.getByRole("status")).toHaveTextContent(aiUsageSv.loading);
    expect(await screen.findByText("0,42 USD av 5,00 USD")).toBeInTheDocument();
    expect(screen.getByText(/^AI denna månad:/)).toBeInTheDocument();
    expect(screen.getByText("3 av 50 starter i dag")).toBeInTheDocument();
    // No estimate from Claude Code: the row does not mention it.
    expect(screen.queryByText(/Claude Code/)).toBeNull();
    expect(aiUsage).toHaveBeenCalledTimes(1);
  });

  it("adds Claude Code's own estimate only when it has one, in English", async () => {
    switchOn();
    const aiUsage = vi
      .fn()
      .mockResolvedValue({ ...usage, client_estimate_usd: 0.1 });
    render(<AiUsageRow transport={{ aiUsage }} locale="en" />);
    expect(await screen.findByText("0.42 USD of 5.00 USD")).toBeInTheDocument();
    expect(
      screen.getByText(
        "3 of 50 starts today · 0.10 USD estimated by Claude Code",
      ),
    ).toBeInTheDocument();
  });

  it("says when the cost could not be read and reads again on Try again", async () => {
    switchOn();
    const aiUsage = vi
      .fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue(usage);
    render(<AiUsageRow transport={{ aiUsage }} locale="en" />);
    expect(await screen.findByText(aiUsageEn.failed)).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: aiUsageEn.retry }),
    );
    await waitFor(() => expect(aiUsage).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("0.42 USD of 5.00 USD")).toBeInTheDocument();
  });

  it("reads again when the room asks", async () => {
    switchOn();
    const aiUsage = vi.fn().mockResolvedValue(usage);
    const { rerender } = render(
      <AiUsageRow transport={{ aiUsage }} locale="sv" refreshKey={0} />,
    );
    await screen.findByText("0,42 USD av 5,00 USD");
    rerender(<AiUsageRow transport={{ aiUsage }} locale="sv" refreshKey={1} />);
    await waitFor(() => expect(aiUsage).toHaveBeenCalledTimes(2));
  });

  it("has the same keys in Swedish and English", () => {
    expect(Object.keys(aiUsageEn).sort()).toEqual(
      Object.keys(aiUsageSv).sort(),
    );
  });
});

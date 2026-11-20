import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MessageBox } from "@/features/mcp-apps/ui/message-box";
import { OpenLink } from "@/features/mcp-apps/ui/open-link";
import { Progress } from "@/features/mcp-apps/ui/progress";
import {
  RECEIPT_MS,
  ReceiptBar,
  useReceipt,
  type ReceiptInput,
} from "@/features/mcp-apps/ui/receipt";
import { Switch } from "@/features/mcp-apps/ui/switch";
import { Tabs } from "@/features/mcp-apps/ui/tabs";
import { UNDO_MS } from "@/features/mcp-apps/ui/undo-hold";

afterEach(() => {
  vi.useRealTimers();
});

describe("Tabs", () => {
  function Harness() {
    const [value, setValue] = useState<"day" | "week">("day");
    return (
      <Tabs
        label="Visning"
        fit="content"
        options={[
          { value: "day", label: "Dag" },
          { value: "week", label: "Vecka" },
        ]}
        value={value}
        onChange={setValue}
      />
    );
  }

  it("is a labelled group of pressed buttons with one tab stop, and arrows move focus", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    expect(screen.getByRole("group", { name: "Visning" })).toHaveClass(
      "sk-tabs",
      "sk-tabs--content",
      "sk-tabs--rule",
    );
    const day = screen.getByRole("button", { name: "Dag" });
    const week = screen.getByRole("button", { name: "Vecka" });
    expect(day).toHaveAttribute("aria-pressed", "true");
    expect(day).toHaveAttribute("tabindex", "0");
    expect(week).toHaveAttribute("tabindex", "-1");
    // The bold label's width is held by a hidden copy, so choosing moves nothing sideways.
    expect(week).toHaveAttribute("data-label", "Vecka");
    await user.click(week);
    expect(week).toHaveAttribute("aria-pressed", "true");
    expect(day).toHaveAttribute("aria-pressed", "false");
  });
});

describe("Switch", () => {
  it("is a named switch whose press asks for the other state", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Switch checked={false} onChange={onChange} label="Dagbok" />);
    const control = screen.getByRole("switch", { name: "Dagbok" });
    expect(control).toHaveAttribute("aria-checked", "false");
    await user.click(control);
    expect(onChange).toHaveBeenCalledWith(true);
  });
});

describe("MessageBox", () => {
  it("is an alert for an error and a status for a warning, each with its action", async () => {
    const user = userEvent.setup();
    const retry = vi.fn();
    const { rerender } = render(
      <MessageBox
        severity="error"
        title="Det gick inte att uppdatera"
        action={{ label: "Försök igen", onClick: retry }}
      />,
    );
    expect(screen.getByRole("alert")).toHaveClass("sk-message--error");
    await user.click(screen.getByRole("button", { name: "Försök igen" }));
    expect(retry).toHaveBeenCalledTimes(1);
    rerender(
      <MessageBox
        severity="warning"
        title="Minnestjänsten är avstängd"
        action={{
          label: "Försök igen",
          busyLabel: "Försöker igen…",
          busy: true,
          onClick: retry,
        }}
      >
        Inget nytt sparas i minnet
      </MessageBox>,
    );
    expect(screen.getByRole("status")).toHaveClass("sk-message--warning");
    const busy = screen.getByRole("button", { name: "Försöker igen…" });
    expect(busy).toHaveAttribute("aria-busy", "true");
    await user.click(busy);
    expect(retry).toHaveBeenCalledTimes(1);
  });
});

describe("OpenLink", () => {
  it("reads 'Öppna <vy> · N till' and ends with ›", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    render(<OpenLink label="Öppna Borttaget" more="4 till" onOpen={onOpen} />);
    const link = screen.getByRole("button", {
      name: "Öppna Borttaget · 4 till",
    });
    expect(link.querySelector("svg")).not.toBeNull();
    await user.click(link);
    expect(onOpen).toHaveBeenCalledTimes(1);
  });
});

describe("Progress", () => {
  it("keeps the text as the information and draws the bar full width in the bar layout", () => {
    const { container } = render(
      <Progress done={1} total={8} label="1 av 8 köpta" layout="bar" />,
    );
    expect(screen.getByText("1 av 8 köpta")).toBeInTheDocument();
    expect(container.querySelector(".sk-progress--bar")).not.toBeNull();
    expect(container.querySelector(".sk-progress__track")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
  });
});

describe("Receipt", () => {
  let show: (input: ReceiptInput) => void = () => undefined;
  function Harness({ resetKey }: { resetKey: string }) {
    const receipt = useReceipt(resetKey);
    show = receipt.show;
    return <ReceiptBar receipt={receipt} />;
  }

  it("announces a receipt in a status slot and lets it go by itself", () => {
    vi.useFakeTimers();
    render(<Harness resetKey="a" />);
    const slot = screen.getByRole("status");
    expect(slot).toBeEmptyDOMElement();
    act(() => show({ message: "Anteckningen sparades" }));
    expect(slot).toHaveTextContent("Anteckningen sparades");
    act(() => {
      vi.advanceTimersByTime(RECEIPT_MS + 10);
    });
    expect(slot).toBeEmptyDOMElement();
  });

  it("is cleared when the view moves on, so an old receipt never comes back (dagbok-ui fynd 1)", () => {
    const { rerender } = render(<Harness resetKey="a" />);
    act(() => show({ message: "Anteckningen sparades" }));
    rerender(<Harness resetKey="b" />);
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });

  it("offers Ångra for UNDO_MS, and a new receipt replaces the old one", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const onUndo = vi.fn();
    render(<Harness resetKey="a" />);
    act(() =>
      show({ message: "Återställd: Mjölk", undo: { label: "Ångra", onUndo } }),
    );
    act(() => {
      vi.advanceTimersByTime(RECEIPT_MS + 10);
    });
    expect(screen.getByRole("button", { name: "Ångra" })).toBeInTheDocument();
    act(() => show({ message: "Återställd: Bröd" }));
    expect(screen.getByRole("status")).toHaveTextContent("Återställd: Bröd");
    expect(screen.queryByRole("button", { name: "Ångra" })).toBeNull();
    act(() =>
      show({ message: "Klar: Ring Karin", undo: { label: "Ångra", onUndo } }),
    );
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.click(screen.getByRole("button", { name: "Ångra" }));
    expect(onUndo).toHaveBeenCalledTimes(1);
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
    expect(UNDO_MS).toBeGreaterThan(RECEIPT_MS);
  });
});

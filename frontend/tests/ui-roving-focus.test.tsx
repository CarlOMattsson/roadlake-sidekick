import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { useRovingFocus } from "@/features/mcp-apps/ui/roving-focus";

function Row({ labels, onPress }: { labels: string[]; onPress?: () => void }) {
  const onKeyDown = useRovingFocus();
  return (
    <>
      <div role="group" aria-label="Vyer" onKeyDown={onKeyDown}>
        {labels.map((label) => (
          <button key={label} type="button" onClick={onPress}>
            {label}
          </button>
        ))}
      </div>
      <button type="button">Utanför</button>
    </>
  );
}

const labels = ["Agenda", "Status", "Projekt"];

describe("useRovingFocus", () => {
  it("moves focus to the next and previous button with the arrow keys", async () => {
    const user = userEvent.setup();
    render(<Row labels={labels} />);
    const agenda = screen.getByRole("button", { name: "Agenda" });
    const status = screen.getByRole("button", { name: "Status" });
    const projekt = screen.getByRole("button", { name: "Projekt" });
    agenda.focus();

    await user.keyboard("{ArrowRight}");
    expect(status).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    expect(projekt).toHaveFocus();
    await user.keyboard("{ArrowLeft}");
    expect(status).toHaveFocus();
    await user.keyboard("{ArrowUp}");
    expect(agenda).toHaveFocus();
  });

  it("wraps at both ends", async () => {
    const user = userEvent.setup();
    render(<Row labels={labels} />);
    const first = screen.getByRole("button", { name: "Agenda" });
    const last = screen.getByRole("button", { name: "Projekt" });
    first.focus();

    await user.keyboard("{ArrowLeft}");
    expect(last).toHaveFocus();
    await user.keyboard("{ArrowRight}");
    expect(first).toHaveFocus();
  });

  it("jumps to the first and last button with Home and End", async () => {
    const user = userEvent.setup();
    render(<Row labels={labels} />);
    const first = screen.getByRole("button", { name: "Agenda" });
    const last = screen.getByRole("button", { name: "Projekt" });
    first.focus();

    await user.keyboard("{End}");
    expect(last).toHaveFocus();
    await user.keyboard("{Home}");
    expect(first).toHaveFocus();
  });

  it("leaves other keys alone so Enter still presses the focused button", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(<Row labels={labels} onPress={onClick} />);
    const status = screen.getByRole("button", { name: "Status" });
    status.focus();

    await user.keyboard("a");
    expect(status).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("ignores arrow keys pressed outside the group", async () => {
    const user = userEvent.setup();
    render(<Row labels={labels} />);
    const outside = screen.getByRole("button", { name: "Utanför" });
    outside.focus();

    await user.keyboard("{ArrowRight}");
    expect(outside).toHaveFocus();
  });
});

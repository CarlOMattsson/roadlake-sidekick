import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  Segmented,
  type SegmentedOption,
} from "@/features/mcp-apps/ui/segmented";

import { readStylesheet } from "./helpers/stylesheet";

const optionsWithBadge: SegmentedOption<string>[] = [
  { value: "todo", label: "Att göra", badge: "7" },
  { value: "doing", label: "Pågår", badge: "3" },
  { value: "blocked", label: "Blockerad", badge: "1" },
  { value: "completed", label: "Klar", badge: "12" },
];

describe("Segmented badge", () => {
  it("shows the badge on a second row and names the option with its count", () => {
    const { container } = render(
      <Segmented
        label="Kolumner"
        options={optionsWithBadge}
        value="doing"
        onChange={vi.fn()}
      />,
    );

    const doing = screen.getByRole("button", { name: "Pågår 3" });
    expect(doing).toHaveAttribute("aria-pressed", "true");
    expect(doing).toHaveClass("sk-segmented__option--badged");

    const badge = doing.querySelector(".sk-segmented__badge");
    expect(badge).not.toBeNull();
    expect(badge?.textContent).toBe("3");
    expect(doing.querySelector(".sk-segmented__label")?.textContent).toBe(
      "Pågår",
    );

    expect(
      screen.getByRole("button", { name: "Att göra 7" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Blockerad 1" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Klar 12" })).toBeInTheDocument();
    expect(container.querySelectorAll(".sk-segmented__badge")).toHaveLength(4);
  });

  it("keeps options without a badge as plain labels", () => {
    const { container } = render(
      <Segmented
        label="Vyer"
        options={[
          { value: "agenda", label: "Agenda" },
          { value: "board", label: "Board", badge: "2" },
        ]}
        value="agenda"
        onChange={vi.fn()}
      />,
    );

    const agenda = screen.getByRole("button", { name: "Agenda" });
    expect(agenda.textContent).toBe("Agenda");
    expect(agenda).not.toHaveClass("sk-segmented__option--badged");
    expect(agenda.querySelector(".sk-segmented__badge")).toBeNull();
    expect(container.querySelectorAll(".sk-segmented__badge")).toHaveLength(1);
  });

  it("calls onChange with the value when a badged option is clicked", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <Segmented
        label="Kolumner"
        options={optionsWithBadge}
        value="todo"
        onChange={onChange}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Klar 12" }));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("completed");
  });
});

describe("Segmented badge styling", () => {
  it("lays the badged option out in two rows with tabular figures and keeps 44 px height", () => {
    const css = readStylesheet("features/mcp-apps/ui/segmented.css");
    render(
      <Segmented
        label="Uppgifter"
        options={optionsWithBadge}
        value="todo"
        onChange={vi.fn()}
      />,
    );
    const option = screen.getByRole("button", { name: "Att göra 7" });

    expect(option).toHaveClass("sk-segmented__option--badged");
    expect(css.styleOf(option)["flex-direction"]).toBe("column");
    expect(
      css.styleOf(option.querySelector(".sk-segmented__badge") as Element)[
        "font-variant-numeric"
      ],
    ).toBe("tabular-nums");
    expect(css.styleOf(option)["min-height"]).toBe("2.75rem");
  });
});

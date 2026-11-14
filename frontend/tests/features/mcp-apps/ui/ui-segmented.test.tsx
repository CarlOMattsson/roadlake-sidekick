import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  Segmented,
  type SegmentedOption,
} from "@/features/mcp-apps/ui/segmented";

const optionsSv: SegmentedOption<string>[] = [
  { value: "agenda", label: "Agenda" },
  { value: "board", label: "Board" },
  { value: "hierarki", label: "Hierarki" },
  { value: "kontakter", label: "Kontakter" },
];

const optionsEn: SegmentedOption<string>[] = [
  { value: "agenda", label: "Agenda" },
  { value: "board", label: "Board" },
  { value: "hierarchy", label: "Hierarchy" },
  { value: "contacts", label: "Contacts" },
];

describe.each([
  {
    name: "sv",
    groupLabel: "Vyer",
    options: optionsSv,
    labels: ["Agenda", "Board", "Hierarki", "Kontakter"],
  },
  {
    name: "en",
    groupLabel: "Views",
    options: optionsEn,
    labels: ["Agenda", "Board", "Hierarchy", "Contacts"],
  },
])("Segmented ($name)", ({ groupLabel, options, labels }) => {
  it("shows every option as a visible button with its label, and no menu", () => {
    render(
      <Segmented
        label={groupLabel}
        options={options}
        value="agenda"
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByRole("group", { name: groupLabel })).toBeInTheDocument();
    const buttons = screen.getAllByRole("button");
    expect(buttons.map((button) => button.textContent)).toEqual(labels);
    buttons.forEach((button) => {
      expect(button).toHaveAttribute("type", "button");
    });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(screen.queryByRole("menuitem")).not.toBeInTheDocument();
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("marks only the value as pressed with aria-pressed", () => {
    render(
      <Segmented
        label={groupLabel}
        options={options}
        value="board"
        onChange={vi.fn()}
      />,
    );

    const buttons = screen.getAllByRole("button");
    expect(buttons[0]).toHaveAttribute("aria-pressed", "false");
    expect(buttons[1]).toHaveAttribute("aria-pressed", "true");
    expect(buttons[2]).toHaveAttribute("aria-pressed", "false");
    expect(buttons[3]).toHaveAttribute("aria-pressed", "false");
  });

  it("calls onChange with the value when an unpressed option is clicked", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <Segmented
        label={groupLabel}
        options={options}
        value="agenda"
        onChange={onChange}
      />,
    );

    await user.click(screen.getByRole("button", { name: labels[1] }));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("board");
  });

  it("does not call onChange when the pressed option is clicked", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <Segmented
        label={groupLabel}
        options={options}
        value="agenda"
        onChange={onChange}
      />,
    );

    await user.click(screen.getByRole("button", { name: labels[0] }));

    expect(onChange).not.toHaveBeenCalled();
  });

  it("selects with Enter and Space on the focused option", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <Segmented
        label={groupLabel}
        options={options}
        value="agenda"
        onChange={onChange}
      />,
    );

    screen.getByRole("button", { name: labels[2] }).focus();
    await user.keyboard("{Enter}");
    expect(onChange).toHaveBeenLastCalledWith(options[2]?.value);

    screen.getByRole("button", { name: labels[3] }).focus();
    await user.keyboard(" ");
    expect(onChange).toHaveBeenLastCalledWith(options[3]?.value);
  });

  it("moves focus with arrow keys without changing the selection", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <Segmented
        label={groupLabel}
        options={options}
        value="agenda"
        onChange={onChange}
      />,
    );

    const first = screen.getByRole("button", { name: labels[0] });
    const second = screen.getByRole("button", { name: labels[1] });
    first.focus();

    await user.keyboard("{ArrowRight}");
    expect(second).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("button", { name: labels[2] })).toHaveFocus();
    await user.keyboard("{ArrowLeft}");
    expect(second).toHaveFocus();
    await user.keyboard("{ArrowUp}");
    expect(first).toHaveFocus();

    expect(onChange).not.toHaveBeenCalled();
    expect(first).toHaveAttribute("aria-pressed", "true");
  });

  it("wraps focus at both ends and jumps with Home and End", async () => {
    const user = userEvent.setup();
    render(
      <Segmented
        label={groupLabel}
        options={options}
        value="agenda"
        onChange={vi.fn()}
      />,
    );

    const first = screen.getByRole("button", { name: labels[0] });
    const last = screen.getByRole("button", { name: labels[3] });
    first.focus();

    await user.keyboard("{ArrowLeft}");
    expect(last).toHaveFocus();
    await user.keyboard("{ArrowRight}");
    expect(first).toHaveFocus();
    await user.keyboard("{End}");
    expect(last).toHaveFocus();
    await user.keyboard("{Home}");
    expect(first).toHaveFocus();
  });

  it("keeps only the pressed option in the Tab order", () => {
    render(
      <Segmented
        label={groupLabel}
        options={options}
        value={options[2]?.value ?? null}
        onChange={vi.fn()}
      />,
    );

    const buttons = screen.getAllByRole("button");
    expect(buttons.map((button) => button.tabIndex)).toEqual([-1, -1, 0, -1]);
  });

  it("makes the first option the Tab stop when nothing is pressed", () => {
    render(
      <Segmented
        label={groupLabel}
        options={options}
        value={null}
        onChange={vi.fn()}
      />,
    );

    const buttons = screen.getAllByRole("button");
    expect(
      buttons.every(
        (button) => button.getAttribute("aria-pressed") === "false",
      ),
    ).toBe(true);
    expect(buttons.map((button) => button.tabIndex)).toEqual([0, -1, -1, -1]);
  });

  it("disables every option while disabled, so clicks do nothing", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <Segmented
        label={groupLabel}
        options={options}
        value="agenda"
        onChange={onChange}
        disabled
      />,
    );

    const buttons = screen.getAllByRole("button");
    buttons.forEach((button) => {
      expect(button).toBeDisabled();
    });

    await user.click(screen.getByRole("button", { name: labels[1] }));
    expect(onChange).not.toHaveBeenCalled();
  });
});

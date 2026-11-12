import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import {
  useViewPicker,
  type PickerOption,
} from "@/features/mcp-apps/ui/view-picker";

// The one picker of the room strip and of the views that use it: with no chosen option (Kontroll, where no
// room is chosen) the button says the placeholder and no option is marked; an opened menu puts the focus on the chosen
// option, or on the first one when none is chosen.

type Room = "arbete" | "dagbok";
const options: PickerOption<Room>[] = [
  { value: "arbete", label: "Arbete" },
  { value: "dagbok", label: "Dagbok" },
];

function Picker({
  value,
  placeholder,
  onChange = vi.fn(),
}: {
  value?: Room;
  placeholder?: string;
  onChange?: (value: Room) => void;
}) {
  const { button, menu } = useViewPicker<Room>({
    label: "Rum",
    options,
    value,
    onChange,
    shown: true,
    placeholder,
  });
  return (
    <>
      {button}
      {menu}
    </>
  );
}

it("with no chosen option it shows the placeholder, marks no option, and focuses the first one when it opens", () => {
  render(<Picker placeholder="Rum" />);
  const button = screen.getByRole("button", { name: /Rum/ });
  expect(button).toHaveTextContent("Rum");
  expect(button).toHaveAttribute("aria-expanded", "false");
  fireEvent.click(button);
  expect(button).toHaveAttribute("aria-expanded", "true");
  const items = screen.getAllByRole("menuitemradio");
  expect(items.map((item) => item.textContent)).toEqual(["Arbete", "Dagbok"]);
  for (const item of items)
    expect(item).toHaveAttribute("aria-checked", "false");
  expect(items[0]).toHaveFocus();
});

it("with no chosen option and no placeholder it shows the first option's name, as before", () => {
  render(<Picker />);
  expect(screen.getByRole("button", { name: /Arbete/ })).toHaveTextContent(
    "Arbete",
  );
});

it("with a chosen option it shows that option, marks it, and focuses it when the menu opens", () => {
  render(<Picker value="dagbok" placeholder="Rum" />);
  const button = screen.getByRole("button", { name: /Dagbok/ });
  expect(button).toHaveTextContent("Dagbok");
  fireEvent.click(button);
  const items = screen.getAllByRole("menuitemradio");
  expect(items[0]).toHaveAttribute("aria-checked", "false");
  expect(items[1]).toHaveAttribute("aria-checked", "true");
  expect(items[1]).toHaveFocus();
});

it("a press on an option reports its value and closes the menu", () => {
  const onChange = vi.fn();
  render(<Picker placeholder="Rum" onChange={onChange} />);
  fireEvent.click(screen.getByRole("button", { name: /Rum/ }));
  fireEvent.click(screen.getByRole("menuitemradio", { name: "Dagbok" }));
  expect(onChange).toHaveBeenCalledWith("dagbok");
  expect(screen.queryByRole("menu")).toBeNull();
});

function Page() {
  return (
    <>
      <button type="button">Före</button>
      <Picker value="arbete" />
      <button type="button">Efter</button>
    </>
  );
}

it("arrow keys, Home and End move between the options and wrap", async () => {
  const user = userEvent.setup();
  render(<Picker value="arbete" />);
  await user.click(screen.getByRole("button", { name: /Arbete/ }));
  const [first, last] = screen.getAllByRole("menuitemradio");
  expect(first).toHaveFocus();
  await user.keyboard("{ArrowDown}");
  expect(last).toHaveFocus();
  await user.keyboard("{ArrowDown}");
  expect(first).toHaveFocus();
  await user.keyboard("{ArrowUp}");
  expect(last).toHaveFocus();
  await user.keyboard("{Home}");
  expect(first).toHaveFocus();
  await user.keyboard("{End}");
  expect(last).toHaveFocus();
});

it("Escape closes the menu and returns the focus to the button", async () => {
  const user = userEvent.setup();
  render(<Picker value="arbete" />);
  const button = screen.getByRole("button", { name: /Arbete/ });
  await user.click(button);
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("menu")).toBeNull();
  expect(button).toHaveFocus();
  expect(button).toHaveAttribute("aria-expanded", "false");
});

it("Tab closes the menu and moves the focus on to the next element, without trapping it", async () => {
  const user = userEvent.setup();
  render(<Page />);
  await user.click(screen.getByRole("button", { name: /Arbete/ }));
  expect(screen.getByRole("menu")).toBeInTheDocument();
  await user.tab();
  expect(screen.queryByRole("menu")).toBeNull();
  expect(screen.getByRole("button", { name: "Efter" })).toHaveFocus();
});

it("Shift+Tab closes the menu and moves the focus back to the button, one more goes on to the previous element", async () => {
  const user = userEvent.setup();
  render(<Page />);
  const button = screen.getByRole("button", { name: /Arbete/ });
  await user.click(button);
  await user.tab({ shift: true });
  expect(screen.queryByRole("menu")).toBeNull();
  expect(button).toHaveFocus();
  await user.tab({ shift: true });
  expect(screen.getByRole("button", { name: "Före" })).toHaveFocus();
});

it("Enter on a focused option chooses it and returns the focus to the button", async () => {
  const user = userEvent.setup();
  const onChange = vi.fn();
  render(<Picker value="arbete" onChange={onChange} />);
  const button = screen.getByRole("button", { name: /Arbete/ });
  await user.click(button);
  await user.keyboard("{ArrowDown}{Enter}");
  expect(onChange).toHaveBeenCalledWith("dagbok");
  expect(screen.queryByRole("menu")).toBeNull();
  expect(button).toHaveFocus();
});

import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  CreateField,
  type CreateFieldProps,
} from "@/features/mcp-apps/ui/create-field";

function renderField(props: Partial<CreateFieldProps> = {}) {
  const handlers = {
    onCreate: vi.fn(),
    onClose: vi.fn(),
  };
  render(
    <CreateField
      label="Ny uppgift"
      placeholder="Ny uppgift, t.ex. ring Anna"
      closeLabel="Stäng"
      addLabel="Lägg till"
      {...handlers}
      {...props}
    />,
  );
  return {
    ...handlers,
    input: screen.getByRole("textbox", { name: "Ny uppgift" }),
  };
}

describe("CreateField", () => {
  it("opens with focus in the field and shows × while the field is empty", () => {
    const { input } = renderField();

    expect(input).toHaveFocus();
    expect(input).toHaveAttribute("placeholder", "Ny uppgift, t.ex. ring Anna");
    expect(screen.getByRole("button", { name: "Stäng" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Lägg till" }),
    ).not.toBeInTheDocument();
  });

  it("shows + once the field has text, and + creates the trimmed text", async () => {
    const user = userEvent.setup();
    const { input, onCreate } = renderField();

    await user.type(input, "  Ring Anna  ");
    expect(
      screen.queryByRole("button", { name: "Stäng" }),
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Lägg till" }));

    expect(onCreate).toHaveBeenCalledTimes(1);
    expect(onCreate).toHaveBeenCalledWith("Ring Anna");
    expect(input).toHaveValue("");
  });

  it("creates on Enter, empties the field and keeps the focus in it", async () => {
    const user = userEvent.setup();
    const { input, onCreate, onClose } = renderField();

    await user.type(input, "Köp mjölk{Enter}");

    expect(onCreate).toHaveBeenCalledTimes(1);
    expect(onCreate).toHaveBeenCalledWith("Köp mjölk");
    expect(input).toHaveValue("");
    expect(input).toHaveFocus();
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Stäng" })).toBeInTheDocument();
  });

  it("does not create for Enter on an empty or blank field", async () => {
    const user = userEvent.setup();
    const { input, onCreate } = renderField();

    await user.type(input, "   {Enter}");
    await user.type(input, "{Enter}");

    expect(onCreate).not.toHaveBeenCalled();
  });

  it("closes on Esc", async () => {
    const user = userEvent.setup();
    const { input, onClose, onCreate } = renderField();

    await user.type(input, "Halvt påbörjad{Escape}");

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onCreate).not.toHaveBeenCalled();
  });

  it("closes when × is pressed on the empty field", async () => {
    const user = userEvent.setup();
    const { onClose } = renderField();

    await user.click(screen.getByRole("button", { name: "Stäng" }));

    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe("CreateField answers from onCreate", () => {
  const failedText = "Det gick inte att spara. Försök igen.";

  it("keeps the text and shows errorLabel when onCreate returns false", async () => {
    const user = userEvent.setup();
    const { input } = renderField({
      onCreate: vi.fn(() => false),
      errorLabel: failedText,
    });

    await user.type(input, "Köp mjölk{Enter}");

    expect(input).toHaveValue("Köp mjölk");
    expect(screen.getByRole("alert")).toHaveTextContent(failedText);
    expect(input).toHaveAttribute(
      "aria-describedby",
      screen.getByRole("alert").id,
    );
  });

  it("keeps the text without an error line when errorLabel is not given", async () => {
    const user = userEvent.setup();
    const { input } = renderField({ onCreate: vi.fn(() => false) });

    await user.type(input, "Köp mjölk{Enter}");

    expect(input).toHaveValue("Köp mjölk");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("empties the field only after a pending promise resolves to true", async () => {
    const user = userEvent.setup();
    let answer!: (value: boolean) => void;
    const onCreate = vi.fn(
      () =>
        new Promise<boolean>((resolve) => {
          answer = resolve;
        }),
    );
    const { input } = renderField({ onCreate });

    await user.type(input, "Ring Anna{Enter}");
    expect(onCreate).toHaveBeenCalledWith("Ring Anna");
    expect(input).toHaveValue("Ring Anna");

    act(() => answer(true));
    await waitFor(() => expect(input).toHaveValue(""));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("keeps text typed on while the write was pending", async () => {
    const user = userEvent.setup();
    let answer!: (value: boolean) => void;
    const onCreate = vi.fn(
      () =>
        new Promise<boolean>((resolve) => {
          answer = resolve;
        }),
    );
    const { input } = renderField({ onCreate });

    await user.type(input, "Ring Anna{Enter}");
    await user.type(input, " Nästa");
    act(() => answer(true));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());

    expect(input).toHaveValue("Ring Anna Nästa");
  });

  it("keeps the text and shows errorLabel when the promise rejects", async () => {
    const user = userEvent.setup();
    const { input } = renderField({
      onCreate: vi.fn(() => Promise.reject(new Error("network"))),
      errorLabel: failedText,
    });

    await user.type(input, "Köp mjölk{Enter}");
    await act(async () => {});

    expect(input).toHaveValue("Köp mjölk");
    expect(screen.getByRole("alert")).toHaveTextContent(failedText);
  });

  it("does not create again while an earlier answer is pending", async () => {
    const user = userEvent.setup();
    const onCreate = vi.fn(() => new Promise<boolean>(() => {}));
    const { input } = renderField({ onCreate });

    await user.type(input, "Ring Anna{Enter}{Enter}");

    expect(onCreate).toHaveBeenCalledTimes(1);
  });
});

describe("CreateField note", () => {
  it("shows note under the field and reads it out politely", () => {
    const { input } = renderField({ note: "Tillagd: Ring Anna · Idag" });

    const note = screen.getByText("Tillagd: Ring Anna · Idag");
    expect(note.tagName).toBe("P");
    expect(note).toHaveAttribute("aria-live", "polite");
    expect(input.closest(".sk-createfield")?.nextElementSibling).toBe(note);
  });

  it("draws nothing for an empty note", () => {
    renderField({ note: "" });

    expect(document.querySelector(".sk-createfield__note")).toBeNull();
  });
});

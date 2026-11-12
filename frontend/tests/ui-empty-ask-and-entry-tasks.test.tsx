// The family's empty state with its chat example, and a journal entry's Tasks by name.
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { EmptyState, emptyAskLabelsFor } from "@/features/mcp-apps/ui/states";
import { EntryTasks } from "@/features/journal-app/entry-tasks";
import { journalEn, journalSv } from "@/features/journal-app/labels";

describe("EmptyState with a chat example", () => {
  it("says what to tell Claude and sends the example as it reads", async () => {
    const onSend = vi.fn();
    render(
      <EmptyState
        title="Inga listor ännu."
        ask={{ locale: "sv-SE", example: "Lägg till mjölk", onSend }}
      >
        <button type="button">Skriv själv</button>
      </EmptyState>,
    );
    expect(screen.getByText("Säg till Claude:")).toBeInTheDocument();
    const example = screen.getByRole("button", {
      name: "Skicka till Claude: Lägg till mjölk",
    });
    expect(example).toHaveTextContent("”Lägg till mjölk”");
    await userEvent.setup().click(example);
    expect(onSend).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Skriv själv" })).toBeVisible();
  });

  it("shows the example as text without a message function, in English quotes in English", () => {
    render(
      <EmptyState
        title="No lists yet."
        ask={{ locale: "en-GB", example: "Add milk" }}
      />,
    );
    expect(screen.getByText("“Add milk”")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
    expect(emptyAskLabelsFor("en").lead).toBe("Tell Claude:");
  });
});

describe("EntryTasks", () => {
  it("shows the count until the titles are read, then one chip per Task that opens it", async () => {
    const onOpenTask = vi.fn();
    const getTaskTitle = vi.fn((id: string) =>
      id === "a"
        ? Promise.resolve("Ring Anna om offerten")
        : Promise.reject(new Error("gone")),
    );
    render(
      <EntryTasks
        taskIds={["a", "b"]}
        labels={journalSv}
        getTaskTitle={getTaskTitle}
        onOpenTask={onOpenTask}
      />,
    );
    expect(screen.getByText(`${journalSv.tasks}: 2`)).toBeInTheDocument();
    const chip = await screen.findByRole("button", {
      name: journalSv.openTaskNamed("Ring Anna om offerten"),
    });
    // A Task whose title could not be read keeps a neutral name and still opens.
    expect(
      screen.getByRole("button", {
        name: journalSv.openTaskNamed(journalSv.taskChipFallback),
      }),
    ).toBeInTheDocument();
    await userEvent.setup().click(chip);
    expect(onOpenTask).toHaveBeenCalledWith("a");
  });

  it("keeps the count on a host that cannot read Tasks", () => {
    render(<EntryTasks taskIds={["a"]} labels={journalEn} />);
    expect(screen.getByText(`${journalEn.tasks}: 1`)).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });
});

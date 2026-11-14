import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { journalEn, journalSv } from "@/features/journal-app/labels";
import {
  clickSave,
  draftId,
  OFFERTEN,
  renderDraft,
  transportMock,
} from "@tests/helpers/journal-app-fixtures";
import { listTagsMock } from "@tests/helpers/journal-tag-fixtures";

async function addTag(
  user: ReturnType<typeof userEvent.setup>,
  text: string,
  input = "New tag",
) {
  await user.type(screen.getByLabelText(input), `${text}{Enter}`);
}

describe("tags on a draft being saved", () => {
  it("lets the owner set tags before saving and sends them with the finalize", async () => {
    const user = userEvent.setup();
    const transport = transportMock({ listTags: listTagsMock() });
    renderDraft(transport);
    await screen.findByRole("heading", { level: 2, name: OFFERTEN });
    expect(
      screen.getByRole("heading", { name: journalEn.draftTags }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Add tag" }));
    await addTag(user, "Viktig");
    await user.click(screen.getByRole("button", { name: "Add tag Familj" }));
    await user.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.getByText("Tags: Viktig and Familj")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save as entry" }));
    await clickSave(user);

    await waitFor(() =>
      expect(transport.finalizeDraft).toHaveBeenCalledTimes(1),
    );
    const finalized = transport.finalizeDraft.mock.calls[0];
    expect(finalized?.[0]).toBe(draftId);
    expect(finalized?.[2]).toMatchObject({ tags: ["viktig", "familj"] });
  });

  it("sends no tags when none were set", async () => {
    const user = userEvent.setup();
    const transport = transportMock({ listTags: listTagsMock() });
    renderDraft(transport);
    await screen.findByRole("heading", { level: 2, name: OFFERTEN });

    await user.click(screen.getByRole("button", { name: "Save as entry" }));
    await clickSave(user);

    await waitFor(() =>
      expect(transport.finalizeDraft).toHaveBeenCalledTimes(1),
    );
    expect(transport.finalizeDraft.mock.calls[0]?.[2]).not.toHaveProperty(
      "tags",
    );
  });

  it("removes a tag again before saving", async () => {
    const user = userEvent.setup();
    const transport = transportMock({ listTags: listTagsMock() });
    renderDraft(transport);
    await screen.findByRole("heading", { level: 2, name: OFFERTEN });

    await user.click(screen.getByRole("button", { name: "Add tag" }));
    await addTag(user, "viktig");
    await user.click(screen.getByRole("button", { name: "Remove tag Viktig" }));
    await user.click(screen.getByRole("button", { name: "Done" }));
    await user.click(screen.getByRole("button", { name: "Save as entry" }));
    await clickSave(user);

    await waitFor(() =>
      expect(transport.finalizeDraft).toHaveBeenCalledTimes(1),
    );
    expect(transport.finalizeDraft.mock.calls[0]?.[2]).not.toHaveProperty(
      "tags",
    );
  });

  it("offers typing without suggestions where the host has no vocabulary", async () => {
    const user = userEvent.setup();
    const transport = transportMock();
    renderDraft(transport);
    await screen.findByRole("heading", { level: 2, name: OFFERTEN });

    await user.click(screen.getByRole("button", { name: "Add tag" }));
    await addTag(user, "Egen");
    expect(screen.queryByText("Your tags")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Done" }));
    await user.click(screen.getByRole("button", { name: "Save as entry" }));
    await clickSave(user);

    await waitFor(() =>
      expect(transport.finalizeDraft).toHaveBeenCalledTimes(1),
    );
    expect(transport.finalizeDraft.mock.calls[0]?.[2]).toMatchObject({
      tags: ["egen"],
    });
  });

  it("stands under the summary, before the key points, and stays while the draft is edited", async () => {
    const user = userEvent.setup();
    renderDraft(transportMock({ listTags: listTagsMock() }));
    await screen.findByRole("heading", { level: 2, name: OFFERTEN });
    const summary = screen.getByText("Kunden vill ha offerten före fredag.");
    const opener = screen.getByRole("button", { name: "Add tag" });
    const keyPoints = screen.getByRole("heading", {
      name: journalEn.keyPoints,
    });
    // Inline the field shares the row under the summary with "Read more" (journal.css): the card gets no row for it.
    expect(opener.closest(".journal-summary-row")).not.toBeNull();
    expect(
      summary.compareDocumentPosition(opener) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      opener.compareDocumentPosition(keyPoints) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    await user.click(opener);
    await addTag(user, "Viktig");
    await user.click(screen.getByRole("button", { name: "Done" }));
    await user.click(screen.getByRole("button", { name: journalEn.edit }));
    expect(screen.getByText("Tags: Viktig")).toBeInTheDocument();
  });

  it("speaks Swedish, with the same parts", async () => {
    const user = userEvent.setup();
    renderDraft(transportMock({ listTags: listTagsMock() }), journalSv);
    await screen.findByRole("heading", { level: 2, name: OFFERTEN });

    expect(
      screen.getByRole("heading", { name: journalSv.draftTags }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Lägg till tagg" }));
    await addTag(user, "Viktig", "Ny tagg");
    await user.click(screen.getByRole("button", { name: "Klar" }));
    expect(screen.getByText("Taggar: Viktig")).toBeInTheDocument();
  });
});

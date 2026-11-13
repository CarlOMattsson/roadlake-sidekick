import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { HostToolError } from "@/features/mcp-apps/bridge";
import { journalEn, journalSv } from "@/features/journal-app/labels";
import type {
  JournalEntry,
  JournalKeyPoint,
  JournalTaskProposal,
} from "@/features/journal-app/transport";
import {
  savedEntryId,
  clickSave,
  entry,
  source,
  draftId,
  createProposal,
  updateProposal,
  draftFixture,
  transportMock,
  decisionButton,
  renderDraft,
  OFFERTEN,
} from "./helpers/journal-app-fixtures";
import { deferred } from "./helpers/deferred";

describe("journal draft review", () => {
  it("turns a conflict on a draft that was handled elsewhere into the handled state after reload", async () => {
    const user = userEvent.setup();
    const getDraft = vi
      .fn()
      .mockResolvedValueOnce({ draft: draftFixture(), source })
      .mockResolvedValueOnce({
        draft: draftFixture({ state: "rejected", version: 2 }),
        source,
      });
    const finalizeDraft = vi
      .fn()
      .mockRejectedValue(new HostToolError("conflict"));
    const transport = transportMock({ getDraft, finalizeDraft });
    renderDraft(transport);
    await screen.findByRole("heading", { level: 2, name: OFFERTEN });
    await user.click(screen.getByRole("button", { name: "Save as entry" }));
    await clickSave(user);
    await screen.findByText(journalEn.conflict);
    await user.click(screen.getByRole("button", { name: "Refresh" }));
    expect(
      await screen.findByText("This draft has already been handled."),
    ).toBeInTheDocument();
    expect(finalizeDraft).toHaveBeenCalledTimes(1);
  });

  it("makes one call for a double click on the confirming button", async () => {
    const user = userEvent.setup();
    const pending = deferred<{
      entry: JournalEntry;
      created_task_ids: string[];
      updated_task_ids: string[];
    }>();
    const finalizeDraft = vi.fn(() => pending.promise);
    const transport = transportMock({ finalizeDraft });
    renderDraft(transport);
    await screen.findByRole("heading", { level: 2, name: OFFERTEN });
    await user.click(screen.getByRole("button", { name: "Save as entry" }));
    await user.dblClick(
      screen.getByRole("button", { name: journalEn.saveWithoutThem }),
    );
    expect(finalizeDraft).toHaveBeenCalledTimes(1);
    pending.resolve({
      entry: { ...entry, id: savedEntryId, title: "Sparad post" },
      created_task_ids: [],
      updated_task_ids: [],
    });
    await waitFor(() => expect(transport.getEntry).toHaveBeenCalled());
    expect(finalizeDraft).toHaveBeenCalledTimes(1);
  });

  it("offers a retry when the draft cannot be read and calm text when it is forbidden", async () => {
    const user = userEvent.setup();
    const getDraft = vi
      .fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockRejectedValueOnce(new HostToolError("forbidden"));
    renderDraft(transportMock({ getDraft }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn’t load this right now",
    );
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText(journalEn.forbidden)).toBeInTheDocument();
  });

  it("shows the draft in Swedish with the required wording", async () => {
    const user = userEvent.setup();
    renderDraft(transportMock(), journalSv);
    await screen.findByRole("heading", { level: 2, name: OFFERTEN });
    expect(
      screen.getByRole("heading", { name: "Original, oförändrat" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("group", { name: "Beslut för Projekt Offert" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Avvisa utkast" }));
    expect(
      screen.getByRole("button", { name: "Ja, avvisa utkastet" }),
    ).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "Behåll utkastet" }));
    await user.click(
      screen.getByRole("button", { name: "Spara som anteckning" }),
    );
    expect(
      screen.getByText("Det här skapar en anteckning."),
    ).toBeInTheDocument();
  });

  it("leaves a part of the confirmation out when its count is zero, in English", async () => {
    const user = userEvent.setup();
    renderDraft(transportMock(), journalEn);
    await screen.findByRole("heading", { level: 2, name: OFFERTEN });
    await user.click(screen.getByRole("button", { name: "Save as entry" }));

    expect(screen.getByText("This saves an entry.")).toBeInTheDocument();
    expect(screen.queryByText(/0 tasks|journal entry/i)).toBeNull();
  });

  it("words the confirmation and the saved note from the nonzero counts only, in both languages", () => {
    expect(journalEn.finalizeConfirm(2, 1, 0)).toBe(
      "This saves an entry with 2 links. It creates 1 task.",
    );
    expect(journalEn.finalizeConfirm(1, 0, 2)).toBe(
      "This saves an entry with 1 link. It updates 2 tasks.",
    );
    expect(journalEn.finalizeConfirm(0, 0, 2)).toBe(
      "This saves an entry. It updates 2 tasks.",
    );
    expect(journalEn.finalizeConfirm(0, 0, 0)).toBe("This saves an entry.");
    expect(journalEn.entrySaved(1, 0)).toBe("Entry saved. 1 task created.");
    expect(journalEn.entrySaved(0, 3)).toBe("Entry saved. 3 tasks updated.");
    expect(journalEn.entrySaved(2, 1)).toBe(
      "Entry saved. 2 tasks created. 1 task updated.",
    );
    expect(journalEn.entrySaved(0, 0)).toBe("Entry saved.");

    expect(journalSv.finalizeConfirm(2, 1, 0)).toBe(
      "Det här skapar en anteckning med 2 kopplingar. 1 uppgift skapas.",
    );
    expect(journalSv.finalizeConfirm(1, 0, 2)).toBe(
      "Det här skapar en anteckning med 1 koppling. 2 uppgifter uppdateras.",
    );
    expect(journalSv.finalizeConfirm(0, 0, 0)).toBe(
      "Det här skapar en anteckning.",
    );
    expect(journalSv.entrySaved(1, 0)).toBe(
      "Anteckningen sparades. 1 uppgift skapades.",
    );
    expect(journalSv.entrySaved(0, 2)).toBe(
      "Anteckningen sparades. 2 uppgifter uppdaterades.",
    );
    expect(journalSv.entrySaved(2, 1)).toBe(
      "Anteckningen sparades. 2 uppgifter skapades. 1 uppgift uppdaterades.",
    );
    expect(journalSv.entrySaved(0, 0)).toBe("Anteckningen sparades.");
  });

  it("unticks a proposal that changed during a reload and says so", async () => {
    const user = userEvent.setup();
    const changed: JournalTaskProposal = {
      ...createProposal,
      priority: "low",
    } as JournalTaskProposal;
    const getDraft = vi
      .fn()
      .mockResolvedValueOnce({ draft: draftFixture(), source })
      .mockResolvedValueOnce({
        draft: draftFixture({
          version: 2,
          task_proposals: [changed, updateProposal],
        }),
        source,
      });
    const rejectDraft = vi
      .fn()
      .mockRejectedValue(new HostToolError("conflict"));
    renderDraft(transportMock({ getDraft, rejectDraft }));
    await screen.findByRole("heading", { level: 2, name: OFFERTEN });
    await user.click(decisionButton("Create task: Ring kunden"));
    await user.click(decisionButton("Update task: Skicka offert"));
    await user.click(screen.getByRole("button", { name: "Reject draft" }));
    await user.click(screen.getByRole("button", { name: "Yes, reject draft" }));
    await screen.findByText(journalEn.conflict);
    await user.click(screen.getByRole("button", { name: "Refresh" }));
    expect(
      await screen.findByText("A suggestion changed and was deselected."),
    ).toBeInTheDocument();
    expect(decisionButton("Create task: Ring kunden")).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    // The unchanged proposal keeps its approval.
    expect(decisionButton("Update task: Skicka offert")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("shows items missing from the catalogue but never lets them be chosen", async () => {
    const user = userEvent.setup();
    const strangerContact = "019f0000-0000-7000-8000-0000000000c9";
    const strangerUpdate: JournalTaskProposal = {
      proposal_id: "019f0000-0000-7000-8000-0000000000a3",
      type: "update_task",
      task_id: "019f0000-0000-7000-8000-0000000000t9",
      expected_task_version: 1,
      status: "blocked",
    };
    const transport = transportMock({
      getDraft: vi.fn(() =>
        Promise.resolve({
          draft: draftFixture({
            suggestions: {
              projects: [],
              tasks: [],
              contacts: [{ id: strangerContact, rationale: null }],
            },
            task_proposals: [strangerUpdate],
            task_proposal_count: 1,
          }),
          source,
        }),
      ),
    });
    renderDraft(transport);
    await screen.findByRole("heading", { level: 2, name: OFFERTEN });
    const unknown = screen.getAllByText("Unknown item, can’t be selected");
    expect(unknown).toHaveLength(2);
    expect(decisionButton("Unknown item")).toBeDisabled();
    expect(decisionButton("Update task: an existing task")).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Save as entry" }));
    await clickSave(user);
    await waitFor(() => expect(transport.finalizeDraft).toHaveBeenCalled());
    expect(transport.finalizeDraft.mock.calls[0]![2]).toMatchObject({
      relation_selection: { contact_ids: [] },
      task_proposals: [],
    });
  });

  it("closes the editor and never writes when proposals become hidden after a reload", async () => {
    const user = userEvent.setup();
    const getDraft = vi
      .fn()
      .mockResolvedValueOnce({ draft: draftFixture(), source })
      .mockResolvedValueOnce({
        draft: draftFixture({
          version: 2,
          task_proposals: [createProposal],
          task_proposal_count: 2,
        }),
        source,
      });
    const updateDraft = vi
      .fn()
      .mockRejectedValue(new HostToolError("conflict"));
    renderDraft(transportMock({ getDraft, updateDraft }));
    await screen.findByRole("heading", { level: 2, name: OFFERTEN });
    await user.click(screen.getByRole("button", { name: "Edit" }));
    await user.type(screen.getByLabelText("Title"), "!");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByText(journalEn.conflict);
    await user.click(screen.getByRole("button", { name: "Refresh" }));
    expect(
      await screen.findByText(
        "Editing was closed because some suggestions are now hidden.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Title")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit" })).toBeDisabled();
    expect(updateDraft).toHaveBeenCalledTimes(1);
  });

  it("keeps links and proposals ticked after a conflict on finalize and on reject", async () => {
    const user = userEvent.setup();
    const getDraft = vi.fn(() =>
      Promise.resolve({ draft: draftFixture({ version: 2 }), source }),
    );
    const finalizeDraft = vi
      .fn()
      .mockRejectedValue(new HostToolError("conflict"));
    const rejectDraft = vi
      .fn()
      .mockRejectedValue(new HostToolError("conflict"));
    renderDraft(transportMock({ getDraft, finalizeDraft, rejectDraft }));
    await screen.findByRole("heading", { level: 2, name: OFFERTEN });
    const project = decisionButton("Projekt Offert");
    await user.click(project);
    await user.click(decisionButton("Create task: Ring kunden"));

    await user.click(screen.getByRole("button", { name: "Save as entry" }));
    await clickSave(user);
    await screen.findByText(journalEn.conflict);
    await user.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(getDraft).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(screen.queryByText(journalEn.conflict)).not.toBeInTheDocument(),
    );
    expect(project).toHaveAttribute("aria-pressed", "true");
    expect(decisionButton("Create task: Ring kunden")).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    await user.click(screen.getByRole("button", { name: "Reject draft" }));
    await user.click(screen.getByRole("button", { name: "Yes, reject draft" }));
    await screen.findByText(journalEn.conflict);
    await user.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(getDraft).toHaveBeenCalledTimes(3));
    await waitFor(() =>
      expect(screen.queryByText(journalEn.conflict)).not.toBeInTheDocument(),
    );
    expect(project).toHaveAttribute("aria-pressed", "true");
    expect(finalizeDraft.mock.calls[0]![1]).toBe(2);
    expect(rejectDraft.mock.calls[0]![1]).toBe(2);
  });

  it("stops at 25 links of a kind and lists at most ten names in the confirmation", async () => {
    const user = userEvent.setup();
    const contacts = Array.from({ length: 26 }, (_, i) => ({
      id: `019f0000-0000-7000-8000-00000000${String(i).padStart(4, "0")}`,
      label: `Kontakt ${i + 1}`,
    }));
    const transport = transportMock({
      getDraft: vi.fn(() =>
        Promise.resolve({
          draft: draftFixture({
            suggestions: { projects: [], tasks: [], contacts: [] },
            task_proposals: [],
            task_proposal_count: 0,
            catalog: { projects: [], tasks: [], contacts },
          }),
          source,
        }),
      ),
    });
    renderDraft(transport);
    await screen.findByRole("heading", { level: 2, name: OFFERTEN });
    for (const contact of contacts.slice(0, 25))
      await user.click(screen.getByRole("checkbox", { name: contact.label }));
    expect(screen.getByRole("checkbox", { name: "Kontakt 26" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Save as entry" }));
    const group = screen.getByRole("group", { name: "Save as entry" });
    expect(within(group).getByText("Kontakt 10")).toBeInTheDocument();
    expect(within(group).queryByText("Kontakt 11")).not.toBeInTheDocument();
    expect(within(group).getByText("+15 more")).toBeInTheDocument();
    await clickSave(user);
    await waitFor(() => expect(transport.finalizeDraft).toHaveBeenCalled());
    const input = transport.finalizeDraft.mock.calls[0]![2] as {
      relation_selection: { contact_ids: unknown[] };
    };
    expect(input.relation_selection.contact_ids).toHaveLength(25);
    // 25 clicks, each re-rendering a 26-row list: about 5 s idle, so it needs headroom under load.
  }, 60_000);

  it("sends user_selected for a project and a task the AI did not suggest", async () => {
    const user = userEvent.setup();
    const ownProject = "019f0000-0000-7000-8000-0000000000p2";
    const ownTask = "019f0000-0000-7000-8000-0000000000t2";
    const transport = transportMock({
      getDraft: vi.fn(() =>
        Promise.resolve({
          draft: draftFixture({
            suggestions: { projects: [], tasks: [], contacts: [] },
            task_proposals: [],
            task_proposal_count: 0,
            catalog: {
              projects: [{ id: ownProject, label: "Eget projekt" }],
              tasks: [{ id: ownTask, label: "Egen uppgift", status: "todo" }],
              contacts: [],
            },
          }),
          source,
        }),
      ),
    });
    renderDraft(transport);
    await screen.findByRole("heading", { level: 2, name: OFFERTEN });
    await user.click(screen.getByRole("checkbox", { name: "Eget projekt" }));
    await user.click(screen.getByRole("checkbox", { name: "Egen uppgift" }));
    await user.click(screen.getByRole("button", { name: "Save as entry" }));
    await clickSave(user);
    await waitFor(() => expect(transport.finalizeDraft).toHaveBeenCalled());
    expect(
      (
        transport.finalizeDraft.mock.calls[0]![2] as {
          relation_selection: unknown;
        }
      ).relation_selection,
    ).toEqual({
      project_ids: [{ id: ownProject, origin: "user_selected" }],
      task_ids: [{ id: ownTask, origin: "user_selected" }],
      contact_ids: [],
    });
  });

  it("retries a failed reject with the same idempotency key", async () => {
    const user = userEvent.setup();
    const rejectDraft = vi
      .fn()
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValueOnce({
        draft: { id: draftId, state: "rejected", version: 2 },
      });
    renderDraft(transportMock({ rejectDraft }));
    await screen.findByRole("heading", { level: 2, name: OFFERTEN });
    await user.click(screen.getByRole("button", { name: "Reject draft" }));
    await user.click(screen.getByRole("button", { name: "Yes, reject draft" }));
    await screen.findByText(journalEn.saveFailed);
    await user.click(screen.getByRole("button", { name: "Yes, reject draft" }));
    await screen.findByText("Draft rejected.");
    expect(rejectDraft).toHaveBeenCalledTimes(2);
    expect(rejectDraft.mock.calls[1]![2]).toBe(rejectDraft.mock.calls[0]![2]);
  });

  it("shows an unsupported key point type as a fact, says so, and sends the fact", async () => {
    const user = userEvent.setup();
    const transport = transportMock({
      getDraft: vi.fn(() =>
        Promise.resolve({
          draft: draftFixture({
            // A kind the schema does not list, as a newer server might send it.
            key_points: [
              {
                kind: "insight" as JournalKeyPoint["kind"],
                text: "Något nytt.",
              },
            ],
          }),
          source,
        }),
      ),
    });
    renderDraft(transport);
    await screen.findByRole("heading", { level: 2, name: OFFERTEN });
    expect(
      screen.getByText(
        "A key point had an unsupported type and is shown as a fact.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Fact: Något nytt.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save as entry" }));
    await clickSave(user);
    await waitFor(() => expect(transport.finalizeDraft).toHaveBeenCalled());
    expect(transport.finalizeDraft.mock.calls[0]![2]).toMatchObject({
      key_points: [{ kind: "fact", text: "Något nytt." }],
    });
  });
});

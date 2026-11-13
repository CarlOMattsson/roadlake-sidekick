import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { HostToolError } from "@/features/mcp-apps/bridge";
import { journalEn } from "@/features/journal-app/labels";
import { ownerToday } from "@/features/mcp-apps/app-timezone";
import {
  savedEntryId,
  sourceId,
  clickSave,
  source,
  draftId,
  projectId,
  contactBo,
  createProposal,
  updateProposal,
  draftFixture,
  transportMock,
  decisionButton,
  renderDraft,
  OFFERTEN,
} from "./helpers/journal-app-fixtures";

describe("journal draft review", () => {
  it("opens a draft from the pending list with nothing chosen by default", async () => {
    const user = userEvent.setup();
    const transport = transportMock();
    renderDraft(transport, journalEn, {
      kind: "pending",
      page: {
        items: [
          {
            source_id: sourceId,
            journal_date: "2026-10-24",
            source_type: "manual_text",
            source_created_at: "2026-10-24T09:31:00Z",
            character_count: 42,
            state: "draft_pending_review",
            draft_id: draftId,
            draft_title: OFFERTEN,
          },
        ],
      },
    });

    await user.click(
      screen.getByRole("button", { name: new RegExp(`^${OFFERTEN}`) }),
    );
    expect(transport.getDraft).toHaveBeenCalledWith(draftId);
    expect(
      await screen.findByRole("heading", { level: 2, name: OFFERTEN }),
    ).toHaveFocus();
    expect(
      screen.getByText("Kunden vill ha offerten före fredag."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Commitment: Skicka offerten på torsdag."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Original, unchanged" }),
    ).toBeInTheDocument();
    // The original stays folded away until the owner asks for it.
    expect(screen.queryByText(/^Råtext:/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show original" }));
    expect(
      screen.getByText("Råtext: Anna vill ha offerten före fredag."),
    ).toBeInTheDocument();
    // Only the candidate the AI did not suggest has a checkbox.
    const boxes = screen.getAllByRole("checkbox");
    expect(boxes).toHaveLength(1);
    expect(boxes[0]).not.toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: "Bo Berg" }),
    ).toBeInTheDocument();
    // Three suggested links and two task proposals each have a Godkänn/Avslå pair, nothing chosen,
    // so no option is pressed.
    const decisions = screen.getAllByRole("group", { name: /^Decision for / });
    expect(decisions).toHaveLength(5);
    for (const decision of decisions)
      expect(
        within(decision).getByRole("button", { name: "Decline" }),
      ).toHaveAttribute("aria-pressed", "false");
    expect(
      screen.getByRole("group", { name: "Decision for Projekt Offert" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Offerten hör till projektet.")).toBeVisible();
    expect(
      screen.queryByText(journalEn.hiddenProposals),
    ).not.toBeInTheDocument();
    expect(transport.finalizeDraft).not.toHaveBeenCalled();
  });

  it("names the day the draft is saved on, with the year when it is not this year", async () => {
    const thisYear = ownerToday().slice(0, 4);
    const lastYear = String(Number(thisYear) - 1);
    const sameYear = transportMock({
      getDraft: vi.fn(() =>
        Promise.resolve({
          draft: draftFixture({ journal_date: `${thisYear}-01-02` }),
          source,
        }),
      ),
    });
    const { unmount } = renderDraft(sameYear);
    expect(
      await screen.findByText(/^Day: 2 Jan\. Not saved yet/),
    ).toBeVisible();
    unmount();
    renderDraft(
      transportMock({
        getDraft: vi.fn(() =>
          Promise.resolve({
            draft: draftFixture({ journal_date: `${lastYear}-12-28` }),
            source,
          }),
        ),
      }),
    );
    expect(
      await screen.findByText(
        `Day: 28 Dec ${lastYear}. Not saved yet. Save it as an entry to keep it.`,
      ),
    ).toBeVisible();
  });

  it("edits only through update with the changed field and the held version", async () => {
    const user = userEvent.setup();
    const transport = transportMock();
    renderDraft(transport);
    await screen.findByRole("heading", { level: 2, name: OFFERTEN });

    await user.click(screen.getByRole("button", { name: "Edit" }));
    const title = screen.getByLabelText("Title");
    expect(title).toHaveFocus();
    // Saving without a change is not a write.
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(transport.updateDraft).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Edit" }));
    await user.clear(screen.getByLabelText("Title"));
    await user.type(screen.getByLabelText("Title"), "Offerten klar");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(transport.updateDraft).toHaveBeenCalledTimes(1));
    const [id, version, fields, key] = transport.updateDraft.mock.calls[0]! as [
      string,
      number,
      unknown,
      unknown,
    ];
    expect(id).toBe(draftId);
    expect(version).toBe(1);
    expect(fields).toEqual({
      title: "Offerten klar",
      summary: "Kunden vill ha offerten före fredag.",
      key_points: [{ kind: "commitment", text: "Skicka offerten på torsdag." }],
      task_proposals: [createProposal, updateProposal],
    });
    expect(typeof key).toBe("string");
    expect(
      await screen.findByRole("heading", { level: 2, name: "Offerten klar" }),
    ).toHaveFocus();
    expect(screen.getByRole("status")).toHaveTextContent("Saved");

    // The next write uses the version the update returned.
    await user.click(screen.getByRole("button", { name: "Reject draft" }));
    await user.click(screen.getByRole("button", { name: "Yes, reject draft" }));
    await waitFor(() => expect(transport.rejectDraft).toHaveBeenCalled());
    expect(transport.rejectDraft.mock.calls[0]![1]).toBe(2);
  });

  it("edits key points and blocks an empty one", async () => {
    const user = userEvent.setup();
    const transport = transportMock();
    renderDraft(transport);
    await screen.findByRole("heading", { level: 2, name: OFFERTEN });

    await user.click(screen.getByRole("button", { name: "Edit" }));
    await user.click(screen.getByRole("button", { name: "Add key point" }));
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByText(journalEn.keyPointRequired)).toBeInTheDocument();
    expect(transport.updateDraft).not.toHaveBeenCalled();
    await user.selectOptions(
      screen.getByLabelText("Type of key point 2"),
      "decision",
    );
    await user.type(screen.getByLabelText("Key point 2"), "Vi tar offerten.");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(transport.updateDraft).toHaveBeenCalledTimes(1));
    expect(transport.updateDraft.mock.calls[0]![2]).toMatchObject({
      title: OFFERTEN,
      key_points: [
        { kind: "commitment", text: "Skicka offerten på torsdag." },
        { kind: "decision", text: "Vi tar offerten." },
      ],
    });
  });

  it("rejects only after a second confirming step, then drops the draft from the list", async () => {
    const user = userEvent.setup();
    const transport = transportMock();
    renderDraft(transport, journalEn, {
      kind: "pending",
      page: {
        items: [
          {
            source_id: sourceId,
            journal_date: "2026-10-24",
            source_type: "manual_text",
            source_created_at: "2026-10-24T09:31:00Z",
            character_count: 42,
            state: "draft_pending_review",
            draft_id: draftId,
            draft_title: OFFERTEN,
          },
        ],
      },
    });
    await user.click(
      screen.getByRole("button", { name: new RegExp(`^${OFFERTEN}`) }),
    );
    await screen.findByRole("heading", { level: 2, name: OFFERTEN });

    await user.click(screen.getByRole("button", { name: "Reject draft" }));
    expect(transport.rejectDraft).not.toHaveBeenCalled();
    expect(
      screen.getByRole("button", { name: "Yes, reject draft" }),
    ).toHaveFocus();
    // Cancelling returns focus to the trigger.
    await user.click(screen.getByRole("button", { name: "Keep draft" }));
    expect(screen.getByRole("button", { name: "Reject draft" })).toHaveFocus();
    expect(transport.rejectDraft).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Reject draft" }));
    await user.click(screen.getByRole("button", { name: "Yes, reject draft" }));
    await waitFor(() => expect(transport.rejectDraft).toHaveBeenCalledTimes(1));
    expect(transport.rejectDraft.mock.calls[0]!.slice(0, 2)).toEqual([
      draftId,
      1,
    ]);
    expect(await screen.findByText("Draft rejected.")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Save as entry" }),
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Back" }));
    expect(
      screen.queryByRole("button", { name: new RegExp(`^${OFFERTEN}`) }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(journalEn.pendingEmpty)).toBeInTheDocument();
  });

  it("finalizes with only the chosen links and proposals and then shows the entry", async () => {
    const user = userEvent.setup();
    const transport = transportMock();
    renderDraft(transport);
    await screen.findByRole("heading", { level: 2, name: OFFERTEN });

    await user.click(decisionButton("Projekt Offert"));
    await user.click(screen.getByRole("checkbox", { name: "Bo Berg" }));
    await user.click(decisionButton("Create task: Ring kunden"));
    await user.click(screen.getByRole("button", { name: "Save as entry" }));
    expect(transport.finalizeDraft).not.toHaveBeenCalled();
    expect(
      screen.getByText("This saves an entry with 2 links. It creates 1 task."),
    ).toBeInTheDocument();
    // Suggestions are still undecided, so the confirmation offers the three choices, not a plain Yes.
    expect(
      screen.getByRole("button", { name: journalEn.reviewThem }),
    ).toHaveFocus();
    expect(
      screen.getByRole("button", { name: journalEn.approveAllAndSave }),
    ).toBeInTheDocument();
    await clickSave(user);

    await waitFor(() =>
      expect(transport.finalizeDraft).toHaveBeenCalledTimes(1),
    );
    const [id, version, input, key] = transport.finalizeDraft.mock
      .calls[0]! as [string, number, unknown, unknown];
    expect([id, version]).toEqual([draftId, 1]);
    expect(typeof key).toBe("string");
    expect(input).toEqual({
      title: OFFERTEN,
      summary: "Kunden vill ha offerten före fredag.",
      key_points: [{ kind: "commitment", text: "Skicka offerten på torsdag." }],
      relation_selection: {
        project_ids: [{ id: projectId, origin: "model_suggested" }],
        task_ids: [],
        contact_ids: [{ id: contactBo, origin: "user_selected" }],
      },
      task_proposals: [createProposal],
    });
    expect(
      await screen.findByRole("heading", { level: 2, name: "Sparad post" }),
    ).toHaveFocus();
    expect(transport.getEntry).toHaveBeenCalledWith(savedEntryId);
    expect(
      screen.getByText("Entry saved. 1 task created."),
    ).toBeInTheDocument();
    // The saved entry replaced the draft: Back has nothing handled to return to.
    expect(
      screen.queryByRole("button", { name: "Back" }),
    ).not.toBeInTheDocument();
  });

  it("finalizes with no links or proposals when nothing was chosen", async () => {
    const user = userEvent.setup();
    const transport = transportMock();
    renderDraft(transport);
    await screen.findByRole("heading", { level: 2, name: OFFERTEN });
    await user.click(screen.getByRole("button", { name: "Save as entry" }));
    await clickSave(user);
    await waitFor(() =>
      expect(transport.finalizeDraft).toHaveBeenCalledTimes(1),
    );
    expect(transport.finalizeDraft.mock.calls[0]![2]).toMatchObject({
      relation_selection: { project_ids: [], task_ids: [], contact_ids: [] },
      task_proposals: [],
    });
  });

  it("says plainly when permission hides some proposals and does not edit around them", async () => {
    transportMock();
    const transport = transportMock({
      getDraft: vi.fn(() =>
        Promise.resolve({
          draft: draftFixture({
            task_proposals: [createProposal],
            task_proposal_count: 3,
          }),
          source,
        }),
      ),
    });
    renderDraft(transport);
    await screen.findByRole("heading", { level: 2, name: OFFERTEN });
    expect(
      screen.getByText(
        "Some suggestions aren’t shown because the app doesn’t have permission.",
      ),
    ).toBeInTheDocument();
    // update_journal_draft replaces all proposals, so a partial list must never be written back.
    expect(screen.getByRole("button", { name: "Edit" })).toBeDisabled();
    expect(screen.getByText(journalEn.editBlockedHidden)).toBeInTheDocument();
  });

  it("shows a conflict banner, keeps typed values on reload and saves again with a new key", async () => {
    const user = userEvent.setup();
    const getDraft = vi
      .fn()
      .mockResolvedValueOnce({ draft: draftFixture(), source })
      .mockResolvedValueOnce({
        draft: draftFixture({
          version: 5,
          summary: "Ändrad någon annanstans.",
        }),
        source,
      });
    const updateDraft = vi
      .fn()
      .mockRejectedValueOnce(new HostToolError("conflict"))
      .mockResolvedValueOnce({
        draft: { id: draftId, state: "pending_review", version: 6 },
      });
    const transport = transportMock({ getDraft, updateDraft });
    renderDraft(transport);
    await screen.findByRole("heading", { level: 2, name: OFFERTEN });

    await user.click(screen.getByRole("button", { name: "Edit" }));
    await user.clear(screen.getByLabelText("Title"));
    await user.type(screen.getByLabelText("Title"), "Mitt eget");
    await user.click(screen.getByRole("button", { name: "Save" }));
    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(journalEn.conflict);
    await waitFor(() => expect(banner).toHaveFocus());

    await user.click(screen.getByRole("button", { name: "Reload" }));
    await waitFor(() => expect(getDraft).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(screen.queryByRole("alert")).not.toBeInTheDocument(),
    );
    // The owner's title is kept; the untouched summary follows the newer draft.
    expect(screen.getByLabelText("Title")).toHaveValue("Mitt eget");
    expect(screen.getByLabelText("Summary")).toHaveValue(
      "Ändrad någon annanstans.",
    );
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(updateDraft).toHaveBeenCalledTimes(2));
    expect(updateDraft.mock.calls[1]![1]).toBe(5);
    expect(updateDraft.mock.calls[1]![2]).toMatchObject({
      title: "Mitt eget",
      summary: "Ändrad någon annanstans.",
    });
    expect(updateDraft.mock.calls[1]![3]).not.toBe(
      updateDraft.mock.calls[0]![3],
    );
  });

  it("retries a failed save with the same idempotency key", async () => {
    const user = userEvent.setup();
    const updateDraft = vi
      .fn()
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValueOnce({
        draft: { id: draftId, state: "pending_review", version: 2 },
      });
    const transport = transportMock({ updateDraft });
    renderDraft(transport);
    await screen.findByRole("heading", { level: 2, name: OFFERTEN });
    await user.click(screen.getByRole("button", { name: "Edit" }));
    await user.type(screen.getByLabelText("Title"), "!");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByText(/Couldn’t save/);
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(updateDraft).toHaveBeenCalledTimes(2));
    expect(updateDraft.mock.calls[1]![3]).toBe(updateDraft.mock.calls[0]![3]);
  });

  it("shows fixed text for a refused value and calm text for a missing permission", async () => {
    const user = userEvent.setup();
    const rejectDraft = vi
      .fn()
      .mockRejectedValueOnce(new HostToolError("validation_error"))
      .mockRejectedValueOnce(new HostToolError("forbidden"));
    const transport = transportMock({ rejectDraft });
    renderDraft(transport);
    await screen.findByRole("heading", { level: 2, name: OFFERTEN });

    await user.click(screen.getByRole("button", { name: "Reject draft" }));
    await user.click(screen.getByRole("button", { name: "Yes, reject draft" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      journalEn.invalidChange,
    );
    await user.click(screen.getByRole("button", { name: "Yes, reject draft" }));
    expect(
      await screen.findByText(journalEn.forbiddenWrite),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows an already handled draft read-only", async () => {
    const transport = transportMock({
      getDraft: vi.fn(() =>
        Promise.resolve({
          draft: draftFixture({ state: "finalized" }),
          source,
        }),
      ),
    });
    renderDraft(transport);
    await screen.findByRole("heading", { level: 2, name: OFFERTEN });
    expect(
      screen.getByText("This draft has already been handled."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Edit" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Save as entry" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Reject draft" }),
    ).not.toBeInTheDocument();
  });
});

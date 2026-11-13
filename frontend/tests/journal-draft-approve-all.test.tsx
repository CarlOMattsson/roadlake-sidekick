import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DraftFrame } from "@/features/journal-app/draft-review";
import {
  journalEn,
  journalSv,
  type JournalLabels,
} from "@/features/journal-app/labels";
import type {
  JournalDraft,
  JournalSource,
  JournalTransport,
} from "@/features/journal-app/transport";

// The journal app's draft frame with a transport mock: approve-all, the undecided confirmation and
// its three choices. Nothing reaches the server except through the finalize mock.
const IDS = {
  draft: "019f0000-0000-7000-8000-0000000000f1",
  source: "019f0000-0000-7000-8000-0000000000f2",
  project: "019f0000-0000-7000-8000-0000000000f3",
  anna: "019f0000-0000-7000-8000-0000000000f4",
  bo: "019f0000-0000-7000-8000-0000000000f5",
  task: "019f0000-0000-7000-8000-0000000000f6",
  unknown: "019f0000-0000-7000-8000-0000000000f7",
  proposal: "019f0000-0000-7000-8000-0000000000f8",
};

/** Two known link suggestions (a project and a contact), one unknown link suggestion, one task proposal. */
function draftWithSuggestions(): JournalDraft {
  return {
    id: IDS.draft,
    source_id: IDS.source,
    journal_date: "2026-10-24",
    state: "pending_review",
    title: "Utkast om offerten",
    summary: "Kunden vill ha offerten före fredag.",
    key_points: [{ kind: "commitment", text: "Skicka offerten på torsdag." }],
    suggestions: {
      projects: [
        { id: IDS.project, rationale: "Offerten hör till projektet." },
        { id: IDS.unknown, rationale: null },
      ],
      tasks: [],
      contacts: [{ id: IDS.anna, rationale: null }],
    },
    task_proposals: [
      {
        proposal_id: IDS.proposal,
        type: "update_task",
        task_id: IDS.task,
        expected_task_version: 1,
        due_at: null,
      },
    ],
    task_proposal_count: 1,
    catalog: {
      projects: [{ id: IDS.project, label: "Projekt Offert" }],
      tasks: [{ id: IDS.task, label: "Följ upp offerten" }],
      contacts: [
        { id: IDS.anna, label: "Anna Andersson" },
        { id: IDS.bo, label: "Bo Berg" },
      ],
    },
    version: 1,
  };
}

/** A draft the AI made no suggestions for: no link candidates in the catalogue, no task proposals. */
function draftWithoutSuggestions(): JournalDraft {
  return {
    ...draftWithSuggestions(),
    suggestions: { projects: [], tasks: [], contacts: [] },
    task_proposals: [],
    task_proposal_count: 0,
    catalog: { projects: [], tasks: [], contacts: [] },
  };
}

function sourceOf(): JournalSource {
  return {
    id: IDS.source,
    source_type: "manual_text",
    journal_date: "2026-10-24",
    occurred_at: null,
    source_recorded_at: null,
    language: null,
    created_at: "2026-10-24T09:31:00Z",
    raw_text: "Anna vill ha offerten före fredag.",
  };
}

function transportFor(draft: JournalDraft): JournalTransport {
  return {
    getDay: vi.fn(),
    getEntry: vi.fn(),
    getSource: vi.fn(),
    getDraft: vi.fn(() => Promise.resolve({ draft, source: sourceOf() })),
    updateDraft: vi.fn(),
    rejectDraft: vi.fn(),
    // Never resolves: the tests only read what was sent.
    finalizeDraft: vi.fn(() => new Promise<never>(() => undefined)),
  };
}

function renderFrame(transport: JournalTransport, labels: JournalLabels) {
  return render(
    <DraftFrame
      id={IDS.draft}
      transport={transport}
      labels={labels}
      moves={0}
      onRejected={vi.fn()}
      onFinalized={vi.fn()}
    />,
  );
}

/** The decision group of one suggestion row, found by the name the row gives it. */
function decisionGroup(name: string) {
  return screen.getByRole("group", { name });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe.each([
  { locale: "en", t: journalEn },
  { locale: "sv", t: journalSv },
])("journal-app approve all suggestions ($locale)", ({ t }) => {
  const projectRow = t.decisionFor("Projekt Offert");
  const annaRow = t.decisionFor("Anna Andersson");
  const proposalRow = t.decisionFor(t.updateTaskProposal("Följ upp offerten"));

  it("shows one summary line with the counts of known suggestions only", async () => {
    const transport = transportFor(draftWithSuggestions());
    renderFrame(transport, t);

    // Two known link suggestions (the unknown one is not counted) and one task proposal.
    expect(
      await screen.findByText(t.suggestionSummary(2, 1)),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: t.approveAll(3) })).toBeEnabled();
    expect(
      screen.getByRole("button", { name: t.chooseYourself }),
    ).toBeEnabled();
  });

  it("keeps the card's one primary on Save: Approve all is secondary and says how many it approves", async () => {
    renderFrame(transportFor(draftWithSuggestions()), t);
    const approve = await screen.findByRole("button", {
      name: t.approveAll(3),
    });
    expect(approve).toHaveClass("sk-btn--secondary");
    expect(approve).not.toHaveClass("sk-btn--primary");
    const primaries = document.querySelectorAll(
      ".journal-draft .sk-btn--primary",
    );
    expect(primaries).toHaveLength(1);
    expect(primaries[0]).toHaveTextContent(t.finalize);
    expect(journalEn.approveAll(3)).toBe("Approve all 3 suggestions");
    expect(journalEn.approveAll(1)).toBe("Approve the suggestion");
    expect(journalSv.approveAll(14)).toBe("Godkänn alla 14 förslag");
    expect(journalSv.approveAll(1)).toBe("Godkänn förslaget");
  });

  it("approve all approves every suggestion like each row's Godkänn, then finalize keeps them", async () => {
    const user = userEvent.setup();
    const draft = draftWithSuggestions();
    const transport = transportFor(draft);
    renderFrame(transport, t);

    await user.click(
      await screen.findByRole("button", { name: t.approveAll(3) }),
    );

    // The summary line is replaced by the status, which takes focus since its button is gone.
    expect(screen.getByText(t.allApproved)).toHaveFocus();
    expect(
      screen.queryByRole("button", { name: t.approveAll(3) }),
    ).not.toBeInTheDocument();
    expect(screen.getAllByText(t.decisionApproved)).toHaveLength(3);
    expect(transport.finalizeDraft).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: t.finalize }));
    await user.click(screen.getByRole("button", { name: t.finalizeYes }));
    await waitFor(() =>
      expect(transport.finalizeDraft).toHaveBeenCalledTimes(1),
    );
    expect(transport.finalizeDraft).toHaveBeenCalledWith(
      IDS.draft,
      1,
      expect.objectContaining({
        relation_selection: {
          project_ids: [{ id: IDS.project, origin: "model_suggested" }],
          task_ids: [],
          contact_ids: [{ id: IDS.anna, origin: "model_suggested" }],
        },
        task_proposals: [draft.task_proposals[0]],
      }),
      expect.any(String),
    );
  });

  it("after approve all the owner can still change one row", async () => {
    const user = userEvent.setup();
    const transport = transportFor(draftWithSuggestions());
    renderFrame(transport, t);

    await user.click(
      await screen.findByRole("button", { name: t.approveAll(3) }),
    );
    await user.click(
      within(decisionGroup(annaRow)).getByRole("button", { name: t.decline }),
    );
    expect(
      within(decisionGroup(annaRow).parentElement!).getByText(
        t.decisionDeclined,
      ),
    ).toBeInTheDocument();
    // One row is no longer approved, so the summary and approve all come back.
    expect(
      await screen.findByRole("button", { name: t.approveAll(3) }),
    ).toBeEnabled();
  });

  it("saving with undecided suggestions shows the note and the three choices", async () => {
    const user = userEvent.setup();
    const transport = transportFor(draftWithSuggestions());
    renderFrame(transport, t);

    await user.click(await screen.findByRole("button", { name: t.finalize }));

    expect(screen.getByText(t.undecidedNote(2, 1))).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: t.approveAllAndSave }),
    ).toBeEnabled();
    expect(
      screen.getByRole("button", { name: t.saveWithoutThem }),
    ).toBeEnabled();
    expect(screen.getByRole("button", { name: t.reviewThem })).toBeEnabled();
    expect(
      screen.queryByRole("button", { name: t.finalizeYes }),
    ).not.toBeInTheDocument();
    // While the confirmation is open, approve all is held like the rows are.
    expect(
      screen.getByRole("button", { name: t.approveAll(3) }),
    ).toBeDisabled();
    expect(transport.finalizeDraft).not.toHaveBeenCalled();
  });

  it("save without them sends only the decided choices", async () => {
    const user = userEvent.setup();
    const transport = transportFor(draftWithSuggestions());
    renderFrame(transport, t);

    await user.click(await screen.findByRole("button", { name: t.finalize }));
    await user.click(screen.getByRole("button", { name: t.saveWithoutThem }));
    await waitFor(() =>
      expect(transport.finalizeDraft).toHaveBeenCalledTimes(1),
    );
    expect(transport.finalizeDraft).toHaveBeenCalledWith(
      IDS.draft,
      1,
      expect.objectContaining({
        relation_selection: { project_ids: [], task_ids: [], contact_ids: [] },
        task_proposals: [],
      }),
      expect.any(String),
    );
  });

  it("save without them keeps an approved row and drops the undecided ones", async () => {
    const user = userEvent.setup();
    const draft = draftWithSuggestions();
    const transport = transportFor(draft);
    renderFrame(transport, t);

    await user.click(await screen.findByRole("button", { name: t.finalize }));
    // Close the confirmation by approving the project row, then save from the decision bar again.
    await user.click(screen.getByRole("button", { name: t.reviewThem }));
    await user.click(
      within(decisionGroup(projectRow)).getByRole("button", {
        name: t.approve,
      }),
    );
    await user.click(screen.getByRole("button", { name: t.finalize }));
    await user.click(screen.getByRole("button", { name: t.saveWithoutThem }));
    await waitFor(() =>
      expect(transport.finalizeDraft).toHaveBeenCalledTimes(1),
    );
    expect(transport.finalizeDraft).toHaveBeenCalledWith(
      IDS.draft,
      1,
      expect.objectContaining({
        relation_selection: {
          project_ids: [{ id: IDS.project, origin: "model_suggested" }],
          task_ids: [],
          contact_ids: [],
        },
        task_proposals: [],
      }),
      expect.any(String),
    );
  });

  it("approve all and save sends every suggestion and the owner's own choice", async () => {
    const user = userEvent.setup();
    const draft = draftWithSuggestions();
    const transport = transportFor(draft);
    renderFrame(transport, t);

    // Bo is not suggested: the owner's own choice, kept next to the approved suggestions.
    await user.click(await screen.findByRole("checkbox", { name: "Bo Berg" }));
    await user.click(screen.getByRole("button", { name: t.finalize }));
    await user.click(screen.getByRole("button", { name: t.approveAllAndSave }));
    await waitFor(() =>
      expect(transport.finalizeDraft).toHaveBeenCalledTimes(1),
    );
    expect(transport.finalizeDraft).toHaveBeenCalledWith(
      IDS.draft,
      1,
      expect.objectContaining({
        relation_selection: {
          project_ids: [{ id: IDS.project, origin: "model_suggested" }],
          task_ids: [],
          contact_ids: [
            { id: IDS.anna, origin: "model_suggested" },
            { id: IDS.bo, origin: "user_selected" },
          ],
        },
        task_proposals: [draft.task_proposals[0]],
      }),
      expect.any(String),
    );
  });

  it("review them closes the confirmation and opens both sections", async () => {
    const user = userEvent.setup();
    const transport = transportFor(draftWithSuggestions());
    renderFrame(transport, t);

    await user.click(await screen.findByRole("button", { name: t.finalize }));
    await user.click(screen.getByRole("button", { name: t.reviewThem }));

    expect(
      screen.queryByRole("button", { name: t.saveWithoutThem }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: t.approveAllAndSave }),
    ).not.toBeInTheDocument();
    expect(transport.finalizeDraft).not.toHaveBeenCalled();
    expect(
      screen.getByRole("button", {
        name: (name: string) => name.startsWith(t.relationsFold),
      }),
    ).toHaveAttribute("aria-expanded", "true");
    expect(
      screen.getByRole("button", {
        name: (name: string) => name.startsWith(t.proposalsFold),
      }),
    ).toHaveAttribute("aria-expanded", "true");
  });

  it("choose yourself opens both sections and keeps the summary", async () => {
    const user = userEvent.setup();
    renderFrame(transportFor(draftWithSuggestions()), t);

    await user.click(
      await screen.findByRole("button", { name: t.chooseYourself }),
    );

    expect(screen.getByText(t.suggestionSummary(2, 1))).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: (name: string) => name.startsWith(t.relationsFold),
      }),
    ).toHaveAttribute("aria-expanded", "true");
  });

  it("a draft where every suggestion is decided gets the plain confirmation", async () => {
    const user = userEvent.setup();
    const transport = transportFor(draftWithSuggestions());
    renderFrame(transport, t);

    await user.click(await screen.findByRole("button", { name: t.finalize }));
    await user.click(screen.getByRole("button", { name: t.reviewThem }));
    await user.click(
      within(decisionGroup(projectRow)).getByRole("button", {
        name: t.approve,
      }),
    );
    // An explicit Avslå counts as decided, so it is not offered as undecided.
    await user.click(
      within(decisionGroup(annaRow)).getByRole("button", { name: t.decline }),
    );
    await user.click(
      within(decisionGroup(proposalRow)).getByRole("button", {
        name: t.decline,
      }),
    );
    await user.click(screen.getByRole("button", { name: t.finalize }));

    expect(
      screen.getByRole("button", { name: t.finalizeYes }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: t.saveWithoutThem }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: t.approveAllAndSave }),
    ).not.toBeInTheDocument();
    expect(transport.finalizeDraft).not.toHaveBeenCalled();
  });

  it("a draft without suggestions shows no summary and the plain confirmation", async () => {
    const user = userEvent.setup();
    const draft = draftWithoutSuggestions();
    const transport = transportFor(draft);
    renderFrame(transport, t);

    await screen.findByRole("heading", { name: draft.title });
    expect(
      screen.queryByRole("button", { name: t.approveAll(3) }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: t.chooseYourself }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: t.finalize }));
    expect(
      screen.getByRole("button", { name: t.finalizeYes }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: t.saveWithoutThem }),
    ).not.toBeInTheDocument();
  });

  it("says nothing about a decision on an undecided row, and names Approved or Declined once one is chosen", async () => {
    const user = userEvent.setup();
    renderFrame(transportFor(draftWithSuggestions()), t);
    await screen.findByRole("button", { name: t.approveAll(3) });

    // The unpressed Approve/Decline pair says it is open; no "No decision yet" and no per-row "Suggested by AI".
    expect(screen.queryByText(/No decision yet|Inget beslut ännu/)).toBeNull();
    expect(screen.queryByText(/Suggested by AI|Föreslaget av AI/)).toBeNull();
    expect(screen.queryByText(t.decisionApproved)).toBeNull();
    expect(screen.queryByText(t.decisionDeclined)).toBeNull();

    await user.click(
      within(decisionGroup(annaRow)).getByRole("button", { name: t.decline }),
    );
    expect(
      within(decisionGroup(annaRow).parentElement!).getByText(
        t.decisionDeclined,
      ),
    ).toBeInTheDocument();
    // The other rows stay silent.
    expect(screen.queryByText(t.decisionApproved)).toBeNull();
    expect(screen.queryByText(/No decision yet|Inget beslut ännu/)).toBeNull();
  });

  it("draws each suggestion section as the app's fold row that names the region it controls", async () => {
    const user = userEvent.setup();
    const { container } = renderFrame(transportFor(draftWithSuggestions()), t);
    await screen.findByRole("button", { name: t.approveAll(3) });

    const toggles = Array.from(
      container.querySelectorAll<HTMLButtonElement>(
        "button.sk-fold.journal-disclosure-toggle",
      ),
    );
    expect(toggles.length).toBeGreaterThanOrEqual(2);
    for (const toggle of toggles) {
      const target = toggle.getAttribute("aria-controls");
      expect(target).toBeTruthy();
      const region = container.querySelector(`[id="${target}"]`);
      expect(region).toHaveClass("journal-disclosure-body");
      expect(toggle).toHaveAttribute("aria-expanded", "false");
      // The chevron is an icon, not a text glyph.
      expect(toggle.querySelector("svg")).not.toBeNull();
      expect(toggle.textContent).not.toMatch(/[▾▴]/);
    }
    // No pair wrapper is left around the toggles.
    expect(container.querySelector(".journal-disclosure-pair")).toBeNull();

    // The count is its own inline box, so the computed name may leave out the space before it.
    const links = screen.getByRole("button", {
      name: new RegExp(`^${t.relationsFold} ?\\(\\d+\\)$`),
    });
    expect(links).toBeInTheDocument();
    await user.click(links);
    expect(links).toHaveAttribute("aria-expanded", "true");
  });

  it("hides the legend of the task proposals visually but keeps it for a screen reader", async () => {
    const { container } = renderFrame(transportFor(draftWithSuggestions()), t);
    await screen.findByRole("button", { name: t.approveAll(3) });

    const legend = Array.from(container.querySelectorAll("legend")).find(
      (candidate) => candidate.textContent === t.proposals,
    );
    expect(legend).toHaveClass("journal-visually-hidden");
    expect(
      screen.getByRole("group", { name: t.proposals }),
    ).toBeInTheDocument();
  });

  it("names an unknown suggestion as an unknown item in words", async () => {
    renderFrame(transportFor(draftWithSuggestions()), t);
    await screen.findByRole("button", { name: t.approveAll(3) });

    expect(screen.getAllByText(t.unknownItem).length).toBeGreaterThan(0);
  });
});

describe("journal-app approve all suggestions, Swedish texts", () => {
  it("renders the Swedish summary, buttons and undecided note", async () => {
    const user = userEvent.setup();
    renderFrame(transportFor(draftWithSuggestions()), journalSv);

    expect(
      await screen.findByText("Claude föreslår 2 kopplingar och 1 uppgift."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Godkänn alla 3 förslag" }),
    ).toBeEnabled();
    expect(screen.getByRole("button", { name: "Välj själv" })).toBeEnabled();

    await user.click(
      screen.getByRole("button", { name: "Spara som anteckning" }),
    );
    expect(
      screen.getByText(
        "2 kopplingsförslag och 1 uppgiftsförslag är inte granskade och sparas inte.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Godkänn alla och spara" }),
    ).toBeEnabled();
    expect(
      screen.getByRole("button", { name: "Spara utan dem" }),
    ).toBeEnabled();
    expect(
      screen.getByRole("button", { name: "Granska dem först" }),
    ).toBeEnabled();
  });
});

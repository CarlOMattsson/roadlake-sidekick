import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ItemEditor } from "@/features/shopping-app/shopping-view-parts/item-editor";
import { shoppingEn, shoppingSv } from "@/features/shopping-app/labels";
import type { ShoppingLabels } from "@/features/shopping-app/labels";
import type { ShoppingItem } from "@/features/shopping-app/transport";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import { WriteFailureRow } from "@/features/work-app/shared/write-failure-row";
import type { WriteFailure } from "@/lib/mcp/errors";

const RETRY_WORDS = /try again|försök igen/i;

describe("the write failure sentences leave the retry to the button", () => {
  it.each([
    ["English", workEn],
    ["Swedish", workSv],
  ])("%s: no failed-write sentence repeats the button", (_name, labels) => {
    for (const sentence of [
      labels.stepSaveFailed,
      labels.stepCreateFailed,
      labels.contactWriteFailed,
      labels.contactCreateFailed,
      labels.taskCreateFailed,
    ])
      expect(sentence).not.toMatch(RETRY_WORDS);
  });
});

describe("WriteFailureRow", () => {
  function row(failure: WriteFailure, labels = workSv) {
    const onRetry = vi.fn();
    render(
      <WriteFailureRow
        failure={failure}
        failedMessage={labels.taskCreateFailed}
        labels={labels}
        onRetry={onRetry}
      />,
    );
    return onRetry;
  }

  it("a transient failure is the family's error row with Försök igen, which repeats the write", async () => {
    const onRetry = row("failed");
    expect(screen.getByRole("alert")).toHaveTextContent(
      workSv.taskCreateFailed,
    );
    await userEvent.click(screen.getByRole("button", { name: "Försök igen" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["conflict", workSv.createConflict],
    ["invalid", workSv.invalidChange],
    ["not_found", workSv.notFound],
  ] as const)("%s explains and has no button", (failure, sentence) => {
    row(failure);
    expect(screen.getByRole("alert")).toHaveTextContent(sentence);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("being forbidden is calm text, not an alert", () => {
    row("forbidden");
    expect(screen.getByText(workSv.forbiddenWrite)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("answers in English with English words", () => {
    row("failed", workEn);
    expect(screen.getByRole("button", { name: "Try again" })).toBeVisible();
  });

  it("a running retry is aria-busy and does not start another", async () => {
    const onRetry = vi.fn();
    render(
      <WriteFailureRow
        failure="failed"
        failedMessage={workSv.taskCreateFailed}
        labels={workSv}
        retrying
        onRetry={onRetry}
      />,
    );
    const button = screen.getByRole("button");
    expect(button).toHaveAttribute("aria-busy", "true");
    await userEvent.click(button);
    expect(onRetry).not.toHaveBeenCalled();
  });
});

const ITEM: ShoppingItem = {
  id: "019f0000-0000-7000-8000-0000000000a0",
  list_id: "019f0000-0000-7000-8000-000000000001",
  name: "Milk",
  quantity: "1",
  unit: null,
  note: null,
  occasion: null,
  offer: null,
  offer_status: "none",
  product_url: null,
  purchased: false,
  purchased_at: null,
  recipient_contact_id: null,
  store: null,
  target_date: null,
  created_at: "2026-10-24T12:00:00Z",
  updated_at: "2026-10-24T12:00:00Z",
  version: 1,
};

describe("the shopping item editor's failed contact search", () => {
  it.each([
    ["English", shoppingEn, "Try again"],
    ["Swedish", shoppingSv, "Försök igen"],
  ] as const)(
    "%s: is the error row with a button that searches again",
    async (_name, labels: ShoppingLabels, retry) => {
      const user = userEvent.setup();
      const contacts = vi
        .fn()
        .mockRejectedValueOnce(new Error("PRIVATE_BACKEND_MESSAGE"))
        .mockResolvedValue({ contacts: [] });
      render(
        <ItemEditor
          item={ITEM}
          labels={labels}
          busy={false}
          focusFirst={false}
          contacts={contacts}
          onCancel={vi.fn()}
          onSave={vi.fn()}
        />,
      );
      await user.click(screen.getByRole("button", { name: labels.moreFields }));
      await user.type(screen.getByLabelText(labels.contactQuery), "Anna");
      await user.click(
        screen.getByRole("button", { name: labels.searchContact }),
      );

      expect(await screen.findByRole("alert")).toHaveTextContent(
        labels.contactSearchFailed,
      );
      expect(screen.queryByText("PRIVATE_BACKEND_MESSAGE")).toBeNull();
      await user.click(screen.getByRole("button", { name: retry }));
      expect(contacts).toHaveBeenCalledTimes(2);
      expect(screen.queryByRole("alert")).toBeNull();
    },
  );
});

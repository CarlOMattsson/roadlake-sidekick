import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { EntryTextForm } from "@/features/journal-app/entry-write";
import {
  BODY_MAX_BYTES,
  entryFitsBody,
  TEXT_MAX,
} from "@/features/journal-app/entry-limits";
import { journalEn, journalSv } from "@/features/journal-app/labels";

describe("entryFitsBody", () => {
  it("accepts the longest ASCII text the backend takes", () => {
    expect(entryFitsBody("Title", "x".repeat(TEXT_MAX))).toBe(true);
  });

  it("accepts the longest two-byte and newline-heavy text", () => {
    expect(entryFitsBody("Title", "ö".repeat(TEXT_MAX))).toBe(true);
    expect(entryFitsBody("Title", "\n".repeat(TEXT_MAX))).toBe(true);
  });

  it("refuses three-byte text that stays under the character limit but over the byte limit", () => {
    const text = "漢".repeat(90_000);
    expect(text.length).toBeLessThanOrEqual(TEXT_MAX);
    expect(new TextEncoder().encode(text).length).toBeGreaterThan(
      BODY_MAX_BYTES,
    );
    expect(entryFitsBody("Title", text)).toBe(false);
  });

  it("counts escaped quotes and control characters at their JSON size", () => {
    expect(entryFitsBody("Title", '"'.repeat(TEXT_MAX))).toBe(true);
    expect(entryFitsBody("Title", "\u0001".repeat(TEXT_MAX))).toBe(false);
  });
});

describe("the entry form and a text over the byte budget", () => {
  function setup(labels: typeof journalEn) {
    const submit = vi.fn().mockResolvedValue(undefined);
    render(
      <EntryTextForm
        labels={labels}
        kind="new"
        signatureBase="2026-10-24"
        submit={submit}
        onCancel={() => {}}
      />,
    );
    return submit;
  }

  it.each([
    ["Swedish", journalSv],
    ["English", journalEn],
  ])("says so in %s and writes nothing", (_name, labels) => {
    const submit = setup(labels);
    fireEvent.input(screen.getByLabelText(labels.titleLabel), {
      target: { value: "Lång" },
    });
    fireEvent.input(screen.getByLabelText(labels.entryTextLabel), {
      target: { value: "漢".repeat(90_000) },
    });
    fireEvent.click(screen.getByRole("button", { name: labels.saveEntry }));
    expect(screen.getByRole("alert").textContent).toBe(labels.entryTooLong);
    expect(submit).not.toHaveBeenCalled();
    expect(screen.getByLabelText(labels.entryTextLabel)).toHaveAttribute(
      "aria-invalid",
      "true",
    );
  });

  it("submits a long but fitting text", () => {
    const submit = setup(journalSv);
    fireEvent.input(screen.getByLabelText(journalSv.titleLabel), {
      target: { value: "Lång" },
    });
    fireEvent.input(screen.getByLabelText(journalSv.entryTextLabel), {
      target: { value: "ö".repeat(TEXT_MAX) },
    });
    fireEvent.click(screen.getByRole("button", { name: journalSv.saveEntry }));
    expect(submit).toHaveBeenCalledTimes(1);
  });
});

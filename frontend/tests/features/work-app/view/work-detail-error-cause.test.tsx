import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { workSv } from "@/features/work-app/shared/labels";
import { WorkView } from "@/features/work-app/view/work-view";
import { type WorkTransport } from "@/features/work-app/transport/transport";

/*
 * A failed Task read shows a second line under the heading: "Sidekick svarade inte. Kontrollera anslutningen." when no answer came from
 * Sidekick, "Sidekick svarade med ett fel." when Sidekick answered with its own closed code (a HostToolError with a code).
 * navigator.onLine decides nothing, and the offline sentence is gone (see ui-states).
 */

const TASK_ID = "019f0000-0000-7000-8000-0000000000a1";

/** The transport parts a Task frame reads when it mounts; the rest is never called. */
function transportWith(overrides: Record<string, unknown>): WorkTransport {
  const emptyPage = { items: [], next_cursor: null };
  return {
    listTaskContacts: vi.fn().mockResolvedValue(emptyPage),
    listTaskSteps: vi.fn().mockResolvedValue(emptyPage),
    listStepActions: vi.fn().mockResolvedValue(emptyPage),
    listTaskExternalReferences: vi.fn().mockResolvedValue(emptyPage),
    listProjectTasks: vi.fn().mockResolvedValue(emptyPage),
    ...overrides,
  } as unknown as WorkTransport;
}

describe("the second line of a failed Task read", () => {
  it("a read answered by Sidekick with a closed code says that Sidekick answered with an error", async () => {
    const transport = transportWith({
      getTask: vi.fn().mockRejectedValue(
        Object.assign(new Error("x"), {
          name: "HostToolError",
          code: "internal_error",
        }),
      ),
    });
    render(
      <WorkView
        transport={transport}
        initial={{ kind: "task", id: TASK_ID }}
        labels={workSv}
      />,
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Uppgiften kunde inte hämtas");
    expect(
      screen.queryByText("Försök igen om en stund."),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: workSv.retry }),
    ).toBeInTheDocument();
  });

  it("a failed fetch with the frame online says that Sidekick did not answer, and no retry-later sentence", async () => {
    const onLine = vi
      .spyOn(window.navigator, "onLine", "get")
      .mockReturnValue(true);
    try {
      const transport = transportWith({
        getTask: vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
      });
      const { container } = render(
        <WorkView
          transport={transport}
          initial={{ kind: "task", id: TASK_ID }}
          labels={workSv}
        />,
      );

      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent("Uppgiften kunde inte hämtas");
      expect(
        screen.queryByText("Försök igen om en stund."),
      ).not.toBeInTheDocument();
      expect(container.querySelector(".sk-error-hint")).toHaveTextContent(
        "Sidekick svarade inte. Kontrollera anslutningen.",
      );
    } finally {
      onLine.mockRestore();
    }
  });

  it("a failed fetch while the frame is offline says the same, Sidekick svarade inte., and no offline sentence", async () => {
    const onLine = vi
      .spyOn(window.navigator, "onLine", "get")
      .mockReturnValue(false);
    try {
      const transport = transportWith({
        getTask: vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
      });
      render(
        <WorkView
          transport={transport}
          initial={{ kind: "task", id: TASK_ID }}
          labels={workSv}
        />,
      );

      expect(
        await screen.findByText(
          "Sidekick svarade inte. Kontrollera anslutningen.",
        ),
      ).toHaveClass("sk-error-hint");
      expect(
        screen.queryByText("Du verkar vara offline. Kontrollera anslutningen."),
      ).not.toBeInTheDocument();
    } finally {
      onLine.mockRestore();
    }
  });
});

describe("the heading of a failed read of a record and the box around it", () => {
  const failing = () =>
    transportWith({
      getTask: vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
      getProject: vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
      getContactContext: vi
        .fn()
        .mockRejectedValue(new TypeError("Failed to fetch")),
    });

  it.each([
    [{ kind: "task", id: TASK_ID }, "Uppgiften kunde inte hämtas"],
    [{ kind: "project", id: TASK_ID }, "Projektet kunde inte hämtas"],
    [{ kind: "contact", id: TASK_ID }, "Kontakten kunde inte hämtas"],
  ] as const)(
    "%j says which record could not be read, in the full view with no card or room name around it",
    async (initial, heading) => {
      render(
        <WorkView
          transport={failing()}
          initial={initial}
          labels={workSv}
          chrome={false}
        />,
      );
      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent(heading);
      expect(alert.closest(".sk-card")).toBeNull();
      expect(document.querySelector(".sk-eyebrow")).not.toHaveTextContent(
        workSv.title,
      );
    },
  );
});

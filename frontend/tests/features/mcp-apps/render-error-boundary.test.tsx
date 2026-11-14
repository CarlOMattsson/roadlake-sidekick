import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
  type MockInstance,
} from "vitest";

import type { HostFeatures } from "@/features/mcp-apps/bridge";
import {
  RenderErrorBoundary,
  StartupError,
} from "@/features/mcp-apps/ui/error-boundary";
import { errorLabelsFor } from "@/features/mcp-apps/ui/states";
import {
  SidekickShell,
  type RoomRegistry,
  type ShellRoomProps,
} from "@/features/mcp-apps/sidekick-shell";
import { ROOM_IDS } from "@/features/mcp-apps/router";

const LOCAL: HostFeatures = {
  serverTools: true,
  message: true,
  openLinks: true,
};

let broken = true;
function Flaky() {
  if (broken) throw new TypeError("secret title: Anna's diagnosis");
  return <p>fine now</p>;
}

let logged: MockInstance<typeof console.error>;
beforeEach(() => {
  broken = true;
  logged = vi.spyOn(console, "error").mockImplementation(() => {});
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("RenderErrorBoundary", () => {
  it("shows a translated notice with a retry instead of a blank view", () => {
    render(
      <RenderErrorBoundary locale="sv" scope="work">
        <Flaky />
      </RenderErrorBoundary>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      errorLabelsFor("sv").render,
    );
    expect(
      screen.getByRole("button", { name: errorLabelsFor("sv").retry }),
    ).toBeInTheDocument();
  });

  it("speaks English when the app language is English", () => {
    render(
      <RenderErrorBoundary locale="en" scope="work">
        <Flaky />
      </RenderErrorBoundary>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "This view couldn’t be shown",
    );
    expect(screen.getByRole("button", { name: "Try again" })).toBeVisible();
  });

  it("logs only the scope and the error class, never the message or stack", () => {
    render(
      <RenderErrorBoundary locale="sv" scope="journal">
        <Flaky />
      </RenderErrorBoundary>,
    );
    const ours = logged.mock.calls.filter(
      ([first]) => first === "[sidekick] render failed",
    );
    expect(ours).toEqual([
      ["[sidekick] render failed", { scope: "journal", kind: "TypeError" }],
    ]);
    expect(document.body.textContent).not.toContain("Anna");
  });

  it("draws the part again from scratch on retry", () => {
    render(
      <RenderErrorBoundary locale="sv" scope="work">
        <Flaky />
      </RenderErrorBoundary>,
    );
    broken = false;
    fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));
    expect(screen.getByText("fine now")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("RenderErrorBoundary in the shell", () => {
  function Stub(props: ShellRoomProps) {
    if (props.entry.room === "journal" && broken) throw new Error("boom");
    return <h2 data-testid={`room-${props.entry.room}`}>{props.entry.room}</h2>;
  }
  const rooms = Object.fromEntries(
    ROOM_IDS.map((room) => [room, Stub]),
  ) as RoomRegistry;

  function shell(full: boolean) {
    return render(
      <SidekickShell
        locale="sv"
        rooms={rooms}
        start={{ room: "journal", view: "day" }}
        full={full}
        features={LOCAL}
        onModelContext={vi.fn()}
        onSendMessage={vi.fn().mockResolvedValue(true)}
      />,
    );
  }

  it("keeps the room strip and the other rooms working when one room fails", () => {
    shell(true);
    expect(screen.getByRole("alert")).toHaveTextContent(
      errorLabelsFor("sv").render,
    );
    fireEvent.click(screen.getByRole("button", { name: "Arbete" }));
    expect(screen.getByTestId("room-work")).toBeVisible();
    broken = false;
    fireEvent.click(screen.getByRole("button", { name: "Dagbok" }));
    fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));
    expect(screen.getByTestId("room-journal")).toBeVisible();
  });

  it("guards the inline card too", () => {
    shell(false);
    expect(screen.getByRole("alert")).toHaveTextContent(
      errorLabelsFor("sv").render,
    );
  });
});

describe("StartupError", () => {
  it("shows a short translated card and retries", () => {
    const onRetry = vi.fn();
    render(<StartupError locale="sv" onRetry={onRetry} />);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Sidekick kunde inte startas",
    );
    fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("is English on request and exposes busy state while retrying", () => {
    render(<StartupError locale="en" onRetry={vi.fn()} retrying />);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Sidekick couldn’t start",
    );
    expect(screen.getByRole("button")).toHaveAttribute("aria-busy", "true");
  });

  it("has the same keys in both languages", () => {
    expect(Object.keys(errorLabelsFor("sv"))).toEqual(
      Object.keys(errorLabelsFor("en")),
    );
  });
});

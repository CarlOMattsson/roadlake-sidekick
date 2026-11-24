import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { JournalRoom } from "@/features/journal-app/room";
import type { RoomTransport } from "@/features/mcp-apps/room-types";
import { HostToolError } from "@/features/mcp-apps/bridge";
import { day, entry } from "@tests/helpers/journal-app-fixtures";

vi.mock("@/features/journal-app/photo-shrink", async (importOriginal) => ({
  ...(await importOriginal<
    typeof import("@/features/journal-app/photo-shrink")
  >()),
  shrinkPhoto: vi.fn(() =>
    Promise.resolve({
      photo: "UEhPVE8=",
      thumbnail: "VEhVTUI=",
      width: 2048,
      height: 1536,
      mediaType: "image/jpeg",
    }),
  ),
}));

const photoId = "019f0000-0000-7000-8000-0000000000f1";
const date = "2026-10-24";

const record = (alt: string | null) => ({
  id: photoId,
  alt_text: alt,
  alt_text_by: alt ? "you" : null,
  byte_size: 100,
  camera: null,
  entry_id: null,
  height: 1536,
  journal_date: date,
  location: null,
  media_type: "image/jpeg",
  orientation: null,
  position: 0,
  taken_at: null,
  version: 1,
  width: 2048,
});

beforeEach(() => {
  document.head.innerHTML = '<meta name="sidekick-app-locale" content="en">';
});
afterEach(() => {
  document.head.innerHTML = "";
});

function hostOf(options: {
  ids?: string[];
  add?: () => Promise<unknown>;
  supportsTool?: (name: string) => boolean;
}) {
  const ids = options.ids ?? [];
  const call = vi.fn<(name: string, args?: object) => Promise<unknown>>(
    (name, args) => {
      if (name === "get_journal_day")
        return Promise.resolve({
          ...day(date, [entry]),
          day_attachments: { count: ids.length, ids },
        });
      if (name === "get_journal_photo")
        return Promise.resolve({
          photo: record("A bridge at dusk"),
          size: (args as { size: string }).size,
          data: "/9j/4AAQ",
        });
      if (name === "add_journal_photo")
        return (
          options.add?.() ?? Promise.resolve({ photo: record("A bridge") })
        );
      return Promise.reject(new Error(`unexpected ${name}`));
    },
  );
  const transport = {
    call,
    requestDisplayMode: vi.fn().mockResolvedValue("fullscreen"),
    updateModelContext: vi.fn().mockResolvedValue(undefined),
    ...(options.supportsTool ? { supportsTool: options.supportsTool } : {}),
  } as unknown as RoomTransport;
  return { call, transport };
}

const photosOf = (call: ReturnType<typeof hostOf>["call"], name: string) =>
  call.mock.calls.filter(([tool]) => tool === name);

function renderDay(transport: RoomTransport) {
  return render(<JournalRoom mode="full" transport={transport} />);
}

describe("the day's photos", () => {
  it("draws the day's photos as named tiles from their thumbnails", async () => {
    const { call, transport } = hostOf({ ids: [photoId] });
    renderDay(transport);

    const tile = await screen.findByRole("img", { name: "A bridge at dusk" });
    expect(tile).toHaveAttribute("src", "data:image/jpeg;base64,/9j/4AAQ");
    expect(call).toHaveBeenCalledWith("get_journal_photo", {
      photo_id: photoId,
      size: "thumb",
    });
    expect(screen.getByRole("list", { name: "Photos" })).toBeInTheDocument();
  });

  it("opens the large photo in the viewer and comes back to the day", async () => {
    const { call, transport } = hostOf({ ids: [photoId] });
    renderDay(transport);
    await userEvent.click(
      await screen.findByRole("button", { name: "A bridge at dusk" }),
    );

    await waitFor(() =>
      expect(call).toHaveBeenCalledWith("get_journal_photo", {
        photo_id: photoId,
        size: "photo",
      }),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: /The day/ }),
    );
    expect(
      await screen.findByRole("button", { name: /Add photo/ }),
    ).toBeVisible();
  });

  it("adds a photo with its caption, once, and reads the day again", async () => {
    const { call, transport } = hostOf({});
    const { container } = renderDay(transport);
    await userEvent.click(
      await screen.findByRole("button", { name: /Add photo/ }),
    );
    const input = container.querySelector<HTMLInputElement>(
      'input[type="file"]',
    ) as HTMLInputElement;
    fireEvent.change(input, {
      target: {
        files: [new File(["x"], "IMG_1.jpg", { type: "image/jpeg" })],
      },
    });

    const caption = await screen.findByLabelText("Caption (optional)");
    await userEvent.type(caption, "A bridge");
    await userEvent.click(
      screen.getByRole("button", { name: "Add to the day" }),
    );

    await waitFor(() =>
      expect(photosOf(call, "add_journal_photo")).toHaveLength(1),
    );
    expect(photosOf(call, "add_journal_photo")[0]?.[1]).toMatchObject({
      journal_date: date,
      photo: "UEhPVE8=",
      thumbnail: "VEhVTUI=",
      alt_text: "A bridge",
    });
    expect(await screen.findByText("Photo added to the day")).toBeVisible();
    // The day is read once to open and once again after the photo.
    await waitFor(() =>
      expect(photosOf(call, "get_journal_day")).toHaveLength(2),
    );
  });

  it("sends the same key when the same photo is tried again after a failure", async () => {
    const add = vi
      .fn<() => Promise<unknown>>()
      .mockRejectedValueOnce(new HostToolError("internal_error"))
      .mockResolvedValue({ photo: record(null) });
    const { call, transport } = hostOf({ add });
    const { container } = renderDay(transport);
    await userEvent.click(
      await screen.findByRole("button", { name: /Add photo/ }),
    );
    fireEvent.change(
      container.querySelector('input[type="file"]') as HTMLInputElement,
      { target: { files: [new File(["x"], "a.jpg", { type: "image/jpeg" })] } },
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Add to the day" }),
    );
    expect(
      await screen.findByText("Couldn’t add the photo. Try again."),
    ).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));

    await waitFor(() =>
      expect(photosOf(call, "add_journal_photo")).toHaveLength(2),
    );
    const [first, second] = photosOf(call, "add_journal_photo").map(
      ([, args]) => (args as { idempotency_key: string }).idempotency_key,
    );
    expect(first).toBeTruthy();
    expect(second).toBe(first);
  });

  it("tells the owner when the file is no picture, and offers nothing without the photo tools", async () => {
    const { shrinkPhoto, ShrinkError } =
      await import("@/features/journal-app/photo-shrink");
    vi.mocked(shrinkPhoto).mockRejectedValueOnce(new ShrinkError("unreadable"));
    const { transport } = hostOf({});
    const { container, unmount } = renderDay(transport);
    await userEvent.click(
      await screen.findByRole("button", { name: /Add photo/ }),
    );
    fireEvent.change(
      container.querySelector('input[type="file"]') as HTMLInputElement,
      { target: { files: [new File(["x"], "a.txt", { type: "text/plain" })] } },
    );
    expect(
      await screen.findByText("That file isn’t a picture that can be used."),
    ).toBeVisible();
    unmount();

    const without = hostOf({
      supportsTool: (name) => name !== "add_journal_photo",
    });
    renderDay(without.transport);
    await screen.findByText(entry.title);
    expect(screen.queryByRole("button", { name: /Add photo/ })).toBeNull();
  });
});

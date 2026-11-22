import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { photoEn, photoSv } from "@/features/mcp-apps/ui/photo-labels";
import {
  PhotoViewer,
  toPhotoSrc,
  type PhotoSource,
  type PhotoViewerAction,
} from "@/features/mcp-apps/ui/photo-viewer";
import {
  PhotoGrid,
  PhotoStrip,
  photoAlt,
  photoSlots,
  safePhotoSrc,
  type Photo,
} from "@/features/mcp-apps/ui/photos";

/** A one-pixel PNG, as a thumbnail arrives in a tool result. */
const PNG =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";
const LARGE = (id: string) => `data:image/jpeg;base64,${btoa(`large-${id}`)}`;

function photos(n: number, extra: Partial<Photo> = {}): Photo[] {
  return Array.from({ length: n }, (_, i) => ({
    id: `p${i + 1}`,
    thumb: PNG,
    alt: `Bild ${i + 1}`,
    date: "2026-11-14",
    width: 1280,
    height: 960,
    ...extra,
  }));
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("photo labels", () => {
  it("have the same keys in Swedish and English", () => {
    expect(Object.keys(photoSv).sort()).toEqual(Object.keys(photoEn).sort());
  });
});

describe("photo names and sources", () => {
  it("uses the caption, and for a photo without one 'Foto {n} från {dag}', never a file name", () => {
    const [first] = photos(1);
    expect(photoAlt(first as Photo, 0, "sv-SE")).toBe("Bild 1");
    expect(photoAlt({ id: "a", alt: "  " }, 1, "sv-SE")).toBe("Foto 2");
    expect(
      photoAlt(
        { id: "a", alt: "IMG_2041.HEIC", date: "2026-11-14" },
        1,
        "sv-SE",
      ),
    ).toBe("Foto 2 från 14 nov");
    expect(
      photoAlt(
        { id: "a", alt: "PXL_20261114_0930", date: "2026-11-14" },
        2,
        "en-GB",
      ),
    ).toBe("Photo 3 from 14 Nov");
    expect(photoAlt({ id: "a", alt: "Hamnen.jpg i dimma" }, 0, "sv-SE")).toBe(
      "Hamnen.jpg i dimma",
    );
  });

  it("draws only raster data: images", () => {
    expect(safePhotoSrc(PNG)).toBe(PNG);
    expect(safePhotoSrc("https://example.invalid/a.jpg")).toBeNull();
    expect(safePhotoSrc("blob:https://example.invalid/1")).toBeNull();
    expect(safePhotoSrc("data:image/svg+xml;base64,PHN2Zy8+")).toBeNull();
    expect(safePhotoSrc("data:text/html;base64,PGI+")).toBeNull();
    expect(safePhotoSrc(undefined)).toBeNull();
  });

  it("reads a Blob into a data: URL and refuses a Blob that is no image", async () => {
    const blob = new Blob([Uint8Array.from([1, 2, 3])], { type: "image/webp" });
    await expect(toPhotoSrc(blob)).resolves.toMatch(
      /^data:image\/webp;base64,/,
    );
    await expect(
      toPhotoSrc(new Blob(["x"], { type: "text/html" })),
    ).resolves.toBeNull();
  });

  it("keeps max - 1 tiles and a '+n' tile for the rest", () => {
    expect(photoSlots(photos(4), 4).more).toBeNull();
    const slots = photoSlots(photos(7), 4);
    expect(slots.shown.map((p) => p.id)).toEqual(["p1", "p2", "p3"]);
    expect(slots.more?.photo.id).toBe("p4");
    expect(slots.more?.count).toBe(4);
  });
});

describe("PhotoStrip and PhotoGrid", () => {
  it("draws nothing without photos", () => {
    const { container } = render(
      <>
        <PhotoStrip photos={[]} locale="sv-SE" onOpen={() => undefined} />
        <PhotoGrid photos={[]} locale="sv-SE" onOpen={() => undefined} />
        <PhotoGrid
          layout="fill"
          photos={[]}
          locale="sv-SE"
          onOpen={() => undefined}
        />
      </>,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("shows at most four tiles, the last '+n', each named and lazy", () => {
    const onOpen = vi.fn();
    const onMore = vi.fn();
    render(
      <PhotoStrip
        photos={photos(6)}
        locale="sv-SE"
        onOpen={onOpen}
        onMore={onMore}
      />,
    );
    const list = screen.getByRole("list", { name: "Foton" });
    expect(list).toHaveClass("sk-photos--64");
    const buttons = within(list).getAllByRole("button");
    expect(buttons).toHaveLength(4);
    expect(screen.getByRole("img", { name: "Bild 1" })).toHaveAttribute(
      "loading",
      "lazy",
    );
    for (const img of list.querySelectorAll("img"))
      expect(img).toHaveAttribute("loading", "lazy");

    const more = screen.getByRole("button", { name: "3 foton till" });
    expect(more).toHaveTextContent("+3");
    fireEvent.click(more);
    expect(onMore).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Bild 2" }));
    expect(onOpen).toHaveBeenCalledWith("p2");
  });

  it("opens the first hidden photo from '+n' when the room gives no onMore, in English too", () => {
    const onOpen = vi.fn();
    render(
      <PhotoStrip
        size={40}
        photos={photos(5)}
        locale="en-GB"
        onOpen={onOpen}
      />,
    );
    expect(screen.getByRole("list", { name: "Photos" })).toHaveClass(
      "sk-photos--40",
    );
    fireEvent.click(screen.getByRole("button", { name: "2 more photos" }));
    expect(onOpen).toHaveBeenCalledWith("p4");
  });

  it("refuses an address that is not a data: image and shows the glyph with the photo's name", () => {
    const { container } = render(
      <PhotoStrip
        photos={[
          {
            id: "a",
            thumb: "https://example.invalid/leak.jpg",
            date: "2026-11-14",
          },
          {
            id: "b",
            thumb: "data:image/svg+xml;base64,PHN2Zy8+",
            alt: "IMG_0001.jpg",
          },
        ]}
        locale="sv-SE"
        onOpen={() => undefined}
      />,
    );
    expect(container.querySelector("img")).toBeNull();
    expect(
      screen.getByRole("img", { name: "Foto 1 från 14 nov" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Foto 2" })).toBeInTheDocument();
    expect(container.innerHTML).not.toContain("example.invalid");
  });

  it("falls back to the glyph when a thumbnail cannot be decoded", () => {
    const { container } = render(
      <PhotoStrip photos={photos(1)} locale="sv-SE" onOpen={() => undefined} />,
    );
    fireEvent.error(container.querySelector("img") as HTMLImageElement);
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByRole("img", { name: "Bild 1" })).toHaveClass(
      "sk-photo__missing",
    );
  });

  it("shows every photo in columns, and two rows of the fill grid with '+n'", () => {
    const { unmount } = render(
      <PhotoGrid photos={photos(9)} locale="sv-SE" onOpen={() => undefined} />,
    );
    expect(screen.getAllByRole("button")).toHaveLength(9);
    unmount();
    // Without layout (jsdom) the fill grid counts four to the row: 2 rows = 8 tiles, the last "+4" of 11.
    render(
      <PhotoGrid
        layout="fill"
        photos={photos(11)}
        locale="sv-SE"
        onOpen={() => undefined}
      />,
    );
    expect(screen.getAllByRole("button")).toHaveLength(8);
    expect(
      screen.getByRole("button", { name: "4 foton till" }),
    ).toBeInTheDocument();
  });
});

function Viewer({
  set,
  load,
  start = "p1",
  actions,
  onClose = () => undefined,
}: {
  set: Photo[];
  load: (id: string) => Promise<PhotoSource>;
  start?: string;
  actions?: PhotoViewerAction[];
  onClose?: () => void;
}) {
  const [current, setCurrent] = useState(start);
  return (
    <PhotoViewer
      photos={set}
      currentId={current}
      onChange={setCurrent}
      onClose={onClose}
      load={load}
      backLabel="Helg i stugan"
      locale="sv-SE"
      actions={actions}
    />
  );
}

describe("PhotoViewer", () => {
  it("fetches only the photo on screen, steps with ← and →, and keeps a fetched photo", async () => {
    const load = vi.fn((id: string) => Promise.resolve(LARGE(id)));
    render(<Viewer set={photos(3)} load={load} />);

    await waitFor(() =>
      expect(screen.getByRole("img", { name: "Bild 1" })).toHaveAttribute(
        "src",
        LARGE("p1"),
      ),
    );
    expect(load.mock.calls.map(([id]) => id)).toEqual(["p1"]);
    expect(screen.getByText("1 av 3 · 14 nov")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Föregående foto" }),
    ).toHaveAttribute("aria-disabled", "true");

    fireEvent.keyDown(window, { key: "ArrowLeft" });
    expect(screen.getByText("1 av 3 · 14 nov")).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(screen.getByText("2 av 3 · 14 nov")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("img", { name: "Bild 2" })).toHaveAttribute(
        "src",
        LARGE("p2"),
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: "Nästa foto" }));
    expect(screen.getByRole("button", { name: "Nästa foto" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    fireEvent.click(screen.getByRole("button", { name: "Nästa foto" }));
    expect(screen.getByText("3 av 3 · 14 nov")).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "ArrowLeft" });
    fireEvent.keyDown(window, { key: "ArrowLeft" });
    // Back on the first photo: drawn at once from what was fetched, no new call.
    expect(screen.getByRole("img", { name: "Bild 1" })).toHaveAttribute(
      "src",
      LARGE("p1"),
    );
    await waitFor(() => expect(load).toHaveBeenCalledTimes(3));
    expect(load.mock.calls.map(([id]) => id)).toEqual(["p1", "p2", "p3"]);
  });

  it("shows the blurred thumbnail while it loads, and the caption under the photo", () => {
    render(
      <Viewer set={photos(2)} load={() => new Promise(() => undefined)} />,
    );
    const preview = screen.getByRole("img", { name: "Bild 1" });
    expect(preview).toHaveAttribute("src", PNG);
    expect(preview).toHaveClass("sk-photo-viewer__img--preview");
    expect(screen.getByRole("status")).toHaveTextContent("Hämtar fotot…");
    expect(
      screen.getByText("Bild 1", { selector: "figcaption" }),
    ).toBeInTheDocument();
    expect(document.activeElement).toHaveClass("sk-photo-viewer__figure");
  });

  it("closes with Esc and with the Back row", () => {
    const onClose = vi.fn();
    render(
      <Viewer
        set={photos(2)}
        load={() => new Promise(() => undefined)}
        onClose={onClose}
      />,
    );
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent.click(
      screen.getByRole("button", { name: "Tillbaka till Helg i stugan" }),
    );
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("offers Försök igen when the fetch fails, and logs no address", async () => {
    const address = "data:image/jpeg;base64,c2VjcmV0";
    const spies = (["log", "info", "warn", "error", "debug"] as const).map(
      (name) => vi.spyOn(console, name).mockImplementation(() => undefined),
    );
    const load = vi
      .fn<(id: string) => Promise<PhotoSource>>()
      .mockRejectedValueOnce(new Error(`could not fetch ${address}`))
      .mockResolvedValueOnce("https://example.invalid/large.jpg")
      .mockResolvedValue(LARGE("p1"));
    render(<Viewer set={photos(2)} load={load} />);

    expect(
      await screen.findByText("Fotot kunde inte hämtas"),
    ).toBeInTheDocument();
    // The thumbnail stays.
    expect(screen.getByRole("img", { name: "Bild 1" })).toHaveAttribute(
      "src",
      PNG,
    );
    fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));
    // An answer that is not a data: image is a failure too, never drawn.
    expect(
      await screen.findByText("Fotot kunde inte hämtas"),
    ).toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain("example.invalid");
    fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));
    await waitFor(() =>
      expect(screen.getByRole("img", { name: "Bild 1" })).toHaveAttribute(
        "src",
        LARGE("p1"),
      ),
    );
    expect(screen.queryByText("Fotot kunde inte hämtas")).toBeNull();

    const logged = spies
      .flatMap((spy) => spy.mock.calls.flat().map(String))
      .join(" ");
    expect(logged).not.toContain("data:");
    expect(logged).not.toContain("example.invalid");
  });

  it("opens ⋯ with the room's entries for the photo on screen; Esc in the menu leaves the viewer open", async () => {
    const chosen = vi.fn();
    const onClose = vi.fn();
    render(
      <Viewer
        set={photos(2)}
        start="p2"
        load={(id) => Promise.resolve(LARGE(id))}
        onClose={onClose}
        actions={[
          { label: "Ändra bildtext", onChoose: chosen },
          { label: "Ta bort foto", onChoose: chosen, danger: true },
        ]}
      />,
    );
    const more = screen.getByRole("button", { name: "Fler val" });
    fireEvent.click(more);
    const remove = screen.getByRole("button", { name: "Ta bort foto" });
    expect(remove).toHaveClass("sk-menu-item--danger");
    act(() => remove.focus());
    fireEvent.keyDown(remove, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Ta bort foto" })).toBeNull();

    fireEvent.click(more);
    fireEvent.click(screen.getByRole("button", { name: "Ändra bildtext" }));
    expect(chosen).toHaveBeenCalledWith(expect.objectContaining({ id: "p2" }));
    await waitFor(() => expect(document.activeElement).toBe(more));
  });

  it("has no ⋯ without entries, and draws a photo without caption by its place", async () => {
    render(
      <Viewer
        set={photos(2, { alt: "" })}
        load={(id) => Promise.resolve(LARGE(id))}
      />,
    );
    expect(screen.queryByRole("button", { name: "Fler val" })).toBeNull();
    await waitFor(() =>
      expect(
        screen.getByRole("img", { name: "Foto 1 från 14 nov" }),
      ).toHaveAttribute("src", LARGE("p1")),
    );
    expect(document.querySelector("figcaption")).toBeNull();
  });
});

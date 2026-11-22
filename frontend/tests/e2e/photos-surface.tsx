import { useState, type ComponentType } from "react";
import { createRoot } from "react-dom/client";

import { Card } from "@/features/mcp-apps/ui/card";
import { OpenLink } from "@/features/mcp-apps/ui/open-link";
import { PhotoViewer } from "@/features/mcp-apps/ui/photo-viewer";
import {
  PhotoGrid,
  PhotoStrip,
  type Photo,
} from "@/features/mcp-apps/ui/photos";
import "@/features/mcp-apps/ui/layout.css";

// A test surface for the photo tiles and the viewer, which no view uses yet: photos-mcp-app.spec.ts builds this file
// (surface-bundle.ts) and loads it into a blank page, so they are measured and photographed in a real Chromium. Not a
// view, not a host: no bridge, no tool call, no request. Every image is drawn on a canvas into a data: URL here, as the
// server's thumbnails arrive in a tool result. The scene comes from data attributes on <html>.

type Scene = "card" | "day" | "entry" | "week" | "viewer";

const settings = document.documentElement.dataset;
const scene = (settings.scene ?? "card") as Scene;
const locale = settings.locale === "en" ? "en-GB" : "sv-SE";
const en = locale.startsWith("en");
const count = Number(settings.count ?? "6");

/** A made-up landscape (sky, sea, a hill, a sun) in its own colours: a data: image, nothing fetched. */
function landscape(seed: number, width: number, height: number): string {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const g = canvas.getContext("2d");
  if (!g) return "";
  const hue = (seed * 47) % 360;
  const sky = g.createLinearGradient(0, 0, 0, height);
  sky.addColorStop(0, `hsl(${hue} 55% 78%)`);
  sky.addColorStop(1, `hsl(${(hue + 30) % 360} 45% 88%)`);
  g.fillStyle = sky;
  g.fillRect(0, 0, width, height);
  g.fillStyle = `hsl(${(hue + 40) % 360} 70% 70%)`;
  g.beginPath();
  g.arc(
    width * (0.25 + (seed % 3) * 0.2),
    height * 0.3,
    height * 0.12,
    0,
    Math.PI * 2,
  );
  g.fill();
  g.fillStyle = `hsl(${(hue + 180) % 360} 35% 42%)`;
  g.fillRect(0, height * 0.62, width, height * 0.38);
  g.fillStyle = `hsl(${(hue + 100) % 360} 30% 30%)`;
  g.beginPath();
  g.ellipse(
    width * 0.7,
    height * 0.66,
    width * 0.45,
    height * 0.22,
    0,
    Math.PI,
    Math.PI * 2,
  );
  g.fill();
  return canvas.toDataURL("image/jpeg", 0.8);
}

const CAPTIONS = en
  ? [
      "The harbour in the morning",
      "",
      "Ring wall by Almedalen",
      "IMG_2041.HEIC",
      "Dinner on the terrace",
    ]
  : [
      "Hamnen i morgonljus",
      "",
      "Ringmuren vid Almedalen",
      "IMG_2041.HEIC",
      "Middag på terrassen",
    ];

function makePhotos(n: number, date = "2026-11-14"): Photo[] {
  return Array.from({ length: n }, (_, i) => {
    const portrait = i % 4 === 2;
    const photo: Photo = {
      id: `p${i + 1}`,
      thumb: landscape(i + 1, 96, 96),
      alt: CAPTIONS[i % CAPTIONS.length],
      date,
      width: portrait ? 960 : 1280,
      height: portrait ? 1280 : 960,
    };
    if (settings.meta === "none") return photo;
    return {
      ...photo,
      taken_at: `${date}T${String(8 + i).padStart(2, "0")}:${i % 2 ? "05" : "30"}:00+01:00`,
      // The third photo has coordinates only (no place name yet), the fourth no location at all.
      location:
        i % 4 === 3
          ? undefined
          : {
              lat: 57.634_81 + i / 1000,
              lon: 18.294_83 - i / 1000,
              name: i % 4 === 2 ? undefined : "Visby",
            },
      camera: i % 2 ? "Pixel 8 Pro" : "iPhone 15",
      orientation: portrait ? 6 : 1,
    };
  });
}

const PHOTOS = makePhotos(count);

function CardScene() {
  const [opened, setOpened] = useState("");
  return (
    <Card
      className="surface-inline"
      eyebrow={en ? "Journal · Saturday 14 Nov" : "Dagbok · lördag 14 nov"}
      title={en ? "Weekend in Visby" : "Helg i Visby"}
    >
      <p className="surface-text">
        {en
          ? "Walked the ring wall at sunrise, coffee by the harbour, then the long way back through the botanical garden before the ferry."
          : "Gick ringmuren i soluppgången, kaffe vid hamnen och sedan den långa vägen tillbaka genom botaniska trädgården före färjan."}
      </p>
      <PhotoStrip photos={PHOTOS} locale={locale} onOpen={setOpened} />
      <output data-testid="opened" hidden>
        {opened}
      </output>
      <OpenLink
        label={en ? "Open the entry" : "Öppna anteckningen"}
        onOpen={() => {}}
      />
    </Card>
  );
}

function DayScene() {
  const [opened, setOpened] = useState("");
  const [all, setAll] = useState(false);
  return (
    <main className="surface-full">
      <h3 className="surface-heading">{en ? "Photos" : "Foton"}</h3>
      <PhotoGrid
        photos={PHOTOS}
        layout="fill"
        locale={locale}
        onOpen={setOpened}
        onMore={() => setAll(true)}
      />
      <output data-testid="opened" hidden>
        {all ? "all" : opened}
      </output>
    </main>
  );
}

function EntryScene() {
  const [opened, setOpened] = useState("");
  return (
    <main className="surface-full">
      <p className="surface-text">
        {en
          ? "Walked the ring wall at sunrise, coffee by the harbour."
          : "Gick ringmuren i soluppgången, kaffe vid hamnen."}
      </p>
      <PhotoGrid
        photos={PHOTOS}
        layout="columns"
        locale={locale}
        onOpen={setOpened}
      />
      <output data-testid="opened" hidden>
        {opened}
      </output>
    </main>
  );
}

const WEEK = en
  ? [
      ["Mon 9 Nov", 2],
      ["Wed 11 Nov", 7],
      ["Sat 14 Nov", 4],
    ]
  : [
      ["mån 9 nov", 2],
      ["ons 11 nov", 7],
      ["lör 14 nov", 4],
    ];

function WeekScene() {
  const [opened, setOpened] = useState("");
  return (
    <main className="surface-full">
      {WEEK.map(([day, n]) => (
        <section key={day} className="surface-day">
          <p className="surface-text">{day}</p>
          <PhotoStrip
            photos={makePhotos(Number(n)).map((photo) => ({
              ...photo,
              id: `${day}-${photo.id}`,
            }))}
            size={40}
            locale={locale}
            onOpen={setOpened}
          />
        </section>
      ))}
      <output data-testid="opened" hidden>
        {opened}
      </output>
    </main>
  );
}

function ViewerScene() {
  const [current, setCurrent] = useState(settings.start ?? "p1");
  const [closed, setClosed] = useState(0);
  const load = (id: string) => {
    if (settings.fail === "true")
      return Promise.reject(new Error("unavailable"));
    if (settings.loading === "true")
      return new Promise<string>(() => undefined);
    const index = Number(id.slice(1)) - 1;
    const photo = PHOTOS[index];
    return Promise.resolve(
      landscape(index + 1, photo?.width ?? 1280, photo?.height ?? 960),
    );
  };
  return (
    <main className="surface-full">
      <PhotoViewer
        photos={PHOTOS}
        currentId={current}
        onChange={setCurrent}
        onClose={() => setClosed((n) => n + 1)}
        load={load}
        backLabel={en ? "Weekend in Visby" : "Helg i Visby"}
        locale={locale}
        actions={[
          { label: en ? "Edit caption" : "Ändra bildtext", onChoose: () => {} },
          {
            label: en ? "Copy caption" : "Kopiera bildtext",
            onChoose: () => {},
          },
          {
            label: en ? "Delete photo" : "Ta bort foto",
            onChoose: () => {},
            danger: true,
          },
        ]}
      />
      <output data-testid="current" hidden>
        {current}
      </output>
      <output data-testid="closed" hidden>
        {closed}
      </output>
    </main>
  );
}

const SCENES: Record<Scene, ComponentType> = {
  card: CardScene,
  day: DayScene,
  entry: EntryScene,
  week: WeekScene,
  viewer: ViewerScene,
};

const Scene = SCENES[scene];
const root = document.getElementById("root");
if (root)
  createRoot(root).render(
    <div className="sidekick-journal">
      <Scene />
    </div>,
  );

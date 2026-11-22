import { useState } from "react";
import { createRoot } from "react-dom/client";

import { Card } from "@/features/mcp-apps/ui/card";
import { FlipCard } from "@/features/mcp-apps/ui/flip-card";
import { OpenLink } from "@/features/mcp-apps/ui/open-link";
import { Progress } from "@/features/mcp-apps/ui/progress";
import { QuestionCard } from "@/features/mcp-apps/ui/question-card";
import { reviewLabelsFor } from "@/features/mcp-apps/ui/review-labels";
import "@/features/mcp-apps/ui/layout.css";

// A test surface for the review cards, which no view uses yet: review-cards-mcp-app.spec.ts builds this file with Vite
// and loads it into a blank page, so the cards are measured and photographed in a real Chromium. Not a view, not a
// host: no bridge, no tool call, no request. The scene comes from data attributes on <html>.

type Scene = "flip" | "flip-loading" | "flip-text" | "question";

const settings = document.documentElement.dataset;
const scene = (settings.scene ?? "flip") as Scene;
const locale = settings.locale === "en" ? "en-GB" : "sv-SE";
const inline = settings.density === "inline";
const en = locale.startsWith("en");
const labels = reviewLabelsFor(locale);

/** A made-up face drawn on a canvas, so the photo is a data: image like the server's and nothing is fetched. */
function portrait(hue: number): string {
  const canvas = document.createElement("canvas");
  canvas.width = 400;
  canvas.height = 400;
  const g = canvas.getContext("2d");
  if (!g) return "";
  g.fillStyle = `hsl(${hue} 30% 72%)`;
  g.fillRect(0, 0, 400, 400);
  g.fillStyle = `hsl(${hue} 25% 38%)`;
  g.beginPath();
  g.ellipse(200, 420, 150, 130, 0, 0, Math.PI * 2);
  g.fill();
  g.fillStyle = "hsl(28 45% 78%)";
  g.beginPath();
  g.ellipse(200, 175, 82, 98, 0, 0, Math.PI * 2);
  g.fill();
  g.fillStyle = `hsl(${hue + 20} 35% 25%)`;
  g.beginPath();
  g.ellipse(200, 110, 90, 52, 0, Math.PI, Math.PI * 2);
  g.fill();
  return canvas.toDataURL("image/png");
}

const LENA = {
  photo: portrait(210),
  title: "Lena Holm",
  meta: en ? "Project manager · Holm Bygg" : "Projektledare · Holm Bygg",
};
const OMAR = {
  photo: portrait(150),
  title: "Omar Said",
  meta: en ? "Electrician · Said El AB" : "Elektriker · Said El AB",
};
const TOTAL = 12;

function FlipScene() {
  const [index, setIndex] = useState(2);
  const [revealed, setRevealed] = useState(settings.revealed === "true");
  const [grades, setGrades] = useState<string[]>([]);
  const person = index % 2 === 0 ? LENA : OMAR;
  const text = scene === "flip-text";
  const next = (grade: string) => {
    setGrades((done) => [...done, grade]);
    setIndex((value) => value + 1);
    setRevealed(false);
  };
  const card = (
    <FlipCard
      locale={locale}
      density={inline ? "inline" : "full"}
      loading={scene === "flip-loading"}
      front={
        text
          ? {
              text: en ? "What does a lux measure?" : "Vad mäter en lux?",
            }
          : {
              photo: {
                src: person.photo,
                alt: en ? "Photo to recognise" : "Foto att känna igen",
              },
              text: en ? "Who is this?" : "Vem är det här?",
            }
      }
      back={
        text
          ? {
              title: en ? "Illuminance" : "Belysningsstyrka",
              meta: en ? "Lumen per square metre" : "Lumen per kvadratmeter",
            }
          : { title: person.title, meta: person.meta }
      }
      revealed={revealed}
      onReveal={() => setRevealed(true)}
      grades={[
        { label: labels.again, onChoose: () => next("again") },
        { label: labels.good, onChoose: () => next("good"), primary: true },
      ]}
    />
  );
  const count = en ? `${index + 1} of ${TOTAL}` : `${index + 1} av ${TOTAL}`;
  return (
    <>
      <output data-testid="grades" hidden>
        {grades.join(",")}
      </output>
      {inline ? (
        <Card
          className="surface-inline"
          eyebrow={`${en ? "Review" : "Repetition"} · ${count}`}
        >
          {card}
          <OpenLink
            label={en ? "Open Home" : "Öppna Start"}
            onOpen={() => {}}
          />
        </Card>
      ) : (
        <main className="surface-full">
          <Progress done={index} total={TOTAL} label={count} layout="bar" />
          {card}
        </main>
      )}
    </>
  );
}

const QUESTION = en
  ? {
      prompt: "What does a lux measure?",
      options: [
        "Luminous flux",
        "Illuminance",
        "Luminous intensity",
        "Luminance",
      ],
      right: 1,
      explain: "A lux is one lumen per square metre.",
    }
  : {
      prompt: "Vad mäter en lux?",
      options: ["Ljusflöde", "Belysningsstyrka", "Ljusstyrka", "Luminans"],
      right: 1,
      explain: "En lux är en lumen per kvadratmeter.",
    };

function QuestionScene() {
  const question = QUESTION;
  const [chosen, setChosen] = useState<number | null>(
    settings.chosen ? Number(settings.chosen) : null,
  );
  const checked = settings.checking !== "true" && chosen !== null;
  const correct = chosen === question.right;
  return (
    <main className="surface-full">
      <QuestionCard
        locale={locale}
        prompt={question.prompt}
        options={question.options}
        onAnswer={setChosen}
        chosen={chosen}
        result={
          checked
            ? {
                correct,
                explain: correct
                  ? question.explain
                  : en
                    ? "Think of what falls on a surface."
                    : "Tänk på det som faller på en yta.",
              }
            : null
        }
        action={{
          label: correct ? labels.question.next : labels.question.retry,
          onClick: () => setChosen(null),
        }}
        unavailable={
          settings.offline === "true"
            ? en
              ? "Needs a connection"
              : "Kräver anslutning"
            : undefined
        }
      />
    </main>
  );
}

const root = document.getElementById("root");
if (root)
  createRoot(root).render(
    scene === "question" ? <QuestionScene /> : <FlipScene />,
  );

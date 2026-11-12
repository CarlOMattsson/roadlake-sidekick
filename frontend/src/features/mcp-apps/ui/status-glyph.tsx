import "./status-glyph.css";

/**
 * Status glyph for tasks, projects and steps (design language section 3.3). The ring says only done or
 * not done: a filled ring with a tick is Klar (or a completed Project), an empty ring is anything else.
 * In progress, blocked and active are told by their text beside the glyph, never by a half fill or a
 * strike (those read as a second state). Colour is only support, so the glyph is drawn with
 * `currentColor`. With `label` the glyph is a labelled image; without it the glyph is hidden from
 * assistive technology. Steps are squares, never rings. Unknown statuses get a dashed outline so a new
 * server value stays visible.
 */
export type StatusGlyphKind = "task" | "project" | "step";

type Shape = "empty" | "check" | "dashed" | "filled";

// The ring is 22 at 24 (was 18: the ring you tap was the smallest thing on the row), with a thinner line.
const RING_RADIUS = 6.5;
// The Step's square is 22 at 24, as the ring, so the check of a Step in its Task and in Status reads as the
// same control as the ring beside it.
const SQUARE_EDGE = 1.25;
const SQUARE_SIZE = 13.5;

function shapeFor(kind: StatusGlyphKind, status: string): Shape {
  if (kind === "project") {
    switch (status) {
      case "active":
        return "empty";
      case "completed":
        return "filled";
      default:
        return "dashed";
    }
  }
  switch (status) {
    case "todo":
      return "empty";
    case "in_progress":
    case "blocked":
      return "empty";
    case "completed":
      return "check";
    default:
      return "dashed";
  }
}

function Frame({
  kind,
  solid,
  dashed,
}: {
  kind: StatusGlyphKind;
  solid: boolean;
  dashed: boolean;
}) {
  const className = [
    "sk-status-glyph__frame",
    solid ? "sk-status-glyph__frame--solid" : "",
    dashed ? "sk-status-glyph__frame--dashed" : "",
  ]
    .filter(Boolean)
    .join(" ");
  if (kind === "step") {
    return (
      <rect
        className={className}
        x={SQUARE_EDGE}
        y={SQUARE_EDGE}
        width={SQUARE_SIZE}
        height={SQUARE_SIZE}
        rx={3}
      />
    );
  }
  return <circle className={className} cx={8} cy={8} r={RING_RADIUS} />;
}

function Mark({ shape }: { shape: Shape }) {
  if (shape === "check") {
    return (
      <path className="sk-status-glyph__check" d="M4.6 8.3L6.9 10.6L11.4 6" />
    );
  }
  return null;
}

export function StatusGlyph({
  kind,
  status,
  label,
}: {
  kind: StatusGlyphKind;
  status: string;
  label?: string;
}) {
  const shape = shapeFor(kind, status);
  const frame = kind === "step" ? "square" : "ring";
  // Filled and check shapes use a solid frame; check draws its tick as a knockout on top.
  const solid = shape === "filled" || shape === "check";
  const dashed = shape === "dashed";
  const accessibility = label
    ? { role: "img" as const, "aria-label": label }
    : { "aria-hidden": true as const };

  return (
    <svg
      className="sk-status-glyph"
      viewBox="0 0 16 16"
      focusable="false"
      data-glyph={`${frame}-${shape}`}
      {...accessibility}
    >
      <Frame kind={kind} solid={solid} dashed={dashed} />
      <Mark shape={shape} />
    </svg>
  );
}

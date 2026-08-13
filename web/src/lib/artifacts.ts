// UI-facing model for session artifacts — the finished work products an agent
// publishes for a human to review (a rendered video, an audio mix, a chart, a
// report).
//
// Artifacts are a separate surface from session *files*: files are attachments
// that get inlined into the model's context, which is why that pipeline is
// capped at images/PDF/text. Artifacts never enter the model's context, so they
// can carry media — and the server decides how each one renders.

/** How the server says an artifact should be rendered. */
export type ArtifactRenderCategory = "image" | "video" | "audio" | "pdf" | "html" | "download";

const RENDER_CATEGORIES: readonly ArtifactRenderCategory[] = [
  "image",
  "video",
  "audio",
  "pdf",
  "html",
  "download",
];

/** A session artifact as the UI consumes it. */
export interface SessionArtifact {
  /** Opaque, stable artifact id — also the content URL's path segment. */
  id: string;
  /** Owning session id, needed to build the content URL. */
  sessionId: string;
  /** Original filename, e.g. ``"final_cut.mp4"``. */
  filename: string;
  /** Human-facing title, when the publisher supplied one. */
  title: string | null;
  /** Human-facing description, when the publisher supplied one. */
  description: string | null;
  /** Resolved MIME type, e.g. ``"video/mp4"``. */
  contentType: string;
  /** Content size in bytes. */
  bytes: number;
  /** Unix epoch seconds when the artifact was published. */
  createdAt: number;
  /**
   * Server-derived renderer selector. Never inferred client-side: the server
   * decides what may render inline, and the content route's
   * `Content-Disposition` follows the same decision.
   */
  renderCategory: ArtifactRenderCategory;
  /** Sibling artifact that previews this one (e.g. a video poster), or null. */
  previewArtifactId: string | null;
}

/** TanStack Query key for a session's artifacts. */
export function artifactsQueryKey(sessionId: string): readonly unknown[] {
  return ["conversation", sessionId, "artifacts"];
}

/** Same-origin content path for an artifact's bytes. */
export function artifactContentPath(sessionId: string, artifactId: string): string {
  return `/v1/sessions/${encodeURIComponent(sessionId)}/resources/artifacts/${encodeURIComponent(
    artifactId,
  )}/content`;
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

/**
 * Convert a wire `session.resource` payload (`type: "session_artifact"`) into
 * the UI record, or `null` when it isn't one.
 *
 * Used for both the REST list and the live `session.resource.created` event, so
 * both sources produce identical records.
 */
export function artifactFromResource(resource: Record<string, unknown>): SessionArtifact | null {
  if (resource.type !== "session_artifact") return null;
  const id = asString(resource.id);
  const sessionId = asString(resource.session_id);
  if (id === null || sessionId === null) return null;

  const raw = resource.metadata;
  const metadata =
    raw && typeof raw === "object" && !Array.isArray(raw) ? (raw as Record<string, unknown>) : {};

  const rawCategory = metadata.render_category;
  // Unknown categories degrade to a download card rather than being dropped:
  // a newer server category should still surface the artifact, just plainly.
  const renderCategory = RENDER_CATEGORIES.includes(rawCategory as ArtifactRenderCategory)
    ? (rawCategory as ArtifactRenderCategory)
    : "download";

  return {
    id,
    sessionId,
    filename: asString(metadata.filename) ?? asString(resource.name) ?? id,
    title: asString(metadata.title),
    description: asString(metadata.description),
    contentType: asString(metadata.content_type) ?? "application/octet-stream",
    bytes: typeof metadata.bytes === "number" ? metadata.bytes : 0,
    createdAt: typeof metadata.created_at === "number" ? metadata.created_at : 0,
    renderCategory,
    previewArtifactId: asString(metadata.preview_artifact_id),
  };
}

/** Newest-first ordering, with the id as a stable tie-break. */
export function compareArtifactsNewestFirst(a: SessionArtifact, b: SessionArtifact): number {
  if (a.createdAt !== b.createdAt) return b.createdAt - a.createdAt;
  return b.id.localeCompare(a.id);
}

const SIZE_UNITS = ["B", "KB", "MB", "GB"] as const;

/** Render a byte count for the artifact card's metadata line. */
export function formatArtifactSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "";
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < SIZE_UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const rounded = unit === 0 ? String(Math.round(value)) : value.toFixed(value < 10 ? 1 : 0);
  return `${rounded} ${SIZE_UNITS[unit]}`;
}

/** Render a media duration (seconds) as `m:ss` / `h:mm:ss`. */
export function formatArtifactDuration(seconds: number): string | null {
  if (!Number.isFinite(seconds) || seconds <= 0) return null;
  const total = Math.round(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return hours > 0 ? `${hours}:${pad(minutes)}:${pad(secs)}` : `${minutes}:${pad(secs)}`;
}

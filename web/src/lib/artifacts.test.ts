// Tests for the session-artifact wire mapping. The renderer a card picks comes
// straight from `renderCategory`, so these pin the server's category through
// the mapping and the degrade-to-download fallback for anything unknown.

import { describe, expect, it } from "vitest";

import {
  artifactContentPath,
  artifactFromResource,
  compareArtifactsNewestFirst,
  formatArtifactDuration,
  formatArtifactSize,
  type SessionArtifact,
} from "./artifacts";

function resource(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: "artifact_1",
    object: "session.resource",
    type: "session_artifact",
    session_id: "conv_1",
    name: "Final cut",
    metadata: {
      filename: "final_cut.mp4",
      content_type: "video/mp4",
      bytes: 2048,
      created_at: 100,
      render_category: "video",
      title: "Final cut",
      description: "The approved edit.",
      preview_artifact_id: "artifact_0",
      ...((overrides.metadata as Record<string, unknown>) ?? {}),
    },
    ...overrides,
  };
}

describe("artifactFromResource", () => {
  it("maps a video artifact with its server-derived category", () => {
    const artifact = artifactFromResource(resource());
    expect(artifact).toEqual({
      id: "artifact_1",
      sessionId: "conv_1",
      filename: "final_cut.mp4",
      title: "Final cut",
      description: "The approved edit.",
      contentType: "video/mp4",
      bytes: 2048,
      createdAt: 100,
      renderCategory: "video",
      previewArtifactId: "artifact_0",
    } satisfies SessionArtifact);
  });

  it("ignores resources that are not artifacts", () => {
    expect(artifactFromResource({ ...resource(), type: "file" })).toBeNull();
    expect(artifactFromResource({ ...resource(), type: "terminal" })).toBeNull();
  });

  it("degrades an unknown category to a download card", () => {
    const artifact = artifactFromResource(resource({ metadata: { render_category: "hologram" } }));
    expect(artifact?.renderCategory).toBe("download");
  });

  it("degrades a missing category to a download card", () => {
    const artifact = artifactFromResource(resource({ metadata: { render_category: undefined } }));
    expect(artifact?.renderCategory).toBe("download");
  });

  it("falls back to the resource name when metadata carries no filename", () => {
    const artifact = artifactFromResource(resource({ metadata: { filename: undefined } }));
    expect(artifact?.filename).toBe("Final cut");
  });

  it("rejects a payload with no session id — the content URL needs it", () => {
    expect(artifactFromResource({ ...resource(), session_id: undefined })).toBeNull();
  });
});

describe("artifactContentPath", () => {
  it("addresses the session-scoped content route", () => {
    expect(artifactContentPath("conv_1", "artifact_1")).toBe(
      "/v1/sessions/conv_1/resources/artifacts/artifact_1/content",
    );
  });

  it("escapes ids so a crafted id cannot alter the path", () => {
    expect(artifactContentPath("conv/1", "a?b")).toBe(
      "/v1/sessions/conv%2F1/resources/artifacts/a%3Fb/content",
    );
  });
});

describe("compareArtifactsNewestFirst", () => {
  it("sorts by creation time, newest first", () => {
    const older = artifactFromResource(resource({ id: "a", metadata: { created_at: 1 } }))!;
    const newer = artifactFromResource(resource({ id: "b", metadata: { created_at: 2 } }))!;
    expect([older, newer].sort(compareArtifactsNewestFirst)).toEqual([newer, older]);
  });
});

describe("formatArtifactSize", () => {
  it("scales to a readable unit", () => {
    expect(formatArtifactSize(512)).toBe("512 B");
    expect(formatArtifactSize(2048)).toBe("2.0 KB");
    expect(formatArtifactSize(5 * 1024 * 1024)).toBe("5.0 MB");
    expect(formatArtifactSize(1536 * 1024 * 1024)).toBe("1.5 GB");
  });
});

describe("formatArtifactDuration", () => {
  it("formats minutes and hours", () => {
    expect(formatArtifactDuration(65)).toBe("1:05");
    expect(formatArtifactDuration(3725)).toBe("1:02:05");
  });

  it("returns null when the duration is unknown", () => {
    expect(formatArtifactDuration(Number.NaN)).toBeNull();
    expect(formatArtifactDuration(0)).toBeNull();
  });
});

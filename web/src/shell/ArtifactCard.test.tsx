// Tests for ArtifactCard — the renderer is selected by the SERVER's
// `renderCategory`, so these pin one case per category plus the embedded-host
// fallback where a direct media URL can't carry the host's auth.

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const getOmnigentHostConfig = vi.fn();

vi.mock("@/lib/host", () => ({
  getOmnigentHostConfig: () => getOmnigentHostConfig(),
}));

// SessionImage owns its own load/caching behaviour and is tested separately; a
// marker keeps the image-category assertion about renderer selection.
vi.mock("@/components/SessionImage", () => ({
  SessionImage: ({ path }: { path?: string }) => <img data-testid="session-image" src={path} />,
}));

import { ArtifactCard } from "./ArtifactCard";
import type { ArtifactRenderCategory, SessionArtifact } from "@/lib/artifacts";

function artifact(overrides: Partial<SessionArtifact> = {}): SessionArtifact {
  return {
    id: "artifact_1",
    sessionId: "conv_1",
    filename: "final_cut.mp4",
    title: "Final cut",
    description: null,
    contentType: "video/mp4",
    bytes: 2048,
    createdAt: 100,
    renderCategory: "video",
    previewArtifactId: null,
    ...overrides,
  };
}

beforeEach(() => {
  getOmnigentHostConfig.mockReturnValue({});
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("renderer selection", () => {
  it("mounts a seekable, inline video player for the video category", () => {
    render(<ArtifactCard artifact={artifact()} />);

    const video = screen.getByTestId("artifact-video");
    expect(video).toHaveAttribute(
      "src",
      "/v1/sessions/conv_1/resources/artifacts/artifact_1/content",
    );
    expect(video).toHaveAttribute("controls");
    // iOS Safari hijacks playback into its own fullscreen player without this.
    expect(video).toHaveAttribute("playsInline");
    expect(video).toHaveAttribute("preload", "metadata");
  });

  it("uses the preview artifact as the video poster", () => {
    render(<ArtifactCard artifact={artifact({ previewArtifactId: "artifact_0" })} />);

    expect(screen.getByTestId("artifact-video")).toHaveAttribute(
      "poster",
      "/v1/sessions/conv_1/resources/artifacts/artifact_0/content",
    );
  });

  it("mounts an audio player for the audio category", () => {
    render(
      <ArtifactCard
        artifact={artifact({
          renderCategory: "audio",
          filename: "mix.mp3",
          contentType: "audio/mpeg",
        })}
      />,
    );

    expect(screen.getByTestId("artifact-audio")).toHaveAttribute("controls");
    expect(screen.queryByTestId("artifact-video")).toBeNull();
  });

  it("renders images through SessionImage", () => {
    render(
      <ArtifactCard
        artifact={artifact({
          renderCategory: "image",
          filename: "chart.png",
          contentType: "image/png",
        })}
      />,
    );

    expect(screen.getByTestId("session-image")).toHaveAttribute(
      "src",
      "/v1/sessions/conv_1/resources/artifacts/artifact_1/content",
    );
  });

  it.each<[ArtifactRenderCategory, string]>([
    ["pdf", "report.pdf"],
    ["html", "report.html"],
    ["download", "mystery.bin"],
  ])("renders %s as a metadata card with a download action", (renderCategory, filename) => {
    render(<ArtifactCard artifact={artifact({ renderCategory, filename, title: null })} />);

    expect(screen.queryByTestId("artifact-video")).toBeNull();
    expect(screen.queryByTestId("artifact-audio")).toBeNull();
    expect(screen.queryByTestId("session-image")).toBeNull();
    expect(screen.getByTestId("artifact-download")).toHaveAttribute("download", filename);
  });
});

describe("embedded host", () => {
  it("falls back to download-only for video when a host fetcher owns auth", () => {
    getOmnigentHostConfig.mockReturnValue({ fetcher: vi.fn() });

    render(<ArtifactCard artifact={artifact()} />);

    // A bare <video src> GET cannot carry the host's CSRF header, so mounting
    // the player would only ever show a broken element.
    expect(screen.queryByTestId("artifact-video")).toBeNull();
    expect(screen.queryByTestId("artifact-fullscreen")).toBeNull();
    expect(screen.getByTestId("artifact-download")).toBeInTheDocument();
  });

  it("falls back to download-only for audio when a host fetcher owns auth", () => {
    getOmnigentHostConfig.mockReturnValue({ fetcher: vi.fn() });

    render(<ArtifactCard artifact={artifact({ renderCategory: "audio" })} />);

    expect(screen.queryByTestId("artifact-audio")).toBeNull();
    expect(screen.getByTestId("artifact-download")).toBeInTheDocument();
  });
});

describe("metadata line", () => {
  it("shows the file size before the browser has read the container", () => {
    render(<ArtifactCard artifact={artifact({ bytes: 5 * 1024 * 1024 })} />);
    expect(screen.getByTestId("artifact-meta")).toHaveTextContent("5.0 MB");
  });

  it("shows the filename under the title when both are present", () => {
    render(<ArtifactCard artifact={artifact()} />);
    expect(screen.getByText("Final cut")).toBeInTheDocument();
    expect(screen.getByText("final_cut.mp4")).toBeInTheDocument();
  });

  it("offers a fullscreen action for directly-streamable media", () => {
    render(<ArtifactCard artifact={artifact()} />);
    expect(screen.getByTestId("artifact-fullscreen")).toBeInTheDocument();
  });
});

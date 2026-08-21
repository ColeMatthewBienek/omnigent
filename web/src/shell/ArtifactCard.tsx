// One published artifact, rendered by the category the SERVER assigned it.
//
// The renderer is never chosen from the filename or a client-side MIME guess:
// `renderCategory` comes from the server, which also decides whether the
// content route serves the bytes `inline` or forces a download. Picking the
// renderer here from anything else would let the two disagree — a card that
// mounts a <video> against a response the server marked `attachment`.
//
// Media plays from a direct same-origin URL rather than a fetched blob so the
// browser can range-request and seek (which is what makes scrubbing work at
// all in iOS Safari). That only holds when web talks to the API directly:
// embedded, the host proxies the API behind a path prefix and CSRF auth a bare
// <video src> can't satisfy, so those categories fall back to a download card.

import { useState } from "react";
import {
  DownloadIcon,
  FileIcon,
  FileTextIcon,
  MaximizeIcon,
  MusicIcon,
  VideoIcon,
} from "lucide-react";

import { SessionImage } from "@/components/SessionImage";
import { Button } from "@/components/ui/button";
import { getOmnigentHostConfig } from "@/lib/host";
import {
  artifactContentPath,
  formatArtifactDuration,
  formatArtifactSize,
  type SessionArtifact,
} from "@/lib/artifacts";
import { cn } from "@/lib/utils";

interface ArtifactCardProps {
  artifact: SessionArtifact;
}

/** Media facts the browser only knows once it has read the container header. */
interface MediaFacts {
  duration: number | null;
  width: number | null;
  height: number | null;
}

const CATEGORY_ICON = {
  image: FileIcon,
  video: VideoIcon,
  audio: MusicIcon,
  pdf: FileTextIcon,
  html: FileTextIcon,
  download: FileIcon,
} as const;

/**
 * Whether media can be addressed by a direct URL the browser loads itself.
 *
 * False when a host fetcher is installed: the host owns API auth, and a
 * `<video src>` GET can't carry it.
 */
function canStreamDirectly(): boolean {
  return !getOmnigentHostConfig().fetcher;
}

export function ArtifactCard({ artifact }: ArtifactCardProps) {
  const [facts, setFacts] = useState<MediaFacts>({ duration: null, width: null, height: null });
  const src = artifactContentPath(artifact.sessionId, artifact.id);
  const poster = artifact.previewArtifactId
    ? artifactContentPath(artifact.sessionId, artifact.previewArtifactId)
    : undefined;
  const streamable = canStreamDirectly();
  const Icon = CATEGORY_ICON[artifact.renderCategory];

  return (
    <li
      data-testid="artifact-card"
      data-artifact-id={artifact.id}
      data-render-category={artifact.renderCategory}
      className="flex flex-col gap-2 rounded-md border border-border bg-card p-3"
    >
      {artifact.renderCategory === "video" && streamable && (
        <video
          data-testid="artifact-video"
          className="max-h-80 w-full rounded bg-black"
          src={src}
          poster={poster}
          controls
          // iOS Safari fullscreens any inline <video> on play without this.
          playsInline
          // Fetch the container header only: an artifacts list can hold several
          // large renders, and the user has not asked to watch any of them yet.
          preload="metadata"
          onLoadedMetadata={(event) => {
            const el = event.currentTarget;
            setFacts({
              duration: Number.isFinite(el.duration) ? el.duration : null,
              width: el.videoWidth || null,
              height: el.videoHeight || null,
            });
          }}
        />
      )}

      {artifact.renderCategory === "audio" && streamable && (
        <audio
          data-testid="artifact-audio"
          className="w-full"
          src={src}
          controls
          preload="metadata"
          onLoadedMetadata={(event) => {
            const el = event.currentTarget;
            setFacts((prev) => ({
              ...prev,
              duration: Number.isFinite(el.duration) ? el.duration : null,
            }));
          }}
        />
      )}

      {artifact.renderCategory === "image" && (
        <SessionImage path={src} alt={artifact.title ?? artifact.filename} />
      )}

      <div className="flex min-w-0 items-start gap-2">
        <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-ui font-medium" title={artifact.title ?? artifact.filename}>
            {artifact.title ?? artifact.filename}
          </p>
          {artifact.title && (
            <p className="truncate text-xs text-muted-foreground" title={artifact.filename}>
              {artifact.filename}
            </p>
          )}
          {artifact.description && (
            <p className="mt-1 text-xs text-muted-foreground">{artifact.description}</p>
          )}
          <p data-testid="artifact-meta" className="mt-1 text-xs text-muted-foreground">
            {[
              formatArtifactSize(artifact.bytes),
              facts.duration !== null ? formatArtifactDuration(facts.duration) : null,
              facts.width && facts.height ? `${facts.width}×${facts.height}` : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {(artifact.renderCategory === "video" || artifact.renderCategory === "audio") &&
            streamable && (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label="Open full screen"
                data-testid="artifact-fullscreen"
                onClick={() => window.open(src, "_blank", "noopener,noreferrer")}
              >
                <MaximizeIcon className="size-4" />
              </Button>
            )}
          <a
            data-testid="artifact-download"
            href={src}
            download={artifact.filename}
            aria-label={`Download ${artifact.filename}`}
            className={cn(
              "inline-flex size-8 items-center justify-center rounded-md",
              "text-muted-foreground hover:bg-accent hover:text-foreground",
            )}
          >
            <DownloadIcon className="size-4" />
          </a>
        </div>
      </div>
    </li>
  );
}

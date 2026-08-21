// Body of the Artifacts surface: the session's published artifacts, newest
// first. Rendered inside `ArtifactsPanelDrawer` (desktop right rail and mobile
// full-screen drawer alike), so it owns no chrome of its own beyond the header
// the drawer asks for.

import { XIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { useSessionArtifacts } from "@/hooks/useSessionArtifacts";
import { ArtifactCard } from "./ArtifactCard";

interface ArtifactsPanelProps {
  conversationId: string;
  /** Dismiss handler for the panel header's close button. */
  onClose?: () => void;
}

export function ArtifactsPanel({ conversationId, onClose }: ArtifactsPanelProps) {
  const { artifacts, isLoading, error } = useSessionArtifacts(conversationId);

  return (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="artifacts-panel">
      <div className="flex shrink-0 items-center justify-between border-b border-border px-3 py-2">
        <h2 className="text-ui font-medium">Artifacts</h2>
        {onClose && (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="Close artifacts"
            onClick={onClose}
          >
            <XIcon className="size-4" />
          </Button>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {isLoading && (
          <div role="status" aria-label="Loading artifacts" className="flex justify-center py-6">
            <Spinner />
          </div>
        )}
        {!isLoading && error && (
          <p className="text-ui text-muted-foreground">Couldn’t load artifacts.</p>
        )}
        {!isLoading && !error && artifacts.length === 0 && (
          <p className="text-ui text-muted-foreground">
            Nothing published yet. Artifacts the agent publishes for review show up here.
          </p>
        )}
        {artifacts.length > 0 && (
          <ul className="flex flex-col gap-3">
            {artifacts.map((artifact) => (
              <ArtifactCard key={artifact.id} artifact={artifact} />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

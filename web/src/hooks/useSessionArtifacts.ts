import { useQuery, useQueryClient } from "@tanstack/react-query";

import { authenticatedFetch } from "@/lib/identity";
import {
  artifactFromResource,
  artifactsQueryKey,
  compareArtifactsNewestFirst,
  type SessionArtifact,
} from "@/lib/artifacts";

/**
 * Fetch a session's published artifacts, newest first.
 *
 * :param sessionId: Session/conversation identifier.
 * :returns: The session's artifacts.
 * :raises Error: When the server rejects the read.
 */
export async function fetchSessionArtifacts(sessionId: string): Promise<SessionArtifact[]> {
  const res = await authenticatedFetch(
    `/v1/sessions/${encodeURIComponent(sessionId)}/resources/artifacts`,
  );
  if (!res.ok) throw new Error(`artifacts list failed: ${res.status} ${res.statusText}`);
  const body = (await res.json()) as { data?: Record<string, unknown>[] };
  return (body.data ?? [])
    .map(artifactFromResource)
    .filter((a): a is SessionArtifact => a !== null)
    .sort(compareArtifactsNewestFirst);
}

/**
 * Live artifacts for a conversation.
 *
 * Two sources feed one query cache, exactly as the terminals list does: an
 * authoritative HTTP seed on mount, and live `session.resource.created`
 * deltas the chatStore patches in via `setQueryData`. The seed unions with
 * whatever the stream already wrote so an event that raced the fetch is not
 * dropped.
 *
 * :param sessionId: Session/conversation identifier, or ``null``.
 * :returns: The artifact list plus its loading/error state.
 */
export function useSessionArtifacts(sessionId: string | null) {
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey:
      sessionId === null ? ["conversation", null, "artifacts"] : artifactsQueryKey(sessionId),
    queryFn: async () => {
      const key = artifactsQueryKey(sessionId!);
      const fetched = await fetchSessionArtifacts(sessionId!);
      const byId = new Map<string, SessionArtifact>();
      for (const a of queryClient.getQueryData<SessionArtifact[]>(key) ?? []) byId.set(a.id, a);
      // Fetched rows win on id collision — they are the fresher snapshot.
      for (const a of fetched) byId.set(a.id, a);
      return [...byId.values()].sort(compareArtifactsNewestFirst);
    },
    enabled: sessionId !== null,
    // Artifacts are immutable once published, so the cache only ever grows —
    // by an SSE delta. Refetching would just risk clobbering one.
    staleTime: Infinity,
  });

  return {
    artifacts: data ?? [],
    isLoading: sessionId !== null && isLoading,
    error: error as Error | null,
  };
}

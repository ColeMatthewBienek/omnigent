"""Session artifact entity."""

from dataclasses import dataclass


@dataclass
class SessionArtifact:
    """
    An agent-published, session-scoped artifact.

    Artifacts are finished work products an agent hands to a human for
    review in the session UI (a rendered video, an audio mix, a chart,
    a report). They are deliberately separate from session *files*:
    files are attachments that get inlined into the model's context, so
    that pipeline is capped at images / PDF / text. Artifacts never
    enter the model context, which is what lets them carry media.

    Binary content lives in the :class:`~omnigent.stores.artifact_store.ArtifactStore`
    keyed by :attr:`id`; this record is the metadata.

    :param id: Unique artifact identifier (bare 32-char hex uuid).
    :param session_id: Owning session/conversation id.
    :param filename: Original filename, e.g. ``"final_cut.mp4"``.
    :param content_type: Resolved MIME type, e.g. ``"video/mp4"``.
    :param bytes: Content size in bytes.
    :param created_at: Unix epoch seconds when the artifact was published.
    :param title: Optional human-facing title.
    :param description: Optional human-facing description.
    :param preview_artifact_id: Optional id of another artifact in the
        same session that previews this one, e.g. a poster image for a
        video. ``None`` when there is no preview.
    """

    id: str
    session_id: str
    filename: str
    content_type: str
    bytes: int
    created_at: int
    title: str | None = None
    description: str | None = None
    preview_artifact_id: str | None = None

    @property
    def render_category(self) -> str:
        """
        How a client should render this artifact.

        Derived server-side from :attr:`content_type` rather than
        stored, so the mapping can never disagree with the bytes'
        declared type and never depends on a client's own sniffing.

        :returns: One of the
            :data:`~omnigent.runtime.session_artifacts.RENDER_CATEGORIES`
            values.
        """
        from omnigent.runtime.session_artifacts import render_category_for_content_type

        return render_category_for_content_type(self.content_type)

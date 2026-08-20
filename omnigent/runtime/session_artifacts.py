"""Publication policy for session artifacts.

Artifacts are agent-published work products a human reviews in the
session UI. They never enter the model's context, so — unlike
attachments (see :mod:`omnigent.runtime.content_resolver`) — they may
carry media. This module owns the two decisions that keeps safe:

* which MIME types may be published at all, and how large each may be;
* which *render category* a stored type maps to, and — separately —
  which types the content route may serve inline.

Both are server-side only. A client never supplies a render category and
never picks its own limit.
"""

from __future__ import annotations

from omnigent.runtime.content_resolver import (
    MAX_IMAGE_UPLOAD_BYTES,
    MAX_PDF_UPLOAD_BYTES,
    _resolve_content_type,
)

# Video/audio artifacts are whole renders (a cut of a film, a mixed
# track), not context material, so they get a cap sized for real media
# rather than the attachment budget. Operators can lower or raise it —
# see :func:`omnigent.server.server_config.artifact_media_bytes_limit`.
MAX_MEDIA_ARTIFACT_BYTES: int = 512 * 1024 * 1024

# HTML artifacts are documents (a report, a chart page). They are served
# as a download in PR1 and will render inside a sandboxed frame later, so
# a media-sized cap would buy nothing but memory pressure.
MAX_HTML_ARTIFACT_BYTES: int = 5 * 1024 * 1024

# How a client should render an artifact. ``download`` is the fallback:
# anything not positively recognised is offered as a file, never inline.
RENDER_CATEGORIES: frozenset[str] = frozenset(
    {"image", "video", "audio", "pdf", "html", "download"}
)

_VIDEO_TYPES: frozenset[str] = frozenset({"video/mp4", "video/quicktime", "video/webm"})

_AUDIO_TYPES: frozenset[str] = frozenset({"audio/mpeg", "audio/mp4", "audio/wav", "audio/ogg"})

# Raster image types that carry no scripting. ``image/svg+xml`` is
# deliberately absent: an SVG is an XML document that can carry
# ``<script>``, and it executes when the browser navigates to it, so
# serving one inline is stored XSS in the server's own origin exactly as
# HTML would be. ``nosniff`` does not help — the type is honest.
_INLINE_IMAGE_TYPES: frozenset[str] = frozenset(
    {"image/png", "image/jpeg", "image/gif", "image/webp", "image/avif"}
)

# Types whose bytes may be served with ``Content-Disposition: inline``.
# The list is positive and explicit: a type renders in place only if it is
# named here. Everything else — SVG, HTML, exotic image formats, anything
# unrecognised — is served as an attachment.
INLINE_SERVABLE_TYPES: frozenset[str] = (
    _INLINE_IMAGE_TYPES | _VIDEO_TYPES | _AUDIO_TYPES | frozenset({"application/pdf"})
)

# Equivalent spellings the platform ``mimetypes`` table (or a client) may
# emit for an allowed type — e.g. Python maps ``.wav`` to ``audio/x-wav``.
# Normalising here keeps the allowlist a single canonical set.
_TYPE_ALIASES: dict[str, str] = {
    "audio/x-wav": "audio/wav",
    "audio/wave": "audio/wav",
    "audio/vnd.wave": "audio/wav",
    "audio/x-m4a": "audio/mp4",
    "audio/mp3": "audio/mpeg",
    "audio/x-mpeg": "audio/mpeg",
    "video/x-quicktime": "video/quicktime",
    "image/jpg": "image/jpeg",
}


def resolve_artifact_content_type(declared: str | None, filename: str | None) -> str:
    """
    Resolve the canonical MIME type for an artifact being published.

    Reuses the attachment resolver (declared type → filename extension →
    fallback), then folds equivalent spellings onto the canonical one so
    the allowlist below compares a single form.

    :param declared: The uploader-declared content type, or ``None``.
    :param filename: The original filename, e.g. ``"final_cut.mp4"``.
    :returns: A bare, lowercase MIME type.
    """
    resolved = _resolve_content_type(declared, filename)
    return _TYPE_ALIASES.get(resolved, resolved)


def render_category_for_content_type(content_type: str) -> str:
    """
    Map a MIME type to the category a client should render it as.

    :param content_type: A canonical MIME type, e.g. ``"video/mp4"``.
        Run it through :func:`resolve_artifact_content_type` first.
    :returns: One of :data:`RENDER_CATEGORIES`.
    """
    normalized = _TYPE_ALIASES.get(content_type, content_type)
    if normalized.startswith("image/"):
        return "image"
    if normalized in _VIDEO_TYPES:
        return "video"
    if normalized in _AUDIO_TYPES:
        return "audio"
    if normalized == "application/pdf":
        return "pdf"
    if normalized == "text/html":
        return "html"
    return "download"


def is_inline_servable(content_type: str) -> bool:
    """
    Whether *content_type* may be served ``Content-Disposition: inline``.

    Decided from the stored MIME type against an explicit allowlist
    (:data:`INLINE_SERVABLE_TYPES`) rather than from the render category:
    the ``image`` category covers ``image/svg+xml``, which is an active
    document and must download rather than render on the server's origin.

    :param content_type: A canonical MIME type, e.g. ``"video/mp4"``.
    :returns: ``True`` when the bytes may render in place.
    """
    normalized = _TYPE_ALIASES.get(content_type, content_type)
    return normalized in INLINE_SERVABLE_TYPES


def artifact_upload_limit(content_type: str) -> int | None:
    """
    Max publishable size (bytes) for *content_type*, or ``None`` if the
    type may not be published at all.

    The allowlist is positive: a type is publishable only if it maps to a
    renderable category. Everything else — archives, office documents,
    executables, plain text — returns ``None`` and is rejected with HTTP
    415, so the artifact surface can't become a general file drop.

    :param content_type: A canonical MIME type, e.g. ``"video/mp4"``.
    :returns: The per-type byte cap, or ``None`` when not publishable.
    """
    category = render_category_for_content_type(content_type)
    if category == "image":
        return MAX_IMAGE_UPLOAD_BYTES
    if category in ("video", "audio"):
        return MAX_MEDIA_ARTIFACT_BYTES
    if category == "pdf":
        return MAX_PDF_UPLOAD_BYTES
    if category == "html":
        return MAX_HTML_ARTIFACT_BYTES
    return None

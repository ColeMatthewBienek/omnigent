"""Tests for the session-artifact MIME allowlist and render-category mapping."""

from __future__ import annotations

import pytest

from omnigent.entities import SessionArtifact
from omnigent.runtime.session_artifacts import (
    MAX_HTML_ARTIFACT_BYTES,
    MAX_MEDIA_ARTIFACT_BYTES,
    RENDER_CATEGORIES,
    artifact_upload_limit,
    is_inline_servable,
    render_category_for_content_type,
    resolve_artifact_content_type,
)


@pytest.mark.parametrize(
    ("content_type", "expected"),
    [
        ("image/png", "image"),
        ("image/jpeg", "image"),
        ("video/mp4", "video"),
        ("video/quicktime", "video"),
        ("video/webm", "video"),
        ("audio/mpeg", "audio"),
        ("audio/mp4", "audio"),
        ("audio/wav", "audio"),
        ("audio/ogg", "audio"),
        ("application/pdf", "pdf"),
        ("text/html", "html"),
        ("application/octet-stream", "download"),
        ("application/zip", "download"),
    ],
)
def test_render_category_for_content_type(content_type: str, expected: str) -> None:
    """Each allowed MIME maps to its documented render category."""
    assert render_category_for_content_type(content_type) == expected
    assert expected in RENDER_CATEGORIES


def test_render_category_falls_back_to_download() -> None:
    """An unknown type renders as a plain download card, never inline."""
    assert render_category_for_content_type("application/x-made-up") == "download"


@pytest.mark.parametrize(
    "content_type",
    [
        "video/mp4",
        "video/quicktime",
        "video/webm",
        "audio/mpeg",
        "audio/mp4",
        "audio/wav",
        "audio/ogg",
    ],
)
def test_media_types_get_the_media_cap(content_type: str) -> None:
    """Video/audio artifacts are allowed up to the large media cap."""
    assert artifact_upload_limit(content_type) == MAX_MEDIA_ARTIFACT_BYTES


def test_image_and_pdf_reuse_the_attachment_caps() -> None:
    """Image/PDF artifacts keep the existing attachment limits."""
    from omnigent.runtime.content_resolver import (
        MAX_IMAGE_UPLOAD_BYTES,
        MAX_PDF_UPLOAD_BYTES,
    )

    assert artifact_upload_limit("image/png") == MAX_IMAGE_UPLOAD_BYTES
    assert artifact_upload_limit("application/pdf") == MAX_PDF_UPLOAD_BYTES


def test_html_gets_the_small_html_cap() -> None:
    """HTML artifacts are capped small — they are documents, not media."""
    assert artifact_upload_limit("text/html") == MAX_HTML_ARTIFACT_BYTES


@pytest.mark.parametrize(
    "content_type",
    ["application/zip", "text/plain", "application/octet-stream", "video/x-msvideo"],
)
def test_types_outside_the_allowlist_are_rejected(content_type: str) -> None:
    """Anything off the allowlist returns ``None`` so callers can 415 it."""
    assert artifact_upload_limit(content_type) is None


def test_resolve_artifact_content_type_prefers_filename_for_media() -> None:
    """A generic declared type is resolved from the filename extension."""
    assert resolve_artifact_content_type("application/octet-stream", "clip.mp4") == "video/mp4"
    assert resolve_artifact_content_type(None, "voice.m4a") == "audio/mp4"
    assert resolve_artifact_content_type(None, "song.wav") == "audio/wav"


def test_resolve_artifact_content_type_strips_parameters() -> None:
    """MIME parameters are dropped so the allowlist compares bare types."""
    assert resolve_artifact_content_type("video/mp4; codecs=avc1", "clip.mp4") == "video/mp4"


def test_entity_render_category_is_derived_from_content_type() -> None:
    """``SessionArtifact.render_category`` is computed, never client-supplied."""
    artifact = SessionArtifact(
        id="a" * 32,
        session_id="b" * 32,
        filename="final.mp4",
        content_type="video/mp4",
        bytes=10,
        created_at=1,
    )
    assert artifact.render_category == "video"


@pytest.mark.parametrize(
    "content_type",
    [
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "image/avif",
        "video/mp4",
        "video/webm",
        "audio/mpeg",
        "application/pdf",
    ],
)
def test_passive_types_may_render_inline(content_type: str) -> None:
    """Raster images, video, audio, and PDF are safe to serve in place."""
    assert is_inline_servable(content_type) is True


@pytest.mark.parametrize(
    "content_type",
    [
        "image/svg+xml",
        "text/html",
        "image/x-icon",
        "image/tiff",
        "application/octet-stream",
        "application/x-made-up",
    ],
)
def test_active_and_unrecognised_types_are_never_inline(content_type: str) -> None:
    """Anything that can script — or that we don't recognise — downloads.

    ``image/svg+xml`` is the trap: it maps to the ``image`` render
    category, so keying disposition off the category alone would serve a
    script-bearing SVG inline on the server's own origin.
    """
    assert is_inline_servable(content_type) is False


def test_svg_is_an_image_category_but_not_inline_servable() -> None:
    """The two decisions are separate, and only one of them gates bytes."""
    assert render_category_for_content_type("image/svg+xml") == "image"
    assert is_inline_servable("image/svg+xml") is False


def test_inline_decision_folds_type_aliases() -> None:
    """An alias spelling resolves to the canonical type's inline verdict."""
    assert is_inline_servable("image/jpg") is True
    assert is_inline_servable("audio/x-wav") is True

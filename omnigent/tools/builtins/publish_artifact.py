"""Publish artifact built-in tool.

Takes a relative path in the workspace, validates it stays within
bounds, checks the type and size against the artifact publication
policy, stores the bytes + metadata, and announces the artifact on the
session stream so the UI shows it without a refresh.

Distinct from ``upload_file`` on purpose: uploads become model
attachments (images / PDF / text only), while artifacts are finished
work a human reviews and may be video, audio, or any other renderable
media.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from omnigent.tools.base import Tool, ToolContext
from omnigent.tools.builtins._arguments import parse_json_object_arguments
from omnigent.tools.builtins.upload_file import safe_resolve

_DESCRIPTION = (
    "Publish a finished file from the workspace as a session artifact so the "
    "user can review it in the session UI. Use this for deliverables the user "
    "should watch, listen to, or read — rendered video (mp4/mov/webm), audio "
    "(mp3/m4a/wav/ogg), images, PDF, or HTML. Returns the artifact id."
)

_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "publish_artifact",
        "description": _DESCRIPTION,
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Relative path to the file within the workspace, "
                        "e.g. 'renders/final_cut.mp4'."
                    ),
                },
                "title": {
                    "type": "string",
                    "description": "Short human-facing title for the artifact.",
                },
                "description": {
                    "type": "string",
                    "description": "What the artifact is, for the reviewer.",
                },
                "preview_path": {
                    "type": "string",
                    "description": (
                        "Optional relative path to a preview image published "
                        "alongside the artifact, e.g. a poster frame for a "
                        "video ('renders/poster.png')."
                    ),
                },
            },
            "required": ["path"],
        },
    },
}


class PublishArtifactTool(Tool):
    """
    Publish a workspace file as a session artifact.

    Reads the file, stores it via the runtime's session-artifact and
    blob store globals, emits a ``session.resource.created`` event, and
    returns a JSON result with the artifact id and its metadata.
    """

    @classmethod
    def name(cls) -> str:
        """
        Tool name for dispatch and schema registration.

        :returns: ``"publish_artifact"``.
        """
        return "publish_artifact"

    @classmethod
    def description(cls) -> str:
        """
        :returns: Human-readable description of the tool.
        """
        return _DESCRIPTION

    def get_schema(self) -> dict[str, Any]:
        """
        Return the OpenAI function schema.

        :returns: The schema dict.
        """
        return _SCHEMA

    def invoke(self, arguments: str, ctx: ToolContext) -> str:
        """
        Publish a workspace file as a session artifact.

        :param arguments: JSON with ``"path"`` and optional ``"title"``,
            ``"description"``, and ``"preview_path"`` keys.
        :param ctx: Execution context with ``workspace`` and
            ``conversation_id``.
        :returns: JSON string with the artifact id and metadata, or an
            ``"Error: …"`` string the model can act on.
        """
        parsed, error = parse_json_object_arguments(arguments)
        if error is not None:
            return f"Error: {error}"
        assert parsed is not None

        rel_path = parsed.get("path", "")
        if not isinstance(rel_path, str) or not rel_path:
            return "Error: path must be a non-empty string"
        if ctx.workspace is None:
            return "Error: no workspace available"
        if ctx.conversation_id is None:
            return "Error: publish_artifact requires a session id"

        preview_rel = parsed.get("preview_path")
        if preview_rel is not None and not isinstance(preview_rel, str):
            return "Error: preview_path must be a string"

        try:
            resolved = _resolve_publishable(rel_path, ctx.workspace)
            preview_resolved = (
                _resolve_publishable(preview_rel, ctx.workspace) if preview_rel else None
            )
        except ValueError as exc:
            return f"Error: {exc}"

        preview_artifact_id: str | None = None
        if preview_resolved is not None:
            # The preview is an artifact in its own right — it needs an id
            # before the artifact that references it can be created.
            published_preview = _publish(
                preview_resolved,
                session_id=ctx.conversation_id,
                title=None,
                description=None,
                preview_artifact_id=None,
            )
            if isinstance(published_preview, str):
                return published_preview
            preview_artifact_id = published_preview["artifact_id"]

        published = _publish(
            resolved,
            session_id=ctx.conversation_id,
            title=_optional_str(parsed.get("title")),
            description=_optional_str(parsed.get("description")),
            preview_artifact_id=preview_artifact_id,
        )
        if isinstance(published, str):
            return published
        return json.dumps(published)


def _optional_str(value: Any) -> str | None:
    """
    Coerce a tool argument to a non-empty string, or ``None``.

    :param value: The raw argument value.
    :returns: The trimmed string, or ``None`` when absent/blank.
    """
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _resolve_publishable(rel_path: str, workspace: Path) -> Path:
    """
    Resolve a workspace-relative path that must name an existing file.

    :param rel_path: Relative path from the model.
    :param workspace: The workspace root directory.
    :returns: The resolved absolute path.
    :raises ValueError: If the path escapes the workspace or is not a file.
    """
    resolved = safe_resolve(rel_path, workspace)
    if not resolved.is_file():
        raise ValueError(f"file not found: {rel_path}")
    return resolved


def _publish(
    resolved: Path,
    *,
    session_id: str,
    title: str | None,
    description: str | None,
    preview_artifact_id: str | None,
) -> dict[str, Any] | str:
    """
    Store one file as a session artifact and announce it.

    :param resolved: Absolute path to the file.
    :param session_id: Owning conversation/session id.
    :param title: Optional human-facing title.
    :param description: Optional human-facing description.
    :param preview_artifact_id: Optional previewing sibling artifact.
    :returns: The artifact metadata dict, or an ``"Error: …"`` string.
    """
    from omnigent.runtime import (
        get_artifact_store,
        get_session_artifact_store,
        session_stream,
    )
    from omnigent.runtime.session_artifacts import (
        artifact_upload_limit,
        render_category_for_content_type,
        resolve_artifact_content_type,
    )

    artifacts = get_session_artifact_store()
    blobs = get_artifact_store()
    if artifacts is None or blobs is None:
        return "Error: artifact publishing is not available on this server"

    filename = resolved.name
    content_type = resolve_artifact_content_type(None, filename)
    limit = artifact_upload_limit(content_type)
    if limit is None:
        return (
            f"Error: '{filename}' resolves to {content_type}, which cannot be "
            "published as an artifact. Publishable types are images, video "
            "(mp4/mov/webm), audio (mp3/m4a/wav/ogg), PDF, and HTML."
        )
    # Check the size from metadata so an over-cap file is never read in.
    size = resolved.stat().st_size
    if size > limit:
        return (
            f"Error: '{filename}' is {size} bytes, which exceeds the "
            f"{limit // (1024 * 1024)} MB limit for {content_type} artifacts."
        )

    data = resolved.read_bytes()
    artifact = artifacts.create(
        session_id=session_id,
        filename=filename,
        content_type=content_type,
        bytes=len(data),
        title=title,
        description=description,
        preview_artifact_id=preview_artifact_id,
    )
    # Blob key is the artifact id — what the content endpoint reads.
    blobs.put(artifact.id, data)

    resource = {
        "id": artifact.id,
        "object": "session.resource",
        "type": "session_artifact",
        "session_id": session_id,
        "name": artifact.title or artifact.filename,
        "metadata": {
            "filename": artifact.filename,
            "content_type": artifact.content_type,
            "bytes": artifact.bytes,
            "created_at": artifact.created_at,
            "render_category": artifact.render_category,
            "title": artifact.title,
            "description": artifact.description,
            "preview_artifact_id": artifact.preview_artifact_id,
        },
    }
    session_stream.publish(
        session_id,
        {"type": "session.resource.created", "resource": resource},
    )

    return {
        "artifact_id": artifact.id,
        "filename": artifact.filename,
        "content_type": artifact.content_type,
        "render_category": render_category_for_content_type(artifact.content_type),
        "bytes": artifact.bytes,
        "title": artifact.title,
        "description": artifact.description,
        "preview_artifact_id": artifact.preview_artifact_id,
    }

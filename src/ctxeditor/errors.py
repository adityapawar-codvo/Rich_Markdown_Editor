"""Typed failures. The UI maps these to messages; services never return a bare False."""
from __future__ import annotations


class EditorError(Exception):
    message = "Something went wrong"

    def __init__(self, message: str | None = None, *, field: str | None = None):
        if message is not None:
            self.message = message
        self.field = field
        super().__init__(self.message)


class NotFound(EditorError):
    """Also raised for another tenant's document, an unassigned project, or a document with no published
    version seen by someone who may not read drafts, so existence is not leaked."""
    message = "Not found"


class PermissionDenied(EditorError):
    message = "You do not have permission to do that"


class ValidationFailed(EditorError):
    message = "Invalid input"


class StaleVersion(EditorError):
    message = "The document changed since you opened it. Reload to see the latest version."

    def __init__(self, current_version: int):
        self.current_version = current_version
        super().__init__()


class AlreadyPublished(EditorError):
    message = "This version is already published"


class AgentUnavailable(EditorError):
    message = "The editing assistant is not available right now. Your document was not changed."

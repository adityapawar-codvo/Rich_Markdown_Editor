"""The AI editing agent: propose, review as a diff, then accept or reject.

The agent can only cause one write: a new draft version (source='agent') when the product owner accepts hunks.
This module has no reference to publishing. Prompts, documents, comments and model output are never logged or put
in audit events; only ids, counts and error classes are.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from ..authz import AuthzService
from ..comments import CommentService
from ..db import Database
from ..diffing import Segment, apply_decisions, diff_html, hunks
from ..documents import DocumentService
from ..errors import AgentUnavailable, NotFound, PermissionDenied, StaleVersion, ValidationFailed
from ..models import AGENT_USE, DOC_EDIT, Actor, DocumentView
from ..sanitizer import sanitize_html
from ..timefmt import utc_now_iso
from .openrouter import AgentCallError, LlmResult
from .prompt import SYSTEM_PROMPT, build_user_message
from .protect import extract_html, protect_blocks, redact_secrets, restore_blocks
from .settings import AgentSettings

log = logging.getLogger(__name__)

MAX_PROMPT = 4000
WINDOW_S = 60.0


class AgentClient(Protocol):
    async def complete(self, system: str, user: str) -> LlmResult: ...


@dataclass(frozen=True)
class Proposal:
    request_id: str
    document_id: str
    base_version: int
    model: str
    segments: list[Segment]
    unchanged: bool


class AgentService:
    def __init__(self, db: Database, authz: AuthzService, docs: DocumentService, comments: CommentService,
                 client: AgentClient, settings: AgentSettings, *, clock: Callable[[], float] = time.monotonic):
        self._db, self._authz, self._docs, self._comments = db, authz, docs, comments
        self._client, self._settings, self._clock = client, settings, clock
        self._recent: dict[str, deque[float]] = {}
        self._in_flight: set[str] = set()

    @property
    def enabled(self) -> bool:
        return self._settings.enabled

    # ------------------------------------------------------------------ helpers

    def _check_rate(self, user_id: str) -> None:
        now = self._clock()
        window = self._recent.setdefault(user_id, deque())
        while window and now - window[0] >= WINDOW_S:
            window.popleft()
        if len(window) >= self._settings.rate_per_minute:
            raise AgentUnavailable("You are sending requests too quickly. Wait a minute and try again.")
        window.append(now)

    def _set(self, request_id: str, **fields) -> None:
        names = ", ".join(f"{k} = ?" for k in fields)
        with self._db.transaction() as conn:
            conn.execute(f"update agent_requests set {names} where id = ?", (*fields.values(), request_id))

    def _fail(self, request_id: str, error_class: str, message: str | None = None) -> AgentUnavailable:
        self._set(request_id, result_status="failed", error_class=error_class)
        log.info("agent request failed id=%s class=%s", request_id, error_class)
        return AgentUnavailable(message) if message else AgentUnavailable()

    def _row(self, actor: Actor, request_id: str):
        with self._db.read() as conn:
            row = conn.execute("select * from agent_requests where id = ?", (request_id,)).fetchone()
        if row is None or row["tenant_id"] != actor.tenant_id or row["requested_by"] != actor.user_id:
            raise NotFound()
        return row

    # ------------------------------------------------------------------ propose

    async def propose(self, actor: Actor, document_id: str, prompt: str, comment_ids: Sequence[str] = (),
                      cancel: asyncio.Event | None = None) -> Proposal:
        prompt = (prompt or "").strip()
        if not prompt or len(prompt) > MAX_PROMPT:
            raise ValidationFailed(f"Describe the change in 1 to {MAX_PROMPT} characters", field="prompt")
        if not self.enabled:
            raise AgentUnavailable("The editing assistant is not configured.")
        with self._db.read() as conn:
            doc, actions = self._docs._load(conn, actor, document_id)
        if AGENT_USE not in actions or DOC_EDIT not in actions:
            raise PermissionDenied()
        if document_id in self._in_flight:
            raise AgentUnavailable("Another request for this document is already running. Wait for it to finish.")
        self._check_rate(actor.user_id)

        self._in_flight.add(document_id)
        request_id = None
        try:
            view = self._docs.get(actor, document_id)
            threads = self._comments.threads_for_agent(actor, document_id, list(comment_ids))
            request_id = self._create_request(actor, doc["project_id"], document_id, prompt, view.version_number,
                                              [t.root.id for t in threads])
            return await self._run(actor, request_id, view, prompt, threads, cancel)
        except AgentUnavailable:
            raise
        except (PermissionDenied, NotFound, ValidationFailed):
            raise
        except Exception:
            log.exception("agent request crashed id=%s", request_id)  # traceback holds no prompt or key (see module)
            if request_id:
                raise self._fail(request_id, "internal") from None
            raise AgentUnavailable() from None
        finally:
            self._in_flight.discard(document_id)

    def _create_request(self, actor, project_id, document_id, prompt, base_version, comment_ids) -> str:
        request_id = str(uuid.uuid4())
        with self._db.transaction() as conn:
            conn.execute(
                "insert into agent_requests (id, tenant_id, project_id, document_id, requested_by, prompt,"
                " comment_ids, model, base_version, result_status, correlation_id, created_at)"
                " values (?,?,?,?,?,?,?,?,?,'pending',?,?)",
                (request_id, actor.tenant_id, project_id, document_id, actor.user_id, prompt,
                 json.dumps(comment_ids), self._settings.model, base_version, str(uuid.uuid4()), utc_now_iso()))
            self._docs._audit(conn, actor, project_id, "agent_requested", request_id, document_id=document_id,
                              base_version=base_version, comments=len(comment_ids), model=self._settings.model)
        return request_id

    async def _run(self, actor, request_id: str, view: DocumentView, prompt: str, threads, cancel) -> Proposal:
        protected, mapping = protect_blocks(view.html)
        user_message = redact_secrets(build_user_message(protected, prompt, threads))
        if len(user_message) + len(SYSTEM_PROMPT) > self._settings.max_input_chars:
            raise self._fail(request_id, "too_large",
                             "This document is too large for the editing assistant. Your document was not changed.")
        if cancel is not None and cancel.is_set():
            raise self._fail(request_id, "cancelled", "The request was cancelled. Your document was not changed.")

        started = time.monotonic()
        try:
            result = await self._call(user_message, cancel)
        except asyncio.CancelledError:
            raise self._fail(request_id, "cancelled", "The request was cancelled. Your document was not changed.") from None
        except AgentCallError as exc:
            raise self._fail(request_id, exc.error_class, exc.user_message) from None
        latency_ms = int((time.monotonic() - started) * 1000)

        extracted = extract_html(result.text)
        if not extracted:
            raise self._fail(request_id, "empty_output",
                             "The editing assistant returned an answer that could not be used. Your document was not changed.")
        try:
            proposal_html = sanitize_html(restore_blocks(extracted, mapping))
        except ValidationFailed:
            raise self._fail(request_id, "invalid_output",
                             "The editing assistant produced content that is not valid (for example a broken chart). "
                             "Your document was not changed.") from None

        segments = diff_html(view.html, proposal_html)
        self._set(request_id, result_status="proposed", proposal_html=proposal_html, tokens_in=result.tokens_in,
                  tokens_out=result.tokens_out, latency_ms=latency_ms)
        log.info("agent request proposed id=%s hunks=%s", request_id, len(hunks(segments)))
        return Proposal(request_id, view.document.id, view.version_number, self._settings.model, segments,
                        unchanged=not hunks(segments))

    async def _call(self, user_message: str, cancel: asyncio.Event | None) -> LlmResult:
        if cancel is None:
            return await self._client.complete(SYSTEM_PROMPT, user_message)
        call = asyncio.ensure_future(self._client.complete(SYSTEM_PROMPT, user_message))
        waiter = asyncio.ensure_future(cancel.wait())
        try:
            await asyncio.wait({call, waiter}, return_when=asyncio.FIRST_COMPLETED)
            if call.done():
                return call.result()
            call.cancel()
            raise asyncio.CancelledError()
        finally:
            waiter.cancel()
            if not call.done():
                call.cancel()

    # ------------------------------------------------------------------ review

    def _proposal_from_row(self, actor: Actor, row) -> Proposal:
        base = self._docs.get(actor, row["document_id"], row["base_version"]).html
        segments = diff_html(base, row["proposal_html"] or "")
        return Proposal(row["id"], row["document_id"], row["base_version"], row["model"], segments,
                        unchanged=not hunks(segments))

    def get_proposal(self, actor: Actor, request_id: str) -> Proposal:
        """Reopen an unresolved proposal (for example after a page refresh). Only the requester can."""
        row = self._row(actor, request_id)
        if row["result_status"] != "proposed":
            raise ValidationFailed("This proposal is no longer open")
        return self._proposal_from_row(actor, row)

    def reject(self, actor: Actor, request_id: str) -> None:
        self.resolve(actor, request_id, set())

    def resolve(self, actor: Actor, request_id: str, accepted: set[str] | None = None) -> DocumentView | None:
        """accepted=None takes every proposed change, a set takes only those hunks, an empty set rejects all.
        Returns the new draft view, or None when nothing was applied."""
        row = self._row(actor, request_id)
        if row["result_status"] != "proposed":
            raise ValidationFailed("This proposal was already resolved")
        proposal = self._proposal_from_row(actor, row)
        ids = {h.hunk_id for h in hunks(proposal.segments)}
        chosen = ids if accepted is None else set(accepted)
        if not chosen <= ids:
            raise ValidationFailed("Unknown change selected")
        if not chosen:
            self._finish(actor, row, "rejected", None, chosen, len(ids))
            return None
        html = apply_decisions(proposal.segments, chosen)
        try:
            view = self._docs.save_draft(actor, row["document_id"], row["base_version"], html, source="agent",
                                         agent_request_id=request_id)
        except StaleVersion:
            self._finish(actor, row, "stale", None, chosen, len(ids))
            raise
        self._finish(actor, row, "accepted" if chosen == ids else "partial", view.version_number, chosen, len(ids))
        return view

    def _finish(self, actor: Actor, row, status: str, resulting_version: int | None, chosen: set[str],
                total: int) -> None:
        with self._db.transaction() as conn:
            conn.execute("update agent_requests set result_status = ?, resulting_version = ?, accepted_hunks = ?"
                         " where id = ?", (status, resulting_version, json.dumps(sorted(chosen)), row["id"]))
            self._docs._audit(conn, actor, row["project_id"], "agent_resolved", row["id"], status=status,
                              accepted=len(chosen), total=total, resulting_version=resulting_version)

from __future__ import annotations

import pytest

from ctxeditor.authz import AuthzService
from ctxeditor.db import Database
from ctxeditor.documents import DocumentService
from ctxeditor.migrate import migrate
from ctxeditor.seed import Seeded, seed


class Env:
    def __init__(self, tmp_path):
        self.db = Database(tmp_path / "test.db")
        migrate(self.db)
        self.seeded: Seeded = seed(self.db)
        self.authz = AuthzService(self.db)
        self.docs = DocumentService(self.db, self.authz)
        self.doc_id = self.seeded.document_id

    def actor(self, key: str):
        actor = self.authz.resolve_actor(self.seeded.users[key])
        assert actor is not None, key
        return actor


@pytest.fixture
def env(tmp_path) -> Env:
    return Env(tmp_path)


@pytest.fixture(scope="module")
def chromium():
    """A headless Chromium (sync API) for browser tests; skipped when Playwright's browser is not installed.
Module-scoped so it never overlaps the async API used by the export tests."""
    playwright_sync = pytest.importorskip("playwright.sync_api")
    with playwright_sync.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # pragma: no cover
            pytest.skip(f"chromium not available: {exc}")
        yield browser
        browser.close()

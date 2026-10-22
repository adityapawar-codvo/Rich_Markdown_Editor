# Project Context Editor

A Word-like document editor for project context, built as a custom NiceGUI element around **TipTap v3**. One place
where project documents are written, versioned, published, commented on, reviewed with an AI assistant, and exported.

This is a **standalone** project. It mirrors the `neio_sdlc_v2` ERD (table and action names) so it can be integrated
later; see [Integrating with neio_sdlc_v2](#integrating-with-neio_sdlc_v2).

## Run it

```bash
uv sync
uv run playwright install chromium     # needed for PDF/Word export and for the browser tests
cp .env.example .env                   # optional: add OPENROUTER_API_KEY to enable the assistant
uv run context-editor                  # http://localhost:8080
```

You need [uv](https://docs.astral.sh/uv/) (it installs the right Python, 3.13, by itself). Node is **not** needed to run
the app. The first start takes a few seconds longer while Python compiles; the page then opens at the URL above.
Without `playwright install chromium` everything works except PDF/Word export (it says so) and the browser tests (they skip).

The first start creates `context_editor_demo.db` (SQLite) and seeds a demo: two tenants, a project in each, one person
per role (use the persona switcher in the header), and one sample document that uses every editor feature.
It has a published version 1 and a newer draft version 2 that the team cannot see.

| Persona | Can do |
| --- | --- |
| Priya Nair, Product Owner | create, edit, save drafts, publish, restore, export (incl. drafts), comment, resolve, use the assistant |
| Erin (Executive), Dmitri (Developer), Arjun (Architect), Sana (QA) | read the latest published version, comment, export the published version |
| Una Unassigned | no project: sees nothing |
| Gwen Park (Globex) | another tenant: cannot see Acme documents |

The persona switcher stands in for sign-in. The services never trust it: every call resolves the person's actions from
the role-action matrix on the server.

## What it does

- **Editor**: bold, italic, underline, strike, sub/superscript, inline code, H1–H4, quotes, rules, bulleted / numbered /
  checklists with indent, links, alignment, text colour, highlight, tables (rows, columns, header row, merge/split),
  code blocks with syntax highlighting, undo/redo, clear formatting, Word-style shortcuts, a fixed toolbar, a floating
  selection toolbar and a `/` menu.
- **Diagrams and charts**: Mermaid (split code/preview dialog with inline errors) and Chart.js (bar, line, pie, area,
  edited through a small table). Both render live in the editor, in the read-only view, in the diff view and in exports,
  through the same renderer.
- **Upload**: the product owner can upload an existing file (Word, PowerPoint, Excel, PDF with a text layer, Markdown,
  HTML, CSV, text; up to 10 MB). It is converted on the server and opens as a new draft in the editor, fully editable.
  Images are skipped (and counted); Excel keeps saved values, not formulas; PDF tables come in as text; a scanned PDF is
  refused. Upload needs the `doc.create` action, and every file is checked (signature, archive guard, XML entity
  refusal) and sanitized like any other content.
- **Versions**: every save is a new immutable version. History, view, compare, restore as a new draft.
- **Draft vs published**: only people holding `doc.read_draft` see drafts. Unsaved edits are kept while the owner looks at
  another version (for example "what the team sees") and come back when they return. Publishing is a separate, audited action with a
  change note. The team sees only the latest published version.
- **Comments**: text-anchored (highlight) and general, one reply level, role badges, version tag, open/resolved filters,
  "text no longer present" when the quoted text is gone. Nothing is hard-deleted.
- **Assistant**: describe a change, get a visual diff, accept or reject all or per change. Saved as a draft; it can
  never publish.
- **Export**: PDF (print-styled, page numbers, title in header) and Word (real headings, lists, tables). Drafts are marked.

## Configuration

| Variable | Purpose |
| --- | --- |
| `OPENROUTER_API_KEY` | Enables the assistant. Read only from the environment; never logged, stored, or sent to the browser. |
| `OPENROUTER_MODEL` | Model id (default `anthropic/claude-sonnet-4.5`). |
| `CONTEXT_EDITOR_DB` | SQLite file (default `context_editor_demo.db`). |
| `PORT`, `NICEGUI_STORAGE_SECRET` | Server port and session secret. |

## Storage format

Documents are **sanitized HTML**. Every write is sanitized with an allowlist (`src/ctxeditor/sanitizer.py`, nh3), and the
same sanitizer runs again on every read, diff, export and assistant call. Custom blocks:

```html
<div data-type="mermaid">diagram source as text</div>
<div data-type="chart" data-chart='{"type":"bar","title":"","labels":[],"series":[{"name":"","values":[]}]}'></div>
<ul data-type="taskList"><li data-type="taskItem" data-checked="true"><div>…</div></li></ul>
```

`tests/test_roundtrip.py` loads a document using every node and mark into the real editor in Chromium and proves
the editor emits exactly what the sanitizer allows.

## Layout

```
src/ctxeditor/
  importer.py                         file upload: docx/pptx/xlsx/pdf/md/html/csv/txt -> sanitized editor HTML
  documents.py comments.py authz.py   services: every method enforces actions on the server
  sanitizer.py diffing.py             HTML allowlist; block diff shared by compare and the assistant
  agent/                              OpenRouter client, prompt, block protection, AgentService
  export/                             headless-Chromium pool, PDF, Word (python-docx)
  seed.py sample_content.py           demo data
  web/editor/                         ui.context_editor: Python element, Vue shell, TipTap bundle (src/, dist/)
  web/pages/workspace.py panels.py    the app: documents, editor, comments, history, assistant
  migrations/ (+ rollback/)           numbered SQL with tested down scripts (ships with the package)
tests/                                pytest (services, sanitizer, diff) + Playwright browser tests
```

## Tests

```bash
uv run pytest                           # everything (~5 min; browser tests start real servers)
uv run pytest -m "not browser"          # fast: services, sanitizer, diff, DOCX, agent (no Chromium)
cd src/ctxeditor/web/editor && npm test # anchor resolution (vitest)
```

## Rebuilding the editor bundle

`src/ctxeditor/web/editor/dist/` is committed so `uv run` needs no Node. To change the editor:

```bash
cd src/ctxeditor/web/editor
npm ci
npm run build      # rollup -> dist/ (index.js, export.js, document.css, lazy chunks for Mermaid)
npm run fonts      # only when fonts change: copies the self-hosted woff2 files and writes static/fonts.css
```

TipTap, Mermaid and Chart.js versions are pinned exactly in `package.json` (all MIT; no TipTap Pro or Cloud features).
Fonts (Inter, Source Serif 4, JetBrains Mono, SIL OFL) are self-hosted; nothing loads from a CDN at runtime.

## Integrating with neio_sdlc_v2

Names already follow its ERD (`tenant_id`, `projects`, `roles`, `actions`, `role_actions`, `membership_roles`,
append-only audit). To move onto the platform:

1. **Identity and RBAC**: replace `AuthzService.resolve_actor` / `_grants` with the platform's membership and role-action
   tables, and drop the persona switcher. Add the `doc.*`, `comment.resolve` and `agent.use` codes (see `models.py`) to
   the platform action catalogue. Role names appear only in `seed.py`.
2. **Storage**: port `src/ctxeditor/migrations/0001_context_editor.sql` to Supabase. Keep the rules in the services as security-definer
   functions (derive the tenant from the caller, check the action, write the change and an audit row in one
   transaction), as the existing tenant RPCs do. `document_versions` and `document_publications` are insert-only;
   `documents.current_version` is the optimistic-lock token. Map `audit_events` to `tenant_audit_events`.
3. **Because Postgres cannot sanitize HTML**, keep the sanitizer on every read as well as every write; a user holding a
   JWT can call an RPC directly.
4. **ERD amendments to request**: `documents` (optionally with a nullable `artifact_id` so a Blob-backed artifact can
   adopt it), `document_publications`, `comments`, `agent_requests`, and the action codes above.
5. Mount `ui.context_editor` (`ctxeditor.web.editor`) and reuse `WorkspaceController`-style pages inside the platform's
   page frame (go-back button, theme).

## Known limits

- The diff works on whole blocks: "accept an individual change" means one changed block (paragraph, table, diagram).
- The Word file is built with python-docx and was checked structurally, not opened in Word.
- The assistant's rate limit and in-flight guard are per process.
- Document text and comments are sent to OpenRouter when the assistant is used. Data-handling policy for that
  (tenant opt-in, zero-retention providers) is deliberately deferred.
- There is no real sign-in; see the persona note above.

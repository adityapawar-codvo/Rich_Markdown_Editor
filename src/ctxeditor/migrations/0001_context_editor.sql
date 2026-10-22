-- 0001: context editor schema. Table names follow the neio_sdlc_v2 ERD (tenant_id is the implementation's name for
-- organization_id) so the feature can be integrated later: tenants, users (stands in for user_profiles), projects,
-- roles, actions, role_actions, memberships, membership_roles. New: documents, document_versions,
-- document_publications, comments, agent_requests, audit_events.
-- Timestamps are UTC ISO-8601 text. Rollback: rollback/0001_context_editor_down.sql (next to this file)

create table tenants (
  id text primary key,
  name text not null,
  slug text not null unique
);

create table users (
  id text primary key,
  tenant_id text not null references tenants (id),
  email text not null unique,
  display_name text not null
);

create table projects (
  id text primary key,
  tenant_id text not null references tenants (id),
  name text not null,
  project_key text not null,
  unique (tenant_id, project_key)
);

create table roles (
  id text primary key,
  tenant_id text not null references tenants (id),
  code text not null,
  name text not null,
  unique (tenant_id, code)
);

create table actions (
  id text primary key,
  code text not null unique,
  allowed_scope text not null check (allowed_scope in ('organization', 'project', 'any')),
  description text not null
);

create table role_actions (
  tenant_id text not null references tenants (id),
  role_id text not null references roles (id),
  action_id text not null references actions (id),
  primary key (role_id, action_id)
);

create table memberships (
  id text primary key,
  tenant_id text not null references tenants (id),
  user_id text not null references users (id),
  status text not null check (status in ('active', 'inactive')),
  unique (tenant_id, user_id)
);

create table membership_roles (
  tenant_id text not null references tenants (id),
  membership_id text not null references memberships (id),
  role_id text not null references roles (id),
  project_id text references projects (id),   -- null = organization-wide
  expires_at text
);
create unique index membership_roles_unique on membership_roles (membership_id, role_id, coalesce(project_id, ''));

-- A document. current_version is the latest saved version and doubles as the optimistic-lock token.
-- published_version is the latest published one (null until first publish).
create table documents (
  id text primary key,
  tenant_id text not null references tenants (id),
  project_id text not null references projects (id),
  doc_type text not null,
  title text not null,
  current_version integer not null check (current_version >= 1),
  published_version integer check (published_version is null or published_version >= 1),
  created_by text not null references users (id),
  created_at text not null,
  updated_by text not null references users (id),
  updated_at text not null,
  published_by text references users (id),
  published_at text,
  check (published_version is null or published_version <= current_version)
);
create index documents_project on documents (project_id);

-- Immutable content. There is deliberately no status column: a version is "published" when it has a publication.
create table document_versions (
  id text primary key,
  tenant_id text not null references tenants (id),
  project_id text not null references projects (id),
  document_id text not null references documents (id),
  version_number integer not null check (version_number >= 1),
  content_html text not null,
  content_hash text not null,
  source text not null check (source in ('manual', 'agent', 'restore')),
  restored_from_version integer,
  agent_request_id text,
  created_by text not null references users (id),
  created_at text not null,
  unique (document_id, version_number)
);

create table document_publications (
  id text primary key,
  tenant_id text not null references tenants (id),
  project_id text not null references projects (id),
  document_id text not null references documents (id),
  version_number integer not null,
  change_note text,
  published_by text not null references users (id),
  published_at text not null,
  unique (document_id, version_number),
  foreign key (document_id, version_number) references document_versions (document_id, version_number)
);

-- anchor_id null = a General comment. Anchored comments carry a text-quote selector; the highlight is drawn by the
-- editor, so the published content never changes when someone comments.
create table comments (
  id text primary key,
  tenant_id text not null references tenants (id),
  project_id text not null references projects (id),
  document_id text not null references documents (id),
  version_number integer not null,
  anchor_id text,
  quoted_text text,
  anchor_prefix text,
  anchor_suffix text,
  anchor_hint integer,
  parent_comment_id text references comments (id),
  author_id text not null references users (id),
  author_role_code text not null,
  author_role_label text not null,
  body text not null,
  status text not null check (status in ('open', 'resolved')),
  created_at text not null,
  edited_at text,
  deleted_at text,
  resolved_by text references users (id),
  resolved_at text,
  check ((anchor_id is null) = (quoted_text is null))
);
create index comments_document on comments (document_id);

create table agent_requests (
  id text primary key,
  tenant_id text not null references tenants (id),
  project_id text not null references projects (id),
  document_id text not null references documents (id),
  requested_by text not null references users (id),
  prompt text not null,
  comment_ids text not null default '[]',
  model text not null,
  base_version integer not null,
  result_status text not null check (result_status in
    ('pending', 'proposed', 'accepted', 'partial', 'rejected', 'failed', 'stale')),
  proposal_html text,
  accepted_hunks text,
  resulting_version integer,
  error_class text,
  correlation_id text not null,
  tokens_in integer,
  tokens_out integer,
  latency_ms integer,
  created_at text not null
);
create index agent_requests_document on agent_requests (document_id);

-- Append-only history of security-relevant and workflow actions. Payloads hold ids, versions and hashes, never
-- document text, comment bodies or prompts.
create table audit_events (
  id text primary key,
  tenant_id text not null references tenants (id),
  project_id text,
  actor_id text not null,
  action text not null,
  subject_id text,
  metadata text not null default '{}',
  occurred_at text not null
);

create trigger audit_events_no_update before update on audit_events
begin select raise(abort, 'audit_events is append-only'); end;
create trigger audit_events_no_delete before delete on audit_events
begin select raise(abort, 'audit_events is append-only'); end;

create trigger document_versions_no_update before update on document_versions
begin select raise(abort, 'document_versions is insert-only'); end;
create trigger document_versions_no_delete before delete on document_versions
begin select raise(abort, 'document_versions is insert-only'); end;
create trigger document_publications_no_update before update on document_publications
begin select raise(abort, 'document_publications is insert-only'); end;
create trigger document_publications_no_delete before delete on document_publications
begin select raise(abort, 'document_publications is insert-only'); end;

-- A version and a publication must share their document's tenant and project.
create trigger document_versions_scope before insert on document_versions
begin
  select raise(abort, 'version tenant or project does not match its document')
  where not exists (select 1 from documents d where d.id = new.document_id
                    and d.tenant_id = new.tenant_id and d.project_id = new.project_id);
end;
create trigger document_publications_scope before insert on document_publications
begin
  select raise(abort, 'publication tenant or project does not match its document')
  where not exists (select 1 from documents d where d.id = new.document_id
                    and d.tenant_id = new.tenant_id and d.project_id = new.project_id);
end;

-- A comment shares its document's tenant and project; a reply belongs to a top-level comment of the same document.
create trigger comments_scope before insert on comments
begin
  select raise(abort, 'comment tenant or project does not match its document')
  where not exists (select 1 from documents d where d.id = new.document_id
                    and d.tenant_id = new.tenant_id and d.project_id = new.project_id);
  select raise(abort, 'reply must belong to a top-level comment of the same document')
  where new.parent_comment_id is not null and not exists (
    select 1 from comments p where p.id = new.parent_comment_id
    and p.document_id = new.document_id and p.parent_comment_id is null);
end;

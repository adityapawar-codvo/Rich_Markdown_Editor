-- Down for 0001: drops everything the migration created. Destroys all documents, versions and comments.
-- Run only on a disposable database or after a verified backup.
drop table if exists agent_requests;
drop table if exists comments;
drop table if exists document_publications;
drop table if exists document_versions;
drop table if exists documents;
drop table if exists audit_events;
drop table if exists membership_roles;
drop table if exists memberships;
drop table if exists role_actions;
drop table if exists actions;
drop table if exists roles;
drop table if exists projects;
drop table if exists users;
drop table if exists tenants;

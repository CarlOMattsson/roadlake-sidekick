"""The 0.1.0 schema baseline: the whole `sidekick` schema in one migration, for new installations.

Every installation of Roadlake Sidekick starts from an empty database, so this is the first migration
of the chain; later migrations (101 onward) are applied on top of it. There is no upgrade path from earlier
development builds, and no backup or export from before 0.1.0 can be imported (see
`docs/explanation/schema-baseline.md`).

The schema is the whole set of tables, constraints, indexes, generated columns, extensions, grants
and default privileges of the product. `backend/tests/integration/test_migration_baseline.py` pins
a fresh install to the checked-in snapshot `backend/tests/fixtures/baseline-catalogue.json`.

On a database that already has a `sidekick` schema, the first statement fails and the whole step is
rolled back, so nothing is changed and nothing is recorded.

One-way: the rollback refuses, because rolling back a baseline would drop every owner table.
"""

# migration-class: contract
# The apply step is a Python function, which the static migration policy check cannot read, so the
# class is declared. 0.1.0 is the first release and is breaking.

from typing import Any

from yoyo import step

__depends__: set[str] = set()

BASELINE_SQL = r"""
SET LOCAL ROLE sidekick_owner;

-- SCHEMA: sidekick
CREATE SCHEMA sidekick AUTHORIZATION sidekick_owner;

-- EXTENSION: pg_trgm
CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;

-- EXTENSION: unaccent
CREATE EXTENSION IF NOT EXISTS unaccent WITH SCHEMA public;

-- TABLE: actions
CREATE TABLE sidekick.actions (
    id uuid NOT NULL,
    owner_id uuid NOT NULL,
    step_id uuid NOT NULL,
    title character varying(200) NOT NULL,
    status character varying(20) NOT NULL,
    "position" integer NOT NULL,
    due_at timestamp with time zone,
    attention_requested boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    version integer NOT NULL,
    archived_at timestamp with time zone,
    note text,
    trashed_at timestamp with time zone,
    CONSTRAINT ck_actions_note CHECK (((note IS NULL) OR (length(note) <= 500))),
    CONSTRAINT ck_actions_position CHECK (("position" >= 0)),
    CONSTRAINT ck_actions_status CHECK ((status IN ('open', 'completed'))),
    CONSTRAINT ck_actions_title CHECK (((length(btrim((title)::text)) >= 1) AND (length(btrim((title)::text)) <= 200))),
    CONSTRAINT ck_actions_version CHECK ((version >= 1))
);

-- TABLE: activity_entries
CREATE TABLE sidekick.activity_entries (
    id uuid NOT NULL,
    owner_id uuid NOT NULL,
    domain_event_id uuid NOT NULL,
    category character varying(48) NOT NULL,
    source character varying(24) NOT NULL,
    operation character varying(80) NOT NULL,
    state character varying(24) NOT NULL,
    aggregate_type character varying(40) NOT NULL,
    aggregate_id uuid NOT NULL,
    summary character varying(300) NOT NULL,
    before_values jsonb DEFAULT '{}'::jsonb NOT NULL,
    after_values jsonb DEFAULT '{}'::jsonb NOT NULL,
    evidence jsonb DEFAULT '{}'::jsonb NOT NULL,
    policy_mode character varying(24),
    correlation_id character varying(64),
    occurred_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_activity_entries_after_values CHECK (((jsonb_typeof(after_values) = 'object'::text) AND (octet_length((after_values)::text) <= 8192))),
    CONSTRAINT ck_activity_entries_before_values CHECK (((jsonb_typeof(before_values) = 'object'::text) AND (octet_length((before_values)::text) <= 8192))),
    CONSTRAINT ck_activity_entries_evidence CHECK (((jsonb_typeof(evidence) = 'object'::text) AND (octet_length((evidence)::text) <= 8192))),
    CONSTRAINT ck_activity_entries_policy_mode CHECK (((policy_mode IS NULL) OR (policy_mode IN ('review', 'auto_reversible', 'disabled')))),
    CONSTRAINT ck_activity_entries_source CHECK ((source IN ('user', 'assistant', 'worker', 'system'))),
    CONSTRAINT ck_activity_entries_state CHECK ((state IN ('applied', 'review', 'failed', 'reverted')))
);

-- TABLE: assistant_automation_control
CREATE TABLE sidekick.assistant_automation_control (
    owner_id uuid NOT NULL,
    pause_all_automation boolean DEFAULT false NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_assistant_automation_control_version CHECK ((version >= 1))
);

-- TABLE: assistant_automation_policies
CREATE TABLE sidekick.assistant_automation_policies (
    owner_id uuid NOT NULL,
    category character varying(48) NOT NULL,
    mode character varying(24) NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_assistant_automation_policy_mode CHECK ((mode IN ('review', 'auto_reversible', 'disabled'))),
    CONSTRAINT ck_assistant_automation_policy_version CHECK ((version >= 1))
);

-- TABLE: assistant_automation_runs
CREATE TABLE sidekick.assistant_automation_runs (
    id uuid NOT NULL,
    owner_id uuid NOT NULL,
    kind character varying(48) NOT NULL,
    trigger character varying(24) NOT NULL,
    status character varying(24) NOT NULL,
    scheduled_for timestamp with time zone NOT NULL,
    created_at timestamp with time zone NOT NULL,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    heartbeat_at timestamp with time zone,
    attempt integer DEFAULT 0 NOT NULL,
    worker_id character varying(120),
    summary jsonb DEFAULT '{}'::jsonb NOT NULL,
    error_code character varying(64),
    correlation_id character varying(64),
    CONSTRAINT ck_automation_runs_attempt CHECK ((attempt >= 0)),
    CONSTRAINT ck_automation_runs_status CHECK ((status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled'))),
    CONSTRAINT ck_automation_runs_summary CHECK (((jsonb_typeof(summary) = 'object'::text) AND (octet_length((summary)::text) <= 8192))),
    CONSTRAINT ck_automation_runs_trigger CHECK ((trigger IN ('scheduled', 'manual', 'system')))
);

-- TABLE: assistant_task_review_findings
CREATE TABLE sidekick.assistant_task_review_findings (
    id uuid NOT NULL,
    owner_id uuid NOT NULL,
    run_id uuid NOT NULL,
    task_id uuid NOT NULL,
    finding_code character varying(48) NOT NULL,
    severity character varying(16) NOT NULL,
    state character varying(24) DEFAULT 'open'::character varying NOT NULL,
    title character varying(240) NOT NULL,
    detail character varying(1000) NOT NULL,
    evidence jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_task_review_findings_evidence CHECK (((jsonb_typeof(evidence) = 'object'::text) AND (octet_length((evidence)::text) <= 8192))),
    CONSTRAINT ck_task_review_findings_severity CHECK ((severity IN ('low', 'medium', 'high'))),
    CONSTRAINT ck_task_review_findings_state CHECK ((state IN ('open', 'dismissed', 'resolved')))
);

-- TABLE: audit_events
CREATE TABLE sidekick.audit_events (
    id uuid NOT NULL,
    actor_id uuid,
    event character varying(80) NOT NULL,
    outcome character varying(24) NOT NULL,
    reason character varying(80),
    correlation_id character varying(64),
    target_type character varying(40),
    target_id uuid,
    occurred_at timestamp with time zone NOT NULL,
    related_id uuid,
    CONSTRAINT audit_events_outcome_check CHECK ((outcome IN ('success', 'denied', 'failure')))
);

-- TABLE: companion_pairings
CREATE TABLE sidekick.companion_pairings (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    label character varying(120) NOT NULL,
    scopes jsonb NOT NULL,
    secret_digest character(64) NOT NULL,
    device_lifetime_days integer NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    consumed_at timestamp with time zone,
    device_token_id uuid,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT companion_pairings_check CHECK ((expires_at > created_at)),
    CONSTRAINT companion_pairings_device_lifetime_days_check CHECK (((device_lifetime_days >= 1) AND (device_lifetime_days <= 90))),
    CONSTRAINT companion_pairings_label_check CHECK ((length(btrim((label)::text)) > 0)),
    CONSTRAINT companion_pairings_scopes_check CHECK (((jsonb_typeof(scopes) = 'array'::text) AND (jsonb_array_length(scopes) > 0)))
);

-- TABLE: contact_aliases
CREATE TABLE sidekick.contact_aliases (
    id uuid NOT NULL,
    owner_id uuid NOT NULL,
    contact_id uuid NOT NULL,
    display_value character varying(120) NOT NULL,
    normalized_key character varying(120) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    search_vector tsvector GENERATED ALWAYS AS (setweight(to_tsvector('simple'::regconfig, (COALESCE(display_value, ''::character varying))::text), 'A'::"char")) STORED,
    CONSTRAINT contact_aliases_display_value_check CHECK ((length(btrim((display_value)::text)) > 0)),
    CONSTRAINT contact_aliases_normalized_key_check CHECK ((length(btrim((normalized_key)::text)) > 0))
);

-- TABLE: contacts
CREATE TABLE sidekick.contacts (
    id uuid NOT NULL,
    owner_id uuid NOT NULL,
    display_name character varying(200) NOT NULL,
    display_name_key character varying(200) NOT NULL,
    context_note text,
    email character varying(320),
    email_key character varying(320),
    phone character varying(64),
    phone_key character varying(64),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    archived_at timestamp with time zone,
    archived boolean DEFAULT false NOT NULL,
    version integer NOT NULL,
    trashed_at timestamp with time zone,
    search_vector tsvector GENERATED ALWAYS AS ((setweight(to_tsvector('simple'::regconfig, (COALESCE(display_name, ''::character varying))::text), 'A'::"char") || setweight(to_tsvector('swedish'::regconfig, COALESCE(context_note, ''::text)), 'B'::"char"))) STORED,
    relationship character varying(80),
    organization character varying(200),
    role character varying(120),
    address character varying(500),
    CONSTRAINT check_paired_email CHECK ((((email IS NULL) AND (email_key IS NULL)) OR ((email IS NOT NULL) AND (email_key IS NOT NULL)))),
    CONSTRAINT check_paired_phone CHECK ((((phone IS NULL) AND (phone_key IS NULL)) OR ((phone IS NOT NULL) AND (phone_key IS NOT NULL)))),
    CONSTRAINT ck_contacts_archive_consistency CHECK ((((archived = false) AND (archived_at IS NULL)) OR ((archived = true) AND (archived_at IS NOT NULL)))),
    CONSTRAINT contacts_display_name_check CHECK ((length(btrim((display_name)::text)) > 0)),
    CONSTRAINT contacts_display_name_key_check CHECK ((length(btrim((display_name_key)::text)) > 0)),
    CONSTRAINT contacts_version_check CHECK ((version >= 1))
);

-- TABLE: daily_journal_summaries
CREATE TABLE sidekick.daily_journal_summaries (
    id uuid NOT NULL,
    owner_id uuid NOT NULL,
    journal_date date NOT NULL,
    origin character varying(24) NOT NULL,
    status character varying(16) NOT NULL,
    overview text NOT NULL,
    content jsonb NOT NULL,
    source_fingerprint character(64) NOT NULL,
    processing_run_id uuid,
    accepted_proposal_id uuid,
    version integer NOT NULL,
    generated_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    manual_edited_at timestamp with time zone,
    CONSTRAINT ck_daily_journal_summaries_content CHECK ((jsonb_typeof(content) = 'object'::text)),
    CONSTRAINT ck_daily_journal_summaries_fingerprint CHECK ((source_fingerprint ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT ck_daily_journal_summaries_origin CHECK ((origin IN ('manual', 'ai_assisted'))),
    CONSTRAINT ck_daily_journal_summaries_origin_provenance CHECK (((((origin)::text = 'manual'::text) AND (processing_run_id IS NULL) AND (accepted_proposal_id IS NULL)) OR (((origin)::text = 'ai_assisted'::text) AND (processing_run_id IS NOT NULL) AND (accepted_proposal_id IS NOT NULL)))),
    CONSTRAINT ck_daily_journal_summaries_overview CHECK (((length(overview) BETWEEN 1 AND 20000) AND (length(btrim(overview)) > 0))),
    CONSTRAINT ck_daily_journal_summaries_status CHECK ((status IN ('current', 'stale'))),
    CONSTRAINT ck_daily_journal_summaries_version CHECK ((version >= 1))
);

-- TABLE: daily_journal_summary_entries
CREATE TABLE sidekick.daily_journal_summary_entries (
    owner_id uuid NOT NULL,
    summary_id uuid NOT NULL,
    entry_id uuid NOT NULL,
    entry_version integer NOT NULL,
    ordinal integer NOT NULL,
    CONSTRAINT ck_daily_journal_summary_entries_ordinal CHECK ((ordinal >= 0)),
    CONSTRAINT ck_daily_journal_summary_entries_version CHECK ((entry_version >= 1))
);

-- TABLE: domain_events
CREATE TABLE sidekick.domain_events (
    id uuid NOT NULL,
    owner_id uuid NOT NULL,
    aggregate_type character varying(40) NOT NULL,
    aggregate_id uuid NOT NULL,
    aggregate_version integer NOT NULL,
    event_type character varying(80) NOT NULL,
    schema_version integer DEFAULT 1 NOT NULL,
    actor_type character varying(24) NOT NULL,
    actor_id uuid,
    command_id uuid NOT NULL,
    correlation_id character varying(64),
    causation_id uuid,
    automation_run_id uuid,
    payload jsonb NOT NULL,
    occurred_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_domain_events_actor_type CHECK ((actor_type IN ('user', 'assistant', 'worker', 'system'))),
    CONSTRAINT ck_domain_events_payload CHECK (((jsonb_typeof(payload) = 'object'::text) AND (octet_length((payload)::text) <= 32768))),
    CONSTRAINT ck_domain_events_schema_version CHECK ((schema_version >= 1)),
    CONSTRAINT ck_domain_events_version CHECK ((aggregate_version >= 1))
);

-- TABLE: domain_tags
CREATE TABLE sidekick.domain_tags (
    owner_id uuid NOT NULL,
    tag_id uuid NOT NULL,
    domain_id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL
);

-- TABLE: domains
CREATE TABLE sidekick.domains (
    id uuid NOT NULL,
    owner_id uuid NOT NULL,
    name character varying(200) NOT NULL,
    description text,
    status character varying(20) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    version integer NOT NULL,
    review_cadence character varying(12),
    last_reviewed_at timestamp with time zone,
    trashed_at timestamp with time zone,
    accent text,
    CONSTRAINT ck_domains_accent CHECK (((accent IS NULL) OR (accent = ANY (ARRAY['slate'::text, 'blue'::text, 'teal'::text, 'green'::text, 'amber'::text, 'orange'::text, 'rose'::text, 'violet'::text])))),
    CONSTRAINT ck_domains_name CHECK (((length(btrim((name)::text)) >= 1) AND (length(btrim((name)::text)) <= 200))),
    CONSTRAINT ck_domains_review_cadence CHECK (((review_cadence IS NULL) OR (review_cadence IN ('daily', 'weekly', 'biweekly', 'monthly', 'quarterly', 'yearly')))),
    CONSTRAINT ck_domains_status CHECK ((status IN ('active', 'archived'))),
    CONSTRAINT ck_domains_version CHECK ((version >= 1))
);

-- TABLE: external_references
CREATE TABLE sidekick.external_references (
    id uuid NOT NULL,
    owner_id uuid NOT NULL,
    kind character varying(20) NOT NULL,
    provider character varying(30) NOT NULL,
    account_ref character varying(200) NOT NULL,
    external_id character varying(500) NOT NULL,
    instance_ref character varying(500),
    title character varying(300) NOT NULL,
    url character varying(2000),
    occurs_at timestamp with time zone,
    snapshot_at timestamp with time zone NOT NULL,
    source character varying(20) NOT NULL,
    version integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT external_references_account_ref_check CHECK (((length(btrim((account_ref)::text)) > 0) AND ((account_ref)::text = lower((account_ref)::text)))),
    CONSTRAINT external_references_external_id_check CHECK ((length(btrim((external_id)::text)) > 0)),
    CONSTRAINT external_references_instance_ref_check CHECK (((instance_ref IS NULL) OR (length(btrim((instance_ref)::text)) > 0))),
    CONSTRAINT external_references_kind_check CHECK ((kind IN ('mail', 'calendar_event', 'document'))),
    CONSTRAINT external_references_provider_check CHECK ((provider IN ('google_gmail', 'google_calendar', 'google_drive', 'other'))),
    CONSTRAINT external_references_source_check CHECK ((source IN ('claude_connector', 'manual'))),
    CONSTRAINT external_references_title_check CHECK ((length(btrim((title)::text)) > 0)),
    CONSTRAINT external_references_url_check CHECK (((url IS NULL) OR ((url)::text ~ '^https://[^[:space:][:cntrl:]\\]+$'::text))),
    CONSTRAINT external_references_version_check CHECK ((version > 0))
);

-- TABLE: idempotency_operations
CREATE TABLE sidekick.idempotency_operations (
    id uuid NOT NULL,
    actor_id uuid NOT NULL,
    operation character varying(80) NOT NULL,
    idempotency_key character varying(128) NOT NULL,
    payload_hash character(64) NOT NULL,
    result jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL
);

-- TABLE: instance_license
CREATE TABLE sidekick.instance_license (
    id smallint NOT NULL,
    license_key text,
    max_seen_on date NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT instance_license_id_check CHECK ((id = 1)),
    CONSTRAINT instance_license_license_key_check CHECK (((license_key IS NULL) OR (length(license_key) BETWEEN 1 AND 1024)))
);

-- TABLE: journal_drafts
CREATE TABLE sidekick.journal_drafts (
    id uuid NOT NULL,
    owner_id uuid NOT NULL,
    source_id uuid NOT NULL,
    processing_run_id uuid,
    catalog_run_id uuid NOT NULL,
    state character varying(24) NOT NULL,
    title character varying(200) NOT NULL,
    summary text,
    key_points jsonb NOT NULL,
    relation_suggestions jsonb NOT NULL,
    task_proposals jsonb NOT NULL,
    version integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    lifecycle_at timestamp with time zone,
    CONSTRAINT ck_journal_drafts_key_points CHECK (((jsonb_typeof(key_points) = 'array'::text) AND (jsonb_array_length(key_points) <= 50))),
    CONSTRAINT ck_journal_drafts_relation_suggestions CHECK ((jsonb_typeof(relation_suggestions) = 'object'::text)),
    CONSTRAINT ck_journal_drafts_state CHECK ((state IN ('pending_review', 'finalized', 'rejected', 'superseded'))),
    CONSTRAINT ck_journal_drafts_summary CHECK (((summary IS NULL) OR (length(summary) <= 10000))),
    CONSTRAINT ck_journal_drafts_task_proposals CHECK (((jsonb_typeof(task_proposals) = 'array'::text) AND (jsonb_array_length(task_proposals) <= 20))),
    CONSTRAINT ck_journal_drafts_title CHECK ((length(btrim((title)::text)) > 0)),
    CONSTRAINT ck_journal_drafts_version CHECK ((version >= 1))
);

-- TABLE: journal_entries
CREATE TABLE sidekick.journal_entries (
    id uuid NOT NULL,
    owner_id uuid NOT NULL,
    source_id uuid NOT NULL,
    journal_date date NOT NULL,
    occurred_at timestamp with time zone,
    title character varying(200) NOT NULL,
    summary text,
    key_points jsonb NOT NULL,
    version integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    archived_at timestamp with time zone,
    trashed_at timestamp with time zone,
    search_vector tsvector GENERATED ALWAYS AS ((setweight(to_tsvector('simple'::regconfig, (COALESCE(title, ''::character varying))::text), 'A'::"char") || setweight(to_tsvector('swedish'::regconfig, COALESCE(summary, ''::text)), 'B'::"char"))) STORED,
    CONSTRAINT ck_journal_entries_archive CHECK (((archived_at IS NULL) OR (archived_at >= created_at))),
    CONSTRAINT ck_journal_entries_key_points CHECK (((jsonb_typeof(key_points) = 'array'::text) AND (jsonb_array_length(key_points) <= 50))),
    CONSTRAINT ck_journal_entries_summary CHECK (((summary IS NULL) OR (length(summary) <= 10000))),
    CONSTRAINT ck_journal_entries_title CHECK ((length(btrim((title)::text)) > 0)),
    CONSTRAINT ck_journal_entries_version CHECK ((version >= 1))
);

-- TABLE: journal_entry_contacts
CREATE TABLE sidekick.journal_entry_contacts (
    owner_id uuid NOT NULL,
    entry_id uuid NOT NULL,
    contact_id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL
);

-- TABLE: journal_entry_projects
CREATE TABLE sidekick.journal_entry_projects (
    owner_id uuid NOT NULL,
    entry_id uuid NOT NULL,
    project_id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL
);

-- TABLE: journal_entry_tasks
CREATE TABLE sidekick.journal_entry_tasks (
    owner_id uuid NOT NULL,
    entry_id uuid NOT NULL,
    task_id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL
);

-- TABLE: journal_processing_runs
CREATE TABLE sidekick.journal_processing_runs (
    id uuid NOT NULL,
    owner_id uuid NOT NULL,
    source_id uuid,
    operation character varying(24) NOT NULL,
    journal_date date NOT NULL,
    status character varying(16) NOT NULL,
    provider character varying(64) NOT NULL,
    model_id character varying(200) NOT NULL,
    prompt_version character varying(64) NOT NULL,
    schema_version character varying(64) NOT NULL,
    input_fingerprint character(64) NOT NULL,
    candidate_catalog jsonb NOT NULL,
    provider_response_id character varying(200),
    failure_category character varying(40),
    input_tokens integer,
    output_tokens integer,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    lease_expires_at timestamp with time zone,
    attempt_count integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_journal_processing_runs_attempt_count CHECK (((attempt_count >= 1) AND (attempt_count <= 100))),
    CONSTRAINT ck_journal_processing_runs_catalog CHECK ((jsonb_typeof(candidate_catalog) = 'object'::text)),
    CONSTRAINT ck_journal_processing_runs_failure CHECK (((failure_category IS NULL) OR (failure_category IN ('provider_configuration', 'provider_timeout', 'provider_unavailable', 'model_unavailable', 'invalid_provider_response', 'invalid_model_output')))),
    CONSTRAINT ck_journal_processing_runs_fingerprint CHECK ((input_fingerprint ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT ck_journal_processing_runs_input_tokens CHECK (((input_tokens IS NULL) OR (input_tokens >= 0))),
    CONSTRAINT ck_journal_processing_runs_model CHECK ((length(btrim((model_id)::text)) > 0)),
    CONSTRAINT ck_journal_processing_runs_operation CHECK ((operation IN ('entry_draft', 'daily_summary'))),
    CONSTRAINT ck_journal_processing_runs_output_tokens CHECK (((output_tokens IS NULL) OR (output_tokens >= 0))),
    CONSTRAINT ck_journal_processing_runs_prompt_version CHECK ((length(btrim((prompt_version)::text)) > 0)),
    CONSTRAINT ck_journal_processing_runs_provider CHECK ((length(btrim((provider)::text)) > 0)),
    CONSTRAINT ck_journal_processing_runs_schema_version CHECK ((length(btrim((schema_version)::text)) > 0)),
    CONSTRAINT ck_journal_processing_runs_source_operation CHECK (((((operation)::text = 'entry_draft'::text) AND (source_id IS NOT NULL)) OR (((operation)::text = 'daily_summary'::text) AND (source_id IS NULL)))),
    CONSTRAINT ck_journal_processing_runs_status CHECK ((status IN ('pending', 'running', 'succeeded', 'failed'))),
    CONSTRAINT ck_journal_processing_runs_timing CHECK (((finished_at IS NULL) OR (started_at IS NULL) OR (finished_at >= started_at)))
);

-- TABLE: journal_sources
CREATE TABLE sidekick.journal_sources (
    id uuid NOT NULL,
    owner_id uuid NOT NULL,
    source_type character varying(24) NOT NULL,
    journal_date date NOT NULL,
    occurred_at timestamp with time zone,
    source_recorded_at timestamp with time zone,
    raw_text text NOT NULL,
    content_fingerprint character(64) NOT NULL,
    language character varying(35),
    replaces_source_id uuid,
    created_at timestamp with time zone NOT NULL,
    trashed_at timestamp with time zone,
    search_vector tsvector GENERATED ALWAYS AS (setweight(to_tsvector('swedish'::regconfig, COALESCE(raw_text, ''::text)), 'C'::"char")) STORED,
    CONSTRAINT ck_journal_sources_fingerprint CHECK ((content_fingerprint ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT ck_journal_sources_language CHECK (((language IS NULL) OR ((length((language)::text) >= 2) AND (length((language)::text) <= 35)))),
    CONSTRAINT ck_journal_sources_not_self_replacement CHECK (((replaces_source_id IS NULL) OR (replaces_source_id <> id))),
    CONSTRAINT ck_journal_sources_raw_text CHECK (((length(raw_text) BETWEEN 1 AND 100000) AND (length(btrim(raw_text)) > 0))),
    CONSTRAINT ck_journal_sources_type CHECK ((source_type IN ('manual_text', 'transcript_text')))
);

-- TABLE: journal_summary_proposals
CREATE TABLE sidekick.journal_summary_proposals (
    id uuid NOT NULL,
    owner_id uuid NOT NULL,
    run_id uuid NOT NULL,
    journal_date date NOT NULL,
    entry_fingerprint character(64) NOT NULL,
    content jsonb NOT NULL,
    state character varying(24) NOT NULL,
    version integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    lifecycle_at timestamp with time zone,
    CONSTRAINT ck_journal_summary_proposals_content CHECK ((jsonb_typeof(content) = 'object'::text)),
    CONSTRAINT ck_journal_summary_proposals_fingerprint CHECK ((entry_fingerprint ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT ck_journal_summary_proposals_state CHECK ((state IN ('pending_review', 'accepted', 'rejected', 'superseded'))),
    CONSTRAINT ck_journal_summary_proposals_version CHECK ((version >= 1))
);

-- TABLE: memory_settings
CREATE TABLE sidekick.memory_settings (
    owner_id uuid NOT NULL,
    journal boolean DEFAULT true NOT NULL,
    contacts boolean DEFAULT true NOT NULL,
    projects boolean DEFAULT true NOT NULL,
    tasks boolean DEFAULT true NOT NULL,
    paused boolean DEFAULT false NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT memory_settings_version_check CHECK ((version >= 1))
);

-- TABLE: memory_sources
CREATE TABLE sidekick.memory_sources (
    id uuid NOT NULL,
    owner_id uuid NOT NULL,
    source_kind character varying(20) NOT NULL,
    source_id uuid NOT NULL,
    doc_key character varying(128) NOT NULL,
    fingerprint character(64) NOT NULL,
    pipeline_version integer NOT NULL,
    status character varying(16) NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    next_attempt_at timestamp with time zone,
    operation_id character varying(200),
    source_updated_at timestamp with time zone NOT NULL,
    retained_at timestamp with time zone,
    failure_category character varying(40),
    excluded boolean DEFAULT false NOT NULL,
    CONSTRAINT ck_memory_sources_failed CHECK (((status NOT IN ('failed', 'parked')) OR (failure_category IS NOT NULL))),
    CONSTRAINT ck_memory_sources_retained CHECK ((((status)::text <> 'retained'::text) OR (retained_at IS NOT NULL))),
    CONSTRAINT ck_memory_sources_submitted CHECK ((((status)::text <> 'submitted'::text) OR (operation_id IS NOT NULL))),
    CONSTRAINT memory_sources_attempts_check CHECK ((attempts >= 0)),
    CONSTRAINT memory_sources_doc_key_check CHECK ((length(btrim((doc_key)::text)) > 0)),
    CONSTRAINT memory_sources_fingerprint_check CHECK ((fingerprint ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT memory_sources_pipeline_version_check CHECK ((pipeline_version >= 1)),
    CONSTRAINT memory_sources_source_kind_check CHECK ((source_kind IN ('journal_entry', 'contact', 'project', 'task'))),
    CONSTRAINT memory_sources_status_check CHECK ((status IN ('pending', 'submitted', 'retained', 'failed', 'parked')))
);

-- TABLE: memory_usage_daily
CREATE TABLE sidekick.memory_usage_daily (
    owner_id uuid NOT NULL,
    usage_date date NOT NULL,
    retain_documents integer DEFAULT 0 NOT NULL,
    backfill_documents integer DEFAULT 0 NOT NULL,
    characters bigint DEFAULT 0 NOT NULL,
    CONSTRAINT memory_usage_daily_backfill_documents_check CHECK ((backfill_documents >= 0)),
    CONSTRAINT memory_usage_daily_characters_check CHECK ((characters >= 0)),
    CONSTRAINT memory_usage_daily_retain_documents_check CHECK ((retain_documents >= 0))
);

-- TABLE: personal_access_tokens
CREATE TABLE sidekick.personal_access_tokens (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    label character varying(120) NOT NULL,
    token_digest character(64) NOT NULL,
    scopes jsonb NOT NULL,
    expires_at timestamp with time zone,
    revoked_at timestamp with time zone,
    last_used_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    purpose character varying(20) DEFAULT 'mcp'::character varying NOT NULL,
    previous_token_digest character(64),
    previous_valid_until timestamp with time zone,
    CONSTRAINT ck_personal_access_tokens_companion_expiry CHECK ((((purpose)::text <> 'companion'::text) OR (expires_at IS NOT NULL))),
    CONSTRAINT ck_personal_access_tokens_previous_pair CHECK (((previous_token_digest IS NULL) = (previous_valid_until IS NULL))),
    CONSTRAINT ck_personal_access_tokens_purpose CHECK ((purpose IN ('mcp', 'companion')))
);

-- TABLE: process_run_outbox
CREATE TABLE sidekick.process_run_outbox (
    id uuid NOT NULL,
    owner_id uuid NOT NULL,
    process_id uuid NOT NULL,
    scheduled_for timestamp with time zone NOT NULL,
    status character varying(16) DEFAULT 'queued'::character varying NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    worker_id character varying(120),
    claimed_at timestamp with time zone,
    processed_at timestamp with time zone,
    process_run_id uuid,
    last_error character varying(120),
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_process_run_outbox_attempts CHECK ((attempts >= 0)),
    CONSTRAINT ck_process_run_outbox_processed CHECK ((((status)::text <> 'delivered'::text) OR ((processed_at IS NOT NULL) AND (process_run_id IS NOT NULL)))),
    CONSTRAINT ck_process_run_outbox_processing CHECK ((((status)::text <> 'processing'::text) OR ((worker_id IS NOT NULL) AND (claimed_at IS NOT NULL)))),
    CONSTRAINT ck_process_run_outbox_status CHECK ((status IN ('queued', 'processing', 'delivered', 'failed')))
);

-- TABLE: process_run_templates
CREATE TABLE sidekick.process_run_templates (
    id uuid NOT NULL,
    owner_id uuid NOT NULL,
    process_id uuid NOT NULL,
    title character varying(200) NOT NULL,
    description text,
    priority character varying(20) DEFAULT 'normal'::character varying NOT NULL,
    estimated_minutes integer,
    due_after_days integer DEFAULT 0 NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    structure jsonb DEFAULT '[]'::jsonb NOT NULL,
    CONSTRAINT ck_process_run_templates_due_after CHECK (((due_after_days >= 0) AND (due_after_days <= 365))),
    CONSTRAINT ck_process_run_templates_estimate CHECK (((estimated_minutes IS NULL) OR ((estimated_minutes >= 1) AND (estimated_minutes <= 12000)))),
    CONSTRAINT ck_process_run_templates_priority CHECK ((priority IN ('low', 'normal', 'high', 'urgent'))),
    CONSTRAINT ck_process_run_templates_structure CHECK ((jsonb_typeof(structure) = 'array'::text)),
    CONSTRAINT ck_process_run_templates_version CHECK ((version >= 1))
);

-- TABLE: process_runs
CREATE TABLE sidekick.process_runs (
    id uuid NOT NULL,
    owner_id uuid NOT NULL,
    process_id uuid NOT NULL,
    task_id uuid NOT NULL,
    scheduled_for timestamp with time zone NOT NULL,
    template_version integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_process_runs_template_version CHECK ((template_version >= 1))
);

-- TABLE: process_tags
CREATE TABLE sidekick.process_tags (
    owner_id uuid NOT NULL,
    tag_id uuid NOT NULL,
    process_id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL
);

-- TABLE: processes
CREATE TABLE sidekick.processes (
    id uuid NOT NULL,
    owner_id uuid NOT NULL,
    domain_id uuid NOT NULL,
    name character varying(200) NOT NULL,
    description text,
    status character varying(20) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    version integer NOT NULL,
    cadence character varying(12),
    trashed_at timestamp with time zone,
    next_expected_run_at timestamp with time zone,
    CONSTRAINT ck_processes_cadence CHECK (((cadence IS NULL) OR (cadence IN ('daily', 'weekly', 'biweekly', 'monthly', 'quarterly', 'yearly')))),
    CONSTRAINT ck_processes_name CHECK (((length(btrim((name)::text)) >= 1) AND (length(btrim((name)::text)) <= 200))),
    CONSTRAINT ck_processes_status CHECK ((status IN ('active', 'paused', 'completed', 'archived'))),
    CONSTRAINT ck_processes_version CHECK ((version >= 1))
);

-- TABLE: project_contacts
CREATE TABLE sidekick.project_contacts (
    owner_id uuid NOT NULL,
    project_id uuid NOT NULL,
    contact_id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL
);

-- TABLE: project_tags
CREATE TABLE sidekick.project_tags (
    owner_id uuid NOT NULL,
    tag_id uuid NOT NULL,
    project_id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL
);

-- TABLE: projects
CREATE TABLE sidekick.projects (
    id uuid NOT NULL,
    owner_id uuid NOT NULL,
    title character varying(200) NOT NULL,
    description text,
    status character varying(20) NOT NULL,
    start_date date,
    target_date date,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    archived_at timestamp with time zone,
    version integer NOT NULL,
    domain_id uuid NOT NULL,
    definition_of_done text,
    trashed_at timestamp with time zone,
    search_vector tsvector GENERATED ALWAYS AS ((setweight(to_tsvector('simple'::regconfig, (COALESCE(title, ''::character varying))::text), 'A'::"char") || setweight(to_tsvector('swedish'::regconfig, COALESCE(description, ''::text)), 'B'::"char"))) STORED,
    CONSTRAINT ck_projects_definition_of_done CHECK (((definition_of_done IS NULL) OR (length(definition_of_done) <= 2000))),
    CONSTRAINT projects_check CHECK (((target_date IS NULL) OR (start_date IS NULL) OR (target_date >= start_date))),
    CONSTRAINT projects_status_check CHECK ((status IN ('active', 'paused', 'completed'))),
    CONSTRAINT projects_title_check CHECK ((length(btrim((title)::text)) > 0)),
    CONSTRAINT projects_version_check CHECK ((version > 0))
);

-- TABLE: push_outbox
CREATE TABLE sidekick.push_outbox (
    id uuid NOT NULL,
    subscription_id uuid NOT NULL,
    kind character varying(1) NOT NULL,
    dedup_key character varying(128) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    next_attempt_at timestamp with time zone,
    attempts integer DEFAULT 0 NOT NULL,
    delivered_at timestamp with time zone,
    last_error_kind character varying(32),
    CONSTRAINT push_outbox_attempts_check CHECK ((attempts >= 0)),
    CONSTRAINT push_outbox_dedup_key_check CHECK ((length((dedup_key)::text) > 0)),
    CONSTRAINT push_outbox_kind_check CHECK ((kind IN ('w', 'r')))
);

-- TABLE: push_reminders
CREATE TABLE sidekick.push_reminders (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    kind character varying(7) NOT NULL,
    task_id uuid,
    dedup_key character varying(128) NOT NULL,
    payload_title character varying(200),
    summary_today integer,
    summary_overdue integer,
    due_at timestamp with time zone,
    scheduled_for timestamp with time zone NOT NULL,
    created_at timestamp with time zone NOT NULL,
    acked_at timestamp with time zone,
    CONSTRAINT ck_push_reminders_shape CHECK (((((kind)::text = 'summary'::text) AND (summary_today IS NOT NULL) AND (summary_overdue IS NOT NULL) AND (task_id IS NULL)) OR (((kind)::text = 'due'::text) AND (task_id IS NOT NULL) AND (payload_title IS NOT NULL) AND (due_at IS NOT NULL)) OR (((kind)::text = 'test'::text) AND (task_id IS NULL) AND (payload_title IS NOT NULL)))),
    CONSTRAINT push_reminders_dedup_key_check CHECK ((length((dedup_key)::text) > 0)),
    CONSTRAINT push_reminders_kind_check CHECK ((kind IN ('summary', 'due', 'test'))),
    CONSTRAINT push_reminders_summary_overdue_check CHECK ((summary_overdue >= 0)),
    CONSTRAINT push_reminders_summary_today_check CHECK ((summary_today >= 0))
);

-- TABLE: push_subscriptions
CREATE TABLE sidekick.push_subscriptions (
    id uuid NOT NULL,
    pairing_id uuid NOT NULL,
    user_id uuid NOT NULL,
    endpoint text NOT NULL,
    endpoint_host character varying(253) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    revoked_at timestamp with time zone,
    last_success_at timestamp with time zone,
    failure_count integer DEFAULT 0 NOT NULL,
    CONSTRAINT push_subscriptions_endpoint_check CHECK ((length(endpoint) BETWEEN 1 AND 512)),
    CONSTRAINT push_subscriptions_endpoint_host_check CHECK ((length((endpoint_host)::text) > 0)),
    CONSTRAINT push_subscriptions_failure_count_check CHECK ((failure_count >= 0))
);

-- TABLE: saved_work_views
CREATE TABLE sidekick.saved_work_views (
    id uuid NOT NULL,
    owner_id uuid NOT NULL,
    name character varying(120) NOT NULL,
    definition jsonb NOT NULL,
    version integer NOT NULL,
    archived_at timestamp with time zone,
    CONSTRAINT ck_saved_work_views_definition CHECK (((jsonb_typeof(definition) = 'object'::text) AND (octet_length((definition)::text) <= 8192))),
    CONSTRAINT ck_saved_work_views_name CHECK (((length(btrim((name)::text)) >= 1) AND (length(btrim((name)::text)) <= 120))),
    CONSTRAINT ck_saved_work_views_version CHECK ((version >= 1))
);

-- TABLE: sessions
CREATE TABLE sidekick.sessions (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    token_digest character(64) NOT NULL,
    csrf_digest character(64) NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    revoked_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL
);

-- TABLE: shopping_item_status_history
CREATE TABLE sidekick.shopping_item_status_history (
    id uuid NOT NULL,
    owner_id uuid NOT NULL,
    item_id uuid NOT NULL,
    purchased boolean NOT NULL,
    item_version integer NOT NULL,
    changed_at timestamp with time zone NOT NULL,
    CONSTRAINT shopping_item_status_history_item_version_check CHECK ((item_version > 0))
);

-- TABLE: shopping_items
CREATE TABLE sidekick.shopping_items (
    id uuid NOT NULL,
    owner_id uuid NOT NULL,
    list_id uuid NOT NULL,
    name character varying(200) NOT NULL,
    quantity numeric(9,3) NOT NULL,
    unit character varying(30),
    note character varying(2000),
    store character varying(200),
    product_url character varying(2000),
    recipient_contact_id uuid,
    occasion character varying(200),
    target_date date,
    offer_price numeric(10,2),
    offer_regular_price numeric(10,2),
    offer_currency character varying(3),
    offer_source character varying(200),
    offer_source_url character varying(2000),
    offer_valid_from date,
    offer_valid_until date,
    offer_checked_on date,
    purchased boolean DEFAULT false NOT NULL,
    purchased_at timestamp with time zone,
    version integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    trashed_at timestamp with time zone,
    CONSTRAINT shopping_items_check CHECK ((purchased = (purchased_at IS NOT NULL))),
    CONSTRAINT shopping_items_check1 CHECK ((((offer_price IS NULL) AND (offer_regular_price IS NULL) AND (offer_currency IS NULL) AND (offer_source IS NULL) AND (offer_source_url IS NULL) AND (offer_valid_from IS NULL) AND (offer_valid_until IS NULL) AND (offer_checked_on IS NULL)) OR ((offer_price IS NOT NULL) AND (offer_price > (0)::numeric) AND (offer_currency IS NOT NULL) AND ((offer_currency)::text ~ '^[A-Z]{3}$'::text) AND (offer_source IS NOT NULL) AND (length(btrim((offer_source)::text)) > 0) AND (offer_valid_from IS NOT NULL) AND (offer_valid_until IS NOT NULL) AND (offer_checked_on IS NOT NULL) AND (offer_valid_until >= offer_valid_from) AND ((offer_regular_price IS NULL) OR (offer_regular_price > offer_price))))),
    CONSTRAINT shopping_items_name_check CHECK ((length(btrim((name)::text)) > 0)),
    CONSTRAINT shopping_items_quantity_check CHECK ((quantity > (0)::numeric)),
    CONSTRAINT shopping_items_version_check CHECK ((version > 0))
);

-- TABLE: shopping_lists
CREATE TABLE sidekick.shopping_lists (
    id uuid NOT NULL,
    owner_id uuid NOT NULL,
    name character varying(200) NOT NULL,
    archived boolean DEFAULT false NOT NULL,
    version integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT shopping_lists_name_check CHECK ((length(btrim((name)::text)) > 0)),
    CONSTRAINT shopping_lists_version_check CHECK ((version > 0))
);

-- TABLE: steps
CREATE TABLE sidekick.steps (
    id uuid NOT NULL,
    owner_id uuid NOT NULL,
    task_id uuid NOT NULL,
    title character varying(200) NOT NULL,
    status character varying(20) NOT NULL,
    "position" integer NOT NULL,
    due_at timestamp with time zone,
    attention_requested boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    version integer NOT NULL,
    archived_at timestamp with time zone,
    instruction text,
    trashed_at timestamp with time zone,
    completed_at timestamp with time zone,
    CONSTRAINT ck_steps_instruction CHECK (((instruction IS NULL) OR (length(instruction) <= 2000))),
    CONSTRAINT ck_steps_position CHECK (("position" >= 0)),
    CONSTRAINT ck_steps_title CHECK (((length(btrim((title)::text)) >= 1) AND (length(btrim((title)::text)) <= 200))),
    CONSTRAINT ck_steps_version CHECK ((version >= 1))
);

-- TABLE: task_contacts
CREATE TABLE sidekick.task_contacts (
    owner_id uuid NOT NULL,
    task_id uuid NOT NULL,
    contact_id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL
);

-- TABLE: task_external_references
CREATE TABLE sidekick.task_external_references (
    owner_id uuid NOT NULL,
    task_id uuid NOT NULL,
    reference_id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL
);

-- TABLE: task_status_history
CREATE TABLE sidekick.task_status_history (
    id uuid NOT NULL,
    owner_id uuid NOT NULL,
    task_id uuid NOT NULL,
    from_status character varying(20),
    to_status character varying(20) NOT NULL,
    changed_at timestamp with time zone NOT NULL,
    source character varying(32) NOT NULL,
    CONSTRAINT ck_task_status_history_from_status CHECK (((from_status IS NULL) OR (from_status IN ('todo', 'in_progress', 'blocked', 'completed')))),
    CONSTRAINT ck_task_status_history_to_status CHECK ((to_status IN ('todo', 'in_progress', 'blocked', 'completed')))
);

-- TABLE: task_tags
CREATE TABLE sidekick.task_tags (
    owner_id uuid NOT NULL,
    tag_id uuid NOT NULL,
    task_id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL
);

-- TABLE: tasks
CREATE TABLE sidekick.tasks (
    id uuid NOT NULL,
    owner_id uuid NOT NULL,
    project_id uuid,
    title character varying(200) NOT NULL,
    description text,
    status character varying(20) NOT NULL,
    priority character varying(20) NOT NULL,
    due_at timestamp with time zone,
    completed_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    archived_at timestamp with time zone,
    version integer NOT NULL,
    domain_id uuid,
    process_id uuid,
    attention_requested boolean DEFAULT false NOT NULL,
    board_rank integer,
    not_before timestamp with time zone,
    estimated_minutes integer,
    waiting_since timestamp with time zone,
    follow_up_at timestamp with time zone,
    waiting_on_contact_id uuid,
    blocked_reminder_cadence character varying(12),
    blocked_reminder_snoozed_until timestamp with time zone,
    blocked_last_reminded_at timestamp with time zone,
    recurrence jsonb,
    last_completed_at timestamp with time zone,
    trashed_at timestamp with time zone,
    search_vector tsvector GENERATED ALWAYS AS ((setweight(to_tsvector('simple'::regconfig, (COALESCE(title, ''::character varying))::text), 'A'::"char") || setweight(to_tsvector('swedish'::regconfig, COALESCE(description, ''::text)), 'B'::"char"))) STORED,
    CONSTRAINT ck_tasks_blocked_reminder_cadence CHECK (((blocked_reminder_cadence IS NULL) OR (blocked_reminder_cadence IN ('daily', 'weekly', 'biweekly', 'monthly', 'quarterly', 'yearly')))),
    CONSTRAINT ck_tasks_context_xor CHECK ((((
CASE
    WHEN (project_id IS NOT NULL) THEN 1
    ELSE 0
END +
CASE
    WHEN (domain_id IS NOT NULL) THEN 1
    ELSE 0
END) +
CASE
    WHEN (process_id IS NOT NULL) THEN 1
    ELSE 0
END) <= 1)),
    CONSTRAINT ck_tasks_estimated_minutes CHECK (((estimated_minutes IS NULL) OR ((estimated_minutes > 0) AND (estimated_minutes <= 12000)))),
    CONSTRAINT ck_tasks_not_before_due_at CHECK (((not_before IS NULL) OR (due_at IS NULL) OR (not_before <= due_at))),
    CONSTRAINT ck_tasks_recurrence_object CHECK (((recurrence IS NULL) OR (jsonb_typeof(recurrence) = 'object'::text))),
    CONSTRAINT ck_tasks_waiting_coherent CHECK (((waiting_since IS NOT NULL) OR ((follow_up_at IS NULL) AND (waiting_on_contact_id IS NULL)))),
    CONSTRAINT tasks_board_rank_check CHECK (((board_rank IS NULL) OR (board_rank > 0))),
    CONSTRAINT tasks_check CHECK ((((status)::text = 'completed'::text) = (completed_at IS NOT NULL))),
    CONSTRAINT tasks_priority_check CHECK ((priority IN ('low', 'normal', 'high', 'urgent'))),
    CONSTRAINT tasks_status_check CHECK ((status IN ('todo', 'in_progress', 'blocked', 'completed'))),
    CONSTRAINT tasks_title_check CHECK ((length(btrim((title)::text)) > 0)),
    CONSTRAINT tasks_version_check CHECK ((version > 0))
);

-- TABLE: users
CREATE TABLE sidekick.users (
    id uuid NOT NULL,
    username character varying(120) NOT NULL,
    display_name character varying(120) NOT NULL,
    password_hash text NOT NULL,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone NOT NULL
);

-- TABLE: work_tags
CREATE TABLE sidekick.work_tags (
    id uuid NOT NULL,
    owner_id uuid NOT NULL,
    slug character varying(60) NOT NULL,
    label character varying(40) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    archived_at timestamp with time zone,
    version integer NOT NULL,
    CONSTRAINT ck_work_tags_label CHECK (((length(btrim((label)::text)) >= 1) AND (length(btrim((label)::text)) <= 40))),
    CONSTRAINT ck_work_tags_slug CHECK ((((slug)::text = btrim((slug)::text)) AND ((length((slug)::text) >= 1) AND (length((slug)::text) <= 60)))),
    CONSTRAINT ck_work_tags_version CHECK ((version >= 1))
);

-- CONSTRAINT: actions actions_pkey
ALTER TABLE ONLY sidekick.actions
    ADD CONSTRAINT actions_pkey PRIMARY KEY (id);

-- CONSTRAINT: activity_entries activity_entries_domain_event_id_key
ALTER TABLE ONLY sidekick.activity_entries
    ADD CONSTRAINT activity_entries_domain_event_id_key UNIQUE (domain_event_id);

-- CONSTRAINT: activity_entries activity_entries_pkey
ALTER TABLE ONLY sidekick.activity_entries
    ADD CONSTRAINT activity_entries_pkey PRIMARY KEY (id);

-- CONSTRAINT: assistant_automation_control assistant_automation_control_pkey
ALTER TABLE ONLY sidekick.assistant_automation_control
    ADD CONSTRAINT assistant_automation_control_pkey PRIMARY KEY (owner_id);

-- CONSTRAINT: assistant_automation_policies assistant_automation_policies_pkey
ALTER TABLE ONLY sidekick.assistant_automation_policies
    ADD CONSTRAINT assistant_automation_policies_pkey PRIMARY KEY (owner_id, category);

-- CONSTRAINT: assistant_automation_runs assistant_automation_runs_pkey
ALTER TABLE ONLY sidekick.assistant_automation_runs
    ADD CONSTRAINT assistant_automation_runs_pkey PRIMARY KEY (id);

-- CONSTRAINT: assistant_task_review_findings assistant_task_review_findings_pkey
ALTER TABLE ONLY sidekick.assistant_task_review_findings
    ADD CONSTRAINT assistant_task_review_findings_pkey PRIMARY KEY (id);

-- CONSTRAINT: audit_events audit_events_pkey
ALTER TABLE ONLY sidekick.audit_events
    ADD CONSTRAINT audit_events_pkey PRIMARY KEY (id);

-- CONSTRAINT: companion_pairings companion_pairings_pkey
ALTER TABLE ONLY sidekick.companion_pairings
    ADD CONSTRAINT companion_pairings_pkey PRIMARY KEY (id);

-- CONSTRAINT: contact_aliases contact_aliases_pkey
ALTER TABLE ONLY sidekick.contact_aliases
    ADD CONSTRAINT contact_aliases_pkey PRIMARY KEY (id);

-- CONSTRAINT: contacts contacts_pkey
ALTER TABLE ONLY sidekick.contacts
    ADD CONSTRAINT contacts_pkey PRIMARY KEY (id);

-- CONSTRAINT: daily_journal_summaries daily_journal_summaries_pkey
ALTER TABLE ONLY sidekick.daily_journal_summaries
    ADD CONSTRAINT daily_journal_summaries_pkey PRIMARY KEY (id);

-- CONSTRAINT: daily_journal_summary_entries daily_journal_summary_entries_pkey
ALTER TABLE ONLY sidekick.daily_journal_summary_entries
    ADD CONSTRAINT daily_journal_summary_entries_pkey PRIMARY KEY (owner_id, summary_id, entry_id);

-- CONSTRAINT: domain_events domain_events_pkey
ALTER TABLE ONLY sidekick.domain_events
    ADD CONSTRAINT domain_events_pkey PRIMARY KEY (id);

-- CONSTRAINT: domain_tags domain_tags_pkey
ALTER TABLE ONLY sidekick.domain_tags
    ADD CONSTRAINT domain_tags_pkey PRIMARY KEY (owner_id, tag_id, domain_id);

-- CONSTRAINT: domains domains_pkey
ALTER TABLE ONLY sidekick.domains
    ADD CONSTRAINT domains_pkey PRIMARY KEY (id);

-- CONSTRAINT: external_references external_references_id_owner_id_key
ALTER TABLE ONLY sidekick.external_references
    ADD CONSTRAINT external_references_id_owner_id_key UNIQUE (id, owner_id);

-- CONSTRAINT: external_references external_references_pkey
ALTER TABLE ONLY sidekick.external_references
    ADD CONSTRAINT external_references_pkey PRIMARY KEY (id);

-- CONSTRAINT: idempotency_operations idempotency_operations_pkey
ALTER TABLE ONLY sidekick.idempotency_operations
    ADD CONSTRAINT idempotency_operations_pkey PRIMARY KEY (id);

-- CONSTRAINT: instance_license instance_license_pkey
ALTER TABLE ONLY sidekick.instance_license
    ADD CONSTRAINT instance_license_pkey PRIMARY KEY (id);

-- CONSTRAINT: journal_drafts journal_drafts_pkey
ALTER TABLE ONLY sidekick.journal_drafts
    ADD CONSTRAINT journal_drafts_pkey PRIMARY KEY (id);

-- CONSTRAINT: journal_entries journal_entries_pkey
ALTER TABLE ONLY sidekick.journal_entries
    ADD CONSTRAINT journal_entries_pkey PRIMARY KEY (id);

-- CONSTRAINT: journal_entry_contacts journal_entry_contacts_pkey
ALTER TABLE ONLY sidekick.journal_entry_contacts
    ADD CONSTRAINT journal_entry_contacts_pkey PRIMARY KEY (owner_id, entry_id, contact_id);

-- CONSTRAINT: journal_entry_projects journal_entry_projects_pkey
ALTER TABLE ONLY sidekick.journal_entry_projects
    ADD CONSTRAINT journal_entry_projects_pkey PRIMARY KEY (owner_id, entry_id, project_id);

-- CONSTRAINT: journal_entry_tasks journal_entry_tasks_pkey
ALTER TABLE ONLY sidekick.journal_entry_tasks
    ADD CONSTRAINT journal_entry_tasks_pkey PRIMARY KEY (owner_id, entry_id, task_id);

-- CONSTRAINT: journal_processing_runs journal_processing_runs_pkey
ALTER TABLE ONLY sidekick.journal_processing_runs
    ADD CONSTRAINT journal_processing_runs_pkey PRIMARY KEY (id);

-- CONSTRAINT: journal_sources journal_sources_pkey
ALTER TABLE ONLY sidekick.journal_sources
    ADD CONSTRAINT journal_sources_pkey PRIMARY KEY (id);

-- CONSTRAINT: journal_summary_proposals journal_summary_proposals_pkey
ALTER TABLE ONLY sidekick.journal_summary_proposals
    ADD CONSTRAINT journal_summary_proposals_pkey PRIMARY KEY (id);

-- CONSTRAINT: memory_settings memory_settings_pkey
ALTER TABLE ONLY sidekick.memory_settings
    ADD CONSTRAINT memory_settings_pkey PRIMARY KEY (owner_id);

-- CONSTRAINT: memory_sources memory_sources_pkey
ALTER TABLE ONLY sidekick.memory_sources
    ADD CONSTRAINT memory_sources_pkey PRIMARY KEY (id);

-- CONSTRAINT: memory_usage_daily memory_usage_daily_pkey
ALTER TABLE ONLY sidekick.memory_usage_daily
    ADD CONSTRAINT memory_usage_daily_pkey PRIMARY KEY (owner_id, usage_date);

-- CONSTRAINT: personal_access_tokens personal_access_tokens_pkey
ALTER TABLE ONLY sidekick.personal_access_tokens
    ADD CONSTRAINT personal_access_tokens_pkey PRIMARY KEY (id);

-- CONSTRAINT: personal_access_tokens personal_access_tokens_token_digest_key
ALTER TABLE ONLY sidekick.personal_access_tokens
    ADD CONSTRAINT personal_access_tokens_token_digest_key UNIQUE (token_digest);

-- CONSTRAINT: process_run_outbox process_run_outbox_pkey
ALTER TABLE ONLY sidekick.process_run_outbox
    ADD CONSTRAINT process_run_outbox_pkey PRIMARY KEY (id);

-- CONSTRAINT: process_run_templates process_run_templates_pkey
ALTER TABLE ONLY sidekick.process_run_templates
    ADD CONSTRAINT process_run_templates_pkey PRIMARY KEY (id);

-- CONSTRAINT: process_runs process_runs_pkey
ALTER TABLE ONLY sidekick.process_runs
    ADD CONSTRAINT process_runs_pkey PRIMARY KEY (id);

-- CONSTRAINT: process_tags process_tags_pkey
ALTER TABLE ONLY sidekick.process_tags
    ADD CONSTRAINT process_tags_pkey PRIMARY KEY (owner_id, tag_id, process_id);

-- CONSTRAINT: processes processes_pkey
ALTER TABLE ONLY sidekick.processes
    ADD CONSTRAINT processes_pkey PRIMARY KEY (id);

-- CONSTRAINT: project_contacts project_contacts_pkey
ALTER TABLE ONLY sidekick.project_contacts
    ADD CONSTRAINT project_contacts_pkey PRIMARY KEY (owner_id, project_id, contact_id);

-- CONSTRAINT: project_tags project_tags_pkey
ALTER TABLE ONLY sidekick.project_tags
    ADD CONSTRAINT project_tags_pkey PRIMARY KEY (owner_id, tag_id, project_id);

-- CONSTRAINT: projects projects_pkey
ALTER TABLE ONLY sidekick.projects
    ADD CONSTRAINT projects_pkey PRIMARY KEY (id);

-- CONSTRAINT: push_outbox push_outbox_pkey
ALTER TABLE ONLY sidekick.push_outbox
    ADD CONSTRAINT push_outbox_pkey PRIMARY KEY (id);

-- CONSTRAINT: push_reminders push_reminders_pkey
ALTER TABLE ONLY sidekick.push_reminders
    ADD CONSTRAINT push_reminders_pkey PRIMARY KEY (id);

-- CONSTRAINT: push_subscriptions push_subscriptions_pkey
ALTER TABLE ONLY sidekick.push_subscriptions
    ADD CONSTRAINT push_subscriptions_pkey PRIMARY KEY (id);

-- CONSTRAINT: saved_work_views saved_work_views_pkey
ALTER TABLE ONLY sidekick.saved_work_views
    ADD CONSTRAINT saved_work_views_pkey PRIMARY KEY (id);

-- CONSTRAINT: sessions sessions_pkey
ALTER TABLE ONLY sidekick.sessions
    ADD CONSTRAINT sessions_pkey PRIMARY KEY (id);

-- CONSTRAINT: sessions sessions_token_digest_key
ALTER TABLE ONLY sidekick.sessions
    ADD CONSTRAINT sessions_token_digest_key UNIQUE (token_digest);

-- CONSTRAINT: shopping_item_status_history shopping_item_status_history_owner_id_item_id_item_version_key
ALTER TABLE ONLY sidekick.shopping_item_status_history
    ADD CONSTRAINT shopping_item_status_history_owner_id_item_id_item_version_key UNIQUE (owner_id, item_id, item_version);

-- CONSTRAINT: shopping_item_status_history shopping_item_status_history_pkey
ALTER TABLE ONLY sidekick.shopping_item_status_history
    ADD CONSTRAINT shopping_item_status_history_pkey PRIMARY KEY (id);

-- CONSTRAINT: shopping_items shopping_items_id_owner_id_key
ALTER TABLE ONLY sidekick.shopping_items
    ADD CONSTRAINT shopping_items_id_owner_id_key UNIQUE (id, owner_id);

-- CONSTRAINT: shopping_items shopping_items_pkey
ALTER TABLE ONLY sidekick.shopping_items
    ADD CONSTRAINT shopping_items_pkey PRIMARY KEY (id);

-- CONSTRAINT: shopping_lists shopping_lists_id_owner_id_key
ALTER TABLE ONLY sidekick.shopping_lists
    ADD CONSTRAINT shopping_lists_id_owner_id_key UNIQUE (id, owner_id);

-- CONSTRAINT: shopping_lists shopping_lists_pkey
ALTER TABLE ONLY sidekick.shopping_lists
    ADD CONSTRAINT shopping_lists_pkey PRIMARY KEY (id);

-- CONSTRAINT: steps steps_pkey
ALTER TABLE ONLY sidekick.steps
    ADD CONSTRAINT steps_pkey PRIMARY KEY (id);

-- CONSTRAINT: task_contacts task_contacts_pkey
ALTER TABLE ONLY sidekick.task_contacts
    ADD CONSTRAINT task_contacts_pkey PRIMARY KEY (owner_id, task_id, contact_id);

-- CONSTRAINT: task_external_references task_external_references_pkey
ALTER TABLE ONLY sidekick.task_external_references
    ADD CONSTRAINT task_external_references_pkey PRIMARY KEY (owner_id, task_id, reference_id);

-- CONSTRAINT: task_status_history task_status_history_pkey
ALTER TABLE ONLY sidekick.task_status_history
    ADD CONSTRAINT task_status_history_pkey PRIMARY KEY (id);

-- CONSTRAINT: task_tags task_tags_pkey
ALTER TABLE ONLY sidekick.task_tags
    ADD CONSTRAINT task_tags_pkey PRIMARY KEY (owner_id, tag_id, task_id);

-- CONSTRAINT: tasks tasks_pkey
ALTER TABLE ONLY sidekick.tasks
    ADD CONSTRAINT tasks_pkey PRIMARY KEY (id);

-- CONSTRAINT: actions uq_actions_id_owner
ALTER TABLE ONLY sidekick.actions
    ADD CONSTRAINT uq_actions_id_owner UNIQUE (id, owner_id);

-- CONSTRAINT: assistant_automation_runs uq_automation_runs_owner_kind_schedule
ALTER TABLE ONLY sidekick.assistant_automation_runs
    ADD CONSTRAINT uq_automation_runs_owner_kind_schedule UNIQUE (owner_id, kind, scheduled_for);

-- CONSTRAINT: contact_aliases uq_contact_aliases_key
ALTER TABLE ONLY sidekick.contact_aliases
    ADD CONSTRAINT uq_contact_aliases_key UNIQUE (owner_id, contact_id, normalized_key);

-- CONSTRAINT: contacts uq_contacts_id_owner
ALTER TABLE ONLY sidekick.contacts
    ADD CONSTRAINT uq_contacts_id_owner UNIQUE (id, owner_id);

-- CONSTRAINT: daily_journal_summaries uq_daily_journal_summaries_id_owner
ALTER TABLE ONLY sidekick.daily_journal_summaries
    ADD CONSTRAINT uq_daily_journal_summaries_id_owner UNIQUE (id, owner_id);

-- CONSTRAINT: daily_journal_summaries uq_daily_journal_summaries_owner_date
ALTER TABLE ONLY sidekick.daily_journal_summaries
    ADD CONSTRAINT uq_daily_journal_summaries_owner_date UNIQUE (owner_id, journal_date);

-- CONSTRAINT: daily_journal_summary_entries uq_daily_journal_summary_entries_ordinal
ALTER TABLE ONLY sidekick.daily_journal_summary_entries
    ADD CONSTRAINT uq_daily_journal_summary_entries_ordinal UNIQUE (owner_id, summary_id, ordinal);

-- CONSTRAINT: domain_events uq_domain_events_aggregate_version
ALTER TABLE ONLY sidekick.domain_events
    ADD CONSTRAINT uq_domain_events_aggregate_version UNIQUE (owner_id, aggregate_type, aggregate_id, aggregate_version);

-- CONSTRAINT: domains uq_domains_id_owner
ALTER TABLE ONLY sidekick.domains
    ADD CONSTRAINT uq_domains_id_owner UNIQUE (id, owner_id);

-- CONSTRAINT: idempotency_operations uq_idempotency_actor_operation_key
ALTER TABLE ONLY sidekick.idempotency_operations
    ADD CONSTRAINT uq_idempotency_actor_operation_key UNIQUE (actor_id, operation, idempotency_key);

-- CONSTRAINT: journal_drafts uq_journal_drafts_id_owner
ALTER TABLE ONLY sidekick.journal_drafts
    ADD CONSTRAINT uq_journal_drafts_id_owner UNIQUE (id, owner_id);

-- CONSTRAINT: journal_drafts uq_journal_drafts_processing_run
ALTER TABLE ONLY sidekick.journal_drafts
    ADD CONSTRAINT uq_journal_drafts_processing_run UNIQUE (processing_run_id);

-- CONSTRAINT: journal_entries uq_journal_entries_id_owner
ALTER TABLE ONLY sidekick.journal_entries
    ADD CONSTRAINT uq_journal_entries_id_owner UNIQUE (id, owner_id);

-- CONSTRAINT: journal_entries uq_journal_entries_owner_source
ALTER TABLE ONLY sidekick.journal_entries
    ADD CONSTRAINT uq_journal_entries_owner_source UNIQUE (owner_id, source_id);

-- CONSTRAINT: journal_processing_runs uq_journal_processing_runs_id_owner
ALTER TABLE ONLY sidekick.journal_processing_runs
    ADD CONSTRAINT uq_journal_processing_runs_id_owner UNIQUE (id, owner_id);

-- CONSTRAINT: journal_sources uq_journal_sources_id_owner
ALTER TABLE ONLY sidekick.journal_sources
    ADD CONSTRAINT uq_journal_sources_id_owner UNIQUE (id, owner_id);

-- CONSTRAINT: journal_summary_proposals uq_journal_summary_proposals_id_owner
ALTER TABLE ONLY sidekick.journal_summary_proposals
    ADD CONSTRAINT uq_journal_summary_proposals_id_owner UNIQUE (id, owner_id);

-- CONSTRAINT: journal_summary_proposals uq_journal_summary_proposals_run
ALTER TABLE ONLY sidekick.journal_summary_proposals
    ADD CONSTRAINT uq_journal_summary_proposals_run UNIQUE (run_id);

-- CONSTRAINT: memory_sources uq_memory_sources_doc_key
ALTER TABLE ONLY sidekick.memory_sources
    ADD CONSTRAINT uq_memory_sources_doc_key UNIQUE (doc_key);

-- CONSTRAINT: memory_sources uq_memory_sources_source
ALTER TABLE ONLY sidekick.memory_sources
    ADD CONSTRAINT uq_memory_sources_source UNIQUE (owner_id, source_kind, source_id);

-- CONSTRAINT: process_run_outbox uq_process_run_outbox_process_run
ALTER TABLE ONLY sidekick.process_run_outbox
    ADD CONSTRAINT uq_process_run_outbox_process_run UNIQUE (process_run_id);

-- CONSTRAINT: process_run_outbox uq_process_run_outbox_schedule
ALTER TABLE ONLY sidekick.process_run_outbox
    ADD CONSTRAINT uq_process_run_outbox_schedule UNIQUE (owner_id, process_id, scheduled_for);

-- CONSTRAINT: process_run_templates uq_process_run_templates_process_owner
ALTER TABLE ONLY sidekick.process_run_templates
    ADD CONSTRAINT uq_process_run_templates_process_owner UNIQUE (process_id, owner_id);

-- CONSTRAINT: process_runs uq_process_runs_process_schedule
ALTER TABLE ONLY sidekick.process_runs
    ADD CONSTRAINT uq_process_runs_process_schedule UNIQUE (owner_id, process_id, scheduled_for);

-- CONSTRAINT: process_runs uq_process_runs_task_owner
ALTER TABLE ONLY sidekick.process_runs
    ADD CONSTRAINT uq_process_runs_task_owner UNIQUE (task_id, owner_id);

-- CONSTRAINT: processes uq_processes_id_owner
ALTER TABLE ONLY sidekick.processes
    ADD CONSTRAINT uq_processes_id_owner UNIQUE (id, owner_id);

-- CONSTRAINT: projects uq_projects_id_owner
ALTER TABLE ONLY sidekick.projects
    ADD CONSTRAINT uq_projects_id_owner UNIQUE (id, owner_id);

-- CONSTRAINT: push_reminders uq_push_reminders_dedup
ALTER TABLE ONLY sidekick.push_reminders
    ADD CONSTRAINT uq_push_reminders_dedup UNIQUE (user_id, dedup_key);

-- CONSTRAINT: saved_work_views uq_saved_work_views_id_owner
ALTER TABLE ONLY sidekick.saved_work_views
    ADD CONSTRAINT uq_saved_work_views_id_owner UNIQUE (id, owner_id);

-- CONSTRAINT: steps uq_steps_id_owner
ALTER TABLE ONLY sidekick.steps
    ADD CONSTRAINT uq_steps_id_owner UNIQUE (id, owner_id);

-- CONSTRAINT: assistant_task_review_findings uq_task_review_findings_run_task_code
ALTER TABLE ONLY sidekick.assistant_task_review_findings
    ADD CONSTRAINT uq_task_review_findings_run_task_code UNIQUE (run_id, task_id, finding_code);

-- CONSTRAINT: tasks uq_tasks_id_owner
ALTER TABLE ONLY sidekick.tasks
    ADD CONSTRAINT uq_tasks_id_owner UNIQUE (id, owner_id);

-- CONSTRAINT: work_tags uq_work_tags_id_owner
ALTER TABLE ONLY sidekick.work_tags
    ADD CONSTRAINT uq_work_tags_id_owner UNIQUE (id, owner_id);

-- CONSTRAINT: work_tags uq_work_tags_owner_slug
ALTER TABLE ONLY sidekick.work_tags
    ADD CONSTRAINT uq_work_tags_owner_slug UNIQUE (owner_id, slug);

-- CONSTRAINT: users users_pkey
ALTER TABLE ONLY sidekick.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);

-- CONSTRAINT: users users_username_key
ALTER TABLE ONLY sidekick.users
    ADD CONSTRAINT users_username_key UNIQUE (username);

-- CONSTRAINT: work_tags work_tags_pkey
ALTER TABLE ONLY sidekick.work_tags
    ADD CONSTRAINT work_tags_pkey PRIMARY KEY (id);

-- INDEX: ix_actions_owner_trashed
CREATE INDEX ix_actions_owner_trashed ON sidekick.actions USING btree (owner_id, trashed_at, updated_at, id);

-- INDEX: ix_actions_step_active_position
CREATE INDEX ix_actions_step_active_position ON sidekick.actions USING btree (owner_id, step_id, archived_at, "position", id);

-- INDEX: ix_actions_step_position
CREATE INDEX ix_actions_step_position ON sidekick.actions USING btree (owner_id, step_id, "position", id);

-- INDEX: ix_activity_entries_owner_category
CREATE INDEX ix_activity_entries_owner_category ON sidekick.activity_entries USING btree (owner_id, category, occurred_at DESC, id DESC);

-- INDEX: ix_activity_entries_owner_occurred
CREATE INDEX ix_activity_entries_owner_occurred ON sidekick.activity_entries USING btree (owner_id, occurred_at DESC, id DESC);

-- INDEX: ix_activity_entries_owner_target
CREATE INDEX ix_activity_entries_owner_target ON sidekick.activity_entries USING btree (owner_id, aggregate_type, aggregate_id, occurred_at DESC);

-- INDEX: ix_audit_events_actor
CREATE INDEX ix_audit_events_actor ON sidekick.audit_events USING btree (actor_id, occurred_at DESC);

-- INDEX: ix_audit_events_occurred
CREATE INDEX ix_audit_events_occurred ON sidekick.audit_events USING btree (occurred_at DESC, id DESC);

-- INDEX: ix_automation_runs_claim
CREATE INDEX ix_automation_runs_claim ON sidekick.assistant_automation_runs USING btree (status, scheduled_for, created_at, id);

-- INDEX: ix_automation_runs_owner_created
CREATE INDEX ix_automation_runs_owner_created ON sidekick.assistant_automation_runs USING btree (owner_id, created_at DESC, id DESC);

-- INDEX: ix_companion_pairings_digest
CREATE UNIQUE INDEX ix_companion_pairings_digest ON sidekick.companion_pairings USING btree (secret_digest);

-- INDEX: ix_contact_aliases_display_value_trgm
CREATE INDEX ix_contact_aliases_display_value_trgm ON sidekick.contact_aliases USING gin (display_value public.gin_trgm_ops);

-- INDEX: ix_contact_aliases_search
CREATE INDEX ix_contact_aliases_search ON sidekick.contact_aliases USING btree (owner_id, normalized_key, contact_id);

-- INDEX: ix_contact_aliases_search_vector
CREATE INDEX ix_contact_aliases_search_vector ON sidekick.contact_aliases USING gin (search_vector);

-- INDEX: ix_contact_aliases_stable
CREATE INDEX ix_contact_aliases_stable ON sidekick.contact_aliases USING btree (owner_id, contact_id, normalized_key, id);

-- INDEX: ix_contacts_display_name_trgm
CREATE INDEX ix_contacts_display_name_trgm ON sidekick.contacts USING gin (display_name public.gin_trgm_ops);

-- INDEX: ix_contacts_email
CREATE INDEX ix_contacts_email ON sidekick.contacts USING btree (owner_id, email_key) WHERE (email_key IS NOT NULL);

-- INDEX: ix_contacts_owner_trashed
CREATE INDEX ix_contacts_owner_trashed ON sidekick.contacts USING btree (owner_id, trashed_at, updated_at, id);

-- INDEX: ix_contacts_phone
CREATE INDEX ix_contacts_phone ON sidekick.contacts USING btree (owner_id, phone_key) WHERE (phone_key IS NOT NULL);

-- INDEX: ix_contacts_search
CREATE INDEX ix_contacts_search ON sidekick.contacts USING btree (owner_id, archived, display_name_key, id);

-- INDEX: ix_contacts_search_vector
CREATE INDEX ix_contacts_search_vector ON sidekick.contacts USING gin (search_vector);

-- INDEX: ix_daily_journal_summary_entries_entry
CREATE INDEX ix_daily_journal_summary_entries_entry ON sidekick.daily_journal_summary_entries USING btree (owner_id, entry_id, summary_id);

-- INDEX: ix_domain_events_owner_aggregate
CREATE INDEX ix_domain_events_owner_aggregate ON sidekick.domain_events USING btree (owner_id, aggregate_type, aggregate_id, aggregate_version);

-- INDEX: ix_domain_events_owner_occurred
CREATE INDEX ix_domain_events_owner_occurred ON sidekick.domain_events USING btree (owner_id, occurred_at DESC, id DESC);

-- INDEX: ix_domain_tags_reverse
CREATE INDEX ix_domain_tags_reverse ON sidekick.domain_tags USING btree (owner_id, domain_id, tag_id);

-- INDEX: ix_domains_owner_trashed
CREATE INDEX ix_domains_owner_trashed ON sidekick.domains USING btree (owner_id, trashed_at, updated_at, id);

-- INDEX: ix_domains_owner_updated
CREATE INDEX ix_domains_owner_updated ON sidekick.domains USING btree (owner_id, updated_at DESC, id DESC);

-- INDEX: ix_journal_drafts_source
CREATE INDEX ix_journal_drafts_source ON sidekick.journal_drafts USING btree (owner_id, source_id, created_at, id);

-- INDEX: ix_journal_entries_owner_trashed
CREATE INDEX ix_journal_entries_owner_trashed ON sidekick.journal_entries USING btree (owner_id, trashed_at, updated_at, id);

-- INDEX: ix_journal_entries_search_vector
CREATE INDEX ix_journal_entries_search_vector ON sidekick.journal_entries USING gin (search_vector);

-- INDEX: ix_journal_entries_source
CREATE INDEX ix_journal_entries_source ON sidekick.journal_entries USING btree (owner_id, source_id);

-- INDEX: ix_journal_entries_timeline
CREATE INDEX ix_journal_entries_timeline ON sidekick.journal_entries USING btree (owner_id, journal_date, archived_at, occurred_at, created_at, id);

-- INDEX: ix_journal_entries_title_trgm
CREATE INDEX ix_journal_entries_title_trgm ON sidekick.journal_entries USING gin (title public.gin_trgm_ops);

-- INDEX: ix_journal_entry_contacts_reverse
CREATE INDEX ix_journal_entry_contacts_reverse ON sidekick.journal_entry_contacts USING btree (owner_id, contact_id, entry_id);

-- INDEX: ix_journal_entry_projects_reverse
CREATE INDEX ix_journal_entry_projects_reverse ON sidekick.journal_entry_projects USING btree (owner_id, project_id, entry_id);

-- INDEX: ix_journal_entry_tasks_reverse
CREATE INDEX ix_journal_entry_tasks_reverse ON sidekick.journal_entry_tasks USING btree (owner_id, task_id, entry_id);

-- INDEX: ix_journal_processing_runs_owner_operation
CREATE INDEX ix_journal_processing_runs_owner_operation ON sidekick.journal_processing_runs USING btree (owner_id, operation, journal_date, created_at, id);

-- INDEX: ix_journal_processing_runs_source
CREATE INDEX ix_journal_processing_runs_source ON sidekick.journal_processing_runs USING btree (owner_id, source_id, created_at, id);

-- INDEX: ix_journal_sources_owner_trashed
CREATE INDEX ix_journal_sources_owner_trashed ON sidekick.journal_sources USING btree (owner_id, trashed_at, created_at, id);

-- INDEX: ix_journal_sources_replacement
CREATE INDEX ix_journal_sources_replacement ON sidekick.journal_sources USING btree (owner_id, replaces_source_id);

-- INDEX: ix_journal_sources_search_vector
CREATE INDEX ix_journal_sources_search_vector ON sidekick.journal_sources USING gin (search_vector);

-- INDEX: ix_journal_sources_timeline
CREATE INDEX ix_journal_sources_timeline ON sidekick.journal_sources USING btree (owner_id, journal_date, created_at, id);

-- INDEX: ix_journal_summary_proposals_day
CREATE INDEX ix_journal_summary_proposals_day ON sidekick.journal_summary_proposals USING btree (owner_id, journal_date, created_at, id);

-- INDEX: ix_memory_sources_due
CREATE INDEX ix_memory_sources_due ON sidekick.memory_sources USING btree (status, next_attempt_at, id);

-- INDEX: ix_pat_previous_digest
CREATE UNIQUE INDEX ix_pat_previous_digest ON sidekick.personal_access_tokens USING btree (previous_token_digest) WHERE (previous_token_digest IS NOT NULL);

-- INDEX: ix_process_run_outbox_due
CREATE INDEX ix_process_run_outbox_due ON sidekick.process_run_outbox USING btree (status, scheduled_for, id);

-- INDEX: ix_process_run_outbox_owner
CREATE INDEX ix_process_run_outbox_owner ON sidekick.process_run_outbox USING btree (owner_id, created_at DESC, id DESC);

-- INDEX: ix_process_run_templates_owner_updated
CREATE INDEX ix_process_run_templates_owner_updated ON sidekick.process_run_templates USING btree (owner_id, updated_at DESC, id DESC);

-- INDEX: ix_process_runs_owner_created
CREATE INDEX ix_process_runs_owner_created ON sidekick.process_runs USING btree (owner_id, created_at DESC, id DESC);

-- INDEX: ix_process_runs_process_scheduled
CREATE INDEX ix_process_runs_process_scheduled ON sidekick.process_runs USING btree (owner_id, process_id, scheduled_for DESC, id DESC);

-- INDEX: ix_process_tags_reverse
CREATE INDEX ix_process_tags_reverse ON sidekick.process_tags USING btree (owner_id, process_id, tag_id);

-- INDEX: ix_processes_owner_domain_updated
CREATE INDEX ix_processes_owner_domain_updated ON sidekick.processes USING btree (owner_id, domain_id, updated_at DESC, id DESC);

-- INDEX: ix_processes_owner_trashed
CREATE INDEX ix_processes_owner_trashed ON sidekick.processes USING btree (owner_id, trashed_at, updated_at, id);

-- INDEX: ix_project_contacts_reverse
CREATE INDEX ix_project_contacts_reverse ON sidekick.project_contacts USING btree (owner_id, contact_id, project_id);

-- INDEX: ix_project_tags_reverse
CREATE INDEX ix_project_tags_reverse ON sidekick.project_tags USING btree (owner_id, project_id, tag_id);

-- INDEX: ix_projects_owner_domain_updated
CREATE INDEX ix_projects_owner_domain_updated ON sidekick.projects USING btree (owner_id, domain_id, updated_at DESC, id DESC);

-- INDEX: ix_projects_owner_trashed
CREATE INDEX ix_projects_owner_trashed ON sidekick.projects USING btree (owner_id, trashed_at, updated_at, id);

-- INDEX: ix_projects_owner_updated
CREATE INDEX ix_projects_owner_updated ON sidekick.projects USING btree (owner_id, updated_at DESC, id DESC);

-- INDEX: ix_projects_search_vector
CREATE INDEX ix_projects_search_vector ON sidekick.projects USING gin (search_vector);

-- INDEX: ix_projects_title_trgm
CREATE INDEX ix_projects_title_trgm ON sidekick.projects USING gin (title public.gin_trgm_ops);

-- INDEX: ix_push_outbox_due
CREATE INDEX ix_push_outbox_due ON sidekick.push_outbox USING btree (next_attempt_at) WHERE ((delivered_at IS NULL) AND (next_attempt_at IS NOT NULL));

-- INDEX: ix_push_outbox_pending_wake
CREATE UNIQUE INDEX ix_push_outbox_pending_wake ON sidekick.push_outbox USING btree (subscription_id) WHERE (((kind)::text = 'w'::text) AND (delivered_at IS NULL) AND (next_attempt_at IS NOT NULL));

-- INDEX: ix_push_outbox_reminder_dedup
CREATE UNIQUE INDEX ix_push_outbox_reminder_dedup ON sidekick.push_outbox USING btree (subscription_id, dedup_key) WHERE ((kind)::text = 'r'::text);

-- INDEX: ix_push_reminders_pending
CREATE INDEX ix_push_reminders_pending ON sidekick.push_reminders USING btree (user_id, scheduled_for DESC) WHERE (acked_at IS NULL);

-- INDEX: ix_push_subscriptions_active_pairing
CREATE UNIQUE INDEX ix_push_subscriptions_active_pairing ON sidekick.push_subscriptions USING btree (pairing_id) WHERE (revoked_at IS NULL);

-- INDEX: ix_push_subscriptions_user_active
CREATE INDEX ix_push_subscriptions_user_active ON sidekick.push_subscriptions USING btree (user_id) WHERE (revoked_at IS NULL);

-- INDEX: ix_saved_work_views_owner_active_name
CREATE INDEX ix_saved_work_views_owner_active_name ON sidekick.saved_work_views USING btree (owner_id, archived_at, name, id);

-- INDEX: ix_saved_work_views_owner_name
CREATE INDEX ix_saved_work_views_owner_name ON sidekick.saved_work_views USING btree (owner_id, name, id);

-- INDEX: ix_shopping_items_list
CREATE INDEX ix_shopping_items_list ON sidekick.shopping_items USING btree (owner_id, list_id, created_at, id);

-- INDEX: ix_shopping_items_owner_trashed
CREATE INDEX ix_shopping_items_owner_trashed ON sidekick.shopping_items USING btree (owner_id, trashed_at, updated_at, id);

-- INDEX: ix_shopping_lists_owner
CREATE INDEX ix_shopping_lists_owner ON sidekick.shopping_lists USING btree (owner_id, created_at, id);

-- INDEX: ix_shopping_recipient
CREATE INDEX ix_shopping_recipient ON sidekick.shopping_items USING btree (owner_id, recipient_contact_id) WHERE (recipient_contact_id IS NOT NULL);

-- INDEX: ix_shopping_status_item
CREATE INDEX ix_shopping_status_item ON sidekick.shopping_item_status_history USING btree (owner_id, item_id, changed_at, id);

-- INDEX: ix_steps_owner_completed_at
CREATE INDEX ix_steps_owner_completed_at ON sidekick.steps USING btree (owner_id, completed_at) WHERE (completed_at IS NOT NULL);

-- INDEX: ix_steps_owner_trashed
CREATE INDEX ix_steps_owner_trashed ON sidekick.steps USING btree (owner_id, trashed_at, updated_at, id);

-- INDEX: ix_steps_task_active_position
CREATE INDEX ix_steps_task_active_position ON sidekick.steps USING btree (owner_id, task_id, archived_at, "position", id);

-- INDEX: ix_steps_task_position
CREATE INDEX ix_steps_task_position ON sidekick.steps USING btree (owner_id, task_id, "position", id);

-- INDEX: ix_task_contacts_reverse
CREATE INDEX ix_task_contacts_reverse ON sidekick.task_contacts USING btree (owner_id, contact_id, task_id);

-- INDEX: ix_task_external_references_reverse
CREATE INDEX ix_task_external_references_reverse ON sidekick.task_external_references USING btree (owner_id, reference_id, task_id);

-- INDEX: ix_task_review_findings_owner_state
CREATE INDEX ix_task_review_findings_owner_state ON sidekick.assistant_task_review_findings USING btree (owner_id, state, updated_at DESC, id DESC);

-- INDEX: ix_task_review_findings_owner_task
CREATE INDEX ix_task_review_findings_owner_task ON sidekick.assistant_task_review_findings USING btree (owner_id, task_id, updated_at DESC, id DESC);

-- INDEX: ix_task_status_history_owner_task_changed
CREATE INDEX ix_task_status_history_owner_task_changed ON sidekick.task_status_history USING btree (owner_id, task_id, changed_at DESC, id DESC);

-- INDEX: ix_task_tags_reverse
CREATE INDEX ix_task_tags_reverse ON sidekick.task_tags USING btree (owner_id, task_id, tag_id);

-- INDEX: ix_tasks_owner_domain_updated
CREATE INDEX ix_tasks_owner_domain_updated ON sidekick.tasks USING btree (owner_id, domain_id, updated_at DESC, id DESC);

-- INDEX: ix_tasks_owner_process_updated
CREATE INDEX ix_tasks_owner_process_updated ON sidekick.tasks USING btree (owner_id, process_id, updated_at DESC, id DESC);

-- INDEX: ix_tasks_owner_status_board_rank
CREATE INDEX ix_tasks_owner_status_board_rank ON sidekick.tasks USING btree (owner_id, status, board_rank, id) WHERE (board_rank IS NOT NULL);

-- INDEX: ix_tasks_owner_trashed
CREATE INDEX ix_tasks_owner_trashed ON sidekick.tasks USING btree (owner_id, trashed_at, updated_at, id);

-- INDEX: ix_tasks_owner_updated
CREATE INDEX ix_tasks_owner_updated ON sidekick.tasks USING btree (owner_id, updated_at DESC, id DESC);

-- INDEX: ix_tasks_owner_waiting_follow_up
CREATE INDEX ix_tasks_owner_waiting_follow_up ON sidekick.tasks USING btree (owner_id, follow_up_at, id) WHERE (waiting_since IS NOT NULL);

-- INDEX: ix_tasks_search_vector
CREATE INDEX ix_tasks_search_vector ON sidekick.tasks USING gin (search_vector);

-- INDEX: ix_tasks_title_trgm
CREATE INDEX ix_tasks_title_trgm ON sidekick.tasks USING gin (title public.gin_trgm_ops);

-- INDEX: ix_work_tags_owner_label
CREATE INDEX ix_work_tags_owner_label ON sidekick.work_tags USING btree (owner_id, label, id);

-- INDEX: uq_external_references_identity
CREATE UNIQUE INDEX uq_external_references_identity ON sidekick.external_references USING btree (owner_id, kind, provider, account_ref, external_id, COALESCE(instance_ref, ''::character varying));

-- FK CONSTRAINT: actions actions_owner_id_fkey
ALTER TABLE ONLY sidekick.actions
    ADD CONSTRAINT actions_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: activity_entries activity_entries_domain_event_id_fkey
ALTER TABLE ONLY sidekick.activity_entries
    ADD CONSTRAINT activity_entries_domain_event_id_fkey FOREIGN KEY (domain_event_id) REFERENCES sidekick.domain_events(id) ON DELETE RESTRICT;

-- FK CONSTRAINT: activity_entries activity_entries_owner_id_fkey
ALTER TABLE ONLY sidekick.activity_entries
    ADD CONSTRAINT activity_entries_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: assistant_automation_control assistant_automation_control_owner_id_fkey
ALTER TABLE ONLY sidekick.assistant_automation_control
    ADD CONSTRAINT assistant_automation_control_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: assistant_automation_policies assistant_automation_policies_owner_id_fkey
ALTER TABLE ONLY sidekick.assistant_automation_policies
    ADD CONSTRAINT assistant_automation_policies_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: assistant_automation_runs assistant_automation_runs_owner_id_fkey
ALTER TABLE ONLY sidekick.assistant_automation_runs
    ADD CONSTRAINT assistant_automation_runs_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: assistant_task_review_findings assistant_task_review_findings_owner_id_fkey
ALTER TABLE ONLY sidekick.assistant_task_review_findings
    ADD CONSTRAINT assistant_task_review_findings_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: assistant_task_review_findings assistant_task_review_findings_run_id_fkey
ALTER TABLE ONLY sidekick.assistant_task_review_findings
    ADD CONSTRAINT assistant_task_review_findings_run_id_fkey FOREIGN KEY (run_id) REFERENCES sidekick.assistant_automation_runs(id) ON DELETE CASCADE;

-- FK CONSTRAINT: audit_events audit_events_actor_id_fkey
ALTER TABLE ONLY sidekick.audit_events
    ADD CONSTRAINT audit_events_actor_id_fkey FOREIGN KEY (actor_id) REFERENCES sidekick.users(id) ON DELETE SET NULL;

-- FK CONSTRAINT: companion_pairings companion_pairings_device_token_id_fkey
ALTER TABLE ONLY sidekick.companion_pairings
    ADD CONSTRAINT companion_pairings_device_token_id_fkey FOREIGN KEY (device_token_id) REFERENCES sidekick.personal_access_tokens(id) ON DELETE SET NULL;

-- FK CONSTRAINT: companion_pairings companion_pairings_user_id_fkey
ALTER TABLE ONLY sidekick.companion_pairings
    ADD CONSTRAINT companion_pairings_user_id_fkey FOREIGN KEY (user_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: contacts contacts_owner_id_fkey
ALTER TABLE ONLY sidekick.contacts
    ADD CONSTRAINT contacts_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: daily_journal_summaries daily_journal_summaries_owner_id_fkey
ALTER TABLE ONLY sidekick.daily_journal_summaries
    ADD CONSTRAINT daily_journal_summaries_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: daily_journal_summary_entries daily_journal_summary_entries_owner_id_fkey
ALTER TABLE ONLY sidekick.daily_journal_summary_entries
    ADD CONSTRAINT daily_journal_summary_entries_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: domain_events domain_events_actor_id_fkey
ALTER TABLE ONLY sidekick.domain_events
    ADD CONSTRAINT domain_events_actor_id_fkey FOREIGN KEY (actor_id) REFERENCES sidekick.users(id) ON DELETE SET NULL;

-- FK CONSTRAINT: domain_events domain_events_owner_id_fkey
ALTER TABLE ONLY sidekick.domain_events
    ADD CONSTRAINT domain_events_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: domain_tags domain_tags_owner_id_fkey
ALTER TABLE ONLY sidekick.domain_tags
    ADD CONSTRAINT domain_tags_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: domains domains_owner_id_fkey
ALTER TABLE ONLY sidekick.domains
    ADD CONSTRAINT domains_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: external_references external_references_owner_id_fkey
ALTER TABLE ONLY sidekick.external_references
    ADD CONSTRAINT external_references_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: actions fk_actions_step_owner
ALTER TABLE ONLY sidekick.actions
    ADD CONSTRAINT fk_actions_step_owner FOREIGN KEY (step_id, owner_id) REFERENCES sidekick.steps(id, owner_id) ON DELETE CASCADE;

-- FK CONSTRAINT: contact_aliases fk_aliases_contact_owner
ALTER TABLE ONLY sidekick.contact_aliases
    ADD CONSTRAINT fk_aliases_contact_owner FOREIGN KEY (contact_id, owner_id) REFERENCES sidekick.contacts(id, owner_id) ON DELETE CASCADE;

-- FK CONSTRAINT: daily_journal_summaries fk_daily_journal_summaries_proposal_owner
ALTER TABLE ONLY sidekick.daily_journal_summaries
    ADD CONSTRAINT fk_daily_journal_summaries_proposal_owner FOREIGN KEY (accepted_proposal_id, owner_id) REFERENCES sidekick.journal_summary_proposals(id, owner_id) ON DELETE RESTRICT;

-- FK CONSTRAINT: daily_journal_summaries fk_daily_journal_summaries_run_owner
ALTER TABLE ONLY sidekick.daily_journal_summaries
    ADD CONSTRAINT fk_daily_journal_summaries_run_owner FOREIGN KEY (processing_run_id, owner_id) REFERENCES sidekick.journal_processing_runs(id, owner_id) ON DELETE RESTRICT;

-- FK CONSTRAINT: daily_journal_summary_entries fk_daily_journal_summary_entries_entry
ALTER TABLE ONLY sidekick.daily_journal_summary_entries
    ADD CONSTRAINT fk_daily_journal_summary_entries_entry FOREIGN KEY (entry_id, owner_id) REFERENCES sidekick.journal_entries(id, owner_id) ON DELETE RESTRICT;

-- FK CONSTRAINT: daily_journal_summary_entries fk_daily_journal_summary_entries_summary
ALTER TABLE ONLY sidekick.daily_journal_summary_entries
    ADD CONSTRAINT fk_daily_journal_summary_entries_summary FOREIGN KEY (summary_id, owner_id) REFERENCES sidekick.daily_journal_summaries(id, owner_id) ON DELETE CASCADE;

-- FK CONSTRAINT: domain_tags fk_domain_tags_tag_owner
ALTER TABLE ONLY sidekick.domain_tags
    ADD CONSTRAINT fk_domain_tags_tag_owner FOREIGN KEY (tag_id, owner_id) REFERENCES sidekick.work_tags(id, owner_id) ON DELETE CASCADE;

-- FK CONSTRAINT: domain_tags fk_domain_tags_target_owner
ALTER TABLE ONLY sidekick.domain_tags
    ADD CONSTRAINT fk_domain_tags_target_owner FOREIGN KEY (domain_id, owner_id) REFERENCES sidekick.domains(id, owner_id) ON DELETE CASCADE;

-- FK CONSTRAINT: journal_drafts fk_journal_drafts_catalog_run_owner
ALTER TABLE ONLY sidekick.journal_drafts
    ADD CONSTRAINT fk_journal_drafts_catalog_run_owner FOREIGN KEY (catalog_run_id, owner_id) REFERENCES sidekick.journal_processing_runs(id, owner_id) ON DELETE RESTRICT;

-- FK CONSTRAINT: journal_drafts fk_journal_drafts_processing_run_owner
ALTER TABLE ONLY sidekick.journal_drafts
    ADD CONSTRAINT fk_journal_drafts_processing_run_owner FOREIGN KEY (processing_run_id, owner_id) REFERENCES sidekick.journal_processing_runs(id, owner_id) ON DELETE RESTRICT;

-- FK CONSTRAINT: journal_drafts fk_journal_drafts_source_owner
ALTER TABLE ONLY sidekick.journal_drafts
    ADD CONSTRAINT fk_journal_drafts_source_owner FOREIGN KEY (source_id, owner_id) REFERENCES sidekick.journal_sources(id, owner_id) ON DELETE RESTRICT;

-- FK CONSTRAINT: journal_entries fk_journal_entries_source_owner
ALTER TABLE ONLY sidekick.journal_entries
    ADD CONSTRAINT fk_journal_entries_source_owner FOREIGN KEY (source_id, owner_id) REFERENCES sidekick.journal_sources(id, owner_id) ON DELETE RESTRICT;

-- FK CONSTRAINT: journal_entry_contacts fk_journal_entry_contacts_contact
ALTER TABLE ONLY sidekick.journal_entry_contacts
    ADD CONSTRAINT fk_journal_entry_contacts_contact FOREIGN KEY (contact_id, owner_id) REFERENCES sidekick.contacts(id, owner_id) ON DELETE RESTRICT;

-- FK CONSTRAINT: journal_entry_contacts fk_journal_entry_contacts_entry
ALTER TABLE ONLY sidekick.journal_entry_contacts
    ADD CONSTRAINT fk_journal_entry_contacts_entry FOREIGN KEY (entry_id, owner_id) REFERENCES sidekick.journal_entries(id, owner_id) ON DELETE CASCADE;

-- FK CONSTRAINT: journal_entry_projects fk_journal_entry_projects_entry
ALTER TABLE ONLY sidekick.journal_entry_projects
    ADD CONSTRAINT fk_journal_entry_projects_entry FOREIGN KEY (entry_id, owner_id) REFERENCES sidekick.journal_entries(id, owner_id) ON DELETE CASCADE;

-- FK CONSTRAINT: journal_entry_projects fk_journal_entry_projects_project
ALTER TABLE ONLY sidekick.journal_entry_projects
    ADD CONSTRAINT fk_journal_entry_projects_project FOREIGN KEY (project_id, owner_id) REFERENCES sidekick.projects(id, owner_id) ON DELETE RESTRICT;

-- FK CONSTRAINT: journal_entry_tasks fk_journal_entry_tasks_entry
ALTER TABLE ONLY sidekick.journal_entry_tasks
    ADD CONSTRAINT fk_journal_entry_tasks_entry FOREIGN KEY (entry_id, owner_id) REFERENCES sidekick.journal_entries(id, owner_id) ON DELETE CASCADE;

-- FK CONSTRAINT: journal_entry_tasks fk_journal_entry_tasks_task
ALTER TABLE ONLY sidekick.journal_entry_tasks
    ADD CONSTRAINT fk_journal_entry_tasks_task FOREIGN KEY (task_id, owner_id) REFERENCES sidekick.tasks(id, owner_id) ON DELETE RESTRICT;

-- FK CONSTRAINT: journal_processing_runs fk_journal_processing_runs_source_owner
ALTER TABLE ONLY sidekick.journal_processing_runs
    ADD CONSTRAINT fk_journal_processing_runs_source_owner FOREIGN KEY (source_id, owner_id) REFERENCES sidekick.journal_sources(id, owner_id) ON DELETE RESTRICT;

-- FK CONSTRAINT: journal_sources fk_journal_sources_replacement_owner
ALTER TABLE ONLY sidekick.journal_sources
    ADD CONSTRAINT fk_journal_sources_replacement_owner FOREIGN KEY (replaces_source_id, owner_id) REFERENCES sidekick.journal_sources(id, owner_id) ON DELETE RESTRICT;

-- FK CONSTRAINT: journal_summary_proposals fk_journal_summary_proposals_run_owner
ALTER TABLE ONLY sidekick.journal_summary_proposals
    ADD CONSTRAINT fk_journal_summary_proposals_run_owner FOREIGN KEY (run_id, owner_id) REFERENCES sidekick.journal_processing_runs(id, owner_id) ON DELETE RESTRICT;

-- FK CONSTRAINT: process_run_outbox fk_process_run_outbox_process_owner
ALTER TABLE ONLY sidekick.process_run_outbox
    ADD CONSTRAINT fk_process_run_outbox_process_owner FOREIGN KEY (process_id, owner_id) REFERENCES sidekick.processes(id, owner_id) ON DELETE RESTRICT;

-- FK CONSTRAINT: process_run_templates fk_process_run_templates_process_owner
ALTER TABLE ONLY sidekick.process_run_templates
    ADD CONSTRAINT fk_process_run_templates_process_owner FOREIGN KEY (process_id, owner_id) REFERENCES sidekick.processes(id, owner_id) ON DELETE CASCADE;

-- FK CONSTRAINT: process_runs fk_process_runs_process_owner
ALTER TABLE ONLY sidekick.process_runs
    ADD CONSTRAINT fk_process_runs_process_owner FOREIGN KEY (process_id, owner_id) REFERENCES sidekick.processes(id, owner_id) ON DELETE RESTRICT;

-- FK CONSTRAINT: process_runs fk_process_runs_task_owner
ALTER TABLE ONLY sidekick.process_runs
    ADD CONSTRAINT fk_process_runs_task_owner FOREIGN KEY (task_id, owner_id) REFERENCES sidekick.tasks(id, owner_id) ON DELETE RESTRICT;

-- FK CONSTRAINT: process_tags fk_process_tags_tag_owner
ALTER TABLE ONLY sidekick.process_tags
    ADD CONSTRAINT fk_process_tags_tag_owner FOREIGN KEY (tag_id, owner_id) REFERENCES sidekick.work_tags(id, owner_id) ON DELETE CASCADE;

-- FK CONSTRAINT: process_tags fk_process_tags_target_owner
ALTER TABLE ONLY sidekick.process_tags
    ADD CONSTRAINT fk_process_tags_target_owner FOREIGN KEY (process_id, owner_id) REFERENCES sidekick.processes(id, owner_id) ON DELETE CASCADE;

-- FK CONSTRAINT: processes fk_processes_domain_owner
ALTER TABLE ONLY sidekick.processes
    ADD CONSTRAINT fk_processes_domain_owner FOREIGN KEY (domain_id, owner_id) REFERENCES sidekick.domains(id, owner_id) ON DELETE RESTRICT;

-- FK CONSTRAINT: project_contacts fk_project_contacts_contact
ALTER TABLE ONLY sidekick.project_contacts
    ADD CONSTRAINT fk_project_contacts_contact FOREIGN KEY (contact_id, owner_id) REFERENCES sidekick.contacts(id, owner_id) ON DELETE CASCADE;

-- FK CONSTRAINT: project_contacts fk_project_contacts_project
ALTER TABLE ONLY sidekick.project_contacts
    ADD CONSTRAINT fk_project_contacts_project FOREIGN KEY (project_id, owner_id) REFERENCES sidekick.projects(id, owner_id) ON DELETE CASCADE;

-- FK CONSTRAINT: project_tags fk_project_tags_tag_owner
ALTER TABLE ONLY sidekick.project_tags
    ADD CONSTRAINT fk_project_tags_tag_owner FOREIGN KEY (tag_id, owner_id) REFERENCES sidekick.work_tags(id, owner_id) ON DELETE CASCADE;

-- FK CONSTRAINT: project_tags fk_project_tags_target_owner
ALTER TABLE ONLY sidekick.project_tags
    ADD CONSTRAINT fk_project_tags_target_owner FOREIGN KEY (project_id, owner_id) REFERENCES sidekick.projects(id, owner_id) ON DELETE CASCADE;

-- FK CONSTRAINT: projects fk_projects_domain_owner
ALTER TABLE ONLY sidekick.projects
    ADD CONSTRAINT fk_projects_domain_owner FOREIGN KEY (domain_id, owner_id) REFERENCES sidekick.domains(id, owner_id) ON DELETE RESTRICT;

-- FK CONSTRAINT: steps fk_steps_task_owner
ALTER TABLE ONLY sidekick.steps
    ADD CONSTRAINT fk_steps_task_owner FOREIGN KEY (task_id, owner_id) REFERENCES sidekick.tasks(id, owner_id) ON DELETE CASCADE;

-- FK CONSTRAINT: task_contacts fk_task_contacts_contact
ALTER TABLE ONLY sidekick.task_contacts
    ADD CONSTRAINT fk_task_contacts_contact FOREIGN KEY (contact_id, owner_id) REFERENCES sidekick.contacts(id, owner_id) ON DELETE CASCADE;

-- FK CONSTRAINT: task_contacts fk_task_contacts_task
ALTER TABLE ONLY sidekick.task_contacts
    ADD CONSTRAINT fk_task_contacts_task FOREIGN KEY (task_id, owner_id) REFERENCES sidekick.tasks(id, owner_id) ON DELETE CASCADE;

-- FK CONSTRAINT: task_external_references fk_task_external_references_reference
ALTER TABLE ONLY sidekick.task_external_references
    ADD CONSTRAINT fk_task_external_references_reference FOREIGN KEY (reference_id, owner_id) REFERENCES sidekick.external_references(id, owner_id) ON DELETE CASCADE;

-- FK CONSTRAINT: task_external_references fk_task_external_references_task
ALTER TABLE ONLY sidekick.task_external_references
    ADD CONSTRAINT fk_task_external_references_task FOREIGN KEY (task_id, owner_id) REFERENCES sidekick.tasks(id, owner_id) ON DELETE CASCADE;

-- FK CONSTRAINT: assistant_task_review_findings fk_task_review_findings_task_owner
ALTER TABLE ONLY sidekick.assistant_task_review_findings
    ADD CONSTRAINT fk_task_review_findings_task_owner FOREIGN KEY (task_id, owner_id) REFERENCES sidekick.tasks(id, owner_id) ON DELETE CASCADE;

-- FK CONSTRAINT: task_status_history fk_task_status_history_task_owner
ALTER TABLE ONLY sidekick.task_status_history
    ADD CONSTRAINT fk_task_status_history_task_owner FOREIGN KEY (task_id, owner_id) REFERENCES sidekick.tasks(id, owner_id) ON DELETE CASCADE;

-- FK CONSTRAINT: task_tags fk_task_tags_tag_owner
ALTER TABLE ONLY sidekick.task_tags
    ADD CONSTRAINT fk_task_tags_tag_owner FOREIGN KEY (tag_id, owner_id) REFERENCES sidekick.work_tags(id, owner_id) ON DELETE CASCADE;

-- FK CONSTRAINT: task_tags fk_task_tags_target_owner
ALTER TABLE ONLY sidekick.task_tags
    ADD CONSTRAINT fk_task_tags_target_owner FOREIGN KEY (task_id, owner_id) REFERENCES sidekick.tasks(id, owner_id) ON DELETE CASCADE;

-- FK CONSTRAINT: tasks fk_tasks_domain_owner
ALTER TABLE ONLY sidekick.tasks
    ADD CONSTRAINT fk_tasks_domain_owner FOREIGN KEY (domain_id, owner_id) REFERENCES sidekick.domains(id, owner_id) ON DELETE RESTRICT;

-- FK CONSTRAINT: tasks fk_tasks_process_owner
ALTER TABLE ONLY sidekick.tasks
    ADD CONSTRAINT fk_tasks_process_owner FOREIGN KEY (process_id, owner_id) REFERENCES sidekick.processes(id, owner_id) ON DELETE RESTRICT;

-- FK CONSTRAINT: tasks fk_tasks_project_owner
ALTER TABLE ONLY sidekick.tasks
    ADD CONSTRAINT fk_tasks_project_owner FOREIGN KEY (project_id, owner_id) REFERENCES sidekick.projects(id, owner_id) ON DELETE RESTRICT;

-- FK CONSTRAINT: tasks fk_tasks_waiting_contact_owner
ALTER TABLE ONLY sidekick.tasks
    ADD CONSTRAINT fk_tasks_waiting_contact_owner FOREIGN KEY (waiting_on_contact_id, owner_id) REFERENCES sidekick.contacts(id, owner_id) ON DELETE RESTRICT;

-- FK CONSTRAINT: idempotency_operations idempotency_operations_actor_id_fkey
ALTER TABLE ONLY sidekick.idempotency_operations
    ADD CONSTRAINT idempotency_operations_actor_id_fkey FOREIGN KEY (actor_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: journal_drafts journal_drafts_owner_id_fkey
ALTER TABLE ONLY sidekick.journal_drafts
    ADD CONSTRAINT journal_drafts_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: journal_entries journal_entries_owner_id_fkey
ALTER TABLE ONLY sidekick.journal_entries
    ADD CONSTRAINT journal_entries_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: journal_entry_contacts journal_entry_contacts_owner_id_fkey
ALTER TABLE ONLY sidekick.journal_entry_contacts
    ADD CONSTRAINT journal_entry_contacts_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: journal_entry_projects journal_entry_projects_owner_id_fkey
ALTER TABLE ONLY sidekick.journal_entry_projects
    ADD CONSTRAINT journal_entry_projects_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: journal_entry_tasks journal_entry_tasks_owner_id_fkey
ALTER TABLE ONLY sidekick.journal_entry_tasks
    ADD CONSTRAINT journal_entry_tasks_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: journal_processing_runs journal_processing_runs_owner_id_fkey
ALTER TABLE ONLY sidekick.journal_processing_runs
    ADD CONSTRAINT journal_processing_runs_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: journal_sources journal_sources_owner_id_fkey
ALTER TABLE ONLY sidekick.journal_sources
    ADD CONSTRAINT journal_sources_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: journal_summary_proposals journal_summary_proposals_owner_id_fkey
ALTER TABLE ONLY sidekick.journal_summary_proposals
    ADD CONSTRAINT journal_summary_proposals_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: memory_settings memory_settings_owner_id_fkey
ALTER TABLE ONLY sidekick.memory_settings
    ADD CONSTRAINT memory_settings_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: memory_sources memory_sources_owner_id_fkey
ALTER TABLE ONLY sidekick.memory_sources
    ADD CONSTRAINT memory_sources_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: memory_usage_daily memory_usage_daily_owner_id_fkey
ALTER TABLE ONLY sidekick.memory_usage_daily
    ADD CONSTRAINT memory_usage_daily_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: personal_access_tokens personal_access_tokens_user_id_fkey
ALTER TABLE ONLY sidekick.personal_access_tokens
    ADD CONSTRAINT personal_access_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: process_run_outbox process_run_outbox_owner_id_fkey
ALTER TABLE ONLY sidekick.process_run_outbox
    ADD CONSTRAINT process_run_outbox_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: process_run_outbox process_run_outbox_process_run_id_fkey
ALTER TABLE ONLY sidekick.process_run_outbox
    ADD CONSTRAINT process_run_outbox_process_run_id_fkey FOREIGN KEY (process_run_id) REFERENCES sidekick.process_runs(id) ON DELETE RESTRICT;

-- FK CONSTRAINT: process_run_templates process_run_templates_owner_id_fkey
ALTER TABLE ONLY sidekick.process_run_templates
    ADD CONSTRAINT process_run_templates_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: process_runs process_runs_owner_id_fkey
ALTER TABLE ONLY sidekick.process_runs
    ADD CONSTRAINT process_runs_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: process_tags process_tags_owner_id_fkey
ALTER TABLE ONLY sidekick.process_tags
    ADD CONSTRAINT process_tags_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: processes processes_owner_id_fkey
ALTER TABLE ONLY sidekick.processes
    ADD CONSTRAINT processes_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: project_contacts project_contacts_owner_id_fkey
ALTER TABLE ONLY sidekick.project_contacts
    ADD CONSTRAINT project_contacts_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: project_tags project_tags_owner_id_fkey
ALTER TABLE ONLY sidekick.project_tags
    ADD CONSTRAINT project_tags_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: projects projects_owner_id_fkey
ALTER TABLE ONLY sidekick.projects
    ADD CONSTRAINT projects_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: push_outbox push_outbox_subscription_id_fkey
ALTER TABLE ONLY sidekick.push_outbox
    ADD CONSTRAINT push_outbox_subscription_id_fkey FOREIGN KEY (subscription_id) REFERENCES sidekick.push_subscriptions(id) ON DELETE CASCADE;

-- FK CONSTRAINT: push_reminders push_reminders_task_id_fkey
ALTER TABLE ONLY sidekick.push_reminders
    ADD CONSTRAINT push_reminders_task_id_fkey FOREIGN KEY (task_id) REFERENCES sidekick.tasks(id) ON DELETE CASCADE;

-- FK CONSTRAINT: push_reminders push_reminders_user_id_fkey
ALTER TABLE ONLY sidekick.push_reminders
    ADD CONSTRAINT push_reminders_user_id_fkey FOREIGN KEY (user_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: push_subscriptions push_subscriptions_pairing_id_fkey
ALTER TABLE ONLY sidekick.push_subscriptions
    ADD CONSTRAINT push_subscriptions_pairing_id_fkey FOREIGN KEY (pairing_id) REFERENCES sidekick.companion_pairings(id) ON DELETE CASCADE;

-- FK CONSTRAINT: push_subscriptions push_subscriptions_user_id_fkey
ALTER TABLE ONLY sidekick.push_subscriptions
    ADD CONSTRAINT push_subscriptions_user_id_fkey FOREIGN KEY (user_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: saved_work_views saved_work_views_owner_id_fkey
ALTER TABLE ONLY sidekick.saved_work_views
    ADD CONSTRAINT saved_work_views_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: sessions sessions_user_id_fkey
ALTER TABLE ONLY sidekick.sessions
    ADD CONSTRAINT sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: shopping_item_status_history shopping_item_status_history_item_id_owner_id_fkey
ALTER TABLE ONLY sidekick.shopping_item_status_history
    ADD CONSTRAINT shopping_item_status_history_item_id_owner_id_fkey FOREIGN KEY (item_id, owner_id) REFERENCES sidekick.shopping_items(id, owner_id) ON DELETE RESTRICT;

-- FK CONSTRAINT: shopping_item_status_history shopping_item_status_history_owner_id_fkey
ALTER TABLE ONLY sidekick.shopping_item_status_history
    ADD CONSTRAINT shopping_item_status_history_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: shopping_items shopping_items_list_id_owner_id_fkey
ALTER TABLE ONLY sidekick.shopping_items
    ADD CONSTRAINT shopping_items_list_id_owner_id_fkey FOREIGN KEY (list_id, owner_id) REFERENCES sidekick.shopping_lists(id, owner_id) ON DELETE RESTRICT;

-- FK CONSTRAINT: shopping_items shopping_items_owner_id_fkey
ALTER TABLE ONLY sidekick.shopping_items
    ADD CONSTRAINT shopping_items_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: shopping_items shopping_items_recipient_contact_id_owner_id_fkey
ALTER TABLE ONLY sidekick.shopping_items
    ADD CONSTRAINT shopping_items_recipient_contact_id_owner_id_fkey FOREIGN KEY (recipient_contact_id, owner_id) REFERENCES sidekick.contacts(id, owner_id) ON DELETE RESTRICT;

-- FK CONSTRAINT: shopping_lists shopping_lists_owner_id_fkey
ALTER TABLE ONLY sidekick.shopping_lists
    ADD CONSTRAINT shopping_lists_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: steps steps_owner_id_fkey
ALTER TABLE ONLY sidekick.steps
    ADD CONSTRAINT steps_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: task_contacts task_contacts_owner_id_fkey
ALTER TABLE ONLY sidekick.task_contacts
    ADD CONSTRAINT task_contacts_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: task_external_references task_external_references_owner_id_fkey
ALTER TABLE ONLY sidekick.task_external_references
    ADD CONSTRAINT task_external_references_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: task_status_history task_status_history_owner_id_fkey
ALTER TABLE ONLY sidekick.task_status_history
    ADD CONSTRAINT task_status_history_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: task_tags task_tags_owner_id_fkey
ALTER TABLE ONLY sidekick.task_tags
    ADD CONSTRAINT task_tags_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: tasks tasks_owner_id_fkey
ALTER TABLE ONLY sidekick.tasks
    ADD CONSTRAINT tasks_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- FK CONSTRAINT: work_tags work_tags_owner_id_fkey
ALTER TABLE ONLY sidekick.work_tags
    ADD CONSTRAINT work_tags_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;

-- ACL: SCHEMA sidekick
GRANT USAGE ON SCHEMA sidekick TO sidekick_app;

-- ACL: TABLE actions
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE sidekick.actions TO sidekick_app;

-- ACL: TABLE activity_entries
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE sidekick.activity_entries TO sidekick_app;

-- ACL: TABLE assistant_automation_control
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE sidekick.assistant_automation_control TO sidekick_app;

-- ACL: TABLE assistant_automation_policies
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE sidekick.assistant_automation_policies TO sidekick_app;

-- ACL: TABLE assistant_automation_runs
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE sidekick.assistant_automation_runs TO sidekick_app;

-- ACL: TABLE assistant_task_review_findings
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE sidekick.assistant_task_review_findings TO sidekick_app;

-- ACL: TABLE audit_events
GRANT SELECT,INSERT ON TABLE sidekick.audit_events TO sidekick_app;

-- ACL: TABLE companion_pairings
GRANT SELECT,INSERT,UPDATE ON TABLE sidekick.companion_pairings TO sidekick_app;

-- ACL: TABLE contact_aliases
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE sidekick.contact_aliases TO sidekick_app;

-- ACL: TABLE contacts
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE sidekick.contacts TO sidekick_app;

-- ACL: TABLE daily_journal_summaries
GRANT SELECT,INSERT,UPDATE ON TABLE sidekick.daily_journal_summaries TO sidekick_app;

-- ACL: TABLE daily_journal_summary_entries
GRANT SELECT,INSERT,DELETE ON TABLE sidekick.daily_journal_summary_entries TO sidekick_app;

-- ACL: TABLE domain_events
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE sidekick.domain_events TO sidekick_app;

-- ACL: TABLE domain_tags
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE sidekick.domain_tags TO sidekick_app;

-- ACL: TABLE domains
GRANT SELECT,INSERT,UPDATE ON TABLE sidekick.domains TO sidekick_app;

-- ACL: TABLE external_references
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE sidekick.external_references TO sidekick_app;

-- ACL: TABLE idempotency_operations
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE sidekick.idempotency_operations TO sidekick_app;

-- ACL: TABLE instance_license
GRANT SELECT,INSERT,UPDATE ON TABLE sidekick.instance_license TO sidekick_app;

-- ACL: TABLE journal_drafts
GRANT SELECT,INSERT,UPDATE ON TABLE sidekick.journal_drafts TO sidekick_app;

-- ACL: TABLE journal_entries
GRANT SELECT,INSERT,UPDATE ON TABLE sidekick.journal_entries TO sidekick_app;

-- ACL: TABLE journal_entry_contacts
GRANT SELECT,INSERT,DELETE ON TABLE sidekick.journal_entry_contacts TO sidekick_app;

-- ACL: TABLE journal_entry_projects
GRANT SELECT,INSERT,DELETE ON TABLE sidekick.journal_entry_projects TO sidekick_app;

-- ACL: TABLE journal_entry_tasks
GRANT SELECT,INSERT,DELETE ON TABLE sidekick.journal_entry_tasks TO sidekick_app;

-- ACL: TABLE journal_processing_runs
GRANT SELECT,INSERT,UPDATE ON TABLE sidekick.journal_processing_runs TO sidekick_app;

-- ACL: TABLE journal_sources
GRANT SELECT,INSERT ON TABLE sidekick.journal_sources TO sidekick_app;

-- ACL: TABLE journal_summary_proposals
GRANT SELECT,INSERT,UPDATE ON TABLE sidekick.journal_summary_proposals TO sidekick_app;

-- ACL: TABLE memory_settings
GRANT SELECT,INSERT,UPDATE ON TABLE sidekick.memory_settings TO sidekick_app;

-- ACL: TABLE memory_sources
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE sidekick.memory_sources TO sidekick_app;

-- ACL: TABLE memory_usage_daily
GRANT SELECT,INSERT,UPDATE ON TABLE sidekick.memory_usage_daily TO sidekick_app;

-- ACL: TABLE personal_access_tokens
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE sidekick.personal_access_tokens TO sidekick_app;

-- ACL: TABLE process_run_outbox
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE sidekick.process_run_outbox TO sidekick_app;

-- ACL: TABLE process_run_templates
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE sidekick.process_run_templates TO sidekick_app;

-- ACL: TABLE process_runs
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE sidekick.process_runs TO sidekick_app;

-- ACL: TABLE process_tags
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE sidekick.process_tags TO sidekick_app;

-- ACL: TABLE processes
GRANT SELECT,INSERT,UPDATE ON TABLE sidekick.processes TO sidekick_app;

-- ACL: TABLE project_contacts
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE sidekick.project_contacts TO sidekick_app;

-- ACL: TABLE project_tags
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE sidekick.project_tags TO sidekick_app;

-- ACL: TABLE projects
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE sidekick.projects TO sidekick_app;

-- ACL: TABLE push_outbox
GRANT SELECT,INSERT,UPDATE ON TABLE sidekick.push_outbox TO sidekick_app;

-- ACL: TABLE push_reminders
GRANT SELECT,INSERT,UPDATE ON TABLE sidekick.push_reminders TO sidekick_app;

-- ACL: TABLE push_subscriptions
GRANT SELECT,INSERT,UPDATE ON TABLE sidekick.push_subscriptions TO sidekick_app;

-- ACL: TABLE saved_work_views
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE sidekick.saved_work_views TO sidekick_app;

-- ACL: TABLE sessions
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE sidekick.sessions TO sidekick_app;

-- ACL: TABLE shopping_item_status_history
GRANT SELECT,INSERT ON TABLE sidekick.shopping_item_status_history TO sidekick_app;

-- ACL: TABLE shopping_items
GRANT SELECT,INSERT,UPDATE ON TABLE sidekick.shopping_items TO sidekick_app;

-- ACL: TABLE shopping_lists
GRANT SELECT,INSERT,UPDATE ON TABLE sidekick.shopping_lists TO sidekick_app;

-- ACL: TABLE steps
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE sidekick.steps TO sidekick_app;

-- ACL: TABLE task_contacts
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE sidekick.task_contacts TO sidekick_app;

-- ACL: TABLE task_external_references
GRANT SELECT,INSERT,DELETE ON TABLE sidekick.task_external_references TO sidekick_app;

-- ACL: TABLE task_status_history
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE sidekick.task_status_history TO sidekick_app;

-- ACL: TABLE task_tags
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE sidekick.task_tags TO sidekick_app;

-- ACL: TABLE tasks
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE sidekick.tasks TO sidekick_app;

-- ACL: TABLE users
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE sidekick.users TO sidekick_app;

-- ACL: TABLE work_tags
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE sidekick.work_tags TO sidekick_app;

-- DEFAULT ACL: DEFAULT PRIVILEGES FOR TABLES
ALTER DEFAULT PRIVILEGES FOR ROLE sidekick_owner IN SCHEMA sidekick GRANT SELECT,INSERT,DELETE,UPDATE ON TABLES TO sidekick_app;

RESET ROLE;
-- The migrating role owns yoyo's bookkeeping table; the readiness check reads it as the app role.
GRANT SELECT ON public._yoyo_migration TO sidekick_app;
"""


def apply_baseline(connection: Any) -> None:
    cursor = connection.cursor()
    try:
        cursor.execute(BASELINE_SQL)
    finally:
        cursor.close()


steps = [
    step(
        apply_baseline,
        """
        DO $refuse$
        BEGIN
          RAISE EXCEPTION 'the 0.1.0 baseline cannot be rolled back: that would drop every owner '
            'table. Restore a backup instead.';
        END
        $refuse$;
        """,
    )
]

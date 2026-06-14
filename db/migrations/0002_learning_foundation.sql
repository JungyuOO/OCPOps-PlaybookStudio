CREATE TABLE IF NOT EXISTS learning_paths (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid REFERENCES tenants(id) ON DELETE SET NULL,
    workspace_id uuid REFERENCES workspaces(id) ON DELETE SET NULL,
    slug text NOT NULL,
    title text NOT NULL,
    description text NOT NULL DEFAULT '',
    audience text NOT NULL DEFAULT 'beginner',
    ocp_version text NOT NULL DEFAULT '',
    language text NOT NULL DEFAULT 'ko',
    source_kind text NOT NULL DEFAULT 'seed',
    source_ref text NOT NULL DEFAULT '',
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, slug)
);

CREATE TABLE IF NOT EXISTS learning_steps (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    learning_path_id uuid NOT NULL REFERENCES learning_paths(id) ON DELETE CASCADE,
    step_key text NOT NULL,
    ordinal integer NOT NULL,
    title text NOT NULL,
    objective text NOT NULL DEFAULT '',
    concept_slugs jsonb NOT NULL DEFAULT '[]'::jsonb,
    prerequisite_step_keys jsonb NOT NULL DEFAULT '[]'::jsonb,
    estimated_minutes integer NOT NULL DEFAULT 0,
    difficulty text NOT NULL DEFAULT 'beginner',
    lesson_markdown text NOT NULL DEFAULT '',
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (learning_path_id, step_key),
    UNIQUE (learning_path_id, ordinal)
);

CREATE TABLE IF NOT EXISTS learning_step_documents (
    learning_step_id uuid NOT NULL REFERENCES learning_steps(id) ON DELETE CASCADE,
    document_chunk_id uuid REFERENCES document_chunks(id) ON DELETE SET NULL,
    document_source_id uuid REFERENCES document_sources(id) ON DELETE SET NULL,
    relation_type text NOT NULL DEFAULT 'evidence',
    rank integer NOT NULL DEFAULT 0,
    evidence_note text NOT NULL DEFAULT '',
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (learning_step_id, relation_type, rank)
);

CREATE TABLE IF NOT EXISTS lab_tasks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    learning_step_id uuid NOT NULL REFERENCES learning_steps(id) ON DELETE CASCADE,
    task_key text NOT NULL,
    ordinal integer NOT NULL,
    title text NOT NULL,
    goal_markdown text NOT NULL DEFAULT '',
    starter_context jsonb NOT NULL DEFAULT '{}'::jsonb,
    expected_outcome jsonb NOT NULL DEFAULT '{}'::jsonb,
    hint_markdown text NOT NULL DEFAULT '',
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (learning_step_id, task_key),
    UNIQUE (learning_step_id, ordinal)
);

CREATE TABLE IF NOT EXISTS command_checks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lab_task_id uuid NOT NULL REFERENCES lab_tasks(id) ON DELETE CASCADE,
    check_key text NOT NULL,
    ordinal integer NOT NULL,
    command_pattern text NOT NULL DEFAULT '',
    expected_command text NOT NULL DEFAULT '',
    validation_kind text NOT NULL DEFAULT 'command_pattern',
    validation_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    success_message text NOT NULL DEFAULT '',
    failure_hint text NOT NULL DEFAULT '',
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (lab_task_id, check_key),
    UNIQUE (lab_task_id, ordinal)
);

CREATE TABLE IF NOT EXISTS learner_progress (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid REFERENCES tenants(id) ON DELETE SET NULL,
    workspace_id uuid REFERENCES workspaces(id) ON DELETE SET NULL,
    learner_id text NOT NULL,
    learning_path_id uuid NOT NULL REFERENCES learning_paths(id) ON DELETE CASCADE,
    learning_step_id uuid REFERENCES learning_steps(id) ON DELETE SET NULL,
    status text NOT NULL DEFAULT 'not_started',
    completed_step_keys jsonb NOT NULL DEFAULT '[]'::jsonb,
    last_activity_at timestamptz NOT NULL DEFAULT now(),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (workspace_id, learner_id, learning_path_id)
);

CREATE TABLE IF NOT EXISTS lab_attempts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    learner_progress_id uuid REFERENCES learner_progress(id) ON DELETE SET NULL,
    lab_task_id uuid NOT NULL REFERENCES lab_tasks(id) ON DELETE CASCADE,
    learner_id text NOT NULL DEFAULT '',
    submitted_command text NOT NULL DEFAULT '',
    stdout text NOT NULL DEFAULT '',
    stderr text NOT NULL DEFAULT '',
    exit_code integer,
    validation_result jsonb NOT NULL DEFAULT '{}'::jsonb,
    status text NOT NULL DEFAULT 'submitted',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_learning_steps_path_ordinal
    ON learning_steps(learning_path_id, ordinal);

CREATE INDEX IF NOT EXISTS idx_lab_tasks_step_ordinal
    ON lab_tasks(learning_step_id, ordinal);

CREATE INDEX IF NOT EXISTS idx_command_checks_task_ordinal
    ON command_checks(lab_task_id, ordinal);

CREATE INDEX IF NOT EXISTS idx_learning_step_documents_chunk
    ON learning_step_documents(document_chunk_id);

CREATE INDEX IF NOT EXISTS idx_lab_attempts_task_created
    ON lab_attempts(lab_task_id, created_at DESC);

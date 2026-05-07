CREATE TABLE IF NOT EXISTS terminal_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid REFERENCES tenants(id) ON DELETE SET NULL,
    workspace_id uuid REFERENCES workspaces(id) ON DELETE SET NULL,
    client_session_id text NOT NULL UNIQUE,
    learner_id text NOT NULL DEFAULT '',
    learning_path_id uuid REFERENCES learning_paths(id) ON DELETE SET NULL,
    learning_step_id uuid REFERENCES learning_steps(id) ON DELETE SET NULL,
    lab_task_id uuid REFERENCES lab_tasks(id) ON DELETE SET NULL,
    shell text NOT NULL DEFAULT '',
    workdir text NOT NULL DEFAULT '',
    status text NOT NULL DEFAULT 'started',
    started_at timestamptz NOT NULL DEFAULT now(),
    ended_at timestamptz,
    exit_code integer,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS terminal_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    terminal_session_id uuid NOT NULL REFERENCES terminal_sessions(id) ON DELETE CASCADE,
    event_ordinal integer NOT NULL,
    event_type text NOT NULL,
    stream text NOT NULL DEFAULT '',
    data text NOT NULL DEFAULT '',
    command_text text NOT NULL DEFAULT '',
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (terminal_session_id, event_ordinal)
);

CREATE TABLE IF NOT EXISTS learning_step_attempts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    learner_id text NOT NULL DEFAULT '',
    learning_path_id uuid REFERENCES learning_paths(id) ON DELETE SET NULL,
    learning_step_id uuid NOT NULL REFERENCES learning_steps(id) ON DELETE CASCADE,
    terminal_session_id uuid REFERENCES terminal_sessions(id) ON DELETE SET NULL,
    status text NOT NULL DEFAULT 'in_progress',
    started_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS command_check_results (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    learning_step_attempt_id uuid REFERENCES learning_step_attempts(id) ON DELETE SET NULL,
    terminal_session_id uuid REFERENCES terminal_sessions(id) ON DELETE CASCADE,
    terminal_event_id uuid REFERENCES terminal_events(id) ON DELETE SET NULL,
    command_check_id uuid NOT NULL REFERENCES command_checks(id) ON DELETE CASCADE,
    lab_task_id uuid NOT NULL REFERENCES lab_tasks(id) ON DELETE CASCADE,
    learner_id text NOT NULL DEFAULT '',
    submitted_command text NOT NULL DEFAULT '',
    stdout text NOT NULL DEFAULT '',
    stderr text NOT NULL DEFAULT '',
    exit_code integer,
    status text NOT NULL DEFAULT 'pending',
    matched boolean NOT NULL DEFAULT false,
    validation_result jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (terminal_session_id, command_check_id)
);

CREATE INDEX IF NOT EXISTS idx_terminal_sessions_learning_step
    ON terminal_sessions(learning_step_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_terminal_events_session_ordinal
    ON terminal_events(terminal_session_id, event_ordinal);

CREATE INDEX IF NOT EXISTS idx_learning_step_attempts_step_started
    ON learning_step_attempts(learning_step_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_command_check_results_session_status
    ON command_check_results(terminal_session_id, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_command_check_results_lab_task
    ON command_check_results(lab_task_id, updated_at DESC);

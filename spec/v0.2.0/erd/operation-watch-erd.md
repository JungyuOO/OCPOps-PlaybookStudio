# Operation Watch ERD Draft

## Goal

Represent user-initiated operations and the resources PlaybookStudio watches until completion, failure, timeout, or cancellation.

## Candidate Tables

- `operation_runs`
- `operation_steps`
- `operation_watch_targets`
- `operation_events`
- `operation_notifications`
- `operation_diagnoses`

## operation_runs

Represents a chat or terminal initiated operation.

Key fields:

- `id`
- `trigger_source`
- `command_text`
- `namespace`
- `owner_user_id`
- `status`
- `started_at`
- `completed_at`
- `failed_at`

## operation_watch_targets

Resources being watched.

Key fields:

- `operation_run_id`
- `resource_kind`
- `namespace`
- `resource_name`
- `selector`
- `status`
- `last_seen_at`

## operation_notifications

Messages emitted to chat/UI.

Key fields:

- `operation_run_id`
- `notification_type`
- `severity`
- `message`
- `evidence`
- `created_at`

## Notes

Operation Watcher must not perform automatic destructive remediation.

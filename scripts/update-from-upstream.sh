#!/usr/bin/env bash
# Safely merge origin/main into a fork branch and validate its migration seam.
set -euo pipefail

# Keep this short, explicit list easy to adjust as the fork's customization surface moves.
SCHEDULED_TASK_TESTS=(
  tests/db/test_migration_scheduled_tasks.py
  tests/stores/test_scheduled_task_store.py
  tests/runner/test_scheduled_task_tool_dispatch.py
  tests/server/integration/test_scheduled_tasks_routes.py
)

allow_dirty=false
check_only=false

usage() {
  cat <<'EOF'
Usage: scripts/update-from-upstream.sh [--check-only] [--allow-dirty]

Safely merge origin/main into the current branch, then validate migrations and
the scheduled-task customization seam.

Options:
  --check-only   Skip backup, fetch, and merge; run only post-merge checks.
  --allow-dirty  Permit a dirty tree for a normal update. Never commits WIP.
  -h, --help     Show this help text.

The normal update snapshots the local database and creates a timestamped branch
and tag backup before fetching.
If a merge conflicts, resolve it manually, then rerun with --check-only.
EOF
}

banner() {
  printf '\n=== %s ===\n' "$1"
}

fail() {
  printf 'FAIL: %s\n' "$1" >&2
}

notice() {
  printf 'NOTICE: %s\n' "$1"
}

while (($# > 0)); do
  case "$1" in
    --check-only) check_only=true ;;
    --allow-dirty) allow_dirty=true ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "Unknown option: $1"
      usage >&2
      exit 2
      ;;
  esac
  shift
done

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "$script_dir/.." && pwd)
cd "$repo_root"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  fail "This script must run from a Git worktree."
  exit 2
fi

# A custom local SQLite URL determines both the guarded and backed-up database path.
if [[ -z "${OMNIGENT_DB_URL:-}" ]]; then
  OMNIGENT_DB_PATH="$HOME/.omnigent/chat.db"
  OMNIGENT_DB_URL="sqlite:///$OMNIGENT_DB_PATH"
elif [[ "$OMNIGENT_DB_URL" == sqlite:///* ]]; then
  OMNIGENT_DB_PATH="${OMNIGENT_DB_URL#sqlite:///}"
else
  OMNIGENT_DB_PATH=""
fi
export OMNIGENT_DB_URL

run_alembic_single_head_guard() {
  local alembic_output head_count

  banner "Alembic single-head guard"
  if ! alembic_output=$(uv run alembic -c omnigent/db/alembic.ini heads 2>&1); then
    printf '%s\n' "$alembic_output"
    fail "Alembic heads could not be inspected. Fix the Alembic error and rerun."
    return 1
  fi
  printf '%s\n' "$alembic_output"

  head_count=$(grep -Ec '\(head\)' <<<"$alembic_output" || true)
  if ((head_count != 1)) || grep -qi 'present more than once' <<<"$alembic_output"; then
    fail "Expected exactly one Alembic head with no duplicate-revision warning."
    printf '%s\n' \
      "This likely means local and upstream migrations reused a revision ID." \
      "Renumber the local migration revision ID(s) and update their down_revision references," \
      "then rerun this check."
    return 1
  fi

  printf 'PASS: exactly one Alembic head detected.\n'
}

run_alembic_database_drift_guard() {
  local alembic_current_output alembic_heads_output current_revisions head_revisions

  banner "Alembic database drift guard"
  if [[ -z "$OMNIGENT_DB_PATH" ]]; then
    notice "OMNIGENT_DB_URL is not a local SQLite URL; skipping database migration drift check."
    return 0
  fi
  if [[ ! -f "$OMNIGENT_DB_PATH" ]]; then
    notice "No database found at $OMNIGENT_DB_PATH; skipping database migration drift check."
    return 0
  fi
  if ! alembic_heads_output=$(uv run alembic -c omnigent/db/alembic.ini heads 2>&1); then
    printf '%s\n' "$alembic_heads_output"
    fail "Alembic heads could not be inspected for database drift."
    return 1
  fi
  if ! alembic_current_output=$(uv run alembic -c omnigent/db/alembic.ini current 2>&1); then
    printf '%s\n' "$alembic_current_output"
    fail "Alembic current revision could not be inspected for database drift."
    return 1
  fi

  head_revisions=$(awk '/\(head\)/ {print $1}' <<<"$alembic_heads_output" | sort)
  current_revisions=$(awk 'NF == 1 || (NF == 2 && $2 == "(head)") {print $1}' <<<"$alembic_current_output" | sort)

  printf 'Alembic heads: %s\n' "${head_revisions:-<none>}"
  printf 'Database current revision: %s\n' "${current_revisions:-<none>}"
  if [[ "$current_revisions" != "$head_revisions" ]]; then
    printf '%s\n' \
      'WARNING: DATABASE MIGRATION DRIFT DETECTED' \
      'The configured database is not stamped at the Alembic head. Pending migrations may exist.' \
      'No migrations were run by this script; restart the omnigent server or run the approved migration workflow.' >&2
    return 0
  fi

  printf 'PASS: database revision matches the Alembic head.\n'
}

run_scheduled_task_tests() {
  banner "Scheduled-task seam tests"
  if uv run pytest -q -p no:cacheprovider "${SCHEDULED_TASK_TESTS[@]}"; then
    printf 'PASS: scheduled-task seam tests passed.\n'
  else
    fail "Scheduled-task seam tests failed. Review upstream API or schema changes."
    return 1
  fi
}

run_post_merge_checks() {
  local checks_failed=false

  banner "Post-merge checks"
  run_alembic_single_head_guard || checks_failed=true
  run_alembic_database_drift_guard || checks_failed=true
  run_scheduled_task_tests || checks_failed=true

  if [[ "$checks_failed" == true ]]; then
    banner "UPDATE CHECKS FAILED"
    printf '%s\n' \
      "Fix the failures above before using this branch. The Alembic guard usually means" \
      "a local-vs-upstream migration revision-ID collision that needs local IDs renumbered."
    return 1
  fi

  banner "UPDATE CHECKS PASSED"
  printf '%s\n' \
    "Review the merge diff; this branch is ready once the review is complete." \
    "Restart any running omnigent server so it loads the merged code and runs new migrations."
}

if [[ "$check_only" == true ]]; then
  banner "Check-only mode"
  run_post_merge_checks
  exit $?
fi

banner "Preflight"
dirty_files=$(git status --short)
if [[ -n "$dirty_files" && "$allow_dirty" != true ]]; then
  fail "Working tree is not clean. Commit or stash your WIP, or rerun with --allow-dirty."
  printf '%s\n' "Dirty files:" "$dirty_files" >&2
  exit 1
fi
if [[ -n "$dirty_files" ]]; then
  printf '%s\n' "WARNING: continuing with a dirty tree; your WIP will not be committed."
else
  printf 'PASS: working tree is clean.\n'
fi

backup_database() {
  local database_backup_path

  if [[ -z "$OMNIGENT_DB_PATH" ]]; then
    notice "OMNIGENT_DB_URL is not a local SQLite URL; skipping database safety backup."
    return 0
  fi
  if [[ ! -f "$OMNIGENT_DB_PATH" ]]; then
    notice "No database found at $OMNIGENT_DB_PATH; skipping database safety backup."
    return 0
  fi

  database_backup_path="$OMNIGENT_DB_PATH.bak-update-$update_timestamp"
  if ! uv run python -c 'import sqlite3,sys; src=sqlite3.connect(sys.argv[1]); dst=sqlite3.connect(sys.argv[2]); src.backup(dst); dst.close(); src.close()' "$OMNIGENT_DB_PATH" "$database_backup_path"; then
    fail "Database backup could not be created."
    return 1
  fi

  printf '%s\n' \
    "Created database backup $database_backup_path." \
    "To restore (with the server stopped): cp $database_backup_path $OMNIGENT_DB_PATH" \
    "Then delete stale sidecars: rm -f $OMNIGENT_DB_PATH-wal $OMNIGENT_DB_PATH-shm"
}

update_timestamp=$(date -u +%Y%m%dT%H%M%SZ)
backup_name="polly-backup-$update_timestamp"
backup_tag="${backup_name}-tag"
banner "Database safety backup"
backup_database
banner "Safety backup"
git branch "$backup_name" HEAD
git tag "$backup_tag" HEAD
printf '%s\n' \
  "Created branch $backup_name and tag $backup_tag." \
  "To restore: git reset --hard $backup_name"

banner "Fetch origin"
git fetch origin

banner "Upstream status"
git rev-list --left-right --count HEAD...origin/main | awk '{printf "Ahead of origin/main: %s\\nBehind origin/main: %s\\n", $1, $2}'

banner "Merge origin/main"
if ! git merge origin/main; then
  if [[ -n "$(git diff --name-only --diff-filter=U)" ]]; then
    fail "Merge conflicts need manual resolution. Resolve conflicts, then rerun with --check-only."
  else
    fail "Merge did not complete. Inspect Git's output, resolve the problem, then rerun with --check-only."
  fi
  exit 1
fi

run_post_merge_checks

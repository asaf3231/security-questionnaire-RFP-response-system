#!/usr/bin/env bash
# scripts/check_graded_artifacts.sh
# Enforces RULE_GRADED_ARTIFACT_LOCK (CLAUDE.md §5.3; QA META-LOCK).
#
# Pre-flight integrity gate, run before `make test` / `make eval`.
# The graded-artifact set is READ-ONLY for modification/deletion:
#   - ADDING a new test/fixture is allowed (encouraged).
#   - MODIFYING or DELETING an existing tracked artifact ABORTS the run (non-zero),
#     unless the human two-key override ALLOW_GRADED_EDIT=1 is set.
# A failing test/metric is a FINDING to report — never "fixed" by editing the check.
# See PM_Methodology_Prompt.md → Metric Integrity & Anti-Gaming (#4–#7).
#
# Portable: to reuse on another project, edit LOCKED_PATHS below — that is the only
# per-project knob. No non-stdlib deps; degrades gracefully outside a git repo.
#
# Scope note: this compares the working tree vs HEAD (catches an in-progress edit
# before commit — the executer/PM review point). Changes already committed on the
# branch are caught by the PM's Verifier-Independence re-run at the pre-edit revision.
set -euo pipefail

# --- The graded-artifact set (PER-PROJECT KNOB: edit this list) --------------
LOCKED_PATHS=("tests" "fixtures")

RULE="RULE_GRADED_ARTIFACT_LOCK"

# --- Not a git work tree / git missing → cannot enforce; warn and pass -------
if ! command -v git >/dev/null 2>&1 || ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "[$RULE] WARN: not a git work tree (or git unavailable) — lock not enforced."
  exit 0
fi

# --- No commits yet → nothing to compare against; pass ----------------------
if ! git rev-parse --verify -q HEAD >/dev/null 2>&1; then
  echo "[$RULE] WARN: no HEAD commit yet — lock not enforced."
  exit 0
fi

# --- Human two-key override -------------------------------------------------
if [ "${ALLOW_GRADED_EDIT:-0}" = "1" ]; then
  echo "[$RULE] OVERRIDE: ALLOW_GRADED_EDIT=1 — graded-artifact edits permitted for this run."
  echo "[$RULE] (This is the human key; it must NOT be set by an autonomous agent.)"
  exit 0
fi

# --- Only keep locked paths that actually exist in this repo -----------------
existing_paths=()
for p in "${LOCKED_PATHS[@]}"; do
  [ -e "$p" ] && existing_paths+=("$p")
done
if [ "${#existing_paths[@]}" -eq 0 ]; then
  echo "[$RULE] OK: no locked paths present yet (${LOCKED_PATHS[*]})."
  exit 0
fi

# --- Detect modified/deleted TRACKED files in the locked set (vs HEAD) -------
# --diff-filter=MD: Modified or Deleted only. Added/untracked files are allowed
# (add-only by default). Covers both staged and unstaged changes to tracked files.
violations="$(git diff HEAD --name-status --diff-filter=MD -- "${existing_paths[@]}" 2>/dev/null || true)"

if [ -n "$violations" ]; then
  {
    echo "ERROR [$RULE]: modification/deletion detected in the locked graded-artifact set:"
    echo "$violations" | sed 's/^/    /'
    echo ""
    echo "  The graded-artifact set (${existing_paths[*]}) is read-only for modify/delete."
    echo "  A failing test/metric is a FINDING to report — not fixed by editing the check."
    echo "  Adding NEW tests/fixtures is allowed; changing an existing one needs human sign-off."
    echo "  To authorize a legitimate, human-approved change for one run:"
    echo "      ALLOW_GRADED_EDIT=1 make test     # (or make eval)"
  } >&2
  exit 1
fi

echo "[$RULE] OK: no unauthorized modification/deletion in the locked set (${existing_paths[*]})."

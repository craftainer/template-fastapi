# Port the hardened issue-moderation workflows into template-base

## Status

Draft

Step 2 of the sequence in
[`2026-09-template-base-extraction.md`](2026-09-template-base-extraction.md)'s
"Execution" section. Repo: **craftainer/template-base**. Work in a
clone of that repo; this plan file stays here in template-fastapi.
Depends on: `2026-09-artifact-actions-pin.md` merged.

## Goal

template-fastapi's moderation workflows were hardened after
template-base was seeded. template-base's `moderate-bug-fix.yml` and
`moderate-feature-build.yml` still run Claude on untrusted issue text
with `contents: write` / `issues: write` / `pull-requests: write`, and
check out the mutable branch name `bug/<n>-repro` after the trust check
(a TOCTOU window). Because template-base classifies
`.github/workflows/` as `replace`, the first sync from template-base
into template-fastapi would **silently downgrade** template-fastapi to
the insecure version. This plan must land before any sync.

## Approach

### 1. Copy template-fastapi's versions verbatim

From template-fastapi's `main` (with plan 1 merged), copy these files
into template-base, overwriting where they exist:

| File | Exists in base? |
|---|---|
| `.github/workflows/moderate-bug-fix.yml` | yes — overwrite |
| `.github/workflows/moderate-bug-fix-apply.yml` | no — add |
| `.github/workflows/moderate-feature-build.yml` | yes — overwrite |
| `.github/workflows/moderate-feature-build-apply.yml` | no — add |
| `.github/scripts/moderate_apply_result.sh` | no — add |
| `.github/scripts/moderate_package_result.sh` | no — add |
| `.github/scripts/prompts/bug-fix.md` | yes — overwrite |
| `.github/scripts/prompts/feature-build.md` | yes — overwrite |

Also diff `moderate-bug-triage.yml`, `moderate-feature-triage.yml`,
`moderate-cleanup.yml`, `moderate-setup.yml`, `run_claude.sh`,
`reset_issue_state.sh`, `moderate_cleanup.sh` and the two triage prompts
between the repos. Expect only Python-vs-generic wording differences
(e.g. `uv run pytest` vs `prek run`). If any diff touches `permissions:`,
`if:` conditions, checkout `ref:`, or secrets handling, copy
template-fastapi's version of that hunk too and list it in the PR.

### 2. Make the copied files language-agnostic

In every file copied in step 1, find Python-specific text:

    grep -n "uv \|uv run\|pytest\|ruff\|mypy\|python\|alembic" <files>

Replace as follows. Anything not covered by this table: stop and ask.

| Found | Replace with |
|---|---|
| `uv run prek run ...` | `prek run ...` |
| allowed-tools entry `Bash(uv run *)` | `Bash(prek run *)` plus the extra-tools suffix below |
| prose naming ruff/mypy/pytest as "the checks" | "the check suite (`prek run --all-files --hook-stage manual`)" |

**Extra-tools extension point.** An instance like template-fastapi needs
Claude to run more than `prek` (e.g. `uv run pytest <path>` for a
targeted repro). In every `--allowedTools` string in all six
`moderate-*.yml` workflows that run Claude, append the optional
repository variable `MODERATION_EXTRA_TOOLS`:

    "Read,Grep,...,Bash(prek run *)${{ vars.MODERATION_EXTRA_TOOLS && format(',{0}', vars.MODERATION_EXTRA_TOOLS) || '' }}"

Keep each file's existing tool list otherwise unchanged. This goes only
into the **read-only** Claude jobs, never into an `-apply` workflow
(those don't run Claude).

### 3. Fix the dangling design links

Six base workflows point at `../../docs/plans/2026-09-issue-moderator.md`,
which doesn't exist in template-base. Replace each such reference with
`../workflows/README.md's "Issue moderation" section`, matching the
wording template-fastapi uses.

### 4. Update `.github/workflows/README.md`

Replace template-base's "Issue moderation" section with
template-fastapi's, then apply step 2's replacements to it. Add one
paragraph documenting `MODERATION_EXTRA_TOOLS`: an optional repository
variable holding extra comma-separated Claude Code `--allowedTools`
entries for the read-only moderation jobs, e.g. `Bash(uv run pytest *)`.
Add both `-apply` workflows to the section's file list.

### 5. Manifest

Both new workflows are already covered by the `.github/workflows/`
`replace` glob and both new scripts by `.github/scripts/`. No manifest
edit here — plan 3 enumerates these paths later.

## Verify

Show the output of each:

    prek run --all-files --hook-stage manual            # passes (includes the manifest-exhaustiveness check)
    grep -rn "2026-09-issue-moderator" .                # prints nothing
    grep -rn "uv run\|pytest\|mypy" .github/            # prints nothing
    grep -n "contents: write\|issues: write\|pull-requests: write" \
      .github/workflows/moderate-bug-fix.yml .github/workflows/moderate-feature-build.yml
                                                        # prints nothing — write perms live only in the -apply files

The workflows can't be exercised end to end without an
`ANTHROPIC_API_KEY` secret. If one is configured on template-base, file
a throwaway issue labelled for bug triage and follow it through to the
`-apply` run, then delete the issue and branch. Otherwise say plainly in
the PR that this wasn't exercised.

## Done when

The PR (`fix(moderation): run Claude read-only, apply results in a
separate workflow`) is merged into template-base `main`. Don't tag a
release yet — plan 4 does that. Set this file's Status to `Done`; the
umbrella plan deletes it at the end.

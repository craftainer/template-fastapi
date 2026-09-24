# Let template sync push workflow files

## Status

Draft

Blocks step 2 of
[`2026-09-fastapi-bootstrap-base.md`](2026-09-fastapi-bootstrap-base.md).
Touches two repos: **craftainer/template-base** (the real fix) and
**craftainer/template-fastapi** (this one; a one-time hand copy of that
fix, so the first sync can push).

## Goal

`template-sync.yml` fails when a sync changes anything under
`.github/workflows/`. The first template-fastapi sync (v1.1.0 → v1.2.0)
failed like this:

    ! [remote rejected] template-sync/v1.2.0 -> template-sync/v1.2.0
      (refusing to allow a GitHub App to create or update workflow
      `.github/workflows/README.md` without `workflows` permission)

The default `GITHUB_TOKEN` can never write to `.github/workflows/`.
`TEMPLATE_SYNC_TOKEN` exists, but it's only used for *reading* the
template (steps "Fetch template tags" and "Check out template at both
tags"). The push goes out with the credentials that `actions/checkout`
stored, and those are always `github.token`.

Fix: use `TEMPLATE_SYNC_TOKEN` (falling back to `github.token`) for the
checkout and for "Open sync PR" too, and document that the token needs
the `workflow` scope.

## Approach

Keep the edits in this plan **exactly** as written. Step 3 copies the
template-base change into template-fastapi byte-for-byte. `.github/workflows/`
is `replace` tier, so if the two copies are identical, the next sync
won't show any diff for that file.

### 1. Ask the user to create the token (you can't do this)

Before anything else, tell the user to:

- Create a PAT: either a classic one with `repo` + `workflow` scopes, or
  a fine-grained one covering both craftainer/template-base and
  craftainer/template-fastapi with **Contents: read/write**,
  **Pull requests: read/write**, **Workflows: read/write**.
- Save it as the Actions secret `TEMPLATE_SYNC_TOKEN` in
  craftainer/template-fastapi (Settings → Secrets and variables →
  Actions → Secrets).
- Delete the stale remote branch `template-sync/bootstrap-v1.2.0` in
  template-fastapi. It's left over from the bootstrap PR (#23).

Continue with step 2 while they do that. Step 4 needs the secret.

### 2. Fix template-base

Work in a local clone of craftainer/template-base, on a new branch
`fix/template-sync-push-token` created from `main`. First read the
README.md chain for the paths you change (`README.md`, then
`.github/CONTENTS.md`, then `.github/workflows/README.md`), as the repo's
CLAUDE.md says.

**2a. `.github/workflows/template-sync.yml`.** Make exactly two edits.

Edit 1: the "Check out repository" step. Replace

```yaml
      - name: Check out repository
        uses: actions/checkout@v7.0.1
```

with

```yaml
      # TEMPLATE_SYNC_TOKEN, not the default GITHUB_TOKEN: checkout stores
      # this token for the later `git push`, and GITHUB_TOKEN can never
      # create or update files under .github/workflows/ -- which most
      # syncs touch. Falls back to GITHUB_TOKEN for a sync that doesn't.
      - name: Check out repository
        uses: actions/checkout@v7.0.1
        with:
          token: ${{ secrets.TEMPLATE_SYNC_TOKEN || github.token }}
```

Keep the `actions/checkout` version the file already uses. Don't change
it.

Edit 2: the "Open sync PR" step. Its `env:` block currently reads

```yaml
        env:
          GH_TOKEN: ${{ github.token }}
```

Change **only that step's** `GH_TOKEN` to

```yaml
        env:
          GH_TOKEN: ${{ secrets.TEMPLATE_SYNC_TOKEN || github.token }}
```

Don't touch the "Bootstrap state file" step's `GH_TOKEN`. That step only
writes `.github/template-sync-state.json`, which `github.token` can push.

Leave every other line unchanged. `git diff` must show only these two
hunks.

**2b. `.github/workflows/README.md`, "Template sync" section.** Replace
the `TEMPLATE_SYNC_TOKEN` bullet with:

```markdown
- `TEMPLATE_SYNC_TOKEN` (secret) — a PAT used to read the template
  repository and to push the sync branch / open the sync PR. It needs
  the `workflow` scope (classic PAT) or **Workflows: read/write**
  (fine-grained), because the default `GITHUB_TOKEN` can't push
  changes to `.github/workflows/`, and nearly every sync includes some.
  Falls back to `GITHUB_TOKEN`, which only works for a public template
  *and* a sync that touches no workflow file.
```

**2c. Verify.** Run and show the output:

    prek run --all-files
    git diff --stat        # exactly 2 files: template-sync.yml, workflows/README.md

If `actionlint` is among the hooks, it must pass. If it isn't, run
`actionlint .github/workflows/template-sync.yml` if it's installed.
Otherwise say it wasn't run.

**2d. Hand off.** Don't commit, push or tag. Give the user this commit
message and ask them to open and merge the PR, then cut a **stable
patch release** (expected tag: `v1.2.1`) the way template-base normally
releases:

    fix(template-sync): push sync branches with TEMPLATE_SYNC_TOKEN

    - check out with TEMPLATE_SYNC_TOKEN so the sync branch push can
      update .github/workflows/ (GITHUB_TOKEN never can)
    - use it for gh pr create in "Open sync PR" too
    - document the workflow scope the token needs

### 3. Copy the fix into template-fastapi

On a new branch `fix/template-sync-push-token` in template-fastapi,
created from `origin/main`, apply **the identical 2a and 2b edits**.
Copy the text from the template-base diff. Don't retype it. Then check
that the two copies match:

    diff <template-base clone>/.github/workflows/template-sync.yml .github/workflows/template-sync.yml
    # must print nothing

`.github/workflows/README.md` is also replace tier, but template-fastapi's
copy may still differ from base's in other sections until the sync lands.
So only compare the `TEMPLATE_SYNC_TOKEN` bullet by eye.

Run `prek run --all-files` and show the output. Give the user a commit
message (`fix(template-sync): push sync branches with
TEMPLATE_SYNC_TOKEN`, same bullets) and ask them to merge it to `main`.
Say in the PR description that this is a stopgap that base v1.2.1
replaces.

### 4. Re-run the sync (user)

Wait until **all** of these are true:
- step 3's PR is merged into template-fastapi `main`
- the `TEMPLATE_SYNC_TOKEN` secret is set
- template-base `v1.2.1` is tagged (optional; see "Open questions")

Then ask the user to run Actions → **Template sync** in template-fastapi
with no inputs. `.github/template-sync-state.json` on `main` already
reads `synced_tag: v1.1.0`, so don't touch it.

Expected: the run succeeds and opens a PR from branch
`template-sync/v1.2.1` (or `template-sync/v1.2.0` if v1.2.1 isn't tagged
yet). If the push fails again, stop and ask the user to paste the "Open
sync PR" step log. Don't try another fix.

### 5. Correct the bootstrap plan

Edit steps 1–2 of
[`2026-09-fastapi-bootstrap-base.md`](2026-09-fastapi-bootstrap-base.md)
so they match what actually works:
- Bootstrap at the tag **before** the target (`v1.1.0`), not at the
  target itself. Bootstrapping at `v1.2.0` makes step 2 a silent no-op
  ("Already synced").
- Step 1 now has a prerequisite: `TEMPLATE_SYNC_TOKEN` must be set with
  workflow permission (link this plan).
- The step 2 sync goes to the newest stable tag (`v1.2.1`), not `v1.2.0`.
  Update the other `v1.2.0` references in that plan where they mean
  "the version being synced to".

Also mark that plan's Status as `In progress` (steps 1–2 done).

Then continue with that plan from its step 3, on the sync PR's branch.

## Open questions

- Should step 4 wait for `v1.2.1`, or sync to `v1.2.0` right away? If you
  sync to `v1.2.0` first, the next sync (to `v1.2.1`) will be a no-op
  for `template-sync.yml`, since step 3 already matches it. Waiting avoids
  a second sync PR. Default: wait, unless the user says otherwise.

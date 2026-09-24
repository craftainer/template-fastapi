# Pin the artifact actions to one exact version each

## Status

Draft

Step 1 of the sequence in
[`2026-09-template-base-extraction.md`](2026-09-template-base-extraction.md)'s
"Execution" section. Repo: **craftainer/template-fastapi** (this one).
No dependencies.

## Goal

`actions/upload-artifact` / `actions/download-artifact` are referenced at
three different versions across `.github/workflows/`, two of them as
floating major tags (`@v4`) where every other action in this repo is
pinned to an exact `x.y.z`. Land Renovate PR #20 and finish the pinning
it leaves floating, so the hardened moderation workflows that
`2026-09-base-hardened-moderation.md` copies into `template-base` carry
the right versions.

## Approach

1. Commit the already-modified `.devcontainer/devcontainer-lock.json`
   on its own first (`chore(devcontainer): lock docker-in-docker
   4.1.1`) — it only catches the lock file up to the `4.1.1` that
   `.devcontainer/devcontainer.json` already requests. Don't bundle it
   with the workflow change.
2. Check out Renovate's branch for PR #20
   (`git fetch origin && git branch -r | grep renovate` — the branch
   whose name contains `major`). Branch off it as
   `chore/pin-artifact-actions`.
3. Make every reference exact. Run:

       grep -rn "actions/upload-artifact@\|actions/download-artifact@" .github/workflows/

   Every hit must end up as exactly `actions/upload-artifact@v7.0.1` or
   `actions/download-artifact@v8.0.1`. If Renovate's branch shows a
   *newer* exact version than these for either action, use Renovate's
   version instead, everywhere, and write down which one you used in
   the PR description — plan 2 needs it.
4. Review the two breaking changes from the release notes against each
   call site (there are 7; the grep above lists them):
   - `download-artifact` v8 errors on a hash mismatch instead of
     warning. No change needed — record in the PR description that
     this is accepted.
   - `download-artifact` v8 adds `skip-decompress` and
     `upload-artifact` v7 adds `archive`. Both default to the old
     behavior. Confirm no call site passes either input; if one does,
     stop and ask.
   - `moderate-bug-fix-apply.yml` and `moderate-feature-build-apply.yml`
     download from *another* workflow run. Confirm they still pass
     `run-id:` and `github-token:` (renamed inputs would be listed in
     the v5–v8 release notes; if any input they use was renamed or
     removed, stop and ask).
5. Verify (show the output of each):

       grep -rn "artifact@v[0-9]*$\|artifact@v[0-9]*\s" .github/workflows/   # must print nothing
       uv run prek run --all-files --hook-stage manual                       # must pass

6. Open a PR titled `ci: pin upload/download-artifact to exact versions`
   that supersedes #20 (say "Supersedes #20" in the body so Renovate
   closes it once merged).

Not verifiable locally: `release.yml` and the two `-apply` workflows only
run on a release / a moderation event. Say so in the PR description
rather than claiming they were exercised.

## Done when

The PR is merged, #20 is closed, and the step 5 grep prints nothing on
`main`. Then delete this file (per `README.md` in this directory).

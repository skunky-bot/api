# Automatic pull-request merge policy

This repository uses **GitHub native auto-merge**. All required checks and reviews
must pass before GitHub merges a pull request. A failed or missing check must
block merging. A draft PR remains excluded.

## Required one-time repository settings

An organization/repository administrator must configure:

1. Settings → General → Pull Requests → **Allow auto-merge** and **Allow squash merging**.
2. Settings → Branches (or Rules → Rulesets) → protect `main`.
3. Require a pull request before merging and require the status check named `test`
   from the `API CI` workflow. Set **Require branches to be up to date** if appropriate.
4. Require conversation resolution; use required review approvals for higher-risk code.
5. Restrict bypass of rules and prevent direct pushes to `main` where permitted.

This automation only requests native auto-merge. It **does not bypass** failures,
required reviews, branch protections, or GitHub rulesets.

## Workflow design

`.github/workflows/auto-merge.yml` uses `pull_request_target` with no
checkout and no execution of pull-request code. Before invoking native auto-merge,
it verifies the protected base branch has an enforced `test` required check.
It does nothing if this condition cannot be verified.

After repository settings are enabled, existing open PRs may require a
`synchronize` (new commit), `reopen`, or explicit auto-merge request.

## Security note

Automation cannot guarantee production correctness from unit tests alone.
Add secret scanning, dependency scanning, integration tests, and deployment
gates as required checks before automating production-impacting merges.
Never grant untrusted PR code access to the privileged automation token.

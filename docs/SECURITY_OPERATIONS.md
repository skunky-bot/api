# Incident response: tracked environment configuration

An environment configuration file was previously committed to this repository.
Removing it from the current tree does **not** remove its contents from Git
history, forks, clones, or cached archives.

## Required owner actions

- Rotate the bootstrap administrator password everywhere it may have been used.
- Review other values in the historical file and rotate any credentials that were
  actually active; investigate access logs if the repository was public.
- Confirm whether the same password was reused on any other system.
- Confirm production configuration is now injected from the deployment secret
  store and that a bootstrap administrator is not created with example defaults.
- Coordinate any repository history rewrite with maintainers. Rewriting history
  requires explicit planning for clones, PRs, tags and forks.
- Add repository-wide secret scanning and push protection as available.

Do not copy credential contents into issues, pull requests, CI logs, or chat.

## API release requirements

- A non-empty, non-example JWT signing key from a secret manager
- Distinct admin credentials per deployment
- A protected default branch with required CI and code review
- Dependency scanning and permission review
- Verified rollback and rotation procedures

The removal is tracked by PR #1. A passing API test does not close this
incident: manual rotation and exposure assessment remain required.

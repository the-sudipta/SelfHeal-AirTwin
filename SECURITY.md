# Security Policy

## Supported versions

Only the latest release receives fixes. Reviewers should always use the latest release image, pulled by digest.

## Reporting a vulnerability

Please **do not open a public issue**. Report privately through GitHub's [private vulnerability reporting](https://github.com/the-sudipta/SelfHeal-AirTwin/security/advisories/new) or by email to **sudiptakumar400@gmail.com**.

Include the affected version or commit, steps to reproduce, and the impact you expect. You will receive an acknowledgement within 7 days and a plan for a fix or mitigation within 30 days.

## In scope

- The Python package, the API and the web twin served from the container.
- The Docker image and compose configuration.
- Supply-chain issues: dependency pinning, dataset checksums, GitHub Actions workflows.
- Anything that lets someone change data, results or releases without the change being detectable (see [INTEGRITY.md](INTEGRITY.md)).

## Built-in safeguards

- Dependencies are pinned with hashes and installed with `pip install --require-hashes`.
- Datasets are verified against pinned SHA-256 values; a mismatch stops the program.
- Every GitHub Action is pinned to a full commit SHA.
- The container runs as a non-root user.
- Commits and tags are signed.

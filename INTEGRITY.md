# Integrity: how to check that nothing was changed

## What this can and cannot promise

Nothing can stop the author from adding new commits to this repository. What the measures below do is make every change **visible**: any rewrite of history, or any swap of data, results or images, can be detected by anyone, without trusting the author. This document grows with each milestone as new safeguards are added.

## 1. Signed commits and tags

Every commit and every release tag on `main` is signed with the author's SSH signing key. On GitHub, each commit shows a green **Verified** badge, and vigilant mode is on, so an unsigned commit pushed under the author's name is flagged as **Unverified**.

Check signatures locally against the public keys GitHub publishes for the author:

```bash
curl -s https://api.github.com/users/the-sudipta/ssh_signing_keys \
  | python3 -c "import sys,json; [print('*', k['key']) for k in json.load(sys.stdin)]" > allowed_signers
git -c gpg.ssh.allowedSignersFile=allowed_signers log --show-signature
git -c gpg.ssh.allowedSignersFile=allowed_signers tag -v v0.1.0
```

Each commit must print `Good "git" signature`.

## 2. Protected `main` branch

A branch ruleset on `main` blocks force pushes and deletion, requires signed commits, requires linear history and requires the CI check to pass. The bypass list is empty, so the rules apply to the author as well.

## 3. History is never rewritten

Published commits are never amended, rebased, reset or force-pushed. Mistakes are fixed with a new commit, so the full history of every result stays visible. A clone made at any time remains a prefix of every later clone; if it does not, history was rewritten.

```bash
git merge-base --is-ancestor <old-commit> origin/main && echo "history intact"
```

## 4. Pinned CI

CI runs on every push. Every GitHub Action is pinned to a full commit SHA, so a moved tag upstream cannot silently change what runs.

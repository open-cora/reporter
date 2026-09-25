# Security Policy

## Supported versions

The reporter is pre-1.0 and under active development. Only the `main` branch
receives security fixes. There are no LTS lines.

## Reporting a vulnerability

Please **do not** open a public issue for security vulnerabilities.

Use **GitHub's private vulnerability reporting** for this repository:

1. Go to the [Security tab](https://github.com/open-cora/reporter/security) of the repo.
2. Click **Report a vulnerability**.
3. Fill in the form with as much detail as you can:
   - the affected component (translator, source, client, session, config)
   - the impact
   - reproduction steps or a proof-of-concept
   - the commit hash you tested against

You will receive an acknowledgement within **5 business days**. We aim to
issue a fix or a public advisory within **30 days** of acknowledgement,
depending on severity and complexity.

## What this software does, which is the thing to read first

A reporter reads one acquisition engine's document stream and writes reports
to the keeper. It creates nothing: the keeper composes the procedure,
dispatches the execution and holds the record, and a report that names no
dispatched step is refused at the far end.

That shape bounds what a defect here can do. The worst case is a wrong or
missing report against a record somebody else made, not a record made out of
nothing.

## Scope

In scope:

- The reporter itself: the translators, the sources, the keeper client, the
  session and the configuration loader.
- CI, build, and tooling in `.github/workflows/` and the `Makefile`.

Out of scope:

- Vulnerabilities in upstream dependencies; report those upstream.
- The keeper's API surface. Report those against
  [the keeper](https://github.com/open-cora/keeper/security).
- An engine's document stream with no access control in front of it. A
  message transport that accepts a publisher without authenticating it is a
  deployment question. What this software promises is that a document it
  reads becomes a report and nothing more, not that only the right process
  published it.

## Hardening notes

- **The configuration holds a bearer token.** It is a file an operator writes
  and this repository must never ship one. Give it the narrowest grant that
  lets the reporter report: it needs to write step outcomes and dataset
  locations, and nothing else.
- **Every call goes out and none comes in.** A reporter needs no inbound port
  and no listening socket. A deployment that adds one has added an attack
  surface this design does not have.
- **A document published while the reporter is down is lost.** That is an
  availability property of the current transport rather than a vulnerability,
  and the README states it. A deployment that needs replay needs a transport
  that offers it.

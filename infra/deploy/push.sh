#!/usr/bin/env bash
# Ships this app to one beamline host from a revision, and records which.
#
#   BEAMLINE=19-bm HOST=radon ./push.sh c7a5a55
#   BEAMLINE=7-bm  HOST=karman PREFIX=corasim7bm:TomoScan: ./push.sh v0.4.0
#
# Which app is read from where this script sits rather than written into
# it, so the same bytes serve every app that deploys into a home directory.
# A mirror carries its own copy, as it carries its own licence, and a test
# in the tree proves the copies identical.
#
# The revision is required rather than defaulting to HEAD. It defaulted
# once, and the day a commit landed that must not reach a beamline, the
# bare command silently became the dangerous one. Naming what you ship is
# the whole point of the script, so it asks.
#
# ## Why this exists rather than an rsync of src
#
# Deploying used to be `rsync -a --delete src/ host:...`, which reads the
# working tree. Whatever sits open in an editor at that moment is what
# reaches the beamline, and nothing between a keystroke and a running
# experiment refuses it. That is not hypothetical: this tree held an
# unfinished change to a client's filing seam for most of one day, and
# either deployed beamline would have taken it.
#
# `git archive` of a commit cannot do that. What lands is something that
# exists in history, so it can be named, compared between beamlines, and
# rolled back to.
#
# ## Why it writes a revision file
#
# A host that cannot say what it runs makes every later question
# unanswerable: whether a fix reached it, whether two beamlines match, what
# to go back to. Before this, the only way to ask was to grep the deployed
# source for a function name and infer.
#
# ## What it does not do
#
# It does not build the virtualenv, which `install.sh` does and only when
# one is missing, and it does not touch the configuration, which holds the
# beamline's token and belongs to whoever runs the keeper.

set -euo pipefail

BEAMLINE="${BEAMLINE:?BEAMLINE is required, for example BEAMLINE=19-bm}"
HOST="${HOST:?HOST is required, for example HOST=radon}"
REF="${1:?a revision is required, for example c7a5a55 or HEAD. It is named rather than defaulted because a default is whatever happened to be committed last}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TREE="$(cd "${APP_DIR}/../.." && pwd)"
APP="$(basename "${APP_DIR}")"
REMOTE="${REMOTE:-cora-${APP}}"

say() { printf '  %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

cd "${TREE}"

SHA="$(git rev-parse --verify --quiet "${REF}^{commit}")" \
  || die "no commit named ${REF}"
SUBJECT="$(git log -1 --format=%s "${SHA}")"
DESCRIBED="$(git describe --tags --always "${SHA}" 2>/dev/null || echo "${SHA}")"

echo "Shipping ${APP} for ${BEAMLINE} to ${HOST}"
say "revision  ${DESCRIBED} (${SHA})"
say "subject   ${SUBJECT}"
echo

# The whole point of the script, so it is said out loud rather than left for
# the operator to realise afterwards. Shipping a commit while the tree holds
# something else is correct and is usually what is wanted, but it must never
# be a surprise.
DIFFERS="$(git diff --name-only "${SHA}" -- "apps/${APP}" | wc -l | tr -d ' ')"
if [ "${DIFFERS}" != "0" ]; then
  echo "Note"
  say "the working tree differs from ${REF} in ${DIFFERS} file(s) under apps/${APP}"
  say "those differences are NOT being shipped. ${DESCRIBED} is."
  git diff --name-only "${SHA}" -- "apps/${APP}" | sed 's/^/    /'
  echo
fi

# What the host is moving from, which is the question the operator is
# really being asked. A revision and a subject say what is going; only the
# span between says what changes, and a commit nobody meant to ship is
# visible here and nowhere else.
echo "Host"
CURRENT="$(ssh "${HOST}" "sed -n 's/^revision //p' ${REMOTE}/REVISION 2>/dev/null" 2>/dev/null || true)"
if [ -z "${CURRENT}" ]; then
  say "carries no REVISION, so what it runs now cannot be named"
elif [ "${CURRENT}" = "${SHA}" ]; then
  say "already at ${DESCRIBED}, so this is a reinstall of the same code"
else
  say "at $(git describe --tags --always "${CURRENT}" 2>/dev/null || echo "${CURRENT}")"
  if git merge-base --is-ancestor "${CURRENT}" "${SHA}" 2>/dev/null; then
    say "shipping $(git rev-list --count "${CURRENT}..${SHA}") commit(s) on top of it:"
    git log --oneline "${CURRENT}..${SHA}" | sed 's/^/    /'
  else
    say "which is not an ancestor of ${DESCRIBED}, so this is not a fast move forward"
  fi
fi
echo

STAGING="$(mktemp -d)"
trap 'rm -rf "${STAGING}"' EXIT

echo "Export"
git archive --format=tar "${SHA}:apps/${APP}" | tar -x -C "${STAGING}" \
  || die "could not export apps/${APP} from ${REF}"
[ -f "${STAGING}/infra/deploy/install.sh" ] \
  || die "${REF} has no infra/deploy/install.sh, so it cannot install itself"

# Written into the exported copy so it travels with the code rather than
# being applied afterwards, which would leave a window where a host carries
# the code and not the answer to what it is.
cat > "${STAGING}/REVISION" <<REV
app ${APP}
revision ${SHA}
described ${DESCRIBED}
ref ${REF}
subject ${SUBJECT}
beamline ${BEAMLINE}
pushed $(date -u '+%Y-%m-%dT%H:%M:%SZ') by $(whoami)@$(hostname -s)
REV
say "ok"
echo

echo "Copy"
# The virtualenv is not in git and must survive, and on a host that cannot
# reach a package index it cannot be rebuilt at all. Everything else under
# the app directory is replaced, so a file deleted in the revision is
# deleted on the host.
rsync -a --delete --exclude '.venv/' "${STAGING}/" "${HOST}:${REMOTE}/"
say "ok"
echo

# Forwarded rather than guessed, because what an installer needs differs by
# app: a reporter is told which records to watch and a conductor is not.
# Anything not set here is left for the installer's own default.
SETTINGS="BEAMLINE='${BEAMLINE}'"
if [ -n "${PREFIX:-}" ]; then
  SETTINGS="${SETTINGS} PREFIX='${PREFIX}'"
fi
if [ -n "${SYNC:-}" ]; then
  SETTINGS="${SETTINGS} SYNC='${SYNC}'"
fi

echo "Install"
ssh "${HOST}" "cd ${REMOTE}/infra/deploy && ${SETTINGS} ./install.sh"

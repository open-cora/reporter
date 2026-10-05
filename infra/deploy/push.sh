#!/usr/bin/env bash
# Ships this app to one host from a revision, and records which.
#
#   BEAMLINE=19-bm HOST=radon ./push.sh c7a5a55
#   BEAMLINE=7-bm  HOST=karman PREFIX=corasim7bm:TomoScan: ./push.sh v0.4.0
#   HOST=lyra ./push.sh HEAD
#
# Which app is read from where this script sits rather than written into
# it, so the same bytes serve every app that deploys into a home directory.
# A mirror carries its own copy, as it carries its own licence, and a test
# in the tree proves the copies identical.
#
# ## Why the beamline is optional and the host is not
#
# A host is what this ships to and there is always one. A beamline is what
# the thing being shipped belongs to, and not everything here belongs to
# one: a thinker is handed an execution and reads where that ran off the
# record, so it has no beamline setting to be told and asking for one
# would mean writing a fiction into the revision file.
#
# It is not merely defaulted, because the apps that do need it need it
# absolutely. Each of their installers requires it on its own, so pushing
# one without it stops at the install step with that installer's own
# message, after a copy that changed nothing a service reads.
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

BEAMLINE="${BEAMLINE:-}"
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

if [ -n "${BEAMLINE}" ]; then
  echo "Shipping ${APP} for ${BEAMLINE} to ${HOST}"
else
  echo "Shipping ${APP} to ${HOST}"
fi
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
REV
# Left out entirely rather than written empty, so somebody reading this
# file for a beamline gets no answer instead of one that looks like a
# name that went missing on the way.
if [ -n "${BEAMLINE}" ]; then
  echo "beamline ${BEAMLINE}" >> "${STAGING}/REVISION"
fi
cat >> "${STAGING}/REVISION" <<REV
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
SETTINGS=""
if [ -n "${BEAMLINE}" ]; then
  SETTINGS="BEAMLINE='${BEAMLINE}'"
fi
# Where the configuration, the CA bundle and the log live, which every
# installer here derives from one directory. It is forwarded because a
# host that is not a beamline wants them somewhere other than the home:
# the central host's home is NFS and mounted by a dozen machines, so a
# token at mode 600 in it is readable by all of them, where the same file
# on that host's local disk is readable on one.
if [ -n "${ETC:-}" ]; then
  SETTINGS="${SETTINGS} ETC='${ETC}'"
fi
# Separately from ETC, because the two come apart on a host that keeps a
# directory for logs. In a home the log belongs beside the configuration
# and ETC decides both; where something else already writes logs to one
# place, a second convention putting them under etc is just wrong.
if [ -n "${LOG:-}" ]; then
  SETTINGS="${SETTINGS} LOG='${LOG}'"
fi
if [ -n "${PREFIX:-}" ]; then
  SETTINGS="${SETTINGS} PREFIX='${PREFIX}'"
fi
if [ -n "${SYNC:-}" ]; then
  SETTINGS="${SETTINGS} SYNC='${SYNC}'"
fi
# What a virtualenv needs beyond the pair every installer syncs. One
# installer here reads it and the other three ignore it, and it is
# forwarded from all four because these scripts are one file: an app that
# grows an optional library needs no change here when it does.
#
# It was not forwarded at all until a deploy that passed it appeared to
# succeed and installed nothing. That is the quietest shape this can fail
# in: the variable is accepted by the shell, the installer documents it,
# and the only thing missing is a library nothing asks for until the
# configuration names it.
if [ -n "${EXTRAS:-}" ]; then
  SETTINGS="${SETTINGS} EXTRAS='${EXTRAS}'"
fi
# Forwarded even when it is empty, which none of the others are, because
# three states have to survive the hop and only two of them have a value.
# An installer that reads this back from the file it is about to rewrite
# takes unset to mean "keep what this host is already enforcing", a value
# to mean "enforce that one", and empty to mean "go permissive", which is
# how an authorization rollback is spelled.
#
# Testing the value with -n would collapse empty into unset, so the
# rollback would rewrite the file with the old setting still in it and
# report success. A rollback that silently does nothing is worse than one
# that fails, because it is run exactly when somebody has stopped reading
# carefully.
if [ -n "${AUTHZ_POLICY_ID+set}" ]; then
  SETTINGS="${SETTINGS} AUTHZ_POLICY_ID='${AUTHZ_POLICY_ID}'"
fi

echo "Install"
# Through `bash -lc` rather than as a bare remote command, because `VAR=value
# cmd` is not a thing every login shell can parse. One of these beamlines runs
# tcsh, where that line fails with "BEAMLINE=32-id: Command not found", after
# a copy that already landed. So the deploy reports a failure having changed
# the source on the host and nothing else, which is the worst of the three
# outcomes available. `-l` because uv is on PATH only for a login shell on
# that same host, and SYNC=1 needs it.
ssh "${HOST}" "bash -lc 'cd ${REMOTE}/infra/deploy && ${SETTINGS} ./install.sh'"

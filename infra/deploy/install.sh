#!/usr/bin/env bash
# Installs a reporter at one beamline as a `systemd --user` service, with no
# root and no system package.
#
#   BEAMLINE=2-bm PREFIX=corasim2bmb:TomoScan: ./install.sh
#
# Re-running it is how a new revision is deployed. It restarts the service
# rather than relying on `enable --now`, which is a no-op against something
# already running and would leave a changed unit on disk that never reaches
# the process.
#
# ## What it does not do
#
# It does not write the configuration, because that file holds the
# beamline's bearer token. Minting and distributing those belongs to
# whoever runs the keeper, and a token that this script could create is a
# token this script could create for any beamline.
#
# It does not install dependencies when a virtualenv is already present. The
# package declares no core dependencies on purpose, so a working install
# needs `--extra service` for the HTTP client and `--extra epics` for
# Channel Access. Set SYNC=1 to do that here, which needs a package index: a
# beamline whose host cannot reach one builds the virtualenv on a machine
# that can and shares it, which is what the shared home is for.
#
# ## Why it reads the records before it starts anything
#
# A reporter that cannot see the engine is not an error anybody notices. It
# starts, polls a record that never answers, reports nothing, and looks
# exactly like a beamline where nothing has run. So the records it will
# watch are read first, and a silent one stops the install.
#
# The two keeper ids are read as well as the scan records, because they are
# the pair that says which step a scan belonged to. A reporter without them
# still runs and ignores every scan for looking hand-started, which is the
# same silence by a different route.
#
# It reads them through the virtualenv's own pyepics, under the EPICS
# environment the unit is about to be given. This used to be caget, which
# is a separate EPICS install a beamline account may not have on its PATH,
# and that is what it turned out to be on the first host this ever ran on.
# Asking the library the service uses, addressed the way the service will
# be addressed, is both one fewer thing to install and the only version of
# this question whose answer is about the service rather than about a shell.

set -euo pipefail

BEAMLINE="${BEAMLINE:?BEAMLINE is required, for example BEAMLINE=2-bm}"
PREFIX="${PREFIX:?PREFIX is required: the record prefix of the engine}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

ETC="${ETC:-${HOME}/.config/cora}"
CONFIG="${CONFIG:-${ETC}/reporter-${BEAMLINE}.toml}"
CA_BUNDLE="${CA_BUNDLE:-${ETC}/ca-bundle.crt}"
EPICS_ENV="${EPICS_ENV:-${ETC}/epics.env}"
LOG="${LOG:-${ETC}/reporter-${BEAMLINE}.log}"

UNIT_DIR="${HOME}/.config/systemd/user"
UNIT="cora-reporter.service"
DEPLOY_HOST="$(hostname)"

say() { printf '  %s\n' "$*"; }
die() { printf 'refused: %s\n' "$*" >&2; exit 1; }

say "beamline    ${BEAMLINE}"
say "prefix      ${PREFIX}"
say "host        ${DEPLOY_HOST}"

[ -r "${CONFIG}" ] || die "no configuration at ${CONFIG}. This script will not write
    it: the file holds this beamline's bearer token, and a script that could
    mint one for this beamline could mint one for any."

mode="$(stat -c '%a' "${CONFIG}" 2>/dev/null || stat -f '%A' "${CONFIG}")"
[ "${mode}" = "600" ] || die "${CONFIG} is mode ${mode} and holds a token. chmod 600 it."
say "config      ${CONFIG}, mode ${mode}"

[ -r "${CA_BUNDLE}" ] || die "no CA bundle at ${CA_BUNDLE}. The keeper presents a
    certificate from a private CA, so this needs a bundle carrying the system
    anchors plus that one."

if [ "${SYNC:-0}" = "1" ]; then
    command -v uv >/dev/null || die "SYNC=1 needs uv on PATH"
    (cd "${APP_DIR}" && uv sync --locked --extra service --extra epics)
fi
[ -x "${APP_DIR}/.venv/bin/python3" ] || die "no virtualenv at ${APP_DIR}/.venv.
    Run again with SYNC=1, or share one built on a machine that can reach a
    package index."
# `epics.PV` rather than `import epics`, and this is not fussiness. A
# beamline account commonly has a directory called `epics` in its home,
# which Python imports as an empty namespace package, so the bare import
# succeeds while pyepics is absent. Measured on the 2-BM host, where
# `-P` does not help either. Touching a name pyepics actually defines is
# what tells the two apart.
"${APP_DIR}/.venv/bin/python3" -c "import epics; epics.PV" 2>/dev/null \
    || die "the virtualenv has no usable pyepics, so a record source cannot run.
    Re-sync with --extra epics, or install it from wheels. Note that a bare
    'import epics' can succeed here against a directory of that name in the
    home, which is why this checks for a name pyepics defines."

EPICS_ENVIRONMENT=""
if [ -r "${EPICS_ENV}" ]; then
    EPICS_ENVIRONMENT="EnvironmentFile=${EPICS_ENV}"
    say "epics env   ${EPICS_ENV}"
else
    say "epics env   none, so the service inherits the user manager's"
fi

ABSENT="$("${APP_DIR}/.venv/bin/python3" - "${PREFIX}" "${EPICS_ENV}" <<'PREFLIGHT'
import os
import sys

prefix, environment = sys.argv[1], sys.argv[2]

# Read before pyepics is imported, because the Channel Access library
# reads its addressing once as it loads and never looks again. Setting
# these afterwards would leave the probe searching a different network
# from the one the service will search, which is a preflight that can
# pass for a beamline where nothing will answer.
if os.path.isfile(environment):
    with open(environment, encoding="utf-8") as settings:
        for line in settings:
            name, assigned, value = line.strip().partition("=")
            if assigned and not name.startswith("#"):
                os.environ[name.strip()] = value.strip()

import epics  # noqa: E402

absent = [
    prefix + suffix
    for suffix in ("StartScan", "ScanStatus", "FullFileName", "KeeperExecutionId", "KeeperStepId")
    if not epics.PV(prefix + suffix, connection_timeout=5.0).wait_for_connection(timeout=5.0)
]
print(" ".join(absent))
PREFLIGHT
)"
[ -z "${ABSENT}" ] || die "these records do not answer: ${ABSENT}.
    A reporter that cannot see the engine starts, polls nothing and reports
    nothing, which looks exactly like a beamline where nothing ran."
say "preflight   every record this will watch answers"

mkdir -p "${ETC}" "${UNIT_DIR}"

sed -e "s|@BEAMLINE@|${BEAMLINE}|g" \
    -e "s|@DEPLOY_HOST@|${DEPLOY_HOST}|g" \
    -e "s|@APP_DIR@|${APP_DIR}|g" \
    -e "s|@CONFIG@|${CONFIG}|g" \
    -e "s|@CA_BUNDLE@|${CA_BUNDLE}|g" \
    -e "s|@PREFIX@|${PREFIX}|g" \
    -e "s|@EPICS_ENVIRONMENT@|${EPICS_ENVIRONMENT}|g" \
    -e "s|@LOG@|${LOG}|g" \
    "${SCRIPT_DIR}/reporter.service.in" > "${UNIT_DIR}/${UNIT}"
say "unit        ${UNIT_DIR}/${UNIT}"

systemctl --user daemon-reload
systemctl --user enable "${UNIT}"
systemctl --user restart "${UNIT}"

sleep 3
systemctl --user is-active --quiet "${UNIT}" \
    || die "the service did not stay up. systemctl --user status ${UNIT}"

if systemctl --user show "${UNIT}" --property=NRestarts --value | grep -qv '^0$'; then
    die "the service is up but has already restarted, so it is failing and
    being brought back. Read ${LOG} before believing it works."
fi

say "running     the reporter is watching ${PREFIX}StartScan"
say "done        a scan that ends carrying both keeper ids will be reported"

# Deploying a reporter

One reporter per beamline, supervised by `systemd --user`, with no root and
no system package.

```bash
BEAMLINE=7-bm PREFIX=corasim7bm:TomoScan: ./install.sh
```

Re-running it deploys a new revision. It restarts the service rather than
relying on `enable --now`, which is a no-op against something already
running and would leave a changed unit on disk that never reaches the
process.

## What it needs first, and does not create

**A configuration file at `~/.config/cora/reporter-<beamline>.toml`, mode
600.** It carries the beamline's bearer token, and minting and distributing
those belongs to whoever runs the keeper. A script that could write this one
could write one for any beamline. The installer refuses to proceed if the
file is missing or readable by anyone else.

It needs a `[dataset]` table as well as a `[keeper]` one, or the reporter
runs and files nothing. That is the difference between a reporter watching a
beamline and a reporter that is installed at one.

`[dataset]` may also carry `describer`, which turns on saying what is inside
the data as well as where it is. It is off unless the key is there, because
there is one format adapter so far and most beamlines are not writing that
format yet. A deployment that sets it needs `--extra describe-hdf5` in the
sync as well, and the process says so at startup rather than on the first
scan that ends.

**A CA bundle at `~/.config/cora/ca-bundle.crt`**, carrying the system
anchors plus the keeper's own CA. Pointing the client at the bare CA would
work and would also make the process distrust every other endpoint, which is
a surprise waiting for the first one.

**Lingering**, or the service stops the moment nobody is logged in. On these
hosts an account can enable it for itself with `loginctl enable-linger`,
needing no administrator, which is worth trying before filing a request.

**An `epics.env`**, only where the reporter cannot find its records by
broadcast. It is picked up automatically when present, and the preflight
reads the records under it, so a wrong address list fails the install rather
than the experiment.

## The virtualenv, and why the package looks empty without it

`reporter` declares no core dependencies on purpose: which engine a
deployment watches is a choice made at its entrypoint. So a plain `uv sync`
installs one package and the process will not start. It needs
`--extra service` for the HTTP client and `--extra epics` for Channel
Access, and `EXTRAS` for anything beyond those two:

```bash
SYNC=1 BEAMLINE=7-bm PREFIX=corasim7bm:TomoScan: ./install.sh

# and where dataset.describer is set
SYNC=1 EXTRAS="--extra describe-hdf5" BEAMLINE=2-bm PREFIX=2bm:TomoScan: ./install.sh
```

which needs a package index. A beamline whose host cannot reach one builds
the virtualenv on a machine that can and shares it, which is what the shared
home is for.

## Which engine it watches

`--records` rather than `--subscribe`, because a TomoScan beamline publishes
no documents. A deployment watching a RunEngine writes the other flag in the
unit template and needs no other change.

`PREFIX` is the record prefix of the scan server, not of the detector or the
motors. Ask a record which server answers for it with `cainfo` rather than
assuming the host you can see it from is the host that serves it.

## ConditionHost is not decoration

`systemd --user` reads units only from `$HOME`, and a beamline's `$HOME` is
NFS mounted by every machine at that beamline. Enabling this once from the
wrong shell starts a second reporter on another machine, watching the same
engine.

Two reporters are a milder fault than two conductors, which is worth being
precise about rather than reassuring. Nothing is driven twice and no
hardware moves. Both see the same scan end and both report it, so the keeper
is told twice about one run, and a second report of a step already reported
is refused rather than believed. The damage is noise in the log rather than
a wrong record. The guard is there anyway, because noise nobody can explain
costs a morning.

## What the installer checks, and why active is not enough

A reporter that cannot see the engine is not an error anybody notices. It
starts, polls a record that never answers, reports nothing, and looks
exactly like a beamline where nothing has run. So the records it will watch
are read first, through the virtualenv's own pyepics and under the EPICS
environment the unit is about to be given, and a silent one stops the
install.

The two keeper id records are read alongside the scan records. They are the
pair that says which step a scan belonged to, and a reporter without them
still runs and ignores every scan for looking hand-started, which is the
same silence by another route.

## Operating it

```bash
systemctl --user status cora-reporter.service
journalctl --user -u cora-reporter.service -f
tail -f ~/.config/cora/reporter-<beamline>.log
```

`Restart=always` with a fifteen second interval, long enough that a
misconfiguration does not become a request flood at the keeper. A reporter
that stops is a beamline whose scans still run and are never reported: the
executions stay open at the keeper and nothing says why.

## Shipping a revision

```bash
BEAMLINE=7-bm HOST=<beamline-host> PREFIX=corasim7bm:TomoScan: ./push.sh v0.4.0
```

`push.sh` exports a named commit rather than the working tree, writes a
`REVISION` file beside the code, and runs this installer over SSH. It is
byte-identical to the copy every other app carries, and a test in the
development tree proves they have not drifted.

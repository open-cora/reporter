"""No tracked file carries a coordinate that locates a facility's machines.

Every project here is published, and this tree is read by people with no
account at the facility it was written against. What keeps that safe is a
split between a finding and a coordinate.

A finding is architecture and it is published: that a beamline has one
routable host and several private ones, that reaching the hardware and
reaching a package index are separate properties and the host with both may
not exist, that a shared account makes a per-client distinction
unenforceable. None of those needs an address to be true, and this tree
states all of them.

A coordinate is what lets a stranger find and reach a machine: an address, a
subnet, a host name, an account, a home directory. Each grants nothing on
its own. Together they are the map anyone attacking the facility would have
to assemble first, and assembling it is not work a public repository should
do for them. They live in an untracked address book, which the ignore rules
keep out of every repository published from this tree. It is named by
ADDRESS_BOOK_NAME below, and no project ever contains one.

## Why the host names are read rather than written here

A deny-list usually states what it refuses. This one cannot: the names are
themselves the coordinate, so a list of them in a tracked file would publish
the thing the rule exists to remove, and every sample in it would too.

So the names come from the address book, which is untracked, and the rule
degrades rather than failing when there is none. Three patterns always run:
an address, a host under a facility domain, a shared home path. The fourth,
bare host names, runs only where the address book is, which is the checkout
of whoever deploys. That is the person who can paste a host name in the
first place, so the check is where the mistake is made. In CI it does not
run at all, and the three that do are the ones a stranger could act on.

## What deliberately passes

EPICS record prefixes stay. `19bmSoft:m1` is a protocol name, meaningless
off the beamline's own network, and carrying one is what a device register
is for. At this facility a beamline's account name and its record prefix are
sometimes the same word, so banning the account would ban the prefix; that
residue is accepted rather than overlooked.

The one allow-listed string is below, and it is meant to be arguable.
"""

from __future__ import annotations

import re
import tomllib
from functools import cache
from typing import TYPE_CHECKING

import pytest

from tests._tracked import PROJECT_ROOT, tracked_files

if TYPE_CHECKING:
    from pathlib import Path

FACILITY_DOMAINS: tuple[str, ...] = ("anl.gov",)
"""Domains whose host names name a real machine at the facility."""

ADDRESS_BOOK_NAME = "hosts.toml"
"""The untracked file holding what this rule may not state itself.

Looked for at the project root and one level down, which is where
the ignore rules expect it. Absent is the normal case and not an error.
"""

_ISSUER_CONSTANT = re.compile(r"^\s*[A-Z0-9_]*ISSUER[A-Z0-9_]*\s*[:=]")
"""The one exemption: a line defining a token issuer.

An issuer is an identifier, not an address. It is compared against a token's
`iss` claim and never resolved, so it names no machine and reaching it would
accomplish nothing. It is also written into every token already issued and
into the verifier that checks them, so changing one invalidates every
credential deployed, which is a real cost against no gain.

Stated as the shape of the definition rather than as the string itself,
because the string would have to be quoted in all five copies of this rule,
and one of the projects forbids its tests naming the tree they came from.
The hole is narrow on purpose: the same host anywhere else on any other line
still fails.
"""

SELF = "test_no_facility_coordinates.py"
"""The one file excluded, because it quotes the shapes it refuses.

Smaller a hole than it looks: no real host name is quoted here, and the
samples below use a documentation address and a host that does not exist.
"""

_ADDRESS = re.compile(r"(?<![\w§.])(?:\d{1,3}\.){3}\d{1,3}\b(?!\.[A-Za-z])")
_HOSTNAME = re.compile(
    r"\b[a-z0-9][a-z0-9.-]*\.(?:"
    + "|".join(d.replace(".", r"\.") for d in FACILITY_DOMAINS)
    + r")\b",
    re.IGNORECASE,
)
_HOME_SEGMENT = "/" + "home/beams"
"""Assembled from fragments rather than written whole, and that is deliberate.

A rule that spells out what it forbids is a target for any later scrub that
uses the same terms. One did: a rewrite of this repository's history replaced
the literal in the pattern below with its own replacement text, leaving a
home-path check that matched no home path. It was caught because the samples
went red with it, which is the only reason this is a comment and not a hole.
"""

_HOME = re.compile(_HOME_SEGMENT + r"[0-9]*\b", re.IGNORECASE)

_EXEMPT_ADDRESSES: frozenset[str] = frozenset({"0.0.0.0", "255.255.255.0", "255.255.255.255"})
"""Addresses that name no host: the unspecified address and netmask shapes."""


def _machine_pattern(names: frozenset[str]) -> re.Pattern[str] | None:
    """A word-boundary alternation over `names`, or None if there are none."""
    if not names:
        return None
    return re.compile(r"\b(?:" + "|".join(re.escape(n) for n in sorted(names)) + r")\b", re.I)


@cache
def _declared_machines() -> frozenset[str]:
    """Host names the address book declares, or an empty set if it is absent."""
    for candidate in (PROJECT_ROOT, *(d for d in PROJECT_ROOT.iterdir() if d.is_dir())):
        book = candidate / ADDRESS_BOOK_NAME
        if book.is_file():
            facility = tomllib.loads(book.read_text(encoding="utf-8")).get("facility", {})
            return frozenset(str(n) for n in facility.get("machines", ()) if str(n).strip())
    return frozenset()


def _addresses(line: str) -> list[str]:
    """Dotted quads in `line` that could be a host's address.

    Loopback and the three ranges RFC 5737 reserves for documentation are
    what an example is supposed to use, so finding one is the rule working
    rather than failing.
    """
    found: list[str] = []
    for candidate in _ADDRESS.findall(line):
        octets = [int(part) for part in candidate.split(".")]
        if any(octet > 255 for octet in octets):
            continue
        if candidate in _EXEMPT_ADDRESSES or octets[0] == 127:
            continue
        if (octets[0], octets[1]) in {(192, 0), (198, 51), (203, 0)}:
            continue
        found.append(candidate)
    return found


def _offenders(paths: frozenset[Path], machines: re.Pattern[str] | None) -> list[str]:
    """Every coordinate in `paths`, by the three patterns plus `machines`.

    The machine pattern is passed in rather than read here, so the two tests
    below can run the always-on half separately from the half that needs the
    address book. A caller passing None gets the three patterns only.
    """
    hits: list[str] = []
    for path in sorted(paths):
        if path.name == SELF:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if _ISSUER_CONSTANT.match(line):
                continue
            found = (
                _addresses(line) + _HOSTNAME.findall(line) + _HOME.findall(line)
                if machines is None
                else machines.findall(line)
            )
            if found:
                hits.append(f"{path.name}:{lineno}: {sorted(set(found))!r} in {line.strip()}")
    return hits


def test_the_home_segment_is_the_path_it_claims_to_be() -> None:
    """The constant restated without sharing a fragment with it.

    Every sample below derives from `_HOME_SEGMENT`, so a wrong constant
    would leave them passing against a pattern that polices nothing, which
    is the hole this file was just repaired for in the other direction.
    This is the one assertion that does not derive from it, split at a
    different point on purpose so a scrub replacing the whole literal
    matches neither spelling.
    """
    assert _HOME_SEGMENT == "/home" + "/" + "beams"


def test_each_coordinate_pattern_still_matches_a_sample() -> None:
    """Guard all four: a pattern matching nothing is a rule matching nothing.

    Against samples rather than against the tree, because the tree is meant
    to be clean. A pattern that has silently stopped matching looks exactly
    like one with nothing left to catch.
    """
    assert _addresses("the host at 10.1.2.3 answers")
    assert _HOSTNAME.findall("reached a-host.example.aps.anl.gov on 5064")
    assert _HOME.findall(f"its home is {_HOME_SEGMENT}/EXAMPLE and it is shared")
    pattern = _machine_pattern(frozenset({"somehost"}))
    assert pattern is not None
    assert pattern.findall("a conductor runs on somehost today")


def test_a_role_and_a_record_prefix_are_left_alone() -> None:
    """The scope decision above, asserted rather than left to the docstring.

    A later widening that swallowed any of these would fail the pages and
    registers this rule exists to keep publishable, for a reason its name
    does not give.
    """
    assert not _addresses("bound to 127.0.0.1 and to 0.0.0.0")
    assert not _addresses("an example at 192.0.2.7 refuses")
    assert not _addresses("passive revocation per RFC 6819 §5.1.5.3 applies")
    assert not _addresses("the PTR name 1.0.0.127.in-addr.arpa resolves")
    assert not _HOSTNAME.findall("19bmSoft:aero:m1 reads 22.4088949931")


def test_an_absent_address_book_disables_only_the_name_check() -> None:
    """Degrading, not failing: the three pattern checks do not need the book.

    This is what runs in CI, where the file never exists. A change that made
    the rule depend on it would turn every CI run green by accident.
    """
    assert _machine_pattern(frozenset()) is None
    assert _addresses("the host at 10.1.2.3 answers")
    assert _HOME.findall(_HOME_SEGMENT + "0")


def test_the_issuer_exemption_spares_a_definition_and_nothing_else() -> None:
    """An exemption is a hole, so it should be the width of one definition.

    The definition is spared. The same host on any other line is not, so an
    address cannot borrow the exemption by sitting near one.
    """
    assert _ISSUER_CONSTANT.match('ISSUER = "https://idp.example.aps.anl.gov/local"')
    assert _ISSUER_CONSTANT.match('TOKEN_ISSUER: str = "https://idp.example.aps.anl.gov"')
    assert not _ISSUER_CONSTANT.match("    reached idp.example.aps.anl.gov for the issuer")
    assert not _ISSUER_CONSTANT.match('HOST = "a-host.example.aps.anl.gov"')
    assert _HOSTNAME.findall("ssh idp.example.aps.anl.gov")


def test_tracked_files_carry_no_address_domain_or_home_path() -> None:
    """The half that needs nothing but the patterns, so it runs everywhere."""
    hits = _offenders(tracked_files(), None)
    assert not hits, (
        "A coordinate locating a facility machine is in a published file:\n"
        + "\n".join(hits)
        + "\n\nPut the value in the untracked address book and name the role here."
    )


def test_tracked_files_name_no_machine_the_address_book_lists() -> None:
    """The half that needs the address book, skipped loudly where there is none.

    A separate test rather than a branch inside the one above, because the
    two have different reach and a reader should be able to see which ran. A
    branch would narrow the check silently, and a check that quietly stops
    covering something is the failure this tree keeps finding.

    Skipped is the honest report in CI, which never has the file. It is also
    the warning: a host name added by somebody without an address book passes
    here and passes CI, and goes red first in the checkout of whoever
    deploys. That is the weakest seam in this rule and it is deliberate,
    because the alternative is listing the names in a tracked file.
    """
    machines = _machine_pattern(_declared_machines())
    if machines is None:
        pytest.skip(
            f"No {ADDRESS_BOOK_NAME} in this checkout, so the host names are "
            "unknown here. Addresses, facility domains and home paths were "
            "still checked. A pasted host name would pass unseen."
        )
    hits = _offenders(tracked_files(), machines)
    assert not hits, (
        "A machine the address book names is in a published file:\n"
        + "\n".join(hits)
        + "\n\nName the role it plays instead, and leave the machine to the address book."
    )

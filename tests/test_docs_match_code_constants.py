"""A number written out in a docs page matches the constant it names.

Two independent sides of one fact, which is the condition for a check
being worth writing: the page cannot drift from the code without one of
them being wrong, and nothing else notices which.

Both entries below were already wrong when this file was written.
`architecture.md` said `EXPECTED_ADAPTERS` is six while the constant
read seven, and `CLAUDE.md` said `seams` declares five capabilities
while it declared six. One rotted when an adapter was added and the
other when a seam was, in different sittings, and both survived a full
green run with lint, types and docs.

That is the shape of the failure this guards. A stated rule is read
every time somebody changes the thing it governs; a count beside it is
read by nobody, because counting is exactly what a reader assumes
somebody else did.
"""

from __future__ import annotations

import re
from typing import TypeAliasType

import pytest

from reporter import seams
from tests._tracked import PROJECT_ROOT
from tests.test_the_core_names_no_seam import EXPECTED_ADAPTERS, EXPECTED_CORE_MODULES

_SPELLED: dict[int, str] = {
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
}


def _declared_capabilities() -> int:
    """How many seams `seams` publishes, counted from the module.

    Read off `__all__` rather than by listing names here, so the
    comparison has a side that moves on its own. A capability is a
    Protocol or the one type alias standing in for one, which is how
    the module itself counts them.

    Counted by what each name is rather than by matching the alias's
    own spelling. The spelling matched while `Delivering` was a plain
    string that no annotation could resolve, so the count read six and
    one of the six was unusable. A kind is the side of this that the
    module cannot drift away from.
    """
    published = set(seams.__all__)
    return sum(1 for name in published if _is_capability(getattr(seams, name, None)))


def _is_capability(candidate: object) -> bool:
    """A Protocol, or an alias an annotation can be written in."""
    return isinstance(candidate, TypeAliasType) or bool(getattr(candidate, "_is_protocol", False))


def _page(name: str) -> str:
    return (PROJECT_ROOT / name).read_text(encoding="utf-8")


def test_the_architecture_page_counts_the_adapters_the_constant_pins() -> None:
    found = re.search(r"`EXPECTED_ADAPTERS` is (\w+)", _page("docs/architecture.md"))
    assert found is not None, "the page stopped naming the constant, so this guards nothing"
    assert found.group(1) == _SPELLED[EXPECTED_ADAPTERS]


def test_the_architecture_page_counts_the_core_modules_the_constant_pins() -> None:
    found = re.search(r"`EXPECTED_CORE_MODULES` is (\w+)", _page("docs/architecture.md"))
    assert found is not None, "the page stopped naming the constant, so this guards nothing"
    assert found.group(1) == _SPELLED[EXPECTED_CORE_MODULES]


def test_the_architecture_page_counts_the_adapters_its_own_diagram_lists() -> None:
    """The prose count and the diagram beneath it, which rotted apart once.

    A second spelling of the same number, caught separately because the
    sentence naming the constant and the heading over the drawing are
    edited by different impulses. The drawing is what a reader trusts.
    """
    page = _page("docs/architecture.md")
    found = re.search(r"the adapters: one outside system each, (\w+) of them", page)
    assert found is not None, "the diagram stopped naming its count, so this guards nothing"
    assert found.group(1) == _SPELLED[EXPECTED_ADAPTERS]

    table = page.split("the adapters:")[1].split("in between")[0]
    drawn = set(re.findall(r"\b(\w+)\.py\b", table))
    assert len(drawn) == EXPECTED_ADAPTERS, f"the diagram draws {sorted(drawn)}"


def test_the_seams_module_opens_by_counting_the_seams_it_declares() -> None:
    """The first line a reader of this package meets, against the module.

    The sibling projects carry this as a file of its own, because the
    claim is repeated in their test prose and the scan has to range
    over more than one file to find it. Here it is written once, so it
    sits with the other counts rather than alone.
    """
    page = (PROJECT_ROOT / "src" / "reporter" / "seams.py").read_text(encoding="utf-8")
    found = re.search(r"The (\w+) outward seams", page)
    assert found is not None, "the module stopped counting them, so this guards nothing"
    assert found.group(1) == _SPELLED[_declared_capabilities()]


def test_the_package_front_door_counts_the_capabilities_the_seams_module_declares() -> None:
    page = (PROJECT_ROOT / "src" / "reporter" / "__init__.py").read_text(encoding="utf-8")
    found = re.search(r"## (\w+) capabilities", page)
    assert found is not None, "the front door stopped counting them, so this guards nothing"
    assert found.group(1).lower() == _SPELLED[_declared_capabilities()]


def test_the_repo_guidance_counts_the_capabilities_the_seams_module_declares() -> None:
    found = re.search(r"`seams` declares (\w+) capabilities", _page("CLAUDE.md"))
    assert found is not None, "the guidance stopped naming the count, so this guards nothing"
    assert found.group(1) == _SPELLED[_declared_capabilities()]


@pytest.mark.parametrize("count", [EXPECTED_ADAPTERS, EXPECTED_CORE_MODULES])
def test_every_pinned_count_has_a_word_for_it(count: int) -> None:
    """A count past the table reads as a passing test and is not one."""
    assert count in _SPELLED, (
        f"{count} has no spelling here, so the assertions above would raise a KeyError "
        "rather than compare. Extend the table in the same change that moves the count."
    )

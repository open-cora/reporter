"""Drive a real engine into a real store and record what the store reports.

Writes `tests/nodes.json`, which the store tests read instead of a store.
It stands up a writable catalog in a temporary directory, runs an engine
into it through the writer a deployment would actually use, and then
interrogates the result from the outside, the way this reporter has to.

It knows nothing about the reporter, which is what makes the capture worth
having: a fixture recorded by the thing under test would agree with it by
construction. Where the store's documentation and its wire disagree, the
wire is what lands here.

**It must run with no project at all**, which is why the make target
passes `--no-project` rather than picking an environment. The store's
client drives its own server through `starlette.testclient`, and the
keeper pins a second httpx beside the first for its own test client; that
code path finds it and refuses.

It is not part of any test run and nothing imports it. The captures are
committed, so this is only ever run deliberately.

    make refresh-captures
"""

from __future__ import annotations

import contextlib
import json
import platform
from datetime import UTC, datetime
from importlib import metadata
import tempfile
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from bluesky import RunEngine, RunEngineInterrupted
from bluesky import plan_stubs as bps
from bluesky.callbacks.tiled_writer import TiledWriter
from bluesky.plans import count
from bluesky.preprocessors import run_decorator
from ophyd.sim import det
from tiled.catalog import in_memory
from tiled.client import Context, from_context
from tiled.client.container import Container
from tiled.queries import Key
from tiled.server.app import build_app

REPORTER = Path(__file__).resolve().parents[1]
OUT = REPORTER / "tests" / "nodes.json"
"""Where the capture is written.

Under the reporter's tests, where the sibling spike's capture also ended
up, because the dataset leg now asserts against it. It lived next to this
script while nothing read it, on the rule that a fixture nothing reads is
a file.

Re-running this overwrites it, which is deliberate: a capture from a newer
store that changes an assertion is the signal worth having, and the diff
is the finding.
"""

IDENTIFIER_VALUE_MAX_LENGTH = 200
"""AROC's bound on the value half of an external reference.

Copied rather than imported, because importing it would mean
`--project apps/api` and that is the environment this half cannot have.
resolve.py imports the real one and checks this copy against it, so the
duplication cannot drift silently.
"""

WRITER_ROOT = "raw"
"""The container the writer is pointed at.

A deployment does not write runs to the root of its store, and the
difference is not cosmetic: see `probe_root_addressing` below.
"""


def fresh_client(stack: ExitStack) -> Container:
    """A writable catalog, served in-process, thrown away on exit.

    Two storage entries rather than one. The writer lands a run's readings
    in a table, and the catalog refuses a table with nowhere to put it:

        RuntimeError: The adapter <class 'tiled.adapters.sql.SQLAdapter'>
        supports storage types ['EmbeddedSQLStorage', 'SQLStorage',
        'RemoteSQLStorage'] but the only available storage types are
        dict_values([FileStorage(...)])

    That refusal is the first thing anybody standing this up will hit, so
    it is written down here rather than left to be rediscovered.
    """
    tmp = Path(tempfile.mkdtemp())
    (tmp / "data").mkdir()
    catalog = in_memory(
        writable_storage=[
            f"file://localhost{tmp}/data",
            f"sqlite:///{tmp}/tables.db",
        ]
    )
    context = stack.enter_context(Context.from_app(build_app(catalog)))
    return from_context(context)


@run_decorator()
def _failing_plan():
    """Opens a run and then breaks, so a node exists for a failure."""
    yield from bps.checkpoint()
    yield from bps.sleep(0.01)
    raise RuntimeError("the spike broke this run on purpose")


@run_decorator()
def _pausing_plan():
    """Opens a run and pauses itself, so an ending from pause is reachable."""
    yield from bps.checkpoint()
    yield from bps.sleep(0.01)
    yield from bps.pause()
    yield from bps.sleep(0.01)


def _addresses(node: Any) -> dict[str, Any]:
    """The three things that could serve as this node's identity.

    They are not variants of one answer. The path is what the store calls
    the node, the URI is what a reader elsewhere would have to be handed,
    and the asset URI is where the bytes are. Only the third survives the
    server being torn down, and only the second is resolvable by somebody
    who was not told which store to ask.
    """
    attributes = node.item["attributes"]
    segments = [*attributes["ancestors"], node.item["id"]]
    assets = [
        asset.get("data_uri")
        for source in attributes.get("data_sources") or []
        for asset in source.get("assets") or []
    ]
    return {
        "key": node.item["id"],
        "ancestors": attributes["ancestors"],
        "path": "/".join(segments),
        "normalised_path": "/".join(segment for segment in segments if segment),
        "uri": node.uri,
        "link_self": node.item["links"]["self"],
        "asset_data_uris": assets,
        "specs": attributes["specs"],
        "structure_family": attributes["structure_family"],
    }


def _tree(node: Any, depth: int = 0) -> list[dict[str, Any]]:
    """Every node at or under one node, flattened, with its addresses."""
    rows = [{"depth": depth, **_addresses(node)}]
    if node.item["attributes"]["structure_family"] == "container":
        for key in node:
            rows.extend(_tree(node[key], depth + 1))
    return rows


def probe_subscription_order() -> dict[str, Any]:
    """Whether the run's node is there yet when a reporter looks.

    The whole of the timing question, and it turns out not to be a timing
    question. Both callbacks run on the engine's thread in the order they
    were subscribed, so what a reporter sees at `stop` is decided by one
    line of wiring rather than by a race it has to survive.

    Probed at `start` as well, because registering a dataset when the run
    opens rather than when it closes is the obvious alternative design and
    deserves an answer rather than an assumption.
    """
    observed: dict[str, Any] = {}
    for order in ("writer first", "reporter first"):
        with ExitStack() as stack:
            client = fresh_client(stack)
            root = client.create_container(WRITER_ROOT)
            run_engine = RunEngine({})
            sightings: list[dict[str, Any]] = []

            def look(name: str, document: dict[str, Any]) -> None:
                if name not in ("start", "stop"):
                    return
                uid = document["uid"] if name == "start" else document["run_start"]
                sightings.append({"at": name, **_look_for(root, uid)})

            writer = TiledWriter(root)
            if order == "writer first":
                run_engine.subscribe(writer)
                run_engine.subscribe(look)
            else:
                run_engine.subscribe(look)
                run_engine.subscribe(writer)
            run_engine(count([det], num=2))

            uid = next(iter(root))
            observed[order] = {
                "sightings": sightings,
                "after_the_plan_returns": _look_for(root, uid),
            }
    return observed


def _look_for(root: Container, uid: str) -> dict[str, Any]:
    """What a reporter asking the store for one run would get back, now."""
    try:
        node = root[uid]
    except Exception as refusal:  # noqa: BLE001 - a spike records, it does not judge
        return {"present": False, "refusal": type(refusal).__name__}
    metadata = node.metadata
    return {
        "present": True,
        "has_start": "start" in metadata,
        "has_stop": "stop" in metadata,
        "children": list(node),
    }


def _over_http(root: Container, uid: str) -> dict[str, Any]:
    """The same node, read off the wire with no store client in the way.

    The question this answers is whether a reporter has to take the
    store's client as a dependency. It does not: `node.item` is the
    `data` member of this response, so an adapter reading the wire reads
    the same keys off the same JSON with one dependency subtracted, and
    `same_key_as_the_client` is what says so rather than assuming it.

    The 404 is captured too, because "there is no node for this run" is
    the reporter's most important answer and an adapter that guessed the
    shape of it would report a missing node as a present one.
    """
    node = root[uid]
    http = root.context.http_client
    self_link = node.item["links"]["self"]

    response = http.get(self_link)
    body: dict[str, Any] = response.json()
    data: dict[str, Any] = body.get("data") or {}
    attributes: dict[str, Any] = data.get("attributes") or {}
    metadata: dict[str, Any] = attributes.get("metadata") or {}
    stop: dict[str, Any] = metadata.get("stop") or {}

    segments = [*(attributes.get("ancestors") or []), data.get("id")]
    over_http = "/".join(str(segment) for segment in segments if segment)

    missing = http.get(self_link.replace(uid, "no-such-run"))
    return {
        "url": str(response.request.url),
        "status": response.status_code,
        "envelope_keys": sorted(body),
        "data_keys": sorted(data),
        "attribute_keys": sorted(attributes),
        "id": data.get("id"),
        "ancestors": attributes.get("ancestors"),
        "metadata_keys": sorted(metadata),
        "stop_time": stop.get("time"),
        "stop_exit_status": stop.get("exit_status"),
        "normalised_path": over_http,
        "same_key_as_the_client": over_http == _addresses(node)["normalised_path"],
        "missing_status": missing.status_code,
    }


def probe_root_addressing() -> dict[str, Any]:
    """Whether one node can have two spellings of its address.

    It can, and not for the reason it first looks like. A handle the client
    got by creating the node carries a leading empty ancestor and a handle
    the client got by searching does not, so the same node reports two
    paths and two URIs depending only on how it was reached. It is not a
    root-only quirk: the nested case below splits the same way.

    One address spelled two ways is one dataset recorded twice, which is
    why `normalised_path` exists in `_addresses` above. This probe is what
    says the normalisation is load-bearing rather than defensive.
    """
    with ExitStack() as stack:
        client = fresh_client(stack)
        created = client.create_container("at_the_root", metadata={"start": {"uid": "u-root"}})
        searched = next(iter(client.search(Key("start.uid") == "u-root").values()))
        nested_parent = client.create_container("nested")
        nested_created = nested_parent.create_container(
            "child", metadata={"start": {"uid": "u-nested"}}
        )
        nested_searched = next(
            iter(nested_parent.search(Key("start.uid") == "u-nested").values())
        )
        return {
            "root": {
                "created": _addresses(created),
                "searched": _addresses(searched),
                "spellings": len({created.uri, searched.uri}),
            },
            "nested": {
                "created": _addresses(nested_created),
                "searched": _addresses(nested_searched),
                "spellings": len({nested_created.uri, nested_searched.uri}),
            },
        }


def probe_where_the_bytes_are() -> dict[str, Any]:
    """Whether a run's readings have a file address a record could point at.

    The third candidate key, and the one that would survive the store being
    torn down. It does not survive contact: an array the client writes
    directly lands as a file and carries an asset saying where, and the
    arrays the writer produces are rows in a table and carry nothing.

    That is not the store being unhelpful. It is why the catalog refused to
    start without SQL storage in `fresh_client` above: a run's readings are
    tabular, so there is no file for a record to name, and a Custody record
    pointing at one would be inventing an address.
    """
    with ExitStack() as stack:
        client = fresh_client(stack)
        root = client.create_container(WRITER_ROOT)
        run_engine = RunEngine({})
        run_engine.subscribe(TiledWriter(root))
        run_engine(count([det], num=2))
        uid = next(iter(root))

        written_directly = client.write_array([1, 2, 3], key="written_directly")
        return {
            "by_the_writer": [
                {
                    "path": row["path"],
                    "structure_family": row["structure_family"],
                    "data_sources": root[uid].item["attributes"].get("data_sources")
                    if row["depth"] == 0
                    else _raw_data_sources(root, row["path"]),
                }
                for row in _tree(root[uid])
            ],
            "by_the_client": {
                "path": _addresses(written_directly)["path"],
                "assets": _addresses(written_directly)["asset_data_uris"],
            },
        }


def _raw_data_sources(root: Container, path: str) -> Any:
    """What a node says about its own storage, asked for directly."""
    relative = path.split("/", 1)[1] if "/" in path else path
    try:
        return root[relative].item["attributes"].get("data_sources")
    except Exception as refusal:  # noqa: BLE001 - a spike records, it does not judge
        return f"unreachable: {type(refusal).__name__}"


def probe_search_scope(root: Container, uid: str, client: Container) -> dict[str, Any]:
    """Whether a search for a run finds it from anywhere, or only from above.

    The reporter's recovery path depends on the answer. If a search only
    sees a container's own children, then a reporter that has forgotten
    where the writer points cannot find a run at all, and where the writer
    points has to be configuration rather than something discovered.
    """
    return {
        "from_the_store_root": list(client.search(Key("start.uid") == uid)),
        "from_the_writer_root": list(root.search(Key("start.uid") == uid)),
    }


def scenario(label: str, plan_factory: Any, *, leave_pause_with: str | None = None) -> dict[str, Any]:
    """Run one plan into a fresh store and capture everything about it.

    The writer is subscribed first throughout, which `probe_subscription_order`
    shows is the arrangement that leaves a complete node at `stop`. A
    scenario measuring anything else would be measuring the wiring.
    """
    with ExitStack() as stack:
        client = fresh_client(stack)
        root = client.create_container(WRITER_ROOT)
        run_engine = RunEngine({})
        documents: list[tuple[str, dict[str, Any]]] = []
        run_engine.subscribe(TiledWriter(root))
        run_engine.subscribe(lambda name, doc: documents.append((name, doc)))

        raised: str | None = None
        try:
            if leave_pause_with is None:
                run_engine(plan_factory())
            else:
                with contextlib.suppress(RunEngineInterrupted):
                    run_engine(plan_factory())
                getattr(run_engine, leave_pause_with)()
        except Exception as error:  # noqa: BLE001 - breaking is the scenario
            raised = f"{type(error).__name__}: {error}"

        starts = [doc for name, doc in documents if name == "start"]
        stops = [doc for name, doc in documents if name == "stop"]
        uid = starts[0]["uid"] if starts else None
        keys = list(root)

        captured: dict[str, Any] = {
            "label": label,
            "raised": raised,
            "document_order": [name for name, _ in documents],
            "run_uid": uid,
            "engine_start_time": starts[0]["time"] if starts else None,
            "engine_stop_time": stops[0]["time"] if stops else None,
            "engine_exit_status": stops[0].get("exit_status") if stops else None,
            "keys_under_the_writer_root": keys,
        }
        if uid is not None and uid in keys:
            node = root[uid]
            metadata = node.metadata
            captured |= {
                "node": _addresses(node),
                "tree": _tree(node),
                "metadata_top_level_keys": sorted(metadata),
                "store_start_time": metadata.get("start", {}).get("time"),
                "store_stop_time": metadata.get("stop", {}).get("time"),
                "store_exit_status": metadata.get("stop", {}).get("exit_status"),
                "search": probe_search_scope(root, uid, client),
                "over_http": _over_http(root, uid),
            }
        return captured


SCENARIOS: dict[str, Any] = {
    "completes": (lambda: count([det], num=3), None),
    "plan_raises": (_failing_plan, None),
    "abort_from_pause": (_pausing_plan, "abort"),
    "stop_from_pause": (_pausing_plan, "stop"),
}



STAMP = REPORTER / "tests" / "collected.json"
"""Where the capture's provenance goes, beside the captures themselves.

Not inside the capture. `nodes.json` could hold it and `documents.json`
could not: its top level IS the scenario list, and `from_capture` in the
shipped reporter iterates it. Teaching shipped code to skip a metadata key
so a fixture can carry one is the wrong way round, so both collectors
write here instead and the two captures stay the shape their readers
expect.

Read by a person, when a refreshed capture turns an assertion red and the
question is which release moved.
"""


def stamp(capture: str, *packages: str) -> None:
    """Record what wrote a capture, and when, without disturbing the other.

    Read-modify-write, so running one collector leaves the other's entry
    alone. Duplicated in the sibling collector rather than shared: the two
    run in separate ephemeral environments with no project between them,
    which is the same reason the bound is copied in this file.
    """
    entries: dict[str, Any] = {}
    if STAMP.exists():
        entries = json.loads(STAMP.read_text(encoding="utf-8"))
    entries[capture] = {
        "collected": datetime.now(tz=UTC).date().isoformat(),
        "python": platform.python_version(),
        **{name: metadata.version(name) for name in packages},
    }
    STAMP.write_text(json.dumps(dict(sorted(entries.items())), indent=2) + "\n", encoding="utf-8")
    print(f"stamped {capture}: {entries[capture]}")


def main() -> None:
    results: dict[str, Any] = {
        "subscription_order": probe_subscription_order(),
        "root_addressing": probe_root_addressing(),
        "where_the_bytes_are": probe_where_the_bytes_are(),
        "scenarios": {
            label: scenario(label, factory, leave_pause_with=leave)
            for label, (factory, leave) in SCENARIOS.items()
        },
    }
    OUT.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    stamp(OUT.name, "tiled", "bluesky", "ophyd")
    print(f"wrote {OUT.relative_to(REPORTER)}\n")

    print("== when the run's node is there, by subscription order ==")
    for order, observed in results["subscription_order"].items():
        print(f"  {order}")
        for sighting in observed["sightings"]:
            if not sighting["present"]:
                print(f"    at {sighting['at']:<6} NOT THERE ({sighting['refusal']})")
                continue
            print(
                f"    at {sighting['at']:<6} present, start={sighting['has_start']} "
                f"stop={sighting['has_stop']} children={sighting['children']}"
            )
        after = observed["after_the_plan_returns"]
        print(f"    after      present, start={after['has_start']} stop={after['has_stop']}")

    print("\n== one node, how many spellings of its address ==")
    for where, observed in results["root_addressing"].items():
        created, searched = observed["created"], observed["searched"]
        print(f"  {where}: {observed['spellings']} uri spellings")
        print(f"    created  uri  {created['uri']}")
        print(f"    searched uri  {searched['uri']}")
        print(f"    created  path {created['path']!r}   normalised {created['normalised_path']!r}")
        print(f"    searched path {searched['path']!r}   normalised {searched['normalised_path']!r}")

    print("\n== per scenario ==")
    header = f"{'scenario':<18} {'exit_status':<12} {'node?':<6} {'children':<10} uri length"
    print(header)
    print("-" * len(header))
    for label, captured in results["scenarios"].items():
        node = captured.get("node")
        children = [row["key"] for row in captured.get("tree", []) if row["depth"] == 1]
        print(
            f"{label:<18} {str(captured['store_exit_status'] or captured['engine_exit_status']):<12} "
            f"{('yes' if node else 'NO'):<6} {','.join(children) or '(none)':<10} "
            f"{len(node['uri']) if node else 0}"
        )

    print(f"\n== candidate keys, and the bound they have to fit ({IDENTIFIER_VALUE_MAX_LENGTH}) ==")
    sample = results["scenarios"]["completes"].get("node")
    if sample is not None:
        for name in ("path", "uri"):
            value = sample[name]
            print(f"  {name:<18} {len(value):>4}  {value}")
        leaf = [row for row in results["scenarios"]["completes"]["tree"] if row["depth"] > 1]
        if leaf:
            deepest = max(leaf, key=lambda row: len(row["uri"]))
            print(f"  {'deepest leaf uri':<18} {len(deepest['uri']):>4}  {deepest['uri']}")

    print("\n== is there a file a record could point at instead ==")
    bytes_are = results["where_the_bytes_are"]
    for row in bytes_are["by_the_writer"]:
        print(f"  writer  {row['path'][:52]:<54} data_sources={row['data_sources']}")
    print(
        f"  client  {bytes_are['by_the_client']['path']:<54} "
        f"assets={bytes_are['by_the_client']['assets']}"
    )

    print("\n== what the store knows about when ==")
    for label, captured in results["scenarios"].items():
        print(
            f"  {label:<18} engine stop={captured['engine_stop_time']} "
            f"store stop={captured.get('store_stop_time')}"
        )

    print("\n== the same node, read without the store's client ==")
    for label, captured in results["scenarios"].items():
        wire = captured.get("over_http")
        if wire is None:
            continue
        print(
            f"  {label:<18} {wire['status']} key={wire['normalised_path']} "
            f"same_as_client={wire['same_key_as_the_client']} "
            f"stop={wire['stop_time']} missing_run={wire['missing_status']}"
        )
    sample_wire = results["scenarios"]["completes"].get("over_http")
    if sample_wire is not None:
        print(f"    envelope   {sample_wire['envelope_keys']}")
        print(f"    data       {sample_wire['data_keys']}")
        print(f"    attributes {sample_wire['attribute_keys']}")

    print("\n== does a search find a run from the store root ==")
    for label, captured in results["scenarios"].items():
        found = captured.get("search")
        if found is None:
            continue
        print(
            f"  {label:<18} from the store root: {found['from_the_store_root'] or '(nothing)'}"
            f"   from the writer root: {found['from_the_writer_root'] or '(nothing)'}"
        )


if __name__ == "__main__":
    main()

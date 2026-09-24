# Reporter

*Iris, messenger of the gods*

Turns one acquisition engine's document stream into run commands, and says
where the data those runs produced is being kept.

A client of keeper, not a part of it. It runs where the engine is; keeper runs
where the database is. Everything it files is something the record was told
rather than something it checked, and it does not pretend otherwise.

## Status

Nothing here yet. The code exists and has run against a live engine. It is
extracted here after keeper moves, for the same reason as conductor.

What it still lacks is durability: a document published while it is down is a
document lost.

## The four

| Repo | Does |
| --- | --- |
| [keeper](https://github.com/open-cora/keeper) | Records what was proposed, run and produced |
| [conductor](https://github.com/open-cora/conductor) | Conducts a procedure across a beamline, one step at a time |
| [reporter](https://github.com/open-cora/reporter) | Reports what an acquisition engine did |
| [thinker](https://github.com/open-cora/thinker) | Proposes what to run next |

## License

Apache-2.0. See [LICENSE](LICENSE).

# cluster-impact — working notes

Public metrics site for the UChicago DSI GPU cluster. Sibling of
`cluster-information-and-policies`; shares its Jekyll chrome deliberately so
the two read as one system.

## The two things that matter most

**1. This repository is public and the site is public.** Everything committed
is world-readable forever. Raw job records, usernames, job names, node names,
and credentials must never be committed. If you are adding a field to
published output, you are changing what the University discloses — treat it
that way.

**2. Merging to `main` deploys.** There is no staging environment. A push to
`main` rebuilds and publishes `cluster-impact.ds.uchicago.edu`.

## Stack

| Part | Tech |
| --- | --- |
| Site | Jekyll 4.3, minimal-mistakes theme, Ruby 3.1 |
| Charts | Apache ECharts 5.5.1, vendored at `assets/js/echarts.min.js` |
| Collector | Python 3.12, stdlib + PyYAML/httpx |
| Local dev | Docker (OrbStack) via Make — **never run Jekyll directly** |
| On-cluster | podman + systemd timer |

## Commands

```bash
make serve        # http://localhost:4000
make collect-dry  # full pipeline against tests/fixtures — no cluster needed
make test         # offline suite
make verify       # privacy assertions over ./data
make lint / fmt
```

`make collect-dry` writes fixture data into `data/`. It is schema-valid and
would deploy fine — which is why CI blocks it (`health.json` must say
`mode: live`). Run `git checkout data/ _data/` when done previewing. **Never
commit fixture-derived data.**

## Architecture

```
collector/sources/*     one module per external system; each degrades to
                        "unavailable" rather than failing the run
collector/transform/
  aggregate.py          job records -> per-day aggregate (INTERNAL: has usernames)
  derive.py             rollups, records, summary, cost avoidance
  privacy.py            the ONLY sanctioned path from aggregate to disk
collector/publish.py    writes data/, stages ONLY allowed_paths, pushes
collector/state.py      on-cluster only: raw cache, hashed user + account index
```

`DayAggregate` carries usernames and must never be serialized directly. Go
through `privacy.scrub_day()`.

## Rules that exist for a reason

- **`sacct --format` must never include `JobName`.** Job names on a research
  cluster carry grant numbers, subject IDs, and unpublished paper titles. Data
  never collected cannot leak.
- **Adding a published field means editing `DAY_SCHEMA` in `privacy.py`.** The
  schema is closed; unknown keys fail the gate. That friction is intentional.
- **k-anonymity is applied at the granularity being published** — per-day for
  the daily series, per-period for rollups (via the on-cluster account index).
  Do not "simplify" rollups to derive from already-suppressed daily records;
  that permanently hides courses whose users never overlap on one day.
- **Two utilization denominators, always.** Available-capacity is the
  headline; installed-capacity and availability are always published beside
  it. Never ship one without the others.
- **Say "allocated", not "utilized".** Slurm knows a GPU was assigned, not
  that it was busy. Real utilization waits on DCGM exporters
  (`sources/dcgm.py`, currently flagged off).
- **Cost avoidance requires a sourced, dated price table** or it is withheld
  entirely. Don't relax `pricing_is_publishable()`.
- **The collector stages only `data/` and `_data/summary.json`.** It holds a
  write-capable deploy key; `publish.py` checks the staged set and aborts on
  anything outside `allowed_paths`.

## Testing

The whole pipeline runs offline against canned command output in
`tests/fixtures/` via `FixtureRunner`. Fixtures deliberately include a
single-user allowlisted lab (`solo-lab`), an unlisted lab, a course whose
users never overlap on one day, and a midnight-crossing job. If you change
suppression logic, those cases are the ones that will catch you.

Poisoned-input tests in `tests/test_privacy.py` assert the gate *fails*. A
gate that has never failed is not a tested gate — keep them.

## Site conventions

- Nav is hand-maintained in `_data/navigation.yml`; adding a page is two edits.
- Hero tiles render at build time from `_data/summary.json` via Liquid so they
  survive JS being off. Time series load client-side from `/data/*.json`.
- Liquid has no thousands-separator filter, so the collector emits compact
  display strings (`"4.2M"`) in `summary.display`.
- Brand maroon is `#800000`, declared once in `assets/css/main.scss`. Don't
  reintroduce the second value the policy site carries.
- Chart colours are categorical and deliberately not a maroon ramp — maroon is
  chrome, not data. See the comment block in `assets/css/_impact.scss`.

## Configuration still incomplete

`python -m collector.cli doctor` lists these. The cloud price table,
the Foreman URL, and `groups.yaml` still need real values.

Settled, so don't re-open them: capacity-timeline dates and the GPU mix are
reconstructed and evidence-cited in `config/cluster.yaml`; Prometheus is
`s10.cs.uchicago.edu:9090`; LDAP is `ldaps://ldap.cs.uchicago.edu` with an
anonymous bind (no credential to deploy); and the site ships **no analytics**
by deliberate choice — see the comment in `_includes/head/custom.html`.

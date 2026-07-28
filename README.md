# cluster-impact

Public usage and impact reporting for the UChicago DSI GPU cluster.

**Live site:** <https://cluster-impact.ds.uchicago.edu/>

A collector runs nightly in a container on the cluster, aggregates Slurm
accounting and storage data to one record per day, strips all identifying
detail, and pushes the result here. GitHub Actions rebuilds the site from the
committed data.

```
 ── DSI network ─────────────────────┐   ┌── public ──────────────────────────
                                     │   │
 slurmdbd ─sacct/sreport─┐           │   │
 cluster-storage2/4 ─zfs─┤           │   │
 LDAP + Foreman ─────────┤           │   │
 Prometheus ─────────────┘           │   │
            ▼                        │   │
   podman: collector (nightly timer) │   │
     raw  → /var/lib/cluster-impact  │   │   never leaves the cluster
     aggregate → scrub → assert      │   │
            │                        │   │
            └── git push (deploy key, data/** only) ──▶ dsi-clinic/cluster-impact
                                     │   │                      │
                                     │   │        privacy-gate (blocks deploy)
                                     │   │                      │
                                     │   │        Jekyll → Pages → live site
```

## This repository is public

It has to be — GitHub Pages requires a public repo on the `dsi-clinic` Team
plan. Everything committed here is world-readable forever.

Consequences that are not negotiable:

- **Raw job records never enter git.** Only aggregated, scrubbed daily figures
  are committed. Raw pulls stay in an on-cluster cache.
- **Individuals are never named.** A research group is named only if it is in
  `config/groups.yaml` *and* clears the k-anonymity threshold for the period.
- **The privacy gate is a build gate.** `collector/transform/privacy.py`
  re-reads published bytes against a closed schema; the Pages deploy job
  depends on it passing.
- **Never commit credentials.** The deploy key lives on the collector node,
  outside this repo.

See [Methodology](https://cluster-impact.ds.uchicago.edu/methodology/) for the
full model.

## Layout

```
collector/          Python: sources -> aggregate -> scrub -> publish
  sources/          slurm, storage, directory, prometheus, dcgm (dark)
  transform/        aggregate.py, derive.py, privacy.py
config/             cluster.yaml, groups.yaml, sources.yaml
data/               PUBLISHED, machine-written, scrubbed
_data/summary.json  headline tiles, rendered server-side by Liquid
pages/              site content
assets/js/          vendored ECharts + impact.js chart builders
tests/              offline suite with canned command output
```

## Local development

Requires Docker (OrbStack) and Python 3.11+. Never run Jekyll directly —
always go through Make.

```bash
make serve          # site at http://localhost:4000
make collect-dry    # run the full pipeline against tests/fixtures
make test           # offline test suite, no cluster access needed
make verify         # re-run every privacy assertion over ./data
make lint
```

`make collect-dry` writes fixture-derived data into `data/`. That data is
schema-valid and would deploy perfectly, which is exactly why CI refuses it:
`health.json` records `mode: fixtures`, and the Pages gate requires
`mode: live`. **Do not commit it** — run `git checkout data/ _data/` when you
are done previewing.

## Deploying the collector

See [`deploy/README.md`](deploy/README.md) for the container build, the
systemd timer, the deploy key, and the one-time backfill.

Before the first live run:

```bash
python -m collector.cli doctor
```

It checks the Slurm client/server version match, munge, storage reachability,
LDAP, Prometheus, the price table, and push access, and prints what is wrong.

## Configuration you must complete

`make doctor` will flag all of these:

- `config/cluster.yaml` — the capacity timeline dates and counts are
  placeholders; the cloud price table has no `source` or `asof` yet, so cost
  avoidance is withheld until you set them.
- `config/groups.yaml` — empty. Every account currently publishes as "Other".
- `config/sources.yaml` — LDAP, Foreman, and Prometheus endpoints are unset.
- `_includes/head/custom.html` — register a new Umami website id.

## Related

- [cluster-information-and-policies](https://github.com/dsi-clinic/cluster-information-and-policies)
  — the cluster documentation site this one is a sibling of.

# Open work — handoff notes

The `imp` gas city rig was removed on 2026-07-29. These notes lived only in that
rig's beads database, so they are preserved here verbatim. Everything below is
analysis that took real digging; the tasks themselves are unstarted.

Three things did land before removal, all merged and intact on `main`: the
Foreman URL, the LDAP user/group search-base split with tests, and the CoreWeave
on-demand price table. The measured GPU variant census lives in
`config/cluster.yaml`, not here.

Most of what remains needs a shell on the cluster. `deploy/gather-facts.sh`
collects the facts for several of these in one read-only pass.


## TODO: restore per-model GPU attribution, then cost avoidance

*added 2026-08-06, after the first live collection run*

**The problem**

Slurm's accounting on this cluster records `gres/gpu` but no typed variants:

```
AccountingStorageTRES = cpu,mem,energy,node,billing,fs/disk,vmem,pages,
                        gres/gpu,gres/gpumem,gres/gpuutil
```

Measured: **zero** typed `gres/gpu:<model>` entries in all of July 2026, in
either `AllocTRES` or `ReqTRES`. Users genuinely do request specific models and
slurmctld honours it at schedule time — the job lands on the right node — but the
type is never persisted, so accounting cannot tell an A40 hour from an H200 hour.

Two consequences on the site today:

- `gpu_hours_by_model` is a single `unspecified` bucket, so the per-model chart
  carries no information.
- Cost avoidance is **withheld**. It joins per-model hours against per-model
  prices; with nothing priceable it would have published `$0` as the headline
  "Cloud cost avoided" tile, which reads as "this cluster saved nothing".
  `estimate_cost_avoided()` now returns `None` in that case instead.

**Two fixes, and they are independent**

1. *Fix it going forward (needs techstaff).* Add the typed TRES to
   `AccountingStorageTRES`:
   `gres/gpu:a40,gres/gpu:a100,gres/gpu:l40s,gres/gpu:h100,gres/gpu:h200`.
   Only affects jobs recorded **after** the change; it cannot recover history.
   Confirm whether this needs a slurmdbd restart and whether adding TRES mid-life
   is safe on 24.11.7 before proposing it.

2. *Recover history from node names (no Slurm change needed).* `sacct` still
   records `NodeList`, and node → GPU model is known from `sinfo`/`gres.conf`
   and already reconstructed in `config/cluster.yaml`. Attributing each job's
   GPU-hours via the nodes it ran on would rebuild the per-model breakdown for
   the entire 2023-05 → present history. This is the higher-value fix and is
   entirely inside this repo. Caveats to handle: a job spanning nodes of
   different models needs proportional splitting, and `NodeList` is currently
   never collected — adding it means editing `SACCT_FIELDS` and re-checking
   `privacy.py`, since node names must NOT be published (they are only an
   intermediate for attribution).

A blended-rate estimate (weighting prices by the installed mix) was considered
as a shortcut and rejected for now: allocation is not proportional to
installation, so it is an estimate rather than a bound and is harder to defend
on a public page than simply withholding. Revisit only if fix 2 proves
impractical.

**Done when:** `gpu_hours_by_model` shows real models across the full history and
`/value/` publishes a cost-avoidance figure again, sourced and defensible.


## Deploy collector to a production cluster host

*was `imp-xe0` · labels: deploy,human-only,infrastructure*

**Task**

> deploy/README.md — The collector needs a persistent home on the cluster: a dedicated admin/utility node (NOT fe01/fe02/fe03 — login nodes are load-balanced and must stay interchangeable). The host needs: Slurm client config + munge, podman, SSH reachability to storage nodes (builder.cs.uchicago.edu can reach root on cluster-storage2/4 via permitted_root_nets). Steps: (1) choose host, (2) build container image, (3) generate ed25519 deploy key + register as GitHub write-access deploy key, (4) clone /var/lib/cluster-impact/repo, (5) install systemd units from deploy/, (6) enable timer.

**What was already worked out**

```
source: deploy/README.md. Full cluster infrastructure access required. Must choose an appropriate non-login-node host first. [human-only]
HOST RECOMMENDATION with evidence: cluster-mgmt.ds.uchicago.edu (fallback cluster-mgmt2). From puppet-modules code/hiera/nodes/cluster-mgmt.ds.uchicago.edu.yaml plus code/modules/role/dsi_cluster/manifests/mgmt.pp, it ALREADY satisfies every prerequisite in this bead:
- podman: 'podman' class applied at the node level.
- slurm client + munge: dsi_cluster::mgmt includes dsi_cluster::slurm::client, which includes dsi_cluster::slurm::munge and manages /etc/slurm/slurm.conf. Package is slurm-smd-client 24.11.7-1 -- pin the collector container's slurm client to 24.11.7 to avoid client/server drift.
- Not a login node: dsi_cluster::type is mgmt, so this satisfies the NOT-fe01/02/03 constraint without inventing a new host.
- Outbound network for git push: it is dsi_cluster::gateway, the cluster's NAT gateway (nat_ip_range 128.135.24.43, nat_ips 128.135.24.44). Egress to github.com is a given.
- Storage reachability: includes ssh::admin_client.
It is also the PushProx proxy that already relays node/dcgm metrics to s10, so it is the established monitoring egress point -- which makes it the single most likely host to already be permitted outbound to s10:9090 (see imp-aey).
Remaining human steps are unchanged: build image, generate the ed25519 deploy key and register it on the repo, clone to /var/lib/cluster-impact/repo, install the systemd units from deploy/, enable the timer.
```

**Done when:** Nightly timer running and healthy. 'systemctl status cluster-impact.timer' shows active. 'journalctl -u cluster-impact.service' shows a successful run. data/health.json mode=live.


## Run one-time historical backfill against slurmdbd (TIME-SENSITIVE)

*was `imp-bba` · labels: deploy,human-only,infrastructure,time-sensitive*

**Task**

> deploy/README.md — slurmdbd has a purge policy; once historical records are purged they are gone forever. The collector commits daily aggregates to git to stop this horizon from receding, but it cannot recover data already purged. The backfill command walks week-sized chunks, is resumable, and skips months already published. It hits slurmdbd hard — run outside business hours. Rehearse with --dry-run first. The resulting git diff should be reviewed before committing and pushing by hand for the first load. Urgency: every day without this is a day of history that may be purged.

**What was already worked out**

```
Human-only. Production host setup (prerequisite) not yet complete. Requires a
human to run the podman backfill on the cluster and manually review/push the
resulting git diff.
```

**Done when:** Historical daily aggregates committed to git back to the earliest date retained by slurmdbd. data/health.json shows the actual date range. The first automated nightly run picks up from the most recent committed date.


## Confirm the collector can reach Prometheus on s10:9090

*was `imp-aey` · labels: none*

**Task**

> Blocks the whole Prometheus half of the design. Prometheus is on s10.cs.uchicago.edu (128.135.164.216), a CS-owned host; the collector runs in podman on a DSI node. The known firewall rule (dsi_cluster::prometheus::slurm.pp) only permits s10 -> fe01:8181, NOT the reverse.
> 
> One command from the intended collector host settles it:
>   curl -s http://s10.cs.uchicago.edu:9090/-/healthy
> 
> If it fails, options are: open the reverse path in Puppet (CS-owned, needs techstaff), proxy through a DSI host, or drop Prometheus-derived metrics (node availability, storage I/O) from v1.
> 
> While there, confirm whether the ZFS collector is present:
>   curl -sG http://s10.cs.uchicago.edu:9090/api/v1/query --data-urlencode 'query=node_zfs_pool_io_read_bytes_total'

**What was already worked out**

```
To answer this, run from the host that will run the collector (NOT your laptop):

  curl -sS -m 5 -o /dev/null -w '%{http_code}\n' http://s10.cs.uchicago.edu:9090/-/ready
  curl -sSG -m 10 http://s10.cs.uchicago.edu:9090/api/v1/query \
    --data-urlencode 'query=node_zfs_pool_io_read_bytes_total' | head -c 400

First command: 200 means reachable. Timeout/refused means the firewall blocks
collector->s10 (only s10->fe01:8181 is known to be permitted), and the whole
Prometheus half of the collector needs rerouting or dropping from v1.
Second command: a non-empty 'result' array means the ZFS collector is enabled
and we can use pool-level I/O counters instead of the block-device regex now in
config/sources.yaml.
```

**Done when:** Yes/no on reachability from the collector host, plus a decision on the fallback if no.


## Populate groups.yaml accounts allowlist from sacctmgr

*was `imp-61u` · labels: config,human-only*

**Task**

> config/groups.yaml:20 — accounts: {} is empty. Every Slurm account publishes as 'Other' on the site. To name a group, add it here with display_name, department, division, and type (lab|course|clinic|core). The k-anonymity floor (default 3 users) still applies after naming — a small group collapses into Other regardless. An empty file is a safe starting state but provides no group-level breakdown on the site. Source data: run 'sacctmgr show account -P' on the cluster to enumerate accounts.

**What was already worked out**

```
source: config/groups.yaml:20. Requires: (1) cluster access to run sacctmgr, (2) human judgment on which accounts to name publicly and what display names/departments to assign. This is a policy decision. [human-only]
```

**Done when:** accounts populated with at least the known major labs, courses, and DSI core accounts. Each entry reviewed for correctness. Doctor or make verify passes.


## Deploy DCGM Prometheus exporters to enable real GPU utilization data

*was `imp-4e1` · labels: human-only,infrastructure,needs-human*

**Task**

> pages/methodology.md Known gaps / config/sources.yaml dcgm.enabled=false — The site currently says 'allocated' (jobs assigned GPUs) rather than 'utilized' (GPUs actually doing work), because Slurm only knows allocation, not real SM activity. The code path exists: sources/dcgm.py queries DCGM_FI_PROF_SM_ACTIVE, DCGM_FI_DEV_GPU_UTIL, DCGM_FI_DEV_FB_USED, DCGM_FI_DEV_POWER_USAGE. Once DCGM exporters are running on the compute nodes and Prometheus is scraping them, setting dcgm.enabled: true in sources.yaml is the entire software rollout. Same DCGM data would enable energy and carbon figures.

**What was already worked out**

```
source: pages/methodology.md Known gaps + config/sources.yaml:64-74. Requires Puppet/cluster infrastructure work to deploy dcgm-exporter on compute nodes. The software side (sources/dcgm.py) is complete and ready. [human-only — infrastructure prerequisite]
SCOPE IS SMALLER THAN THIS BEAD ASSUMES -- the Prometheus half is already built.
1. s10 already scrapes a DSI DCGM job. puppet-modules code/hiera/nodes/s10.cs.uchicago.edu.yaml prometheus::collect_scrape_jobs contains 'dcgm_dsi_proxy' with proxy_url http://128.135.24.43:8080 (= cluster-mgmt.ds.uchicago.edu, the DSI PushProx proxy). So the scrape path and firewall traversal for DSI DCGM metrics already exist. Nothing needs to change on s10.
2. A working exporter pattern already exists for the sibling cluster. code/modules/role/ai_cluster/manifests/prometheus/node.pp runs nvcr.io/nvidia/k8s/dcgm-exporter:3.3.5-3.4.0-ubuntu22.04 with DCGM_EXPORTER_LISTEN=":9401". The dsi_cluster role has no equivalent -- that gap IS this bead.
So the work is: port that manifest from role/ai_cluster to role/dsi_cluster, apply it to the GPU node groups, and confirm the pushprox client on each node advertises :9401.
WORTH CHECKING FIRST, because it may already be flowing: query s10 for DSI instances under that job. If it returns data, cluster-impact can flip sources.dcgm.enabled to true with no exporter rollout at all, and the site's SM-activity / memory / power / energy panels light up immediately.
  curl -sG http://s10.cs.uchicago.edu:9090/api/v1/query --data-urlencode 'query=count(DCGM_FI_DEV_GPU_UTIL) by (job)'
Note: puppet-modules is CS-owned and read-only reference for us, so the manifest change is a PR/request to techstaff, not something this rig can land.
HOLD -- do not action. Bennett 2026-07-29: wants to discuss scope before any work starts. He is open to a sub-agent doing it, under a hard constraint: IT MUST NOT AFFECT CLUSTER USABILITY. That rules out anything touching slurmd, driver state, cgroups, or GPU exclusivity on nodes running user jobs. Any future plan here needs to state explicitly how it avoids disturbing running work (e.g. exporter in a container with read-only DCGM access, rolled out one node at a time behind a drain, or applied only to idle nodes) and must be reviewed by Bennett before it is applied. Evidence already gathered is in the earlier note -- the s10 scrape job exists and role/ai_cluster has a working exporter manifest, so the remaining work is a puppet-modules change owned by CS techstaff, not this rig. No agent should pick this up from the pool.
```

**Done when:** DCGM Prometheus exporters running on compute nodes, Prometheus scraping them, dcgm.enabled: true in sources.yaml, site rendering actual utilization figures on the /utilization/ page.


## Support mixed GPU form factors within one GRES type

*was `imp-gpx` · labels: agent-ready,config,design*

**Task**

> Bennett believes the H100 fleet may be a MIX of SXM5 and PCIe. If so, config/cluster.yaml cannot express it and two numbers are affected differently.
> 
> THE PROBLEM
> gpu_models is keyed by GRES type ('h100') and carries one tflops_fp16_dense. SXM5 is 989.4 dense FP16, PCIe/NVL is ~756. One constant cannot be correct for a mixed fleet. Worse, Slurm cannot help: gres.conf sets Type=h100 for all of them, so sacct AllocTRES reports gres/gpu:h100 regardless of the physical card. The collector is structurally blind to the difference.
> 
> WHY IT IS NOT ONE FIX
> The two consumers have different needs:
> 
> 1. Peak PFLOPS (headline + /capacity/). This is pure installed-hardware inventory -- it never needs Slurm. It CAN be exact, if capacity_timeline entries carry variant-level counts (e.g. h100_sxm5: 8, h100_pcie: 8) that sum independently of the GRES type used for attribution.
> 
> 2. Per-model GPU-hours -> cloud cost avoidance (/value/). This MUST come from Slurm's typed GRES, which cannot distinguish variants. It has to collapse to one rate per GRES type. Use the LOWER (PCIe) figure so the published number understates rather than overstates -- consistent with the existing choice to use dense rather than sparse tensor figures.
> 
> PROPOSED SHAPE
> - gpu_models keeps GRES-type keys for attribution; where a type is mixed, its tflops value is the conservative one and a comment says why.
> - capacity_timeline gains optional variant sub-counts used ONLY for the peak-PFLOPS sum. Absent variants means the fleet is uniform and current behaviour is unchanged.
> - derive.py computes peak PFLOPS from variant counts when present, GRES-type counts otherwise.
> - /methodology/ states plainly that peak PFLOPS is exact per installed card while per-model GPU-hours are attributed by GRES type and therefore conservative for mixed fleets.
> 
> BLOCKED until imp-5rj returns the actual mix from deploy/gather-facts.sh -- do not guess the split. If the fleet turns out uniform, close this as not needed.

**What was already worked out**

```
UNBLOCKED — real variant census now in config/cluster.yaml (see the GPU VARIANT CENSUS comment block). Implement with these measured counts:
  h100: SXM5 4 (l001) @ 989.4 dense FP16 / 700W ; NVL 12 (m001,m002,n001) @ 835.5 / 400W
  h200: SXM  4 (o001) @ 989.4 / 700W            ; NVL 16 (p001-p003,q001) @ 835.5 / 600W
n001 is assumed NVL because it has been down since 2026-07-28 and could not be read; make that assumption visible in the config, not buried in code.
Published today is the conservative 57.9 PFLOPS (both mixed keys carry the lower NVL figure). Exact per-variant is 59.2. Target is 59.2 with the pricing join intact.
CRITICAL CONSTRAINT confirmed by reading the code: gpu_models and cloud_pricing keys MUST stay GRES-typed (a40/a100/l40s/h100/h200). config.py pricing_is_publishable() requires a price for every key in capacity_timeline[-1].gpus, and cost avoidance joins sacct's gres/gpu:<type> against cloud_pricing by that key. Variant-keying either dict silently breaks the join or trips the pricing gate. So add per-variant counts as an OPTIONAL sub-structure consumed only by config.py peak_pflops(), which is already generic over its keys — leave total_gpus() and the sinfo drift guard summing to 140.
```

**Done when:** Peak PFLOPS is computed from per-variant installed counts when capacity_timeline provides them, and is unchanged when it does not. Mixed GRES types use the conservative rate for per-model GPU-hours. Methodology page explains both. Tests cover a mixed-fleet timeline entry and the uniform fallback.


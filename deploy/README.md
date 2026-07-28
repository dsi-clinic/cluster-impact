# Deploying the collector

The collector runs on a DSI cluster node that can reach slurmdbd, the storage
nodes, LDAP/Foreman, and Prometheus.

## Choosing the host

**Do not pin this to `fe01`.** The login nodes sit behind the load balancer
and should stay interchangeable; a timer that only exists on one of them is a
pet. Use a dedicated admin or utility node.

The host needs:

- Slurm client configuration (`/etc/slurm/slurm.conf`) and a munge socket
- `podman`
- SSH reachability to the storage nodes. Root on `cluster-storage2/4` is
  reachable from `builder`, not from `fe0x` (`permitted_root_nets`), so
  `sources.storage.ssh_via` must name the right jump host.
- Outbound HTTPS/SSH to github.com

## Build

```bash
podman build -f Containerfile.collector -t cluster-impact-collector .
```

The image pins a `slurm-client` package. It must be close enough in version to
the cluster's `slurmctld`; `doctor` compares them and fails loudly on a
mismatch. If they ever diverge irreconcilably, `collect --from-dump` reads
`sacct` output captured on the host instead.

## Deploy key

Use a **repository deploy key with write access**, not a personal access
token — it cannot touch the other repositories in the `dsi-clinic` org.

```bash
ssh-keygen -t ed25519 -f /etc/cluster-impact/deploy_key -C "cluster-impact collector" -N ""
chmod 600 /etc/cluster-impact/deploy_key
cat /etc/cluster-impact/deploy_key.pub
# Add at: github.com/dsi-clinic/cluster-impact -> Settings -> Deploy keys
#         -> Add deploy key -> [x] Allow write access
```

Clone the working copy the collector will push from:

```bash
mkdir -p /var/lib/cluster-impact
GIT_SSH_COMMAND='ssh -i /etc/cluster-impact/deploy_key -o IdentitiesOnly=yes' \
  git clone git@github.com:dsi-clinic/cluster-impact.git /var/lib/cluster-impact/repo
```

## Check before the first run

```bash
podman run --rm --network host \
  -v /etc/slurm/slurm.conf:/etc/slurm/slurm.conf:ro \
  -v /run/munge/munge.socket.2:/run/munge/munge.socket.2:ro \
  -v /var/lib/cluster-impact/repo:/repo \
  -v /etc/cluster-impact/deploy_key:/secrets/deploy_key:ro \
  cluster-impact-collector doctor --repo /repo
```

Fix everything it reports before going further. In particular it will tell you
whether `config/cluster.yaml`'s capacity timeline matches what `sinfo` reports.

## One-time backfill

Do this early. The accounting database has a purge policy; committing daily
aggregates to git is what stops that horizon from receding, but it cannot
recover what has already been purged.

Rehearse first:

```bash
podman run --rm ... cluster-impact-collector backfill --dry-run
```

Then run it. It walks week-sized chunks, is resumable, and skips months
already published:

```bash
podman run --rm ... cluster-impact-collector backfill
```

A multi-year backfill takes a while and hits slurmdbd hard. Run it outside
business hours. If it is interrupted, run it again — it picks up where it
stopped.

It does **not** commit. Review the diff, then commit and push by hand for the
first load.

## Nightly timer

Install the units:

```bash
install -m 0644 deploy/cluster-impact.service /etc/systemd/system/
install -m 0644 deploy/cluster-impact.timer   /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now cluster-impact.timer
systemctl list-timers cluster-impact.timer
```

systemd rather than crontab: `systemctl status` shows the last outcome,
journald keeps the logs, and `Persistent=true` catches up a run missed while
the host was down.

Watch a run:

```bash
journalctl -u cluster-impact.service -f
systemctl start cluster-impact.service   # trigger one now
```

## Monitoring

The collector cannot reliably mail `@uchicago.edu` from the cluster network
(Proofpoint blocks the range), so it does not try. Instead it writes
`data/health.json` on every run, the site shows a "data as of" badge, and the
`freshness` GitHub Action fails if that heartbeat is more than 36 hours old —
which notifies through GitHub.

To verify the alarm works, stop the timer for two days and confirm the
workflow goes red and the badge on the site goes stale.

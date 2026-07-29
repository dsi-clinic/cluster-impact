#!/usr/bin/env bash
#
# gather-facts.sh — collect the cluster facts that cannot be derived from any
# repo, in one read-only pass.
#
# Run this on cluster-mgmt.ds.uchicago.edu (the recommended collector host), or
# on any node with the Slurm client. It answers imp-5rj, imp-aey, imp-61u, and
# the open question on imp-4e1.
#
#   ssh cluster-mgmt.ds.uchicago.edu 'bash -s' < deploy/gather-facts.sh | tee /tmp/facts.txt
#
# NO CONFIG OR FILESYSTEM CHANGES. Everything is a query: sinfo, sacctmgr show,
# scontrol show, curl GETs. It writes no files and changes no state.
#
# One honest caveat: section 1 uses `srun` to read nvidia-smi on each node, and
# that does submit a real (1-minute, 1-GPU, --immediate=20) job per node. It is
# the only way to see the marketing model name if you cannot ssh to the nodes
# directly. If you would rather not put anything in the queue, delete section 1
# and instead run:  for n in m001 n001 o001 p001 q001; do ssh $n nvidia-smi -L; done
#
# SAFE TO PASTE BACK. It deliberately does NOT print usernames. Account names,
# GPU models, and per-account user COUNTS are all that leave the cluster, which
# is the same class of data the public site already publishes. The one thing to
# glance at before pasting is the account list in section 3 — if any account is
# literally a person's username, say so instead of pasting it.
set -uo pipefail

hr() { printf '\n===== %s =====\n' "$1"; }

hr "0. where am I"
hostname -f 2>/dev/null || hostname
printf 'slurm client: '; sinfo --version 2>/dev/null || echo 'NOT INSTALLED'
printf 'podman: ';       podman --version 2>/dev/null || echo 'NOT INSTALLED'

# --- imp-5rj: GPU form factors -------------------------------------------
# The headline PFLOPS figure depends on SXM vs PCIe for H100/H200. nvidia-smi
# reports the marketing name, which distinguishes them ("H100 SXM5" vs
# "H100 PCIe"). Nothing in Puppet records this.
hr "1. GPU models per node (imp-5rj)"
for n in m001 n001 o001 p001 q001 g002 h001 k001; do
  printf '%-6s ' "$n"
  timeout 25 srun --nodelist="$n" --gres=gpu:1 -t 1 --immediate=20 \
      nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null \
    | sort -u | paste -sd' | ' - \
    || echo "(could not reach - node busy/down, or try: ssh $n nvidia-smi -L)"
done

hr "1b. GRES as Slurm sees it (cross-check against config/cluster.yaml)"
sinfo --Node --noheader --format "%N|%G|%T" 2>/dev/null | sort || echo "sinfo failed"

hr "1c. GPU totals by type"
sinfo --Node --noheader --format "%G" 2>/dev/null \
  | tr ',' '\n' | grep -oE 'gpu:[a-z0-9]+:[0-9]+' \
  | awk -F: '{t[$2]+=$3} END {s=0; for (k in t) {printf "%-8s %d\n", k, t[k]; s+=t[k]} printf "%-8s %d\n","TOTAL",s}'

# --- imp-aey: can the collector reach Prometheus? ------------------------
hr "2. Prometheus reachability from THIS host (imp-aey)"
printf 'GET s10:9090/-/ready -> '
curl -sS -m 6 -o /dev/null -w '%{http_code}\n' \
  http://s10.cs.uchicago.edu:9090/-/ready 2>&1 || echo 'UNREACHABLE'

printf 'ZFS pool counters present? '
curl -sSG -m 10 http://s10.cs.uchicago.edu:9090/api/v1/query \
  --data-urlencode 'query=count(node_zfs_pool_io_read_bytes_total)' 2>/dev/null \
  | head -c 200; echo

printf 'storage-node disk counters present? '
curl -sSG -m 10 http://s10.cs.uchicago.edu:9090/api/v1/query \
  --data-urlencode 'query=count(node_disk_read_bytes_total{instance=~"cluster-storage[0-9]+.*"})' 2>/dev/null \
  | head -c 200; echo

# --- imp-4e1: is DCGM already flowing for DSI? ---------------------------
printf 'DCGM series by job (imp-4e1): '
curl -sSG -m 10 http://s10.cs.uchicago.edu:9090/api/v1/query \
  --data-urlencode 'query=count(DCGM_FI_DEV_GPU_UTIL) by (job)' 2>/dev/null \
  | head -c 400; echo

# --- imp-61u: the account allowlist -------------------------------------
# Accounts and their org/description only. No usernames: the second query
# prints a COUNT per account, which is exactly what the k-anonymity threshold
# needs and reveals nobody.
hr "3. Slurm accounts for config/groups.yaml (imp-61u)"
sacctmgr --parsable2 --noheader show account format=Account,Descr,Org 2>/dev/null \
  | sort || echo "sacctmgr failed"

hr "3b. distinct users per account (counts only, no names)"
sacctmgr --parsable2 --noheader show assoc format=Account,User 2>/dev/null \
  | awk -F'|' '$2!=""{c[$1]++} END {for (a in c) printf "%-24s %d\n", a, c[a]}' \
  | sort || echo "sacctmgr failed"

hr "4. partitions and QoS (for the utilization page)"
sinfo --noheader --format "%P|%a|%l|%D" 2>/dev/null | sort || true
sacctmgr --parsable2 --noheader show qos format=Name,MaxWall,Priority 2>/dev/null | sort || true

hr "5. accounting retention horizon (bounds the backfill, imp-bba)"
printf 'PurgeJobAfter/PurgeStepAfter: '
scontrol show config 2>/dev/null | grep -iE "purge" | paste -sd'; ' - || echo '(check slurmdbd.conf on the dbd host)'
printf 'earliest job in slurmdbd: '
sacct --allusers --allocations --noheader --parsable2 -X \
      --starttime=2020-01-01 --endtime=now --format=Start -n 2>/dev/null \
  | grep -vE '^(None|Unknown|)$' | sort | head -1 || echo '(query failed)'

hr "done"
echo "Paste this back with:  bead-answer imp-aey \"<paste>\""

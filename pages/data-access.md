---
title: "Open Data"
permalink: /data-access/
nav_order: 8
---

Everything on this site is rendered from static JSON files served from this
domain. There is no API key, no rate limit, and no registration. Take the
numbers and check them.

<span id="freshness" class="freshness freshness--unknown">Data freshness unknown</span>

## Files

| File | Contents |
| --- | --- |
| [`/data/index.json`]({{ '/data/index.json' | relative_url }}) | List of available month files |
| `/data/daily/YYYY-MM.json` | One record per day for that month |
| [`/data/rollups/monthly.json`]({{ '/data/rollups/monthly.json' | relative_url }}) | Monthly aggregates |
| [`/data/rollups/yearly.json`]({{ '/data/rollups/yearly.json' | relative_url }}) | Yearly aggregates |
| [`/data/records.json`]({{ '/data/records.json' | relative_url }}) | All-time records and cumulative totals |
| [`/data/inventory.json`]({{ '/data/inventory.json' | relative_url }}) | Live node and GPU inventory |
| [`/data/growth.json`]({{ '/data/growth.json' | relative_url }}) | New-user growth and retention cohorts |
| [`/data/storage.json`]({{ '/data/storage.json' | relative_url }}) | Filesystem capacity |
| [`/data/pricing.json`]({{ '/data/pricing.json' | relative_url }}) | Cloud rate table used for cost avoidance |
| [`/data/health.json`]({{ '/data/health.json' | relative_url }}) | Last collector run and per-source status |

## A day record

```json
{
  "date": "2026-07-20",
  "gpu_hours": {
    "allocated": 1843.5, "available": 3072.0, "reported": 3360.0,
    "down": 288.0, "idle": 1228.5
  },
  "cpu_hours_allocated": 7412.0,
  "utilization": {
    "available": 0.6001, "installed": 0.5486,
    "availability": 0.9143, "from_sreport": true
  },
  "jobs": {
    "total": 142,
    "by_state": { "COMPLETED": 128, "FAILED": 9, "TIMEOUT": 5 },
    "by_size": { "1": 84, "2-4": 41, "5-8": 17 },
    "success_rate": 0.9014
  },
  "gpu_hours_by_model": { "h100": 921.0, "a100": 612.5, "l40s": 310.0 },
  "gpu_hours_by_partition": { "general": 1712.0, "interactive": 131.5 },
  "gpu_hours_by_qos": { "general": 1640.0, "interactive": 131.5, "protected": 72.0 },
  "active_users": 37,
  "wait_seconds": { "p50": 94.0, "p90": 1820.0, "p99": 14400.0, "samples": 142 },
  "hourly_gpu_hours": [64.2, "... 24 entries ..."],
  "records": {
    "largest_job_gpus": 8, "largest_job_gpu_hours": 96.0,
    "longest_job_hours": 23.8, "max_nodes_in_job": 2
  },
  "groups": [
    {
      "name": "Example Lab", "department": "Statistics",
      "division": "Physical Sciences Division", "type": "lab",
      "gpu_hours": 421.0, "cpu_hours": 1684.0, "jobs": 22, "users": 5
    }
  ]
}
```

## What you will not find

No usernames, job IDs, job names, exit codes, or node names. No per-person
series of any kind. A research group appears by name only if an operator
added it to the allowlist and it clears the anonymity threshold for the period
shown; everything else is aggregated into `"Other"`. The
[methodology]({{ '/methodology/' | relative_url }}) explains the guarantees and
how they are enforced.

## Reuse

These are public University figures — use them in proposals, reports, and
talks. A link back to this site is appreciated so readers can find the
methodology. Charts on this site each have a download button in their top
right corner that exports a PNG at 2× resolution for slides.

Source code and data history:
[github.com/dsi-clinic/cluster-impact](https://github.com/dsi-clinic/cluster-impact).

<script>
  document.addEventListener('DOMContentLoaded', function () {
    Impact.freshness('#freshness');
  });
</script>

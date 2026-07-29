---
title: "Capacity & Storage"
permalink: /capacity/
nav_order: 4
---

{% assign s = site.data.summary %}
{% assign d = s.display %}

What the cluster is made of, and how much data it holds.

<span id="freshness" class="freshness freshness--unknown">Data freshness unknown</span>

<div class="stat-grid">
  {% include stat-tile.html label="Peak performance" value=d.peak_pflops_fp16 unit=" PFLOPS" note="Aggregate dense FP16 tensor throughput. No sparsity multiplier applied." %}
  {% include stat-tile.html label="GPUs installed" value=d.gpus_installed %}
  {% include stat-tile.html label="GPUs online" value=s.gpus_online note="Currently up and schedulable." %}
  {% include stat-tile.html label="Storage" value=s.storage_pib unit=" PB" note="Provisioned across all shared filesystems." %}
</div>

## Hardware

<div class="chart-card">
  <div class="chart-card__head">
    <h3 class="chart-card__title">GPU mix</h3>
  </div>
  <p class="chart-card__sub">
    Discovered live from the scheduler, not read from a config file — so this
    cannot drift from reality.
  </p>
  <div id="chart-gpus" class="chart"></div>
</div>

## Storage

<div class="chart-card">
  <div class="chart-card__head">
    <h3 class="chart-card__title">Capacity by filesystem</h3>
  </div>
  <p class="chart-card__sub">
    Used and free space across project and scratch filesystems. Scratch is
    purged on a rolling window; project storage is persistent.
  </p>
  <div id="chart-storage" class="chart"></div>
</div>

<div class="chart-card">
  <div class="chart-card__head">
    <h3 class="chart-card__title">Storage I/O (yesterday)</h3>
  </div>
  <p class="chart-card__sub">
    Total bytes read and written across the shared storage nodes in the
    most recent complete calendar day, integrated from Prometheus rate
    series. See the <a href="{{ '/methodology/' | relative_url }}">methodology
    page</a> for why cumulative counters from <code>zpool iostat</code> are
    not used.
  </p>
  <div id="chart-storage-io" class="chart"></div>
</div>

<p class="methodology-note">
  Peak PFLOPS is a theoretical ceiling computed from vendor specifications for
  the installed hardware, using dense (non-sparse) tensor-core figures. It is
  a description of the machine, not a benchmark result, and no real workload
  reaches it.
</p>

<script>
  document.addEventListener('DOMContentLoaded', function () {
    Impact.freshness('#freshness');
    Impact.gpuMix('chart-gpus');
    Impact.storageChart('chart-storage');
    Impact.storageIo('chart-storage-io');
  });
</script>

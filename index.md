---
title: "DSI Cluster Impact"
layout: single
permalink: /
classes: [wide, left-aligned]
hide_hero: true
author_profile: false
---

{% assign s = site.data.summary %}
{% assign d = s.display %}

The University of Chicago Data Science Institute operates a shared GPU cluster
for research and teaching across the University. This site reports what that
machine actually delivers — updated nightly, computed from Slurm accounting
records, and published with its methodology attached.

<span id="freshness" class="freshness freshness--unknown">Data freshness unknown</span>

{% include no-data.html %}

<div class="stat-grid">
  {% include stat-tile.html label="Peak performance" value=d.peak_pflops_fp16 unit=" PFLOPS" note="Aggregate dense FP16 tensor throughput of every installed GPU." %}
  {% include stat-tile.html label="GPUs installed" value=d.gpus_installed note="Across A40, A100, L40S, H100, and H200 nodes." %}
  {% include stat-tile.html label="GPU-hours this year" value=d.gpu_hours_ytd note="Allocated to research and coursework since 1 January." %}
  {% include stat-tile.html label="Utilization" value=d.utilization_ytd unit="%" note="Of GPU-hours the scheduler could offer. See Methodology for the denominator." %}
  {% include stat-tile.html label="Researchers" value=d.unique_users_trailing_year note="Distinct people who ran at least one job in the last 12 months." %}
  {% include stat-tile.html label="Labs & courses served" value=s.labs_named_trailing_year note="Named research groups, courses, and clinic teams in the last 12 months." %}
  {% include stat-tile.html label="Compute delivered" value=d.total_gpu_years unit=" GPU-years" note="Cumulative, across all recorded history." %}
  {% include stat-tile.html label="Cloud cost avoided" value=d.cloud_cost_avoided_ytd_usd prefix="$" note="This year, at public on-demand list rates. See Value Delivered." %}
</div>

## How busy is the cluster?

<div class="chart-card">
  <div class="chart-card__head">
    <h3 class="chart-card__title">GPU-hours per day</h3>
  </div>
  <p class="chart-card__sub">
    Allocated, idle, and unavailable GPU-hours, stacked to total installed
    capacity. Drag the slider to change the range; hover for exact figures.
  </p>
  <div id="chart-utilization" class="chart chart--tall"></div>
</div>

<div class="chart-card">
  <div class="chart-card__head">
    <h3 class="chart-card__title">Utilization and availability</h3>
  </div>
  <p class="chart-card__sub">
    Utilization is allocated GPU-hours divided by the GPU-hours the scheduler
    could actually offer. Availability is the share of installed capacity that
    was up and schedulable.
  </p>
  <div id="chart-rate" class="chart"></div>
</div>

## Who uses it?

<div class="chart-card">
  <div class="chart-card__head">
    <h3 class="chart-card__title">GPU-hours by research group</h3>
  </div>
  <p class="chart-card__sub">
    Most recent full year. Groups below the anonymity threshold are combined
    into “Other”; their usage still counts toward every total on this page.
  </p>
  <div id="chart-groups" class="chart chart--tall"></div>
</div>

<div class="chart-card">
  <div class="chart-card__head">
    <h3 class="chart-card__title">When the cluster is busy</h3>
  </div>
  <p class="chart-card__sub">
    Mean GPU-hours allocated by hour of day and day of week, over the last 90
    days.
  </p>
  <div id="chart-heatmap" class="chart"></div>
</div>

<p class="methodology-note">
  Every figure on this site is derived from Slurm accounting records and
  published as open JSON. Individual users are never named. Read the
  <a href="{{ '/methodology/' | relative_url }}">methodology</a>, including
  what these numbers cannot yet tell you, or
  <a href="{{ '/data-access/' | relative_url }}">download the underlying data</a>.
</p>

<script>
  document.addEventListener('DOMContentLoaded', function () {
    Impact.freshness('#freshness');
    Impact.utilizationTrend('chart-utilization', { days: 180 });
    Impact.utilizationRate('chart-rate', { days: 180 });
    Impact.groupBreakdown('chart-groups', { granularity: 'yearly', top: 12 });
    Impact.hourHeatmap('chart-heatmap', { days: 90 });
  });
</script>

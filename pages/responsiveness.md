---
title: "Responsiveness"
permalink: /responsiveness/
nav_order: 3
---

{% assign s = site.data.summary %}
{% assign d = s.display %}

A busy cluster that nobody can get onto is not a success. These are the
numbers users actually feel: how long they wait, and whether their jobs
finish.

<span id="freshness" class="freshness freshness--unknown">Data freshness unknown</span>

<div class="stat-grid">
  {% include stat-tile.html label="Job success rate" value=d.success_rate_ytd unit="%" note="Completed vs. all finished jobs, year to date." %}
  {% include stat-tile.html label="Jobs run" value=d.jobs_ytd note="Year to date." %}
  {% include stat-tile.html label="Availability" value=d.availability_ytd unit="%" note="Share of installed GPU-hours that were up and schedulable." %}
</div>

## Queue wait

<div class="chart-card">
  <div class="chart-card__head">
    <h3 class="chart-card__title">Time from submit to start</h3>
  </div>
  <p class="chart-card__sub">
    Median, 90th, and 99th percentile. The tail matters more than the median:
    a cluster with a five-minute median and a twelve-hour p99 feels
    unpredictable, and unpredictable is what drives people to the cloud.
  </p>
  <div id="chart-wait" class="chart"></div>
</div>

## Outcomes

<div class="chart-card">
  <div class="chart-card__head">
    <h3 class="chart-card__title">How jobs end</h3>
  </div>
  <p class="chart-card__sub">
    Last 120 days. Failures and out-of-memory exits are as much a
    documentation problem as a hardware one — this chart is how we find out.
  </p>
  <div id="chart-outcomes" class="chart"></div>
</div>

<div class="chart-card">
  <div class="chart-card__head">
    <h3 class="chart-card__title">Job sizes</h3>
  </div>
  <p class="chart-card__sub">
    A healthy shared cluster serves both single-GPU exploration and
    multi-node capability runs. This shows whether it actually does.
  </p>
  <div id="chart-sizes" class="chart"></div>
</div>

<script>
  document.addEventListener('DOMContentLoaded', function () {
    Impact.freshness('#freshness');
    Impact.waitPercentiles('chart-wait', { days: 180 });
    Impact.jobOutcomes('chart-outcomes', { days: 120 });
    Impact.jobSizes('chart-sizes', { days: 120 });
  });
</script>

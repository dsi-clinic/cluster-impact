---
title: "Value Delivered"
permalink: /value/
nav_order: 6
---

{% assign s = site.data.summary %}
{% assign d = s.display %}

What it would have cost to rent this compute instead of owning it.

<span id="freshness" class="freshness freshness--unknown">Data freshness unknown</span>

<div class="stat-grid">
  {% include stat-tile.html label="Cloud cost avoided" value=d.cloud_cost_avoided_ytd_usd prefix="$" note="Year to date, at public on-demand list rates." %}
  {% include stat-tile.html label="GPU-hours delivered" value=d.gpu_hours_ytd note="Year to date." %}
  {% include stat-tile.html label="Compute delivered" value=d.total_gpu_years unit=" GPU-years" note="Cumulative, all recorded history." %}
</div>

## Read this before quoting the number

This is the figure most likely to be challenged, so here is exactly what it is
and is not.

**What it is.** Allocated GPU-hours for each model, multiplied by that model's
public on-demand hourly rate, summed. Nothing else.

**What it is not.** It is not a budget, a saving that appears in any ledger,
or a claim that the same work would have been purchased at list price. Anyone
running this volume in the cloud would negotiate committed-use discounts, use
spot capacity, or restructure the work — all of which would lower the bill
substantially. Treat it as an upper bound on replacement cost at list price.

**What it leaves out in the other direction.** It excludes the staff,
facilities, power, cooling, and networking that make the cluster run, and it
excludes the data-transfer charges that dominate real cloud bills for
research workloads. It is a comparison of compute rental rates, not a total
cost of ownership analysis.

The rate table, its source, and the date it was retrieved are printed below
and versioned in the repository. The site refuses to display a dollar figure
at all unless a source and an as-of date are recorded alongside the rates.

## Rate table

<div id="pricing-table"></div>

## Cost avoided by year

<div class="chart-card">
  <div class="chart-card__head">
    <h3 class="chart-card__title">Estimated cloud cost avoided</h3>
  </div>
  <div id="chart-cost" class="chart"></div>
</div>

<script>
  document.addEventListener('DOMContentLoaded', function () {
    Impact.freshness('#freshness');
    Impact.pricingTable('pricing-table');
    Impact.costByPeriod('chart-cost');
  });
</script>

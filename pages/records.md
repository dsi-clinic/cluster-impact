---
title: "Records"
permalink: /records/
nav_order: 5
---

The wall. Biggest, longest, busiest — across everything the accounting
database still remembers.

<span id="freshness" class="freshness freshness--unknown">Data freshness unknown</span>

<div id="record-wall" class="record-grid"></div>

## Cumulative totals

<div id="record-totals"></div>

<p class="methodology-note">
  Records are computed from daily aggregates, so a record for a single job is
  the largest observed on any one day rather than a query over every job ever
  submitted. Records reach only as far back as the accounting database
  retains — see <a href="{{ '/methodology/' | relative_url }}">Methodology</a>
  for the horizon.
</p>

<script>
  document.addEventListener('DOMContentLoaded', function () {
    Impact.freshness('#freshness');
    Impact.recordWall('record-wall');
    Impact.recordTotals('record-totals');
  });
</script>

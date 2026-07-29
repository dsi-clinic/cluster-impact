/* Dashboard runtime.
 *
 * One shared ECharts theme so every chart on the site reads as one system,
 * plus a small set of chart builders. Each builder is defensive: if the data
 * file is missing or empty it renders an honest "no data" panel rather than
 * an empty axis, because a blank chart looks like a broken site and an
 * explicit message looks like an honest one.
 */
(function (global) {
  'use strict';

  var BASE = (global.IMPACT_BASEURL || '') + '/data';

  var PALETTE = [
    '#2a5d9f', '#c8811a', '#3f8a6e', '#8b5aa6', '#b04a4a', '#4a7a8c',
    '#6d7f2f', '#a0522d'
  ];

  var INK = '#1f2124';
  var MUTED = '#6a6f76';
  var LINE = '#e3e5e8';
  var IDLE = '#c3c7cc';
  var DOWN = '#9aa0a6';

  var FONT = '"Source Sans Pro", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';

  var reduceMotion =
    global.matchMedia && global.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ---------------------------------------------------------------- theme

  function baseOption(opts) {
    opts = opts || {};
    return {
      color: PALETTE,
      animation: !reduceMotion,
      animationDuration: 400,
      textStyle: { fontFamily: FONT, color: INK },
      grid: {
        left: 8,
        right: 16,
        bottom: opts.zoom ? 48 : 8,
        top: opts.legend === false ? 16 : 40,
        containLabel: true
      },
      legend:
        opts.legend === false
          ? { show: false }
          : {
              top: 4,
              left: 0,
              icon: 'roundRect',
              itemWidth: 10,
              itemHeight: 10,
              itemGap: 14,
              textStyle: { fontSize: 12, color: MUTED }
            },
      tooltip: {
        trigger: opts.trigger || 'axis',
        backgroundColor: 'rgba(255,255,255,0.97)',
        borderColor: LINE,
        borderWidth: 1,
        padding: [8, 10],
        textStyle: { fontSize: 12, color: INK },
        axisPointer: { type: 'line', lineStyle: { color: LINE } }
      },
      toolbox: {
        right: 4,
        top: 0,
        feature: {
          saveAsImage: {
            title: 'Download PNG',
            name: opts.exportName || 'dsi-cluster-impact',
            pixelRatio: 2,
            backgroundColor: '#ffffff'
          }
        },
        iconStyle: { borderColor: MUTED }
      }
    };
  }

  function categoryAxis(data, opts) {
    opts = opts || {};
    return {
      type: 'category',
      data: data,
      boundaryGap: opts.boundaryGap !== false,
      axisLine: { lineStyle: { color: LINE } },
      axisTick: { show: false },
      axisLabel: { color: MUTED, fontSize: 11, hideOverlap: true },
      splitLine: { show: false }
    };
  }

  function valueAxis(opts) {
    opts = opts || {};
    return {
      type: 'value',
      name: opts.name || '',
      nameTextStyle: { color: MUTED, fontSize: 11, align: 'left' },
      nameGap: 12,
      max: opts.max,
      min: opts.min,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: MUTED, fontSize: 11, formatter: opts.formatter },
      splitLine: { lineStyle: { color: LINE, type: 'dashed' } }
    };
  }

  // ------------------------------------------------------------ utilities

  function fmtNumber(value, digits) {
    if (value === null || value === undefined || isNaN(value)) return '—';
    return Number(value).toLocaleString('en-US', {
      minimumFractionDigits: digits || 0,
      maximumFractionDigits: digits === undefined ? 0 : digits
    });
  }

  function fmtPercent(value, digits) {
    if (value === null || value === undefined || isNaN(value)) return '—';
    return (value * 100).toFixed(digits === undefined ? 1 : digits) + '%';
  }

  function fmtCompact(value) {
    if (value === null || value === undefined || isNaN(value)) return '—';
    var abs = Math.abs(value);
    if (abs >= 1e9) return (value / 1e9).toFixed(1) + 'B';
    if (abs >= 1e6) return (value / 1e6).toFixed(1) + 'M';
    if (abs >= 1e3) return (value / 1e3).toFixed(1) + 'k';
    return String(Math.round(value));
  }

  function fmtBytes(value) {
    if (value === null || value === undefined || isNaN(value)) return '—';
    var abs = Math.abs(value);
    if (abs >= 1099511627776) return (value / 1099511627776).toFixed(1) + ' TiB';
    if (abs >= 1073741824) return (value / 1073741824).toFixed(1) + ' GiB';
    if (abs >= 1048576) return (value / 1048576).toFixed(1) + ' MiB';
    if (abs >= 1024) return (value / 1024).toFixed(1) + ' KiB';
    return String(Math.round(value)) + ' B';
  }

  function fmtDuration(seconds) {
    if (seconds === null || seconds === undefined || isNaN(seconds)) return '—';
    if (seconds < 90) return Math.round(seconds) + 's';
    if (seconds < 5400) return (seconds / 60).toFixed(1) + ' min';
    if (seconds < 172800) return (seconds / 3600).toFixed(1) + ' h';
    return (seconds / 86400).toFixed(1) + ' d';
  }

  function unavailable(el, message) {
    if (!el) return;
    el.innerHTML =
      '<div class="chart__fallback">' +
      (message || 'No data available yet. The collector has not published this series.') +
      '</div>';
  }

  var registry = [];

  function mount(id, builder) {
    var el = document.getElementById(id);
    if (!el) return;
    if (!global.echarts) {
      unavailable(el, 'Charts require JavaScript. Summary figures above are rendered without it.');
      return;
    }
    try {
      var chart = global.echarts.init(el, null, { renderer: 'canvas' });
      var option = builder(chart);
      if (!option) {
        chart.dispose();
        unavailable(el);
        return;
      }
      chart.setOption(option);
      registry.push(chart);
    } catch (err) {
      unavailable(el, 'This chart could not be rendered.');
      if (global.console) global.console.error(id, err);
    }
  }

  var resizeTimer = null;
  global.addEventListener('resize', function () {
    if (resizeTimer) clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      registry.forEach(function (chart) {
        chart.resize();
      });
    }, 120);
  });

  // ----------------------------------------------------------------- data

  var cache = {};

  function load(name) {
    if (cache[name]) return cache[name];
    cache[name] = fetch(BASE + '/' + name + '.json', { credentials: 'same-origin' })
      .then(function (response) {
        if (!response.ok) throw new Error(response.status + ' ' + response.statusText);
        return response.json();
      })
      .catch(function (err) {
        if (global.console) global.console.warn('impact: could not load ' + name, err);
        return null;
      });
    return cache[name];
  }

  /* Every month file, concatenated into one chronological day array.
   * The index lists which months exist so the browser does not have to
   * guess at filenames or 404 its way through the calendar. */
  function loadDays() {
    if (cache.__days) return cache.__days;
    cache.__days = load('index').then(function (index) {
      if (!index || !Array.isArray(index.months) || !index.months.length) return [];
      return Promise.all(
        index.months.map(function (month) {
          return load('daily/' + month);
        })
      ).then(function (files) {
        var days = [];
        files.forEach(function (file) {
          if (file && Array.isArray(file.days)) days = days.concat(file.days);
        });
        days.sort(function (a, b) {
          return a.date < b.date ? -1 : a.date > b.date ? 1 : 0;
        });
        return days;
      });
    });
    return cache.__days;
  }

  function lastN(days, n) {
    return n && days.length > n ? days.slice(days.length - n) : days;
  }

  // --------------------------------------------------------------- charts

  function utilizationTrend(id, options) {
    options = options || {};
    loadDays().then(function (days) {
      days = lastN(days, options.days || 180);
      if (!days.length) return unavailable(document.getElementById(id));
      mount(id, function () {
        var opt = baseOption({ exportName: 'gpu-utilization', zoom: true });
        opt.xAxis = categoryAxis(
          days.map(function (d) { return d.date; }),
          { boundaryGap: false }
        );
        opt.yAxis = valueAxis({
          name: 'GPU-hours / day',
          formatter: function (v) { return fmtCompact(v); }
        });
        opt.dataZoom = [
          { type: 'inside', throttle: 50 },
          { type: 'slider', height: 18, bottom: 12, borderColor: LINE,
            fillerColor: 'rgba(42,93,159,0.10)', handleStyle: { color: '#2a5d9f' },
            textStyle: { color: MUTED, fontSize: 10 } }
        ];
        opt.tooltip.valueFormatter = function (v) { return fmtNumber(v, 0) + ' GPU-h'; };
        opt.series = [
          {
            name: 'Allocated',
            type: 'line',
            stack: 'capacity',
            areaStyle: { opacity: 0.85 },
            lineStyle: { width: 0 },
            symbol: 'none',
            color: PALETTE[0],
            data: days.map(function (d) { return d.gpu_hours.allocated; })
          },
          {
            name: 'Idle',
            type: 'line',
            stack: 'capacity',
            areaStyle: { opacity: 0.7 },
            lineStyle: { width: 0 },
            symbol: 'none',
            color: IDLE,
            data: days.map(function (d) {
              return Math.max(d.gpu_hours.available - d.gpu_hours.allocated, 0);
            })
          },
          {
            name: 'Unavailable',
            type: 'line',
            stack: 'capacity',
            areaStyle: { opacity: 0.7 },
            lineStyle: { width: 0 },
            symbol: 'none',
            color: DOWN,
            data: days.map(function (d) { return d.gpu_hours.down; })
          }
        ];
        return opt;
      });
    });
  }

  function utilizationRate(id, options) {
    options = options || {};
    loadDays().then(function (days) {
      days = lastN(days, options.days || 180);
      if (!days.length) return unavailable(document.getElementById(id));
      mount(id, function () {
        var opt = baseOption({ exportName: 'utilization-rate' });
        opt.xAxis = categoryAxis(days.map(function (d) { return d.date; }),
          { boundaryGap: false });
        opt.yAxis = valueAxis({
          max: 1,
          formatter: function (v) { return Math.round(v * 100) + '%'; }
        });
        opt.tooltip.valueFormatter = function (v) { return fmtPercent(v); };
        opt.series = [
          {
            name: 'Utilization (of available)',
            type: 'line',
            smooth: true,
            symbol: 'none',
            lineStyle: { width: 2 },
            color: PALETTE[0],
            data: days.map(function (d) { return d.utilization.available; })
          },
          {
            name: 'Availability',
            type: 'line',
            smooth: true,
            symbol: 'none',
            lineStyle: { width: 1.5, type: 'dashed' },
            color: PALETTE[2],
            data: days.map(function (d) { return d.utilization.availability; })
          }
        ];
        return opt;
      });
    });
  }

  function stackedByKey(id, key, options) {
    options = options || {};
    loadDays().then(function (days) {
      days = lastN(days, options.days || 120);
      if (!days.length) return unavailable(document.getElementById(id));

      var totals = {};
      days.forEach(function (d) {
        Object.keys(d[key] || {}).forEach(function (name) {
          totals[name] = (totals[name] || 0) + d[key][name];
        });
      });
      var names = Object.keys(totals).sort(function (a, b) { return totals[b] - totals[a]; });
      if (!names.length) return unavailable(document.getElementById(id));
      names = names.slice(0, options.top || 8);

      mount(id, function () {
        var opt = baseOption({ exportName: key, zoom: true });
        opt.xAxis = categoryAxis(days.map(function (d) { return d.date; }),
          { boundaryGap: false });
        opt.yAxis = valueAxis({
          name: 'GPU-hours / day',
          formatter: function (v) { return fmtCompact(v); }
        });
        opt.dataZoom = [
          { type: 'inside' },
          { type: 'slider', height: 18, bottom: 12, borderColor: LINE,
            textStyle: { color: MUTED, fontSize: 10 } }
        ];
        opt.tooltip.valueFormatter = function (v) { return fmtNumber(v, 0) + ' GPU-h'; };
        opt.series = names.map(function (name, i) {
          return {
            name: options.labels && options.labels[name] ? options.labels[name] : name,
            type: 'line',
            stack: 'total',
            areaStyle: { opacity: 0.8 },
            lineStyle: { width: 0 },
            symbol: 'none',
            color: PALETTE[i % PALETTE.length],
            data: days.map(function (d) { return (d[key] || {})[name] || 0; })
          };
        });
        return opt;
      });
    });
  }

  function activeUsers(id, options) {
    options = options || {};
    loadDays().then(function (days) {
      days = lastN(days, options.days || 180);
      if (!days.length) return unavailable(document.getElementById(id));
      mount(id, function () {
        var opt = baseOption({ exportName: 'active-users' });
        opt.xAxis = categoryAxis(days.map(function (d) { return d.date; }),
          { boundaryGap: false });
        opt.yAxis = valueAxis({ name: 'researchers' });
        opt.tooltip.valueFormatter = function (v) { return fmtNumber(v) + ' researchers'; };
        opt.series = [
          {
            name: 'Active that day',
            type: 'bar',
            color: PALETTE[0],
            barMaxWidth: 14,
            data: days.map(function (d) { return d.active_users; })
          }
        ];
        return opt;
      });
    });
  }

  function monthlyUniqueUsers(id) {
    load('rollups/monthly').then(function (rollup) {
      if (!rollup || !rollup.periods || !rollup.periods.length) {
        return unavailable(document.getElementById(id));
      }
      var periods = rollup.periods.filter(function (p) { return p.unique_users !== null; });
      if (!periods.length) {
        return unavailable(
          document.getElementById(id),
          'Unique-user history is not available for this range.'
        );
      }
      mount(id, function () {
        var opt = baseOption({ exportName: 'unique-researchers-monthly' });
        opt.xAxis = categoryAxis(periods.map(function (p) { return p.period; }));
        opt.yAxis = valueAxis({ name: 'distinct researchers' });
        opt.tooltip.valueFormatter = function (v) { return fmtNumber(v); };
        opt.series = [
          {
            name: 'Distinct researchers',
            type: 'bar',
            color: PALETTE[0],
            barMaxWidth: 32,
            data: periods.map(function (p) { return p.unique_users; })
          }
        ];
        return opt;
      });
    });
  }

  function newUsers(id) {
    load('growth').then(function (growth) {
      if (!growth || !growth.available) {
        return unavailable(document.getElementById(id), 'Growth history is not available yet.');
      }
      var months = Object.keys(growth.new_users_by_month).sort();
      if (!months.length) return unavailable(document.getElementById(id));
      var running = 0;
      var cumulative = months.map(function (m) {
        running += growth.new_users_by_month[m];
        return running;
      });
      mount(id, function () {
        var opt = baseOption({ exportName: 'researcher-growth' });
        opt.xAxis = categoryAxis(months);
        opt.yAxis = [
          valueAxis({ name: 'new' }),
          valueAxis({ name: 'cumulative' })
        ];
        opt.series = [
          {
            name: 'New researchers',
            type: 'bar',
            color: PALETTE[0],
            barMaxWidth: 28,
            data: months.map(function (m) { return growth.new_users_by_month[m]; })
          },
          {
            name: 'Cumulative',
            type: 'line',
            yAxisIndex: 1,
            smooth: true,
            symbol: 'none',
            lineStyle: { width: 2 },
            color: PALETTE[1],
            data: cumulative
          }
        ];
        return opt;
      });
    });
  }

  function waitPercentiles(id, options) {
    options = options || {};
    loadDays().then(function (days) {
      days = lastN(days, options.days || 120).filter(function (d) {
        return d.wait_seconds && d.wait_seconds.samples > 0;
      });
      if (!days.length) return unavailable(document.getElementById(id));
      mount(id, function () {
        var opt = baseOption({ exportName: 'queue-wait' });
        opt.xAxis = categoryAxis(days.map(function (d) { return d.date; }),
          { boundaryGap: false });
        opt.yAxis = valueAxis({
          name: 'queue wait',
          formatter: function (v) { return fmtDuration(v); }
        });
        opt.tooltip.valueFormatter = function (v) { return fmtDuration(v); };
        [
          ['p50', 'Median', PALETTE[0]],
          ['p90', '90th percentile', PALETTE[1]],
          ['p99', '99th percentile', PALETTE[4]]
        ].forEach(function (spec) {
          opt.series = opt.series || [];
          opt.series.push({
            name: spec[1],
            type: 'line',
            smooth: true,
            symbol: 'none',
            lineStyle: { width: spec[0] === 'p50' ? 2 : 1.5 },
            color: spec[2],
            data: days.map(function (d) { return d.wait_seconds[spec[0]]; })
          });
        });
        return opt;
      });
    });
  }

  function jobOutcomes(id, options) {
    options = options || {};
    loadDays().then(function (days) {
      days = lastN(days, options.days || 120);
      if (!days.length) return unavailable(document.getElementById(id));
      var totals = {};
      days.forEach(function (d) {
        Object.keys(d.jobs.by_state || {}).forEach(function (state) {
          totals[state] = (totals[state] || 0) + d.jobs.by_state[state];
        });
      });
      var states = Object.keys(totals);
      if (!states.length) return unavailable(document.getElementById(id));
      var colorFor = function (state) {
        if (state === 'COMPLETED') return '#3f8a6e';
        if (state === 'RUNNING' || state === 'PENDING') return IDLE;
        if (state === 'CANCELLED') return DOWN;
        return PALETTE[(states.indexOf(state) % PALETTE.length)];
      };
      mount(id, function () {
        var opt = baseOption({ trigger: 'item', exportName: 'job-outcomes', legend: true });
        opt.tooltip.formatter = function (p) {
          return p.name + '<br/>' + fmtNumber(p.value) + ' jobs (' + p.percent + '%)';
        };
        opt.series = [
          {
            type: 'pie',
            radius: ['48%', '72%'],
            center: ['50%', '56%'],
            itemStyle: { borderColor: '#fff', borderWidth: 2 },
            label: { color: MUTED, fontSize: 11 },
            data: states
              .sort(function (a, b) { return totals[b] - totals[a]; })
              .map(function (state) {
                return {
                  name: state,
                  value: totals[state],
                  itemStyle: { color: colorFor(state) }
                };
              })
          }
        ];
        return opt;
      });
    });
  }

  function jobSizes(id, options) {
    options = options || {};
    var ORDER = ['cpu_only', '1', '2-4', '5-8', '9-16', '17+'];
    var LABELS = {
      cpu_only: 'CPU only',
      '1': '1 GPU',
      '2-4': '2–4 GPUs',
      '5-8': '5–8 GPUs',
      '9-16': '9–16 GPUs',
      '17+': '17+ GPUs'
    };
    loadDays().then(function (days) {
      days = lastN(days, options.days || 120);
      if (!days.length) return unavailable(document.getElementById(id));
      var totals = {};
      days.forEach(function (d) {
        Object.keys(d.jobs.by_size || {}).forEach(function (bucket) {
          totals[bucket] = (totals[bucket] || 0) + d.jobs.by_size[bucket];
        });
      });
      var buckets = ORDER.filter(function (b) { return totals[b]; });
      if (!buckets.length) return unavailable(document.getElementById(id));
      mount(id, function () {
        var opt = baseOption({ exportName: 'job-sizes', legend: false });
        opt.xAxis = categoryAxis(buckets.map(function (b) { return LABELS[b] || b; }));
        opt.yAxis = valueAxis({ name: 'jobs', formatter: fmtCompact });
        opt.tooltip.valueFormatter = function (v) { return fmtNumber(v) + ' jobs'; };
        opt.series = [
          {
            type: 'bar',
            barMaxWidth: 48,
            color: PALETTE[0],
            data: buckets.map(function (b) { return totals[b]; })
          }
        ];
        return opt;
      });
    });
  }

  function hourHeatmap(id, options) {
    options = options || {};
    var DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
    loadDays().then(function (days) {
      days = lastN(days, options.days || 90);
      if (!days.length) return unavailable(document.getElementById(id));
      var grid = {};
      days.forEach(function (d) {
        if (!Array.isArray(d.hourly_gpu_hours)) return;
        // JS getUTCDay: 0=Sun. Shift so Monday is index 0.
        var weekday = (new Date(d.date + 'T00:00:00Z').getUTCDay() + 6) % 7;
        d.hourly_gpu_hours.forEach(function (value, hour) {
          var key = weekday + ':' + hour;
          if (!grid[key]) grid[key] = { sum: 0, n: 0 };
          grid[key].sum += value;
          grid[key].n += 1;
        });
      });
      var data = [];
      var max = 0;
      Object.keys(grid).forEach(function (key) {
        var parts = key.split(':');
        var mean = grid[key].sum / grid[key].n;
        max = Math.max(max, mean);
        data.push([Number(parts[1]), Number(parts[0]), Math.round(mean * 10) / 10]);
      });
      if (!data.length) return unavailable(document.getElementById(id));
      mount(id, function () {
        var opt = baseOption({ trigger: 'item', legend: false, exportName: 'usage-heatmap' });
        opt.grid = { left: 8, right: 16, top: 16, bottom: 60, containLabel: true };
        opt.xAxis = categoryAxis(
          Array.apply(null, { length: 24 }).map(function (_, h) { return h; }),
          { boundaryGap: true }
        );
        opt.yAxis = {
          type: 'category',
          data: DAYS,
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: { color: MUTED, fontSize: 11 },
          splitLine: { show: false }
        };
        opt.visualMap = {
          min: 0,
          max: max || 1,
          orient: 'horizontal',
          left: 'center',
          bottom: 8,
          itemWidth: 12,
          itemHeight: 90,
          textStyle: { color: MUTED, fontSize: 10 },
          // Sequential single-hue ramp: this encodes magnitude, not category,
          // so it must not reuse the categorical palette.
          inRange: { color: ['#eef2f7', '#9db8d6', '#4a7ab0', '#1f4675'] }
        };
        opt.tooltip.formatter = function (p) {
          return DAYS[p.value[1]] + ' ' + String(p.value[0]).padStart(2, '0') + ':00<br/>' +
            fmtNumber(p.value[2], 1) + ' GPU-h (mean)';
        };
        opt.series = [
          {
            type: 'heatmap',
            data: data,
            itemStyle: { borderColor: '#fff', borderWidth: 1 },
            emphasis: { itemStyle: { borderColor: INK, borderWidth: 1 } }
          }
        ];
        return opt;
      });
    });
  }

  function groupBreakdown(id, options) {
    options = options || {};
    load('rollups/' + (options.granularity || 'yearly')).then(function (rollup) {
      if (!rollup || !rollup.periods || !rollup.periods.length) {
        return unavailable(document.getElementById(id));
      }
      var period = rollup.periods[rollup.periods.length - 1];
      var groups = (period.groups || []).slice(0, options.top || 12);
      if (!groups.length) return unavailable(document.getElementById(id));
      mount(id, function () {
        var opt = baseOption({ legend: false, exportName: 'usage-by-group' });
        opt.grid = { left: 8, right: 40, top: 8, bottom: 8, containLabel: true };
        opt.xAxis = valueAxis({ name: 'GPU-hours', formatter: fmtCompact });
        opt.yAxis = {
          type: 'category',
          data: groups.map(function (g) { return g.name; }).reverse(),
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: { color: INK, fontSize: 11 }
        };
        opt.tooltip.valueFormatter = function (v) { return fmtNumber(v) + ' GPU-h'; };
        opt.series = [
          {
            type: 'bar',
            barMaxWidth: 18,
            data: groups
              .map(function (g) {
                return {
                  value: g.gpu_hours,
                  itemStyle: { color: g.type === 'other' ? IDLE : PALETTE[0] }
                };
              })
              .reverse(),
            label: {
              show: true,
              position: 'right',
              color: MUTED,
              fontSize: 10,
              formatter: function (p) { return fmtCompact(p.value); }
            }
          }
        ];
        return opt;
      });
    });
  }

  function storageChart(id) {
    load('storage').then(function (storage) {
      if (!storage || !storage.available || !storage.filesystems.length) {
        return unavailable(
          document.getElementById(id),
          'Storage metrics are not being collected yet.'
        );
      }
      mount(id, function () {
        var opt = baseOption({ exportName: 'storage-capacity' });
        opt.xAxis = categoryAxis(storage.filesystems.map(function (f) { return f.name; }));
        opt.yAxis = valueAxis({ name: 'TiB', formatter: fmtCompact });
        opt.tooltip.valueFormatter = function (v) { return fmtNumber(v, 1) + ' TiB'; };
        opt.series = [
          {
            name: 'Used',
            type: 'bar',
            stack: 'cap',
            color: PALETTE[0],
            data: storage.filesystems.map(function (f) { return f.used_tib; })
          },
          {
            name: 'Free',
            type: 'bar',
            stack: 'cap',
            color: IDLE,
            data: storage.filesystems.map(function (f) {
              return Math.max(f.total_tib - f.used_tib, 0);
            })
          }
        ];
        return opt;
      });
    });
  }

  function storageIo(id) {
    load('storage').then(function (storage) {
      if (!storage || !storage.io_available) {
        return unavailable(
          document.getElementById(id),
          'Storage I/O metrics are not yet collected. Configure prometheus.queries.storage_read_bytes and storage_write_bytes.'
        );
      }
      mount(id, function () {
        var labels = ['Read', 'Write'];
        var values = [storage.io_read_bytes, storage.io_write_bytes];
        var opt = baseOption({
          exportName: 'storage-io',
          legend: false
        });
        opt.xAxis = categoryAxis(labels);
        opt.yAxis = valueAxis({
          name: 'bytes',
          formatter: function (v) { return fmtBytes(v); }
        });
        opt.tooltip.valueFormatter = function (v) { return fmtBytes(v); };
        opt.series = [
          {
            type: 'bar',
            barMaxWidth: 80,
            data: [
              { value: values[0], itemStyle: { color: PALETTE[0] } },
              { value: values[1], itemStyle: { color: PALETTE[1] } }
            ]
          }
        ];
        return opt;
      });
    });
  }

  function gpuMix(id) {
    load('inventory').then(function (inventory) {
      if (!inventory || !inventory.available) return unavailable(document.getElementById(id));
      var models = Object.keys(inventory.gpus_by_model || {});
      if (!models.length) return unavailable(document.getElementById(id));
      mount(id, function () {
        var opt = baseOption({ trigger: 'item', exportName: 'gpu-mix' });
        opt.tooltip.formatter = function (p) {
          return p.name + '<br/>' + fmtNumber(p.value) + ' GPUs (' + p.percent + '%)';
        };
        opt.series = [
          {
            type: 'pie',
            radius: ['48%', '72%'],
            center: ['50%', '56%'],
            itemStyle: { borderColor: '#fff', borderWidth: 2 },
            label: { color: MUTED, fontSize: 11 },
            data: models.map(function (model, i) {
              return {
                name: model.toUpperCase(),
                value: inventory.gpus_by_model[model],
                itemStyle: { color: PALETTE[i % PALETTE.length] }
              };
            })
          }
        ];
        return opt;
      });
    });
  }

  // ----------------------------------------------------------- record wall

  var RECORD_LABELS = {
    largest_job_gpus: ['Most GPUs in one job', 'GPUs'],
    largest_job_gpu_hours: ['Largest single job', 'GPU-hours'],
    longest_job_hours: ['Longest running job', 'hours'],
    max_nodes_in_job: ['Most nodes in one job', 'nodes'],
    busiest_day_gpu_hours: ['Busiest day', 'GPU-hours'],
    most_jobs_in_a_day: ['Most jobs in a day', 'jobs'],
    most_users_in_a_day: ['Most researchers in a day', 'people']
  };

  function recordWall(id) {
    var el = document.getElementById(id);
    if (!el) return;
    load('records').then(function (records) {
      if (!records || !records.available || !records.entries.length) {
        el.innerHTML =
          '<div class="data-state">No records have been computed yet.</div>';
        return;
      }
      var html = records.entries
        .map(function (entry) {
          var spec = RECORD_LABELS[entry.metric] || [entry.metric, ''];
          var when = entry.date
            ? new Date(entry.date + 'T00:00:00Z').toLocaleDateString('en-US', {
                year: 'numeric', month: 'long', day: 'numeric', timeZone: 'UTC'
              })
            : '';
          return (
            '<div class="record-card">' +
            '<div class="record-card__value">' + fmtNumber(entry.value, entry.value % 1 ? 1 : 0) +
            '</div>' +
            '<div class="record-card__label">' + spec[0] +
            (spec[1] ? ' <span style="color:var(--ci-muted)">(' + spec[1] + ')</span>' : '') +
            '</div>' +
            (when ? '<div class="record-card__when">' + when + '</div>' : '') +
            '</div>'
          );
        })
        .join('');
      el.innerHTML = html;
    });
  }

  function recordTotals(id) {
    var el = document.getElementById(id);
    if (!el) return;
    load('records').then(function (records) {
      if (!records || !records.available) return;
      var rows = [
        ['First day on record', records.first_day],
        ['Days observed', fmtNumber(records.days_observed)],
        ['Total GPU-hours delivered', fmtNumber(records.total_gpu_hours)],
        ['Total GPU-years delivered', fmtNumber(records.total_gpu_years, 1)],
        ['Total CPU-hours delivered', fmtNumber(records.total_cpu_hours)],
        ['Total jobs run', fmtNumber(records.total_jobs)]
      ];
      if (records.researchers_all_time) {
        rows.push(['Researchers, all time', fmtNumber(records.researchers_all_time)]);
      }
      el.innerHTML =
        '<table class="impact-table"><tbody>' +
        rows
          .map(function (r) {
            return '<tr><td>' + r[0] + '</td><td class="num">' + r[1] + '</td></tr>';
          })
          .join('') +
        '</tbody></table>';
    });
  }

  // --------------------------------------------------------------- pricing

  function pricingTable(id) {
    var el = document.getElementById(id);
    if (!el) return;
    load('pricing').then(function (pricing) {
      if (!pricing || !pricing.available) {
        el.innerHTML =
          '<div class="data-state"><span class="data-state__title">' +
          'Cost avoidance is not published yet</span>' +
          'A dollar figure is only shown once the price table has a named ' +
          'source and an as-of date recorded alongside it. Until then this ' +
          'site reports GPU-hours and lets you apply your own rate.</div>';
        return;
      }
      var models = Object.keys(pricing.usd_per_gpu_hour || {});
      el.innerHTML =
        '<table class="impact-table"><thead><tr>' +
        '<th>GPU</th><th class="num">Rate (USD / GPU-hour)</th>' +
        '</tr></thead><tbody>' +
        models
          .map(function (m) {
            var rate = pricing.usd_per_gpu_hour[m];
            return (
              '<tr><td>' + m.toUpperCase() + '</td><td class="num">' +
              (rate === null || rate === undefined ? '—' : '$' + Number(rate).toFixed(2)) +
              '</td></tr>'
            );
          })
          .join('') +
        '</tbody></table>' +
        '<p class="methodology-note">Basis: ' + (pricing.basis || 'unspecified') +
        '. Source: <a href="' + pricing.source + '" rel="nofollow noopener">' +
        pricing.source + '</a>, retrieved ' + pricing.asof + '.</p>';
    });
  }

  function costByPeriod(id) {
    load('rollups/yearly').then(function (rollup) {
      if (!rollup || !rollup.periods) return unavailable(document.getElementById(id));
      var periods = rollup.periods.filter(function (p) {
        return p.cloud_cost_avoided_usd !== undefined && p.cloud_cost_avoided_usd !== null;
      });
      if (!periods.length) {
        return unavailable(
          document.getElementById(id),
          'Cost avoidance is not published until the price table is sourced and dated.'
        );
      }
      mount(id, function () {
        var opt = baseOption({ legend: false, exportName: 'cost-avoided' });
        opt.xAxis = categoryAxis(periods.map(function (p) { return p.period; }));
        opt.yAxis = valueAxis({
          name: 'USD',
          formatter: function (v) { return '$' + fmtCompact(v); }
        });
        opt.tooltip.valueFormatter = function (v) { return '$' + fmtNumber(v); };
        opt.series = [
          {
            type: 'bar',
            barMaxWidth: 56,
            color: PALETTE[0],
            data: periods.map(function (p) { return p.cloud_cost_avoided_usd; })
          }
        ];
        return opt;
      });
    });
  }

  // ------------------------------------------------------------- freshness

  function freshness(selector) {
    var el = document.querySelector(selector || '#freshness');
    if (!el) return;
    load('health').then(function (health) {
      if (!health || !health.last_run) {
        el.className = 'freshness freshness--unknown';
        el.textContent = 'Data freshness unknown';
        return;
      }
      var last = new Date(health.last_run);
      var hours = (Date.now() - last.getTime()) / 3600000;
      var stale = hours > 36;
      el.className = 'freshness' + (stale ? ' freshness--stale' : '');
      el.textContent =
        'Data as of ' +
        last.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' }) +
        (stale ? ' — update overdue' : '');
    });
  }

  global.Impact = {
    load: load,
    loadDays: loadDays,
    mount: mount,
    palette: PALETTE,
    fmtNumber: fmtNumber,
    fmtPercent: fmtPercent,
    fmtCompact: fmtCompact,
    fmtBytes: fmtBytes,
    fmtDuration: fmtDuration,
    utilizationTrend: utilizationTrend,
    utilizationRate: utilizationRate,
    stackedByKey: stackedByKey,
    activeUsers: activeUsers,
    monthlyUniqueUsers: monthlyUniqueUsers,
    newUsers: newUsers,
    waitPercentiles: waitPercentiles,
    jobOutcomes: jobOutcomes,
    jobSizes: jobSizes,
    hourHeatmap: hourHeatmap,
    groupBreakdown: groupBreakdown,
    storageChart: storageChart,
    storageIo: storageIo,
    gpuMix: gpuMix,
    recordWall: recordWall,
    recordTotals: recordTotals,
    pricingTable: pricingTable,
    costByPeriod: costByPeriod,
    freshness: freshness
  };
})(window);

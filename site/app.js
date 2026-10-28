(() => {
  const HZ = ["short", "current_q", "next_q"];
  const HZ_SHORT = { short: "短期", current_q: "本季度", next_q: "下季度" };
  const GROUPS = ["technical", "macro", "sentiment", "options", "valuation", "event"];
  const ZONES = [
    { from: 25, to: 100, label: "看多", color: "#ff4d4f" },
    { from: 10, to: 25, label: "偏多", color: "#ff8a80" },
    { from: -10, to: 10, label: "中性", color: "#8c97ad" },
    { from: -25, to: -10, label: "偏空", color: "#5cd6a0" },
    { from: -100, to: -25, label: "看空", color: "#13c27a" },
  ];
  const C = { up: "#ff4d4f", down: "#13c27a", muted: "#7d8aa5", line: "#243049", text: "#d6deeb", accent: "#f0b429" };
  const app = document.getElementById("app");
  const state = { summary: null, cache: {}, hz: "current_q", charts: [] };

  const fmt = (v, d = 2) => (v == null || Number.isNaN(v) ? "-" : Number(v).toLocaleString("zh-CN", { minimumFractionDigits: d, maximumFractionDigits: d }));
  const pct = (v) => (v == null ? "-" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`);
  const sgn = (v) => (v == null ? "" : v >= 0 ? "up" : "down");
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const scoreColor = (s) => {
    if (s == null) return "transparent";
    const a = Math.min(Math.abs(s) / 70, 1) * 0.55 + 0.06;
    return s >= 0 ? `rgba(255,77,79,${a})` : `rgba(19,194,122,${a})`;
  };
  const clsOf = (s) => {
    for (const l of state.summary.labels) if (s >= l.min) return l.cls;
    return "bear2";
  };
  const bar = (s) => {
    if (s == null) return '<span class="muted">-</span>';
    const w = Math.min(Math.abs(s), 100) / 2;
    const left = s >= 0 ? 50 : 50 - w;
    return `<div class="bar"><i style="left:${left}%;width:${w}%;background:${s >= 0 ? C.up : C.down}"></i></div>`;
  };

  async function getJSON(path) {
    if (state.cache[path]) return state.cache[path];
    const r = await fetch(`${path}?v=${state.summary?.generated_at ?? Date.now()}`);
    if (!r.ok) throw new Error(`${path} ${r.status}`);
    return (state.cache[path] = await r.json());
  }

  function disposeCharts() {
    state.charts.forEach((c) => c.dispose());
    state.charts = [];
  }
  function chart(el) {
    const c = echarts.init(el, null, { renderer: "canvas" });
    state.charts.push(c);
    return c;
  }
  window.addEventListener("resize", () => state.charts.forEach((c) => c.resize()));

  function setNav(route) {
    document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.route === route));
  }

  function renderMeta() {
    const s = state.summary;
    const bad = s.status.filter((x) => !x.ok);
    document.getElementById("meta").innerHTML = `
      <span>数据更新：<b class="num">${s.generated_at}</b>（北京时间）</span>
      <span class="status-link" title="${esc(bad.map((b) => `${b.name}: ${b.error || ""}`).join("\n"))}">
        <span class="dot ${bad.length ? "warn" : "ok"}"></span>数据源 ${s.status.length - bad.length}/${s.status.length} 正常</span>`;
  }

  function hzSeg(onChange) {
    const el = document.createElement("div");
    el.className = "seg";
    el.innerHTML = HZ.map((h) => `<button data-h="${h}" class="${h === state.hz ? "on" : ""}">${state.summary.horizons[h].name}</button>`).join("");
    el.addEventListener("click", (e) => {
      const h = e.target.dataset.h;
      if (!h) return;
      state.hz = h;
      el.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.h === h));
      onChange(h);
    });
    return el;
  }

  // ---------------- 总览 ----------------
  function renderHome() {
    setNav("home");
    const s = state.summary;
    const upcoming = s.events.filter((e) => e.date >= s.today).slice(0, 10);
    app.innerHTML = `
      <div id="stkStrip"></div>
      <section class="hero">
        <div class="hero-head">
          <div><h2>各指数多空结论</h2>
            <div class="note">基于各指数最新收盘数据 · 每个交易日收盘后自动刷新 · 点击任一行查看详情</div></div>
          ${zoneLegend()}
        </div>
        ${heroHTML()}
      </section>
      <div class="section-title">维度得分热力图 <span id="segHost"></span></div>
      <div class="panel" style="padding:4px 8px;overflow-x:auto"><table id="heat"></table></div>
      <div class="grid2" style="margin-top:14px">
        <div class="panel"><div class="section-title" style="margin-top:0">多空分布 <span class="sub" id="distSub"></span></div>
          ${zoneLegend()}<div id="dist" style="height:${s.indices.length * 44 + 60}px;margin-top:8px"></div></div>
        <div class="panel"><div class="section-title" style="margin-top:0">近期重要事件 <a class="sub" href="#/events">全部 →</a></div>
          <div class="ev-list">${upcoming.map(evHTML).join("")}</div></div>
      </div>
      <div class="section-title">行情概览</div>
      <div class="cards">${s.indices.map(cardHTML).join("")}</div>`;
    document.querySelectorAll(".hero-row").forEach((el) => el.addEventListener("click", () => (location.hash = `#/index/${el.dataset.id}`)));
    document.getElementById("segHost").appendChild(hzSeg(() => { renderHeat(); renderDist(); }));
    s.indices.forEach((it) => {
      const el = document.getElementById(`spark-${it.id}`);
      const up = it.spark[it.spark.length - 1] >= it.spark[0];
      chart(el).setOption({
        grid: { left: 0, right: 0, top: 2, bottom: 2 },
        xAxis: { type: "category", show: false, data: it.spark.map((_, i) => i) },
        yAxis: { type: "value", show: false, scale: true },
        series: [{ type: "line", data: it.spark, symbol: "none", lineStyle: { width: 1.5, color: up ? C.up : C.down },
          areaStyle: { color: up ? "rgba(255,77,79,.10)" : "rgba(19,194,122,.10)" } }],
      });
    });
    document.querySelectorAll(".card").forEach((el) => el.addEventListener("click", () => (location.hash = `#/index/${el.dataset.id}`)));
    renderHeat();
    renderDist();
    homeStockStrip();
  }

  function cardHTML(it) {
    const st = it.stats;
    return `<div class="card" data-id="${it.id}">
      <div class="card-head">
        <div><span class="card-name">${esc(it.name)}</span><span class="tag">${it.market === "CN" ? "A股" : "美股"}</span></div>
        <div><span class="price num">${fmt(st.close)}</span><span class="chg num ${sgn(st.chg1d)}">${pct(st.chg1d)}</span></div>
      </div>
      <div class="note">${st.date}${st.stale ? ' <span class="imp-high">数据未更新</span>' : ""} · 近20日 <span class="${sgn(st.chg20d)}">${pct(st.chg20d)}</span> · 年初至今 <span class="${sgn(st.chg_ytd)}">${pct(st.chg_ytd)}</span></div>
      <div class="spark" id="spark-${it.id}"></div>
      <div class="pills">${HZ.map((h) => {
        const v = it.horizons[h];
        return `<div class="pill ${v.cls}"><div class="h">${HZ_SHORT[h]}</div>
          <div class="v">${v.label} <span class="num">${v.score > 0 ? "+" : ""}${v.score.toFixed(0)}</span></div>
          <div class="c">置信度 ${v.confidence}%</div></div>`;
      }).join("")}</div>
    </div>`;
  }

  function zoneLegend() {
    const range = (z) => (z.from === -100 ? `≤ ${z.to}` : z.to === 100 ? `≥ ${z.from}` : `${z.from} ~ ${z.to}`);
    return `<div class="zone-legend">${[...ZONES].reverse().map((z) =>
      `<span><i style="background:${z.color}"></i><b style="color:${z.color}">${z.label}</b><em class="num">${range(z)}</em></span>`).join("")}</div>`;
  }

  function tally(items, h) {
    const cnt = {};
    items.forEach((it) => (cnt[it.horizons[h].label] = (cnt[it.horizons[h].label] || 0) + 1));
    return ZONES.filter((z) => cnt[z.label]).map((z) => `<b style="color:${z.color}">${z.label} ${cnt[z.label]}</b>`).join("　");
  }

  function heroHTML() {
    const s = state.summary;
    const head = `<div class="hero-row hero-colhead"><div></div>${HZ.map((h) =>
      `<div>${s.horizons[h].name}<div class="note num">${s.horizons[h].window[0]} ~ ${s.horizons[h].window[1]}</div></div>`).join("")}</div>`;
    const body = [["CN", "A股"], ["US", "美股"]].map(([m, label]) => {
      const items = s.indices.filter((i) => i.market === m);
      if (!items.length) return "";
      return `<div class="hero-row hero-mkt"><div>${label}</div>${HZ.map((h) => `<div>${tally(items, h)}</div>`).join("")}</div>` +
        items.map((it) => {
          const st = it.stats;
          return `<div class="hero-row hero-item" data-id="${it.id}">
            <div class="hero-name"><b>${esc(it.name)}</b>
              <div><span class="num">${fmt(st.close)}</span> <span class="num ${sgn(st.chg1d)}">${pct(st.chg1d)}</span></div>
              <div class="note">收盘 ${st.date}${st.stale ? ' <span class="imp-high">未更新</span>' : ""}</div></div>
            ${HZ.map((h) => {
              const v = it.horizons[h];
              return `<div class="vcell ${v.cls}">
                <div class="big">${v.label}</div>
                <div class="vmeta"><span class="num vscore">${v.score > 0 ? "+" : ""}${v.score.toFixed(0)}</span>
                  <span class="conf" title="置信度"><i style="width:${v.confidence}%"></i></span><span class="note num">${v.confidence}%</span></div>
              </div>`;
            }).join("")}
          </div>`;
        }).join("");
    }).join("");
    return `<div class="hero-table">${head}${body}</div>
      <div class="note" style="margin-top:8px">分数范围 -100 ~ +100；进度条为置信度，越长说明各维度信号越一致。</div>`;
  }

  function renderHeat() {
    const s = state.summary;
    const h = state.hz;
    const w = s.horizons[h].weights;
    const rows = [...s.indices].sort((a, b) => b.horizons[h].score - a.horizons[h].score);
    document.getElementById("heat").innerHTML = `
      <thead><tr><th>指数</th><th style="text-align:center">综合得分</th><th>结论</th><th style="text-align:center">置信度</th>
        ${GROUPS.map((g) => `<th style="text-align:center">${s.group_names[g]}<br><span class="muted">权重 ${Math.round((w[g] || 0) * 100)}%</span></th>`).join("")}</tr></thead>
      <tbody>${rows.map((it) => {
        const v = it.horizons[h];
        return `<tr class="click" onclick="location.hash='#/index/${it.id}'">
          <td><b>${esc(it.name)}</b></td>
          <td class="heat" style="background:${scoreColor(v.score)}">${v.score.toFixed(1)}</td>
          <td><span class="badge ${v.cls}">${v.label}</span></td>
          <td class="heat">${v.confidence}%</td>
          ${GROUPS.map((g) => `<td class="heat" style="background:${scoreColor(v.groups[g])}">${v.groups[g] == null ? '<span class="muted">-</span>' : v.groups[g].toFixed(0)}</td>`).join("")}
        </tr>`;
      }).join("")}</tbody>`;
  }

  function renderDist() {
    const s = state.summary;
    const el = document.getElementById("dist");
    const old = state.charts.find((c) => c.getDom() === el);
    if (old) { old.dispose(); state.charts = state.charts.filter((c) => c !== old); }
    const h = state.hz;
    document.getElementById("distSub").textContent = s.horizons[h].name;
    const rows = [...s.indices].sort((a, b) => a.horizons[h].score - b.horizons[h].score);
    const zoneColor = (v) => ZONES.find((z) => v >= z.from).color;
    chart(el).setOption({
      grid: { left: 96, right: 24, top: 28, bottom: 28 },
      xAxis: { type: "value", min: -100, max: 100, interval: 25, splitLine: { show: false },
        axisLabel: { color: C.muted, fontSize: 12 }, axisLine: { show: true, lineStyle: { color: C.line } } },
      yAxis: { type: "category", data: rows.map((r) => r.name), axisTick: { show: false },
        axisLabel: { color: C.text, fontSize: 13, fontWeight: 600 }, axisLine: { lineStyle: { color: C.line } } },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, backgroundColor: "#121826", borderColor: C.line, textStyle: { color: C.text },
        formatter: (p) => { const r = rows[p[0].dataIndex].horizons[h]; return `${p[0].name}<br>${r.label} ${r.score.toFixed(1)} · 置信度 ${r.confidence}%`; } },
      series: [{
        type: "bar", barWidth: 18,
        data: rows.map((r) => ({ value: r.horizons[h].score, itemStyle: { color: zoneColor(r.horizons[h].score), borderRadius: 3 } })),
        label: { show: true, fontSize: 13, fontWeight: 700, color: C.text,
          position: "right", formatter: (p) => `${p.value > 0 ? "+" : ""}${p.value.toFixed(0)} ${rows[p.dataIndex].horizons[h].label}` },
        labelLayout: (p) => {
          if (rows[p.dataIndex].horizons[h].score >= 0) return {};
          return p.rect.x - 72 < 96 ? { x: p.rect.x + p.rect.width + 6, align: "left" } : { x: p.rect.x - 6, align: "right" };
        },
        markArea: { silent: true, data: ZONES.map((z) => [
          { xAxis: z.from, itemStyle: { color: z.color, opacity: 0.07 },
            label: { show: true, position: "insideTop", distance: -20, color: z.color, fontSize: 12, fontWeight: 700, formatter: z.label } },
          { xAxis: z.to }]) },
        markLine: { silent: true, symbol: "none", label: { show: false }, lineStyle: { color: "#3a4a6b", type: "dashed" },
          data: [{ xAxis: -25 }, { xAxis: -10 }, { xAxis: 10 }, { xAxis: 25 }] },
      }],
    });
  }

  function evHTML(e) {
    const past = e.date < state.summary.today;
    return `<div class="ev ${past ? "past" : ""}">
      <span class="num">${e.date.slice(5)}${e.confirmed ? "" : '<span class="muted">*</span>'}</span>
      <span class="mk">${{ ALL: "全球", CN: "中国", US: "美国" }[e.market]}</span>
      <span class="${e.importance === "high" ? "imp-high" : ""}">${esc(e.title)}${e.note ? ` <span class="note">${esc(e.note)}</span>` : ""}</span>
      <span class="note">${e.bias != null ? `影响 ${e.bias > 0 ? "+" : ""}${e.bias}` : e.importance === "high" ? "重要" : ""}</span>
    </div>`;
  }

  // ---------------- 指数详情 ----------------
  async function renderIndex(id) {
    setNav("home");
    app.innerHTML = '<div class="loading">加载中…</div>';
    const d = await getJSON(`data/index_${id}.json`);
    const st = d.stats;
    app.innerHTML = `
      <div class="detail-head">
        <div><a class="note" href="#/">← 返回总览</a><h1>${esc(d.name)} <span class="tag">${d.symbol}</span></h1></div>
        <div class="kv"><span class="k">最新收盘（${st.date}）</span><span class="v num">${fmt(st.close)}</span></div>
        ${[["日涨跌", st.chg1d], ["近5日", st.chg5d], ["近20日", st.chg20d], ["年初至今", st.chg_ytd]]
          .map(([k, v]) => `<div class="kv"><span class="k">${k}</span><span class="v num ${sgn(v)}">${pct(v)}</span></div>`).join("")}
        <div class="kv"><span class="k">52周区间</span><span class="v num">${fmt(st.low_52w, 0)} – ${fmt(st.high_52w, 0)}</span></div>
      </div>
      <div class="section-title">三个周期的结论 <span class="sub">点击切换下方明细</span></div>
      <div class="verdicts" id="verdicts"></div>
      <div class="section-title">行情与技术面得分走势 <span class="sub">下方曲线为当前周期的技术面得分（-100~100）</span></div>
      <div class="panel"><div id="kline" class="chart-big"></div></div>
      <div class="grid2" style="margin-top:14px">
        <div class="panel" id="signals"></div>
        <div>
          <div class="panel" id="backtest"></div>
          <div class="panel" id="hzEvents" style="margin-top:14px"></div>
        </div>
      </div>`;
    const draw = () => { drawVerdicts(d); drawKline(d); drawSignals(d); drawBacktest(d); drawHzEvents(d); };
    draw();
    document.getElementById("verdicts").addEventListener("click", (e) => {
      const el = e.target.closest(".verdict");
      if (!el) return;
      state.hz = el.dataset.h;
      disposeCharts();
      draw();
    });
  }

  function drawVerdicts(d) {
    const names = state.summary.group_names;
    document.getElementById("verdicts").innerHTML = HZ.map((h) => {
      const v = d.horizons[h];
      const contrib = Object.entries(v.weights).map(([g, w]) => [g, v.groups[g] * w]);
      return `<div class="panel verdict ${v.cls} ${h === state.hz ? "sel" : ""}" data-h="${h}">
        <div class="row" style="justify-content:space-between">
          <div><div style="font-weight:600">${v.name}</div><div class="note num">${v.window[0]} ~ ${v.window[1]}</div></div>
          <span class="badge">${v.label}</span>
        </div>
        <div class="row" style="justify-content:space-between;margin-top:6px">
          <span class="score">${v.score > 0 ? "+" : ""}${v.score.toFixed(1)}</span>
          <div style="text-align:right"><div class="note">置信度</div><div class="num" style="font-size:20px;font-weight:700">${v.confidence}%</div></div>
        </div>
        <div class="gauge"><i style="left:${(v.score + 100) / 2}%"></i></div>
        <div class="contrib">${contrib.map(([g, c]) => `<span class="muted">${names[g]}</span>${bar(c * 2)}<span class="num ${sgn(c)}" style="text-align:right">${c >= 0 ? "+" : ""}${c.toFixed(1)}</span>`).join("")}</div>
        <div class="note" style="margin-top:8px">各维度对总分的加权贡献 · 信号一致度 ${v.agreement}%${v.event_penalty ? ` · 重大事件扣减置信度 ${v.event_penalty}` : ""}</div>
      </div>`;
    }).join("");
  }

  function drawKline(d) {
    const ch = d.chart;
    const key = { short: "tech_short", current_q: "tech_cq", next_q: "tech_nq" }[state.hz];
    const start = Math.max(0, 100 - (250 / ch.date.length) * 100);
    const line = (name, data, color, extra = {}) => ({ name, type: "line", data, symbol: "none", itemStyle: { color }, lineStyle: { width: 1, color, ...extra }, xAxisIndex: 0, yAxisIndex: 0 });
    chart(document.getElementById("kline")).setOption({
      animation: false,
      legend: { top: 0, textStyle: { color: C.muted }, data: ["K线", "MA20", "MA60", "MA250", "布林上轨", "布林下轨"] },
      tooltip: { trigger: "axis", axisPointer: { type: "cross" }, backgroundColor: "#121826", borderColor: C.line, textStyle: { color: C.text } },
      axisPointer: { link: [{ xAxisIndex: "all" }] },
      grid: [{ left: 60, right: 20, top: 30, height: "52%" }, { left: 60, right: 20, top: "64%", height: "10%" }, { left: 60, right: 20, top: "77%", height: "15%" }],
      xAxis: [0, 1, 2].map((i) => ({ type: "category", data: ch.date, gridIndex: i, boundaryGap: true, axisLine: { lineStyle: { color: C.line } },
        axisLabel: { show: i === 2, color: C.muted }, axisTick: { show: false } })),
      yAxis: [
        { scale: true, gridIndex: 0, splitLine: { lineStyle: { color: C.line } }, axisLabel: { color: C.muted } },
        { scale: true, gridIndex: 1, splitNumber: 2, axisLabel: { show: false }, splitLine: { show: false } },
        { min: -100, max: 100, gridIndex: 2, splitNumber: 2, splitLine: { lineStyle: { color: C.line } }, axisLabel: { color: C.muted } },
      ],
      dataZoom: [{ type: "inside", xAxisIndex: [0, 1, 2], start, end: 100 },
        { type: "slider", xAxisIndex: [0, 1, 2], start, end: 100, bottom: 4, height: 16, borderColor: C.line, textStyle: { color: C.muted } }],
      series: [
        { name: "K线", type: "candlestick", data: ch.ohlc, itemStyle: { color: C.up, color0: C.down, borderColor: C.up, borderColor0: C.down } },
        line("MA20", ch.ma20, "#f0b429"), line("MA60", ch.ma60, "#4ea8ff"), line("MA250", ch.ma250, "#c77dff"),
        line("布林上轨", ch.boll_up, "#5b6b8c", { type: "dashed" }), line("布林下轨", ch.boll_dn, "#5b6b8c", { type: "dashed" }),
        { name: "成交量", type: "bar", xAxisIndex: 1, yAxisIndex: 1, data: ch.volume.map((v, i) => ({ value: v,
          itemStyle: { color: ch.ohlc[i][1] >= ch.ohlc[i][0] ? "rgba(255,77,79,.6)" : "rgba(19,194,122,.6)" } })) },
        { name: "技术面得分", type: "line", xAxisIndex: 2, yAxisIndex: 2, data: ch[key], symbol: "none", lineStyle: { width: 1.2, color: C.accent },
          areaStyle: { origin: 0, color: "rgba(240,180,41,.12)" },
          markLine: { silent: true, symbol: "none", lineStyle: { color: C.muted, type: "dashed" }, data: [{ yAxis: 0 }] } },
      ],
    });
  }

  function signalTable(sigs) {
    if (!sigs.length) return '<div class="note">暂无数据（未设置事件影响时，事件只用于调整置信度）</div>';
    return `<table><thead><tr><th>指标</th><th>数值</th><th>得分</th><th class="hide-sm">解读</th></tr></thead><tbody>
      ${sigs.map((x) => `<tr><td>${esc(x.name)}<div class="note num">${x.asof}</div></td><td class="num">${esc(x.value)}</td>
        <td><div class="row" style="gap:8px;flex-wrap:nowrap">${bar(x.score)}<span class="num ${sgn(x.score)}">${x.score == null ? "-" : x.score.toFixed(0)}</span></div></td>
        <td class="note hide-sm">${esc(x.note)}</td></tr>`).join("")}</tbody></table>`;
  }

  function drawSignals(d) {
    const v = d.horizons[state.hz];
    const names = state.summary.group_names;
    document.getElementById("signals").innerHTML = `<div class="section-title" style="margin-top:0">信号明细 · ${v.name}</div>` +
      GROUPS.map((g) => `<div class="group-title">${names[g]} <span class="note">维度得分 ${v.groups[g] == null ? "-" : v.groups[g].toFixed(1)} · 权重 ${Math.round((v.weights[g] || 0) * 100)}%</span></div>${signalTable(v.signals[g])}`).join("");
  }

  function drawBacktest(d) {
    const rows = HZ.map((h) => [h, d.backtests[h]]);
    document.getElementById("backtest").innerHTML = `
      <div class="section-title" style="margin-top:0">技术面信号历史检验 <span class="sub">近8年，仅检验技术面得分</span></div>
      <table><thead><tr><th>周期</th><th>持有期</th><th>看多后上涨概率</th><th>看空后下跌概率</th><th>基准上涨概率</th></tr></thead><tbody>
      ${rows.map(([h, b]) => `<tr><td>${HZ_SHORT[h]}</td><td class="num">${b.fwd_days}日</td>
        <td class="num">${b.bull_hit ?? "-"}%<div class="note">平均 ${b.bull_avg ?? "-"}%</div></td>
        <td class="num">${b.bear_hit ?? "-"}%<div class="note">平均 ${b.bear_avg ?? "-"}%</div></td>
        <td class="num">${b.base_up ?? "-"}%</td></tr>`).join("")}</tbody></table>
      <div class="note" style="margin-top:8px">看多/看空分别指技术面得分 ≥10 / ≤-10。上涨概率明显高于基准，说明该信号在这个指数上有效；接近基准则说明趋势信号区分度有限，需要更多参考宏观与估值。</div>`;
  }

  function drawHzEvents(d) {
    const v = d.horizons[state.hz];
    const evs = state.summary.events.filter((e) => (e.market === "ALL" || e.market === d.market) && e.date >= v.window[0] && e.date <= v.window[1]);
    document.getElementById("hzEvents").innerHTML = `<div class="section-title" style="margin-top:0">周期内事件 <span class="sub">${v.window[0]} ~ ${v.window[1]} · *为预计日期</span></div>
      <div class="ev-list">${evs.length ? evs.map(evHTML).join("") : '<div class="note">无</div>'}</div>`;
  }

  // ---------------- 宏观 ----------------
  async function renderMacro() {
    setNav("macro");
    app.innerHTML = '<div class="loading">加载中…</div>';
    const m = await getJSON("data/macro.json");
    const block = (title, mk) => `
      <div class="section-title">${title}</div>
      <div class="grid2">
        <div class="panel"><div class="group-title" style="margin-top:0">宏观信号（含油价）</div>${signalTable(m.signals[mk])}</div>
        <div>
          <div class="panel"><div class="group-title" style="margin-top:0">期权信号${mk === "CN" ? "（沪深300）" : "（标普500）"}</div>${signalTable(m.signals[mk + "_opt"] || [])}</div>
          <div class="panel" style="margin-top:14px"><div class="group-title" style="margin-top:0">情绪与资金信号</div>${signalTable(m.signals[mk + "_sent"])}</div>
        </div>
      </div>
      <div class="grid4" style="margin-top:14px">${Object.keys(m.charts[mk]).map((k, i) => `<div class="panel" style="padding:10px"><div class="note">${k}</div><div class="mini-chart" id="mc-${mk}-${i}"></div></div>`).join("")}</div>`;
    app.innerHTML = block("中国宏观", "CN") + block("美国宏观", "US");
    for (const mk of ["CN", "US"]) {
      Object.entries(m.charts[mk]).forEach(([k, pts], i) => {
        const up = pts.length > 1 && pts[pts.length - 1][1] >= pts[Math.max(0, pts.length - 13)][1];
        chart(document.getElementById(`mc-${mk}-${i}`)).setOption({
          grid: { left: 40, right: 8, top: 8, bottom: 22 },
          tooltip: { trigger: "axis", backgroundColor: "#121826", borderColor: C.line, textStyle: { color: C.text } },
          xAxis: { type: "time", axisLabel: { color: C.muted, fontSize: 10 }, axisLine: { lineStyle: { color: C.line } } },
          yAxis: { type: "value", scale: true, splitLine: { lineStyle: { color: C.line } }, axisLabel: { color: C.muted, fontSize: 10 } },
          series: [{ type: "line", data: pts, symbol: "none", lineStyle: { width: 1.3, color: up ? C.accent : "#4ea8ff" } }],
        });
      });
    }
  }

  // ---------------- 事件 ----------------
  function renderEvents() {
    setNav("events");
    const s = state.summary;
    let mk = "ALL";
    app.innerHTML = `<div class="section-title" style="margin-top:4px">宏观事件日历 <span class="sub">*为预计日期 · 自动生成的周期性事件日期为近似值 · 在 config/events.yaml 中维护</span></div>
      <div class="seg" id="mkSeg"><button data-m="ALL" class="on">全部</button><button data-m="CN">中国</button><button data-m="US">美国</button></div>
      <div id="evBody"></div>`;
    const draw = () => {
      const evs = s.events.filter((e) => mk === "ALL" || e.market === "ALL" || e.market === mk);
      const byMonth = {};
      evs.forEach((e) => (byMonth[e.date.slice(0, 7)] ??= []).push(e));
      document.getElementById("evBody").innerHTML = Object.entries(byMonth).map(([mo, list]) =>
        `<div class="section-title">${mo.replace("-", "年")}月</div><div class="panel ev-list">${list.map(evHTML).join("")}</div>`).join("");
    };
    document.getElementById("mkSeg").addEventListener("click", (e) => {
      if (!e.target.dataset.m) return;
      mk = e.target.dataset.m;
      document.querySelectorAll("#mkSeg button").forEach((b) => b.classList.toggle("on", b.dataset.m === mk));
      draw();
    });
    draw();
  }

  // ---------------- 方法 ----------------
  function renderMethod() {
    setNav("method");
    const s = state.summary;
    app.innerHTML = `<div class="panel method" style="max-width:960px;margin:0 auto">
      <h2 style="margin-top:0">方法说明</h2>
      <p>本仪表盘采用<b>透明的规则打分模型</b>：每个指标按规则映射为 -100（极度看空）到 +100（极度看多）的得分，同一维度内按指标权重平均，再按周期对五个维度加权得到综合得分。</p>
      <h3>周期权重</h3>
      <table><thead><tr><th>周期</th>${GROUPS.map((g) => `<th>${s.group_names[g]}</th>`).join("")}</tr></thead><tbody>
        ${HZ.map((h) => `<tr><td>${s.horizons[h].name}</td>${GROUPS.map((g) => `<td class="num">${Math.round((s.horizons[h].weights[g] || 0) * 100)}%</td>`).join("")}</tr>`).join("")}
      </tbody></table>
      <p class="note">某个维度没有可用数据时（例如未设置事件影响），其权重按比例分配给其他维度。</p>
      <h3>结论划分</h3>
      <p>${s.labels.map((l) => `<span class="badge ${l.cls}">${l.label}</span> ${l.min > -999 ? `≥ ${l.min}` : "其余"}`).join("　")}</p>
      <h3>各维度说明</h3>
      <ul>
        <li><b>技术面</b>：均线（20/60/120/250日，含偏离度与斜率）、均线排列、MACD、RSI、布林带、量价配合、动量、ADX。偏离度与动量按指数自身的历史波动率标准化，避免高波动指数被过度打分。短期侧重MACD、RSI与20日线，季度侧重60日线与均线排列，下季度侧重年线与120日动量。</li>
        <li><b>宏观面</b>：中国看PMI、PPI、CPI、M1-M2剪刀差、社融、10年国债收益率，以及美元与美债等外部因素；美国看联邦基金利率、CPI、萨姆规则失业率、10年美债、期限利差、金融条件指数NFCI、美元。两地都纳入WTI原油：近3月涨幅越大、价格分位越高，通胀和成本压力越大，得分越低；暴跌时视为需求走弱。</li>
        <li><b>情绪资金</b>：高收益债利差、两市融资余额变化、成交活跃度分位（极端过热时反向扣分），A股另参考VIX代表的全球风险偏好。</li>
        <li><b>期权</b>：隐含波动率（A股为QVIX，美股为VIX/VXN/VXD）的近3年分位与近1月变化，波动率处于极端高位时视为恐慌见底、反向加分；美股另看VIX期限结构（VIX/VIX3M，倒挂代表短期恐慌）、SKEW尾部风险，以及CBOE个股认沽认购比；A股看对应ETF期权的认沽认购比。认沽认购比为反向指标：偏高说明避险过度，偏低说明看涨过热。</li>
        <li><b>估值</b>：A股使用市盈率/市净率近10年分位和股债性价比分位；美股使用跟踪ETF的市盈率计算股债性价比，并辅以价格偏离3年均值的历史分位。</li>
        <li><b>事件</b>：周期内的重大事件会降低置信度。如在 <code>config/events.yaml</code> 中为事件填写 bias（影响方向），该判断会计入事件维度得分。</li>
      </ul>
      <h3>置信度</h3>
      <p>置信度 = 基础分 + 综合得分强度 + 各信号方向一致度 − 周期内重大事件扣减 − 数据过期扣减，范围 15%～90%。置信度低说明各维度信号互相矛盾，结论参考价值有限。</p>
      <div class="warn-box">注意：北向资金自2024年8月起不再披露每日净买入，故改用融资余额与成交活跃度衡量资金面。美股估值目前只有当前市盈率，历史分位会随每日更新逐渐积累。模型输出是对当前信号状态的汇总，不是收益预测，也不构成投资建议。</div>
      <h3>扩展指数</h3>
      <p>在 <code>config/indices.yaml</code> 中新增一项（代码、名称、市场、数据源、估值来源），下次自动更新时会出现在页面上。</p>
    </div>`;
  }

  // ---------------- 个股计划 ----------------
  const REPO = "https://github.com/chenzhi123/market-trend-dashboard";
  const ST_COLOR = { below_plan: "#c77dff", deep: "#e0457b", add: "#ff4d4f", buy: "#ff7a45", starter: "#f0b429",
    near: "#4ea8ff", watch: "#8c97ad", reassess: "#5cd6a0", trim: "#13c27a", nodata: "#5b6b8c" };
  const ZONE_COLOR = { starter: "#f0b429", buy: "#ff7a45", add: "#ff4d4f", deep: "#e0457b", reassess: "#5cd6a0", trim: "#13c27a" };
  const ST_ORDER = ["below_plan", "deep", "add", "buy", "starter", "near", "watch", "reassess", "trim", "nodata"];
  const BUY_T = ["starter", "buy", "add", "deep"];
  const TG = [["bear", "悲观"], ["base", "中性"], ["bull", "乐观"]];
  const sk = { dim: null, sort: "status", q: "", only: false };

  async function getStocks(force = false) {
    const key = "data/stocks.json";
    if (state.cache[key] && !force) return state.cache[key];
    const r = await fetch(`${key}?t=${Date.now()}`);
    if (!r.ok) throw new Error(`${key} ${r.status}`);
    return (state.cache[key] = await r.json());
  }

  const num = (v) => (v == null ? "-" : Number(v).toLocaleString("zh-CN", { maximumFractionDigits: 2 }));
  const cur = (s) => (s.currency === "HKD" ? "HK$" : "$");
  const zr = (z) => (z.low != null && z.high != null ? `${num(z.low)}–${num(z.high)}` : z.low != null ? `≥ ${num(z.low)}` : `≤ ${num(z.high)}`);
  const daysSince = (d, today) => (d ? (new Date(today) - new Date(d)) / 864e5 : Infinity);
  const isNew = (s, d) => s.status.level !== "none" && daysSince(s.status.since, d.generated_at.slice(0, 10)) <= 3;
  const sBadge = (s, d) => `<span class="sbadge" style="--c:${ST_COLOR[s.status.key]}">${s.status.label}</span>${d && isNew(s, d) ? '<span class="new">新</span>' : ""}`;
  const topBuy = (s) => s.zones.filter((z) => BUY_T.includes(z.type)).sort((a, b) => b.high - a.high)[0];
  const byStatus = (a, b) => ST_ORDER.indexOf(a.status.key) - ST_ORDER.indexOf(b.status.key) || (a.metrics.dist_to_buy ?? 1e9) - (b.metrics.dist_to_buy ?? 1e9);

  function planText(s) {
    const st = s.status, z = st.zone;
    if (st.key === "below_plan") return `已低于计划最低一档（${zr(z)}），先复核基本面再决定是否继续买入`;
    if (st.key === "near") return `距第一档 ${zr(z)} 还差 ${((1 - z.high / s.price.last) * 100).toFixed(1)}%：${z.action}`;
    if (!z) return "";
    return `${z.name} ${zr(z)}${z.size ? ` · 仓位 ${z.size}` : ""} · ${z.action}`;
  }

  function ladderHTML(s, big = false) {
    const p = s.price?.last, t = s.targets || {};
    const vals = [p, t.bear, t.base, ...s.zones.flatMap((z) => [z.low, z.high])].filter((v) => v != null);
    let lo = Math.min(...vals), hi = Math.max(...vals);
    if (t.bull != null && t.bull <= hi * 1.3) hi = Math.max(hi, t.bull);
    const pad = (hi - lo) * 0.05 || 1;
    lo -= pad; hi += pad;
    const x = (v) => ((v - lo) / (hi - lo)) * 100;
    const segs = s.zones.map((z) => {
      const a = z.low ?? lo, b = z.high ?? hi;
      return `<i class="lz" style="left:${x(a)}%;width:${Math.max(x(b) - x(a), 0.8)}%;background:${ZONE_COLOR[z.type]}" title="${z.name} ${zr(z)}"></i>`;
    }).join("");
    const ticks = TG.filter(([k]) => t[k] != null && t[k] >= lo && t[k] <= hi)
      .map(([k, n]) => `<b class="lt" style="left:${x(t[k])}%" title="${n} ${num(t[k])}"><em>${n}</em></b>`).join("");
    const mark = p != null ? `<span class="lp" style="left:${x(p)}%"><em class="num">${num(p)}</em></span>` : "";
    return `<div class="ladder ${big ? "big" : ""}"><div class="track">${segs}${ticks}${mark}</div></div>`;
  }

  function stockCard(s, d) {
    const p = s.price || {}, t = s.targets, m = s.metrics;
    const tb = topBuy(s);
    const foot = s.status.zone || s.status.key === "near" ? planText(s)
      : tb && p.last ? `距第一档 ${zr(tb)} 还差 ${((1 - tb.high / p.last) * 100).toFixed(1)}%` : "";
    return `<div class="scard" data-t="${s.ticker}" style="--c:${ST_COLOR[s.status.key]}">
      <div class="card-head">
        <div><span class="card-name">${esc(s.name)}</span><span class="tag">${s.symbol}</span><span class="tag">${esc(s.tags.industry)}</span></div>
        <div>${sBadge(s, d)}</div>
      </div>
      <div class="row" style="gap:10px;align-items:baseline;margin-top:2px">
        <span class="price num">${cur(s)}${num(p.last)}</span><span class="chg num ${sgn(p.chg1d)}">${pct(p.chg1d)}</span>
        <span class="note">${p.date ?? ""}${p.stale ? ' <span class="imp-high">未更新</span>' : ""}</span>
      </div>
      ${ladderHTML(s)}
      ${t ? `<div class="tg3">${TG.map(([k, n]) => `<div><div class="note">${n}${k === "base" ? ` · ${s.target_year}年底` : ""}</div>
        <div class="num tv">${num(t[k])}</div><div class="num ${sgn(m["upside_" + k])}" style="font-size:12px">${pct(m["upside_" + k])}</div></div>`).join("")}</div>`
        : '<div class="note" style="margin:6px 0">ETF：没有目标价，按回撤预算分批建仓</div>'}
      <div class="sfoot">${esc(foot)}</div>
    </div>`;
  }

  function alertRow(s, d) {
    const p = s.price, t = s.targets;
    const guards = s.guards_hit.map((g) => `<div class="imp-high" style="font-size:12px">⚠ ${esc(g.note)}</div>`).join("");
    return `<div class="arow" data-t="${s.ticker}" style="--c:${ST_COLOR[s.status.key]}">
      <div><b>${esc(s.name)}</b> <span class="tag">${s.symbol}</span></div>
      <div class="num">${cur(s)}${num(p.last)} <span class="${sgn(p.chg1d)}" style="font-size:12px">${pct(p.chg1d)}</span></div>
      <div>${sBadge(s, d)}</div>
      <div class="a-plan">${esc(planText(s))}${guards}</div>
      <div class="note num">${t ? `中性 ${num(t.base)}（${pct(s.metrics.upside_base)}）` : "ETF"}</div>
    </div>`;
  }

  async function renderStocks(force = false) {
    setNav("stocks");
    if (!state.cache["data/stocks.json"]) app.innerHTML = '<div class="loading">加载中…</div>';
    const d = await getStocks(force);
    const dims = d.categories.dimensions;
    sk.dim ??= d.categories.default;
    const L = (lv) => d.stocks.filter((s) => s.status.level === lv).sort(byStatus);
    const [buy, near, sell] = [L("alert"), L("near"), L("sell")];
    const sub = d.substack;
    app.innerHTML = `
      <div class="detail-head" style="align-items:center">
        <div><h1>个股计划看板</h1>
          <div class="note">来源 <a class="link" href="${sub.url}" target="_blank">Substack · Zane说美股</a>（${sub.count} 篇）· 价格更新 ${d.generated_at}（北京时间）· 状态按收盘价判定</div></div>
        <div class="row" style="margin-left:auto;gap:8px">
          <button class="btn" id="refresh">刷新数据</button>
          <a class="btn" href="${REPO}/actions/workflows/update.yml" target="_blank" title="在 GitHub Actions 中手动运行一次，约 3 分钟后刷新页面">立即抓价 ↗</a>
        </div>
      </div>
      ${sub.pending.length ? `<div class="warn-box">Substack 有 <b>${sub.pending.length}</b> 篇新帖子尚未录入计划：
        ${sub.pending.map((p) => `<a class="link" href="${p.url}" target="_blank">${p.date} ${esc(p.title)}</a>`).join("；")}
        <div class="note">在 Cursor 中说「更新个股」即可提取并录入。</div></div>` : ""}
      ${sub.ok ? "" : `<div class="note" title="${esc(sub.error)}">云端无法访问 Substack，「待录入」以上次在本机同步的结果为准；发新帖后在 Cursor 中说「更新个股」即可。</div>`}
      <div class="section-title">已进入买入 / 加仓区间 <span class="sub">${buy.length} 只 · 「新」表示 3 天内新进入该状态</span></div>
      <div class="panel alerts">${buy.length ? buy.map((s) => alertRow(s, d)).join("") : '<div class="note">暂无</div>'}</div>
      <div class="grid2" style="margin-top:14px">
        <div class="panel"><div class="group-title" style="margin-top:0;color:${ST_COLOR.near}">接近买入区（距第一档 ≤ ${d.near_pct}%）</div>
          <div class="alerts compact">${near.length ? near.map((s) => alertRow(s, d)).join("") : '<div class="note">暂无</div>'}</div></div>
        <div class="panel"><div class="group-title" style="margin-top:0;color:${ST_COLOR.trim}">已到重新评估 / 兑现区</div>
          <div class="alerts compact">${sell.length ? sell.map((s) => alertRow(s, d)).join("") : '<div class="note">暂无</div>'}</div></div>
      </div>
      <div class="section-title">全部标的 <span class="sub">${d.stocks.length} 只 · 点击卡片查看完整交易计划</span></div>
      <div class="toolbar">
        <span class="note">分组</span>
        <div class="seg" id="dimSeg">${dims.map((x) => `<button data-k="${x.key}" class="${x.key === sk.dim ? "on" : ""}">${x.name}</button>`).join("")}</div>
        <span class="note">排序</span>
        <select id="sortSel">
          ${[["status", "状态优先"], ["dist", "距买入区最近"], ["upside", "到中性目标空间最大"], ["chg", "今日跌幅最大"]]
            .map(([k, n]) => `<option value="${k}" ${k === sk.sort ? "selected" : ""}>${n}</option>`).join("")}
        </select>
        <label class="note"><input type="checkbox" id="onlyChk" ${sk.only ? "checked" : ""}> 只看提醒中的标的</label>
        <input id="q" placeholder="搜索代码 / 名称" value="${esc(sk.q)}">
        <span class="zone-legend" style="margin-left:auto">${["starter", "buy", "add", "deep", "reassess", "trim"].map((k) =>
          `<span><i style="background:${ZONE_COLOR[k]}"></i>${{ starter: "试探", buy: "主要买入", add: "加仓", deep: "深度加仓", reassess: "重新评估", trim: "兑现" }[k]}</span>`).join("")}
          <span><i style="background:#fff;width:3px"></i>现价</span></span>
      </div>
      <div id="groups"></div>`;
    const draw = () => drawGroups(d);
    draw();
    document.getElementById("refresh").addEventListener("click", () => renderStocks(true));
    document.getElementById("dimSeg").addEventListener("click", (e) => {
      if (!e.target.dataset.k) return;
      sk.dim = e.target.dataset.k;
      document.querySelectorAll("#dimSeg button").forEach((b) => b.classList.toggle("on", b.dataset.k === sk.dim));
      draw();
    });
    document.getElementById("sortSel").addEventListener("change", (e) => { sk.sort = e.target.value; draw(); });
    document.getElementById("onlyChk").addEventListener("change", (e) => { sk.only = e.target.checked; draw(); });
    document.getElementById("q").addEventListener("input", (e) => { sk.q = e.target.value; draw(); });
    app.addEventListener("click", stockClick);
  }

  function stockClick(e) {
    const el = e.target.closest("[data-t]");
    if (el && !e.target.closest("a")) location.hash = `#/stock/${el.dataset.t}`;
  }

  function drawGroups(d) {
    const dim = d.categories.dimensions.find((x) => x.key === sk.dim);
    const q = sk.q.trim().toLowerCase();
    let list = d.stocks.filter((s) => (!sk.only || s.status.level !== "none")
      && (!q || `${s.ticker} ${s.name} ${s.symbol}`.toLowerCase().includes(q)));
    const sorter = {
      status: byStatus,
      dist: (a, b) => (a.metrics.dist_to_buy ?? 1e9) - (b.metrics.dist_to_buy ?? 1e9),
      upside: (a, b) => (b.metrics.upside_base ?? -1e9) - (a.metrics.upside_base ?? -1e9),
      chg: (a, b) => (a.price?.chg1d ?? 1e9) - (b.price?.chg1d ?? 1e9),
    }[sk.sort];
    list = [...list].sort(sorter);
    const groups = {};
    list.forEach((s) => {
      const g = dim.key === "status" ? s.status.label : s.tags[dim.key] || "未分类";
      (groups[g] ??= []).push(s);
    });
    const order = dim.order || [];
    const names = Object.keys(groups).sort((a, b) => (order.indexOf(a) + 1 || 999) - (order.indexOf(b) + 1 || 999));
    document.getElementById("groups").innerHTML = names.length ? names.map((g) => {
      const items = groups[g];
      const hot = items.filter((s) => s.status.level === "alert").length;
      return `<div class="section-title">${esc(g)} <span class="sub">${items.length} 只${hot ? ` · <b style="color:${ST_COLOR.buy}">${hot} 只在买入区间</b>` : ""}</span></div>
        <div class="cards">${items.map((s) => stockCard(s, d)).join("")}</div>`;
    }).join("") : '<div class="loading">没有符合条件的标的</div>';
  }

  async function renderStock(tk) {
    setNav("stocks");
    app.innerHTML = '<div class="loading">加载中…</div>';
    const d = await getStocks();
    const s = d.stocks.find((x) => x.ticker === tk);
    if (!s) { app.innerHTML = `<div class="loading">未找到 ${esc(tk)}，<a class="link" href="#/stocks">返回个股计划</a></div>`; return; }
    const p = s.price || {}, t = s.targets, m = s.metrics;
    const zones = [...s.zones].sort((a, b) => (b.high ?? b.low) - (a.high ?? a.low));
    const rows = [];
    let placed = p.last == null;
    zones.forEach((z) => {
      if (!placed && p.last > (z.high ?? z.low)) {
        rows.push(`<tr class="now"><td colspan="5">◆ 现价 ${cur(s)}${num(p.last)} · ${s.status.label}</td></tr>`);
        placed = true;
      }
      const sell = !BUY_T.includes(z.type);
      const edge = sell ? z.low : z.high;
      const dist = p.last && edge ? (edge / p.last - 1) * 100 : null;
      const zc = s.status.zone;
      const isCur = zc && s.status.key === z.type && z.low === zc.low && z.high === zc.high;
      rows.push(`<tr class="${isCur ? "cur" : ""}">
        <td><span class="zdot" style="background:${ZONE_COLOR[z.type]}"></span>${z.name}</td>
        <td class="num">${zr(z)}</td><td class="num">${esc(z.size ?? "-")}</td><td>${esc(z.action)}</td>
        <td class="num ${sgn(dist)}">${dist == null ? "-" : pct(dist)}</td></tr>`);
    });
    if (!placed) rows.push(`<tr class="now"><td colspan="5">◆ 现价 ${cur(s)}${num(p.last)} · ${s.status.label}</td></tr>`);
    const list = (title, arr, cls = "") => (arr && arr.length ? `<div class="group-title">${title}</div><ul class="plist ${cls}">${arr.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : "");
    app.innerHTML = `
      <div class="detail-head">
        <div><a class="note" href="#/stocks">← 返回个股计划</a>
          <h1>${esc(s.name)} <span class="tag">${s.symbol}</span><span class="tag">${esc(s.tags.market)}</span><span class="tag">${esc(s.tags.industry)}</span></h1></div>
        <div class="kv"><span class="k">最新收盘（${p.date ?? "-"}）</span><span class="v num">${cur(s)}${num(p.last)}</span></div>
        ${[["日涨跌", p.chg1d], ["近5日", p.chg5d], ["近20日", p.chg20d], ["相对发帖参考价", m.vs_ref]]
          .map(([k, v]) => `<div class="kv"><span class="k">${k}</span><span class="v num ${sgn(v)}">${pct(v)}</span></div>`).join("")}
        <div class="kv"><span class="k">当前状态</span><span class="v">${sBadge(s, d)}</span></div>
      </div>
      <div class="panel" style="margin-top:16px;--c:${ST_COLOR[s.status.key]};border-left:4px solid var(--c)">
        <div style="font-size:15px;font-weight:600">${esc(s.summary)}</div>
        <div class="note" style="margin-top:4px">${esc(planText(s))}</div>
        ${s.guards_hit.map((g) => `<div class="imp-high" style="margin-top:4px">⚠ 已触发复核线：${esc(g.note)}</div>`).join("")}
        ${ladderHTML(s, true)}
      </div>
      <div class="grid2" style="margin-top:14px">
        <div class="panel">
          <div class="section-title" style="margin-top:0">交易计划 <span class="sub">距现价 = 现价需变动多少才进入该档</span></div>
          <table class="plan"><thead><tr><th>档位</th><th>价格区间</th><th>仓位</th><th>计划动作</th><th>距现价</th></tr></thead>
            <tbody>${rows.join("")}</tbody></table>
          ${s.reserve ? `<div class="note" style="margin-top:8px">预留资金：${esc(s.reserve)}</div>` : ""}
          ${(s.guards || []).map((g) => `<div class="note">复核线：${cur(s)}${num(g.below)} 以下 · ${esc(g.note)}</div>`).join("")}
          ${list("计划成立的前提", s.conditions)}
          ${list("需要下调估值 / 放弃计划的信号", s.invalidation, "warn")}
        </div>
        <div class="panel">
          <div class="section-title" style="margin-top:0">${t ? `${s.target_year} 年底情景目标价` : "ETF 说明"} <span class="sub">${cur(s) === "HK$" ? "港元" : "美元"}</span></div>
          ${t ? `<div class="tg3 big">${TG.map(([k, n]) => `<div><div class="note">${n}</div><div class="num tv">${num(t[k])}</div>
            <div class="num ${sgn(m["upside_" + k])}">${pct(m["upside_" + k])}</div></div>`).join("")}</div>` : ""}
          ${list("估值关键假设", s.assumptions)}
          ${s.quotes?.length ? `<div class="group-title">原文摘录</div>${s.quotes.map((q) => `<blockquote>${esc(q)}</blockquote>`).join("")}` : ""}
          <div class="group-title">来源帖子</div>
          ${s.posts.map((x) => `<div><a class="link" href="${x.url}" target="_blank">${x.date} · ${esc(x.title)} ↗</a></div>`).join("")}
          ${s.ref ? `<div class="note">发帖参考价 ${cur(s)}${num(s.ref.price)}（${s.ref.date}）</div>` : ""}
          ${s.history?.length ? `<div class="group-title">修订历史</div>${s.history.map((h) => `<div class="note">${h.date} · ${esc(h.note)}</div>`).join("")}` : ""}
        </div>
      </div>
      <div class="section-title">近一年走势与计划区间 <span class="sub">色带为计划区间，虚线为情景目标价，竖线为发帖日</span></div>
      <div class="panel"><div id="stkChart" style="height:460px"></div></div>`;
    if (s.chart?.length) drawStockChart(s);
  }

  function drawStockChart(s) {
    const closes = s.chart.map((x) => x[1]);
    const hMin = Math.min(...closes), hMax = Math.max(...closes);
    const t = s.targets || {};
    const cand = [hMin, hMax, ...s.zones.flatMap((z) => [z.low, z.high]), t.bear, t.base].filter((v) => v != null && v < hMax * 1.8 && v > hMin * 0.5);
    const lo = Math.min(...cand) * 0.95, hi = Math.max(...cand) * 1.05;
    const first = s.chart[0][0];
    chart(document.getElementById("stkChart")).setOption({
      animation: false,
      grid: { left: 60, right: 90, top: 20, bottom: 50 },
      tooltip: { trigger: "axis", backgroundColor: "#121826", borderColor: C.line, textStyle: { color: C.text } },
      xAxis: { type: "time", axisLabel: { color: C.muted }, axisLine: { lineStyle: { color: C.line } } },
      yAxis: { type: "value", min: +lo.toPrecision(4), max: +hi.toPrecision(4), splitLine: { lineStyle: { color: C.line } },
        axisLabel: { color: C.muted, showMinLabel: false, showMaxLabel: false } },
      dataZoom: [{ type: "inside" }, { type: "slider", bottom: 8, height: 16, borderColor: C.line, textStyle: { color: C.muted } }],
      series: [{
        name: "收盘价", type: "line", data: s.chart, symbol: "none", lineStyle: { width: 1.5, color: "#e6edf7" },
        markArea: { silent: true, label: { show: false }, data: s.zones.map((z) => [
          { yAxis: z.low ?? lo, name: `${z.name} ${zr(z)}`, itemStyle: { color: ZONE_COLOR[z.type], opacity: 0.18 } },
          { yAxis: Math.min(z.high ?? hi, hi) }]) },
        markLine: { silent: true, symbol: "none", data: [
          ...TG.filter(([k]) => t[k] != null && t[k] >= lo && t[k] <= hi).map(([k, n]) => ({ yAxis: t[k],
            lineStyle: { type: "dashed", color: k === "base" ? C.accent : C.muted },
            label: { formatter: `${n} ${num(t[k])}`, color: k === "base" ? C.accent : C.muted, position: "end" } })),
          ...s.posts.filter((x) => x.date >= first).map((x) => ({ xAxis: x.date,
            lineStyle: { type: "dotted", color: "#4ea8ff" }, label: { formatter: "发帖", color: "#4ea8ff", position: "end" } })),
        ] },
      }],
    });
  }

  async function homeStockStrip() {
    try {
      const d = await getStocks();
      const el = document.getElementById("stkStrip");
      if (!el) return;
      const a = d.stocks.filter((s) => s.status.level === "alert").sort(byStatus);
      const n = d.stocks.filter((s) => s.status.level === "near").length;
      el.innerHTML = `<a class="stk-strip" href="#/stocks"><b>个股提醒</b>
        <span>${a.length} 只处于买入 / 加仓区间${n ? `，${n} 只接近买入区` : ""}${d.substack.pending.length ? `，${d.substack.pending.length} 篇新帖待录入` : ""}</span>
        <span class="strip-list">${a.slice(0, 10).map((s) => `<span class="sbadge" style="--c:${ST_COLOR[s.status.key]}">${s.currency === "HKD" ? esc(s.name) : s.ticker} · ${s.status.label}</span>`).join("")}</span>
        <span class="note" style="margin-left:auto">查看个股计划 →</span></a>`;
    } catch (e) { /* 个股数据缺失时不影响总览 */ }
  }

  // ---------------- 路由 ----------------
  async function route() {
    disposeCharts();
    window.scrollTo(0, 0);
    const h = location.hash.replace(/^#\/?/, "");
    try {
      if (h.startsWith("index/")) await renderIndex(h.slice(6));
      else if (h === "stocks") await renderStocks();
      else if (h.startsWith("stock/")) await renderStock(decodeURIComponent(h.slice(6)));
      else if (h === "macro") await renderMacro();
      else if (h === "events") renderEvents();
      else if (h === "method") renderMethod();
      else renderHome();
    } catch (e) {
      app.innerHTML = `<div class="loading">加载失败：${esc(e.message)}</div>`;
    }
  }

  (async () => {
    try {
      state.summary = await (await fetch(`data/summary.json?t=${Date.now()}`)).json();
    } catch (e) {
      app.innerHTML = `<div class="loading">数据加载失败：${esc(e.message)}</div>`;
      return;
    }
    renderMeta();
    window.addEventListener("hashchange", route);
    route();
  })();
})();

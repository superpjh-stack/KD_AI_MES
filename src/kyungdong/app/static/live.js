/* 실시간 패널 갱신 (D-223) — 화면 003·022 의 `#live` 를 `GET /api/ingest/live` 로 다시 그린다.
 *
 * · 서버가 처음 그린 것과 **같은 자리, 같은 뜻**으로만 바꾼다. 여기서 값을 계산하지 않는다.
 * · 갱신 주기는 `data-interval`(PLC 수집 주기, .env KYUNGDONG_PLC_POLL_SEC) — 최소 2초.
 * · 실패는 숨기지 않는다: 401/403/503 은 상태 코드와 함께 `#lv-err` 에 그대로 뜬다(§2.5 · G-30).
 *   조용히 마지막 값을 계속 보여 주면 "수집 중" 처럼 읽힌다 — 그래서 실패 시 갱신 표시를 지운다.
 * · 외부 라이브러리 0. 추이는 SVG polyline 이다 (CSP script-src 'self').
 */
(function () {
  "use strict";
  var root = document.getElementById("live");
  if (!root) return;
  var url = root.getAttribute("data-live");
  var every = Math.max(2, parseInt(root.getAttribute("data-interval") || "5", 10)) * 1000;
  var on = true, timer = null, failures = 0;
  var $ = function (id) { return document.getElementById(id); };

  function esc(s) { return String(s == null ? "" : s); }
  function fmt(v, d) { return (v == null || v === "") ? "—" : Number(v).toLocaleString("ko-KR", { minimumFractionDigits: d, maximumFractionDigits: d }); }
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }

  function drawStatus(d) {
    var s = $("lv-status"); s.textContent = "";
    var dot = el("span", "lv-dot");
    if (!d.last) {
      s.appendChild(dot); s.appendChild(document.createTextNode("미수집 (D-06) — PLC 수집 신호 0건"));
    } else {
      var cls = d.last.alarm_code ? "alarm" : ((d.device && d.device.stale) ? "stale" : (d.last.run_status === "가동" ? "run" : ""));
      dot.className = "lv-dot " + cls; s.appendChild(dot);
      var t = esc(d.last.run_status || "—");
      if (d.last.alarm_code) t += " · 알람 " + d.last.alarm_code;
      t += " · 마지막 수집 " + d.last.collect_dt;
      if (d.device && d.device.seconds_since != null) t += " (" + d.device.seconds_since + "초 전)";
      s.appendChild(document.createTextNode(t));
    }
    var n = $("lv-notice");
    if (d.device && d.device.notice) { n.textContent = d.device.notice; n.hidden = false; } else { n.hidden = true; }
  }

  function drawTags(d) {
    var box = $("lv-tags"); box.textContent = "";
    if (!d.last) return;
    d.last.tags.forEach(function (t) {
      var c = el("div", "lv-tag" + (t.name === "ALARM_CODE" && t.value ? " alarm" : ""));
      c.appendChild(el("span", "k", t.ko));
      var v = el("span", "v");
      var val = (t.value == null || t.value === "") ? "—" : (typeof t.value === "number" ? fmt(t.value, 2) : t.value);
      v.appendChild(document.createTextNode(val));
      v.appendChild(el("span", "u", t.uom));
      c.appendChild(v); box.appendChild(c);
    });
  }

  function drawChart(d) {
    var svg = $("lv-chart"); while (svg.firstChild) svg.removeChild(svg.firstChild);
    var W = 600, H = 150, pad = 8, rows = d.recent || [];
    var ns = "http://www.w3.org/2000/svg";
    if (rows.length < 2) {
      var t = document.createElementNS(ns, "text"); t.setAttribute("x", "12"); t.setAttribute("y", "80");
      t.setAttribute("font-size", "12"); t.setAttribute("fill", "#5b6470");
      t.textContent = rows.length ? "신호 1건 — 추이는 2주기부터 그린다" : "미수집 (D-06) — 신호 0건";
      svg.appendChild(t); return;
    }
    var series = [["speed", "#1f5fa8"], ["pressure", "#7ba7d7"], ["current", "#c8322b"], ["temp", "#e0a020"]];
    series.forEach(function (sp) {
      var key = sp[0], vals = rows.map(function (r) { return r[key]; });
      var nums = vals.filter(function (v) { return v != null; });
      if (!nums.length) return;
      var lo = Math.min.apply(null, nums), hi = Math.max.apply(null, nums), span = (hi - lo) || 1;
      var pts = [];
      vals.forEach(function (v, i) {
        if (v == null) return;
        var x = pad + (W - 2 * pad) * i / (rows.length - 1);
        var y = H - pad - (H - 2 * pad) * (v - lo) / span;
        pts.push(x.toFixed(1) + "," + y.toFixed(1));
      });
      var p = document.createElementNS(ns, "polyline");
      p.setAttribute("points", pts.join(" ")); p.setAttribute("fill", "none");
      p.setAttribute("stroke", sp[1]); p.setAttribute("stroke-width", "1.6"); svg.appendChild(p);
    });
    rows.forEach(function (r, i) {           // 알람 주기는 세로 표시
      if (!r.alarm_code) return;
      var x = pad + (W - 2 * pad) * i / (rows.length - 1);
      var l = document.createElementNS(ns, "line");
      l.setAttribute("x1", x); l.setAttribute("x2", x); l.setAttribute("y1", "0"); l.setAttribute("y2", H);
      l.setAttribute("stroke", "#c8322b"); l.setAttribute("stroke-dasharray", "3 3"); l.setAttribute("opacity", "0.5");
      svg.appendChild(l);
    });
  }

  function drawToday(d) {
    var t = d.today, p = $("lv-today"); p.textContent = "";
    function kv(label, v) { p.appendChild(document.createTextNode(label + " ")); p.appendChild(el("b", null, v)); }
    kv("신호", String(t.signals)); p.appendChild(document.createTextNode(" 건 · "));
    kv("가동시간", fmt(t.run_minute, 1)); p.appendChild(document.createTextNode(" 분 · "));
    kv("생산수량", fmt(t.produce_qty, 0)); p.appendChild(document.createTextNode(" ea · "));
    kv("알람", String(t.alarms)); p.appendChild(document.createTextNode(" 건 · "));
    kv("가동률", t.utilisation_pct == null ? "—" : t.utilisation_pct + " %");
    if (t.unmapped) { p.appendChild(document.createTextNode(" · ")); p.appendChild(el("span", "badge undetermined", "작업지시 미매핑 신호 " + t.unmapped + " 건")); }
    p.appendChild(document.createTextNode(" · Gateway 대기 버퍼 ")); p.appendChild(el("b", null, String(d.buffer_pending))); p.appendChild(document.createTextNode(" 배치"));
  }

  function drawMes(d) {
    var p = $("lv-mes"); p.textContent = "";
    if (!d.work_order) { p.appendChild(el("span", "badge undetermined", d.mapping_note || "작업지시 미매핑")); return; }
    p.appendChild(document.createTextNode("작업지시 "));
    var b = el("b"); var a = el("a", null, d.work_order.work_order_no);
    a.href = "/prc/024?project=" + encodeURIComponent(d.work_order.project_no || ""); b.appendChild(a); p.appendChild(b);
    p.appendChild(document.createTextNode(" · 프로젝트 " + esc(d.work_order.project_no) + " "));
    p.appendChild(el("span", "meta", "(" + d.work_order.source + ")")); p.appendChild(el("br"));
    var f = d.performance;
    if (f) {
      p.appendChild(document.createTextNode("자동 실적 #" + f.perf_id + " — " + f.method + " · 실적수량 "));
      p.appendChild(el("b", null, fmt(f.good_qty, 0))); p.appendChild(document.createTextNode(" ea · 공수 "));
      p.appendChild(el("b", null, String(f.manhour))); p.appendChild(document.createTextNode(" h · " + f.start_dt + " ~ " + f.end_dt + " "));
      p.appendChild(el("span", "meta", "· " + f.note));
    } else {
      p.appendChild(document.createTextNode("자동 실적 — 오늘 매핑된 신호가 아직 없다 (다음 배치부터 도출)"));
    }
  }

  function drawThresholds(d) {
    var p = $("lv-thr"); p.textContent = "";
    var th = d.thresholds;
    if (th.blocked) { p.appendChild(el("span", "badge undetermined", th.note)); return; }
    p.appendChild(document.createTextNode(th.note + " — "));
    th.items.forEach(function (it, i) {
      p.appendChild(document.createTextNode(it.cond_item + " " + (it.actual == null ? "—" : it.actual) + "/" + it.std + (it.uom || "")));
      if (it.out_of_tol) { p.appendChild(document.createTextNode(" ")); p.appendChild(el("span", "badge bad", "허용범위 초과")); }
      if (i < th.items.length - 1) p.appendChild(document.createTextNode(" · "));
    });
  }

  function drawAlerts(d) {
    var ul = $("lv-alerts"); ul.textContent = "";
    if (!d.alerts.length) { ul.appendChild(el("li", "meta", "금일 알림 0 건 — 장비 알람 코드가 오면 041 알림 화면에 `알림추천` 으로 올라간다")); return; }
    d.alerts.forEach(function (a) {
      var li = el("li"); var link = el("a", null, "#" + a.reco_id); link.href = "/agt/041"; li.appendChild(link);
      li.appendChild(document.createTextNode(" " + a.at + " — " + a.summary + " "));
      li.appendChild(el("span", "badge " + (a.review_status === "미검토" ? "undetermined" : "notice"), a.review_status));
      ul.appendChild(li);
    });
  }

  function render(d) {
    drawStatus(d); drawTags(d); drawChart(d); drawToday(d); drawMes(d); drawThresholds(d); drawAlerts(d);
    $("lv-tick").textContent = "갱신 " + d.checked_at;
    $("lv-err").textContent = "";
  }

  function tick() {
    if (!on) return;
    fetch(url, { headers: { "Accept": "application/json" }, credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) { return r.text().then(function (t) { throw new Error("HTTP " + r.status + " — " + t.slice(0, 160)); }); }
        return r.json();
      })
      .then(function (d) { failures = 0; render(d); })
      .catch(function (e) {
        failures += 1;
        $("lv-err").textContent = "갱신 실패 (" + failures + "회): " + e.message;
        $("lv-tick").textContent = "";
        if (failures >= 5) { on = false; setBtn(); $("lv-err").textContent += " — 5회 연속 실패로 갱신을 멈췄다. 버튼으로 다시 켠다"; }
      })
      .finally(function () { if (on) timer = setTimeout(tick, every); });
  }

  function setBtn() {
    var b = $("lv-toggle");
    b.setAttribute("aria-pressed", on ? "true" : "false");
    b.textContent = (on ? "실시간 갱신 켜짐 · " : "실시간 갱신 꺼짐 · ") + (every / 1000) + "초";
  }
  $("lv-toggle").addEventListener("click", function () {
    on = !on; setBtn();
    if (on) { failures = 0; tick(); } else if (timer) { clearTimeout(timer); timer = null; }
  });
  setBtn();
  tick();
})();

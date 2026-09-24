/* Minneapolis assessment check: address search + per-home context + citywide stats. */
(function () {
  const $ = (id) => document.getElementById(id);
  const money = (v) => "$" + Math.round(v).toLocaleString("en-US");
  const pct = (v, d = 0) => (v * 100).toFixed(d) + "%";
  const NS = "http://www.w3.org/2000/svg";
  let index = null, keys = [], summary = null;
  const zipCache = {};


  const ABBR = { STREET: "ST", AVENUE: "AVE", ROAD: "RD", PLACE: "PL", TERRACE: "TER", BOULEVARD: "BLVD", DRIVE: "DR", LANE: "LN",
    PARKWAY: "PKWY", NORTHEAST: "NE", NORTHWEST: "NW", SOUTHEAST: "SE", SOUTHWEST: "SW", NORTH: "N", SOUTH: "S", EAST: "E", WEST: "W" };
  const norm = (s) => s.toUpperCase().replace(/[.,#]/g, " ").replace(/\b[A-Z]+\b/g, (w) => ABBR[w] || w)
    .replace(/\s+/g, " ").trim();
  // The Twin Cities Living Quality Map links here with #<address>, and this page links back with ?q=.
  const MAP_URL = "https://twin-cities-living-quality-map.vercel.app/";

  function el(tag, attrs, parent, textContent) {
    const n = document.createElementNS(NS, tag);
    for (const k in attrs) n.setAttribute(k, attrs[k]);
    if (textContent != null) n.textContent = textContent;
    if (parent) parent.appendChild(n);
    return n;
  }
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const title = (s) => s.toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase()).replace(/\b(Ne|Se|Nw|Sw)\b/g, (m) => m.toUpperCase());

  // ---- search ----
  fetch("data/addresses.json").then((r) => r.json()).then((d) => { index = d; keys = Object.keys(d); });
  let active = -1, matches = [];
  $("q").addEventListener("input", () => {
    const q = norm($("q").value);
    const box = $("suggest");
    if (!index || q.length < 3) { box.hidden = true; return; }
    matches = [];
    for (const k of keys) { if (k.startsWith(q)) { matches.push(k); if (matches.length >= 8) break; } }
    if (matches.length < 8) for (const k of keys) { if (!k.startsWith(q) && k.includes(q)) { matches.push(k); if (matches.length >= 8) break; } }
    active = -1;
    box.innerHTML = matches.map((m, i) => `<button type="button" data-i="${i}">${esc(title(m))} <span class="muted small">${index[m]}</span></button>`).join("")
      || `<div class="muted small" style="padding:10px 16px">No matching single-family home in Minneapolis.</div>`;
    box.hidden = false;
  });
  $("q").addEventListener("keydown", (e) => {
    const btns = [...$("suggest").querySelectorAll("button")];
    if (!btns.length) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      active = (active + (e.key === "ArrowDown" ? 1 : -1) + btns.length) % btns.length;
      btns.forEach((b, i) => b.classList.toggle("active", i === active));
    } else if (e.key === "Enter") {
      e.preventDefault();
      choose(matches[Math.max(active, 0)]);
    }
  });
  $("suggest").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (b) choose(matches[+b.dataset.i]);
  });
  document.addEventListener("click", (e) => { if (!e.target.closest(".search")) $("suggest").hidden = true; });

  async function choose(addr) {
    $("suggest").hidden = true;
    $("q").value = title(addr);
    const zc = index[addr];
    if (!zipCache[zc]) zipCache[zc] = await fetch(`data/zip/${zc}.json`).then((r) => r.json());
    render(zipCache[zc][addr], zc);
    history.replaceState(null, "", "#" + encodeURIComponent(addr));
  }

  // ---- per-home result ----
  const round = (v) => money(Math.round(v / 5000) * 5000);
  const help = `
    <h3 style="margin-top:24px">Think your value is too high?</h3>
    <ul class="list">
      <li><b>Call the City Assessor's office first.</b> Your notice lists your appraiser. Many questions get settled with a phone call.
        <a href="https://www.minneapolismn.gov/resident-services/property-housing/property-values-taxes/market-value/appeal/" target="_blank" rel="noopener">City of Minneapolis: questions about your value</a></li>
      <li>Bring what matters most: recent sales of truly similar homes, and anything about your home's condition (repairs it needs, photos).</li>
      <li>If that doesn't resolve it, there's a formal appeal each spring:
        <a href="https://www.minneapolismn.gov/resident-services/property-housing/property-values-taxes/market-value/appeal/process/" target="_blank" rel="noopener">how to appeal</a>.</li>
    </ul>`;

  function render(h, zc) {
    const box = $("result");
    const year = summary ? summary.assessment_year : "";
    const nowMonth = summary ? new Date(summary.estimate_month + "-15").toLocaleString("en-US", { month: "long", year: "numeric" }) : "";
    const facts = [h.sqft && `${h.sqft.toLocaleString()} sq ft`, h.bd != null && `${h.bd} bed`, h.ba != null && `${h.ba} bath`,
      h.yb && `built ${h.yb}`].filter(Boolean).join(" · ");
    const head = `<div class="eyebrow">${esc(h.nb ? title(h.nb) : "")}</div><h2 style="margin:4px 0">${esc(title(h.a))}</h2>
      <p class="muted small">${facts}</p>
      <p class="small noprint"><a href="${MAP_URL}?q=${encodeURIComponent(title(h.a) + ", Minneapolis, MN")}" target="_blank" rel="noopener">How does this neighborhood score for safety, amenities and transit? See it on the Living Quality Map ↗</a></p>`;
    if (!h.ok) {
      box.innerHTML = `<div class="card">${head}
        <p class="big">The city values this home at <b>${money(h.v)}</b>.</p>
        <p>We couldn't find enough similar homes that sold nearby to compare it with, so we'd rather not guess.</p>${help}</div>`;
      return;
    }
    const prices = h.c.map((c) => c[3]).sort((a, b) => a - b);
    const low = prices[Math.floor(prices.length * 0.25)], high = prices[Math.ceil(prices.length * 0.75) - 1];
    // Two independent checks: nearby sales of similar homes, and our model (which also accounts for
    // lot size and exact location). Only call a value high or low when both agree.
    const compsHigh = h.pct >= 0.8, compsLow = h.pct <= 0.2;
    const modelHigh = h.v > h.hi50, modelLow = h.v < h.lo50;
    const share = (p) => (p >= 0.995 ? "all" : pct(p));
    let lead, extra, tone = "var(--accent)";
    if (compsHigh && modelHigh) {
      tone = "var(--warm)";
      lead = `That's <b>on the high side</b>: higher than ${share(h.pct)} of similar homes nearby sold for, and above our own estimate.`;
      extra = `<p>This doesn't mean the value is wrong. The city may know things we can't, like updates or the condition inside. But if your home isn't in better shape than these, it may be worth a call to the assessor.</p>`;
    } else if (compsLow && modelLow) {
      lead = `That's <b>on the low side</b>: lower than ${share(1 - h.pct)} of similar homes nearby sold for, and below our own estimate.`;
      extra = `<p>A lower value usually means a lower tax bill, so there's nothing to do here.</p>`;
    } else if (compsHigh || compsLow) {
      lead = `The picture is <b>mixed</b>. Similar homes nearby sold for ${compsHigh ? "less" : "more"}, but our estimate, which also accounts for lot size and exact location, puts this home at about ${round(h.e)} as of January.`;
      extra = `<p>When the two checks disagree, something about this home (a bigger lot, a standout location, its condition) probably sets it apart from the nearby sales. The city's value looks reasonable given that.</p>`;
    } else {
      lead = `That's <b>about the same</b> as what similar homes nearby sold for.`;
      extra = `<p>Nothing stands out here.</p>`;
    }
    box.innerHTML = `<div class="card">${head}
      <p class="big">The city values this home at <b>${money(h.v)}</b> for ${year}.</p>
      <p class="big">Similar homes nearby sold for about <b>${round(h.cm)}</b>, usually between ${round(low)} and ${round(high)}.</p>
      <p class="big">Our computer model estimates it would sell for about <b>${round(h.n)}</b> in ${nowMonth}, most likely between ${round(h.nlo50)} and ${round(h.nhi50)}.</p>
      <p class="small muted">The model is typically within about 9% of the actual sale price, but it can't see inside the home, so condition and updates can move the price well outside that range.</p>
      ${h.tier > 0 ? `<p class="small muted">There weren't many sales of very similar homes right around this one, so we looked up to a mile away${h.tier > 1 ? " and back three years" : ""}. Treat this comparison as rougher than usual.</p>` : ""}
      <p class="verdict" style="border-color:${tone}">${lead}</p>
      ${extra}
      <div id="strip" style="margin-top:12px"></div>
      <details style="margin-top:16px"><summary><b>See the similar homes</b></summary>
        <p class="small muted">Prices are updated to January ${year} using how much Minneapolis home prices changed since each sale.</p>
        <div class="tablewrap"><table><tr><th>Address</th><th>Sold</th><th>Price then</th><th>Price today*</th><th>Sq ft</th><th>Built</th><th>Beds / baths</th></tr>
          ${h.c.map((c) => `<tr><td>${esc(title(c[0]))}</td><td>${new Date(c[1] + "-15").toLocaleString("en-US", { month: "short", year: "numeric" })}</td><td>${money(c[2])}</td><td>${money(c[3])}</td><td>${c[4].toLocaleString()}</td><td>${c[5]}</td><td>${c[6] ?? "–"} / ${c[7] ?? "–"}</td></tr>`).join("")}
        </table></div>
        <p class="small muted">*Estimated price as of January ${year}.</p>
        <p class="small muted">Our computer model, which never sees the city's value, expects this home would sell for about <b>${round(h.n)}</b> in ${nowMonth}.
          About half of homes like this sell between ${round(h.nlo50)} and ${round(h.nhi50)}.
          Condition can move it much further: 9 in 10 homes like this sell between ${round(h.nlo)} and ${round(h.nhi)}.
          As of January ${year}, the date the city values homes, its estimate is about ${round(h.e)}.</p>
      </details>
      ${help}
      <p class="noprint" style="margin-top:16px"><button class="btn" type="button" id="download">Download as PDF</button></p>
    </div>`;
    strip(h, prices);
    $("download").onclick = () => downloadPdf(h);
  }

  // PDF of the result card. The library loads only when someone asks for a download.
  function downloadPdf(h) {
    const go = () => window.html2pdf().set({
      margin: 12, filename: `home-value-comparison-${h.a.toLowerCase().replace(/[^a-z0-9]+/g, "-")}.pdf`,
      html2canvas: { scale: 2, backgroundColor: getComputedStyle(document.body).backgroundColor },
      jsPDF: { unit: "mm", format: "letter" },
    }).from($("result")).save();
    if (window.html2pdf) return go();
    const tag = document.createElement("script");
    tag.src = "https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js";
    tag.onload = go;
    document.head.appendChild(tag);
  }

  // Simple number line: each similar home is a dot, the city's value is a labelled marker.
  function strip(h, prices) {
    const W = 800, H = 96, L = 20, R = 20;
    const lo = Math.min(...prices, h.v) * 0.93, hi = Math.max(...prices, h.v) * 1.07;
    const x = (v) => L + ((v - lo) / (hi - lo)) * (W - L - R);
    const s = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "The city's value compared with what similar homes sold for" });
    el("line", { x1: L, x2: W - R, y1: 40, y2: 40, stroke: "var(--grid)", "stroke-width": 2 }, s);
    prices.forEach((v) => el("circle", { cx: x(v), cy: 40, r: 7, fill: "var(--accent)", stroke: "var(--card)", "stroke-width": 2 }, s));
    el("text", { x: L, y: 16 }, s, "Blue dots: what similar homes sold for");
    el("line", { x1: x(h.v), x2: x(h.v), y1: 26, y2: 56, stroke: "var(--warm)", "stroke-width": 4, "stroke-linecap": "round" }, s);
    el("text", { x: Math.min(Math.max(x(h.v), 90), W - 90), y: 76, "text-anchor": "middle", class: "lbl" }, s, `city's value ${money(h.v)}`);
    el("text", { x: L, y: 94 }, s, "lower");
    el("text", { x: W - R, y: 94, "text-anchor": "end" }, s, "higher");
    $("strip").replaceChildren(s);
  }

  // ---- citywide + methods ----
  fetch("data/summary.json").then((r) => r.json()).then((s) => {
    summary = s;
    $("year").textContent = s.assessment_year;
    const f = s.fairness, d = f.by_price_decile;
    const typical = Math.round(f.overall.median_ratio * 100);
    $("fair-sub").innerHTML = `For a typical Minneapolis house, the city's value was about <b>${typical}% of what it sold for</b>, a bit below the sale price. But that isn't true for every home:`;
    $("fair-chart-sub").textContent = `Homes that sold in ${s.fairness_window.replace("sales ", "")}, grouped from cheapest to most expensive. Each dot shows the city's value as a share of the sale price. We left out ${f.trimmed} unusual sales (for example, homes sold as-is for far below their value).`;
    // Dot chart on a zoomed axis: dots (not bars) so the non-zero baseline doesn't exaggerate differences.
    const W = 800, H = 260, L = 48, R = 12, T = 16, B = 48;
    const s2 = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "City value as a share of sale price, by price tier" });
    const lo = Math.min(0.8, Math.floor(Math.min(...d.map((g) => g.median_ratio)) * 20) / 20);
    const hi = Math.max(1.05, Math.ceil(Math.max(...d.map((g) => g.median_ratio)) * 20) / 20);
    const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
    for (let t = lo; t <= hi + 1e-9; t += 0.05) {
      const v = +t.toFixed(2);
      el("line", { x1: L, x2: W - R, y1: y(v), y2: y(v), stroke: v === 1 ? "var(--muted)" : "var(--grid)", "stroke-dasharray": v === 1 ? "5 5" : "" }, s2);
      el("text", { x: L - 8, y: y(v) + 4, "text-anchor": "end" }, s2, Math.round(v * 100) + "%");
    }
    el("text", { x: W - R, y: y(1) - 8, "text-anchor": "end" }, s2, "100% = valued at exactly the sale price");
    const bw = (W - L - R) / d.length;
    const cx = (i) => L + i * bw + bw / 2;
    el("path", { d: d.map((g, i) => `${i ? "L" : "M"}${cx(i)},${y(g.median_ratio)}`).join(""), fill: "none", stroke: "var(--accent)", "stroke-width": 2, opacity: 0.4 }, s2);
    d.forEach((g, i) => {
      const c = el("circle", { cx: cx(i), cy: y(g.median_ratio), r: 8, fill: "var(--accent)", stroke: "var(--card)", "stroke-width": 2 }, s2);
      el("title", {}, c, `Homes that sold for ${money(g.price_min)}–${money(g.price_max)}: valued at ${Math.round(g.median_ratio * 100)}% of sale price (${g.n} sales)`);
      el("text", { x: cx(i), y: y(g.median_ratio) + 24, "text-anchor": "middle", class: "lbl" }, s2, Math.round(g.median_ratio * 100) + "%");
      el("text", { x: cx(i), y: H - 26, "text-anchor": "middle" }, s2, "$" + Math.round(g.price_min / 1000) + "k");
    });
    el("text", { x: L, y: H - 6 }, s2, "← cheaper homes");
    el("text", { x: W - R, y: H - 6, "text-anchor": "end" }, s2, "more expensive homes →");
    $("decile").replaceChildren(s2);
    const avg = (a) => a.reduce((t, g) => t + g.median_ratio, 0) / a.length;
    if (avg(d.slice(0, 3)) > avg(d.slice(-3)) + 0.03) {
      const note = document.createElement("p");
      note.innerHTML = "<b>Cheaper homes tend to be valued closer to their sale price than expensive homes.</b> The gap is modest, but it means owners of cheaper homes can pay a bit more tax relative to what their home is worth. This pattern is common across the U.S.";
      $("decile").after(note);
    }

    const years = Object.keys(s.backtest);
    const row = (label, fn) => `<tr><td>${label}</td>${years.map((yv) => `<td>${fn(s.backtest[yv])}</td>`).join("")}</tr>`;
    $("bt").innerHTML = `<tr><th></th>${years.map((yv) => `<th>${yv}</th>`).join("")}</tr>` +
      row("Homes tested", (a) => a.test_sales.toLocaleString()) +
      row("Our model was typically off by*", (a) => pct(a.model_median_abs_pct_error)) +
      row("The city's value was typically off by", (a) => pct(a.assessor_median_abs_pct_error));
    $("bt").insertAdjacentHTML("afterend", `<p class="small muted">*Our model estimates the price for the month each home sold, using only data from before January. The city's value is set for January 2 and isn't adjusted for later price changes, so part of its gap is timing.</p>`);
    $("why-no-verdict").textContent = "Why don't we just tell you \"your value is too high\"? We tried. About 1 in 5 homes we would have flagged still sold for more than the city's value, which is too often to be sure. So we show you the comparison and let you decide.";

    const hash = decodeURIComponent(location.hash.slice(1));
    // A hash that isn't an exact key (e.g. "3217 48th Avenue South" from the map) is normalized; failing that it
    // pre-fills the search box so the suggestions show.
    if (hash) {
      const wait = setInterval(() => {
        if (!index) return;
        clearInterval(wait);
        const key = index[hash] ? hash : norm(hash);
        if (index[key]) choose(key);
        else { $("q").value = hash; $("q").dispatchEvent(new Event("input")); $("q").focus(); }
      }, 100);
    }
  });
})();

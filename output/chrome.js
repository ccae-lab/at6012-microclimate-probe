/* Shared chrome for the infrared.city Buildathon AT6012 pages:
   top banner + SDK link + live countdown, and a shared footer with
   resources, the Day-3 schedule, cohort-city cross-links and the
   curricula.dev triad. Include on every page:  <script src="chrome.js" defer></script> */
(function () {
  var PAGES = [
    ["tool.html", "🛰 Probe tool"],
    ["index.html", "Learning module"],
    ["scorecard.html", "Marseille"],
    ["scorecard_cork.html", "Cork"],
    ["scorecard_rome.html", "Rome"],
    ["timeseries.html", "Time series"],
    ["api-guide.html", "📘 Data & API guide"]
  ];
  var TRIAD = [
    ["https://engage.curricula.dev", "ENGAGE"],
    ["https://explore.curricula.dev", "Explore"],
    ["https://energetic.curricula.dev", "Energetic"]
  ];
  // Submission deadline: Sunday 31 May 2026, end of day (CEST = UTC+2).
  var DEADLINE = new Date("2026-05-31T23:59:59+02:00");

  var css = document.createElement("style");
  css.textContent = [
    ".ir-banner{position:relative;z-index:99999;background:#0f1b2a;color:#eaf0f6;",
    "font:600 14px -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;",
    "display:flex;flex-wrap:wrap;align-items:center;gap:10px 18px;padding:10px 18px;border-bottom:2px solid #e67e22}",
    ".ir-banner .ir-brand{font-weight:800;color:#fff;letter-spacing:.02em}",
    ".ir-banner a{color:#ffd9b3;text-decoration:none}.ir-banner a:hover{text-decoration:underline}",
    ".ir-nav{display:flex;flex-wrap:wrap;gap:4px 12px;font-weight:600}",
    ".ir-nav a.ir-active{color:#fff;border-bottom:2px solid #e67e22}",
    ".ir-count{margin-left:auto;background:#e67e22;color:#1b2733;font-weight:800;",
    "padding:4px 12px;border-radius:999px;white-space:nowrap}",
    ".ir-count.ir-over{background:#c0392b;color:#fff}",
    "nav.navbar{top:var(--ir-banner-h,0)!important}",
    ".ir-footer{background:#0f1b2a;color:#c7d3df;margin-top:50px;",
    "font:14px/1.6 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif}",
    ".ir-footer .ir-fwrap{max-width:1000px;margin:0 auto;padding:30px 24px;",
    "display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:24px}",
    ".ir-footer h4{color:#fff;font-size:13px;text-transform:uppercase;letter-spacing:.05em;margin:0 0 10px}",
    ".ir-footer a{color:#ffd9b3;text-decoration:none}.ir-footer a:hover{text-decoration:underline}",
    ".ir-footer ul{list-style:none;padding:0;margin:0}.ir-footer li{margin:4px 0}",
    ".ir-footer .ir-bottom{border-top:1px solid #24323f;padding:14px 24px;text-align:center;color:#8aa0b3;font-size:12px}"
  ].join("");
  document.head.appendChild(css);

  var here = (location.pathname.split("/").pop() || "index.html").toLowerCase();

  function links(list, active) {
    return list.map(function (p) {
      var a = active && p[0] === active ? ' class="ir-active"' : "";
      return '<a href="' + p[0] + '"' + a + ">" + p[1] + "</a>";
    }).join("");
  }
  function ext(list) {
    return list.map(function (p) { return '<a href="' + p[0] + '" target="_blank" rel="noopener">' + p[1] + "</a>"; });
  }

  // ---- Banner ----
  var banner = document.createElement("div");
  banner.className = "ir-banner";
  banner.innerHTML =
    '<span class="ir-brand">🔥 infrared.city Buildathon 2026</span>' +
    '<span class="ir-nav">' + links(PAGES, here) + "</span>" +
    '<a href="https://infrared.city/docs/sdk/" target="_blank" rel="noopener">SDK&nbsp;docs ↗</a>' +
    '<span class="ir-count" id="ir-count">⏰ …</span>';
  document.body.insertBefore(banner, document.body.firstChild);
  document.documentElement.style.setProperty("--ir-banner-h", banner.offsetHeight + "px");

  // ---- Footer ----
  var footer = document.createElement("footer");
  footer.className = "ir-footer";
  footer.innerHTML =
    '<div class="ir-fwrap">' +
      '<div><h4>Case studies</h4><ul>' +
        PAGES.map(function (p) { return "<li><a href='" + p[0] + "'>" + p[1] + "</a></li>"; }).join("") +
      "</ul></div>" +
      '<div><h4>Day-1 resources (live)</h4><ul>' +
        "<li>" + ext([["https://infrared.city/docs/sdk/", "SDK docs"]])[0] + "</li>" +
        "<li>" + ext([["https://github.com/Infrared-city/infrared-skills", "SDK Skill (official)"]])[0] + "</li>" +
        "<li>" + ext([["https://github.com/ccae-lab/infrared-skills", "SDK Skill (CCAE fork)"]])[0] + "</li>" +
        "<li>" + ext([["https://slides.infrared.city/buildathon-launch-2026/", "Day-1 slide deck"]])[0] + "</li>" +
      "</ul></div>" +
      '<div><h4>Day 3 — final day (CEST)</h4><ul>' +
        "<li>09:00–10:00 — Morning Q&A</li>" +
        "<li>17:00–19:00 — Closing session</li>" +
        "<li><strong>Submission: Sun, EOD</strong></li>" +
        "<li>Mon — showcase &amp; sharing</li>" +
      "</ul></div>" +
      '<div><h4>curricula.dev triad</h4><ul>' +
        ext(TRIAD).map(function (a) { return "<li>" + a + "</li>"; }).join("") +
      "</ul></div>" +
    "</div>" +
    '<div class="ir-bottom">AT6012 Design Research · CCAE / UCC School of Architecture · infrared.city SDK 0.4.9</div>';
  document.body.appendChild(footer);

  // ---- Countdown ----
  var el = document.getElementById("ir-count");
  function tick() {
    var ms = DEADLINE - new Date();
    if (ms <= 0) { el.className = "ir-count ir-over"; el.textContent = "⏰ Submission closed"; return; }
    var d = Math.floor(ms / 86400000),
        h = Math.floor(ms / 3600000) % 24,
        m = Math.floor(ms / 60000) % 60,
        s = Math.floor(ms / 1000) % 60;
    el.textContent = "⏰ " + d + "d " + ("0" + h).slice(-2) + "h " +
      ("0" + m).slice(-2) + "m " + ("0" + s).slice(-2) + "s → submission (Sun EOD)";
  }
  tick();
  setInterval(tick, 1000);
})();

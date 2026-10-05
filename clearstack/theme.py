"""Shared browser-local theme controls for ClearStack dashboard pages."""


def theme_head():
    """Return semantic palette overrides and the persistence script."""
    return """<style>
:root {
  --sky-top:#232937;--sky-mid:#30394a;--sky-low:#465266;--sky-horizon:#667487;
  --surface:rgba(22,27,36,.78);--surface-strong:rgba(31,38,50,.94);--border:rgba(181,195,218,.20);
  --ink:#edf2fa;--muted:#aebbd0;--line:rgba(181,195,218,.16);
  --aqua:#79a9ff;--aqua-deep:#b7d0ff;--mint:#69c69a;--coral:#ef8795;--amber:#efba65;
  --shadow:0 2px 3px rgba(0,0,0,.20),0 18px 34px -16px rgba(0,0,0,.72);
}
html[data-clearstack-theme="paper"] {
  --sky-top:#e7e9e3;--sky-mid:#d9ddd6;--sky-low:#cbd2c9;--sky-horizon:#bcc5bb;
  --surface:rgba(250,251,248,.73);--surface-strong:rgba(255,255,252,.92);--border:rgba(36,46,38,.16);
  --ink:#1f2a22;--muted:#607066;--line:rgba(36,46,38,.15);
  --aqua:#477960;--aqua-deep:#254c37;--mint:#33734d;--coral:#b65462;--amber:#9b6a1e;
  --shadow:0 2px 3px rgba(37,48,39,.08),0 18px 34px -16px rgba(37,48,39,.28);
}
html[data-clearstack-theme="dusk"] {
  --sky-top:#241f35;--sky-mid:#342850;--sky-low:#594277;--sky-horizon:#8a6c9c;
  --surface:rgba(34,25,53,.78);--surface-strong:rgba(47,36,69,.94);--border:rgba(232,211,255,.20);
  --ink:#f3ecfa;--muted:#c9b9d8;--line:rgba(232,211,255,.16);
  --aqua:#c5a8ff;--aqua-deep:#eadbff;--mint:#80d2b1;--coral:#fa9aaa;--amber:#ffc978;
  --shadow:0 2px 3px rgba(0,0,0,.20),0 18px 34px -16px rgba(0,0,0,.72);
}
.theme-picker { position:relative; z-index:3; }
.theme-picker summary { cursor:pointer; color:var(--aqua-deep); border:1px solid var(--border); background:var(--surface-strong); border-radius:999px; padding:6px 12px; font-size:12px; font-weight:650; list-style:none; white-space:nowrap; }
.theme-picker summary::-webkit-details-marker { display:none; }
.theme-picker[open] summary { border-bottom-left-radius:8px; border-bottom-right-radius:8px; }
.theme-menu { position:absolute; right:0; top:34px; width:286px; padding:14px; background:var(--surface-strong); color:var(--ink); border:1px solid var(--border); border-radius:12px; box-shadow:var(--shadow); }
.theme-menu label { display:block; color:var(--muted); font-size:12px; margin:0 0 5px; }
.theme-menu select, .theme-menu input { width:100%; color:var(--ink); background:var(--surface); border:1px solid var(--border); border-radius:6px; padding:6px; }
.theme-menu select { margin-bottom:12px; }
.theme-menu fieldset { border:0; padding:0; margin:0; display:grid; grid-template-columns:1fr 1fr; gap:8px; }
.theme-menu fieldset label { display:flex; align-items:center; gap:6px; margin:0; }
.theme-menu input[type=color] { width:28px; height:24px; padding:1px; flex:none; }
.theme-menu .theme-hint { font-size:11px; line-height:1.4; margin:12px 0 0; color:var(--muted); }
@media(max-width:700px) { .theme-menu { right:auto; left:0; } }
</style>
<script>
(function() {
  var storageKey = "clearstack.theme";
  var budgetKey = "clearstack.spend-guardrail.14d";
  var tokens = ["sky-top", "sky-mid", "sky-low", "sky-horizon", "surface", "surface-strong", "ink", "muted", "aqua", "aqua-deep", "mint", "coral", "amber"];
  var defaults = {};
  var html = document.documentElement;
  var read = function() { try { return JSON.parse(localStorage.getItem(storageKey) || "{}"); } catch (_) { return {}; } };
  var save = function(state) { localStorage.setItem(storageKey, JSON.stringify(state)); };
  var apply = function(state) {
    var theme = state.theme || "midnight";
    html.setAttribute("data-clearstack-theme", theme);
    tokens.forEach(function(token) { html.style.removeProperty("--" + token); });
    if (theme === "custom") Object.keys(state.custom || {}).forEach(function(token) { html.style.setProperty("--" + token, state.custom[token]); });
  };
  var hex = function(value) {
    var match = String(value || "").match(/^#([0-9a-f]{6})$/i);
    return match ? "#" + match[1] : "#000000";
  };
  var snapshot = function() {
    var styles = getComputedStyle(html), palette = {};
    tokens.forEach(function(token) { palette[token] = hex(styles.getPropertyValue("--" + token).trim()); });
    return palette;
  };
  var state = read();
  apply(state);
  document.addEventListener("change", function(event) {
    if (event.target.matches("[data-clearstack-theme-select]")) {
      state = read();
      state.theme = event.target.value;
      if (state.theme === "custom") state.custom = state.custom || snapshot();
      save(state); apply(state); sync();
    }
    if (event.target.matches("[data-theme-token]")) {
      state = read();
      state.theme = "custom";
      state.custom = state.custom || snapshot();
      state.custom[event.target.dataset.themeToken] = event.target.value;
      save(state); apply(state); sync();
    }
  });
  function sync() {
    var current = read(), palette;
    document.querySelectorAll("[data-clearstack-theme-select]").forEach(function(select) { select.value = current.theme || "midnight"; });
    palette = current.theme === "custom" ? (current.custom || {}) : snapshot();
    document.querySelectorAll("[data-theme-token]").forEach(function(input) { input.value = hex(palette[input.dataset.themeToken]); });
    syncBudget();
  }
  function syncBudget() {
    var guardrail = document.querySelector("[data-billing-spend]");
    if (!guardrail) return;
    var spend = Number(guardrail.dataset.billingSpend || 0);
    var input = document.getElementById("clearstack-spend-cap");
    var output = guardrail.querySelector("[data-spend-guardrail]");
    var cap = Number(localStorage.getItem(budgetKey));
    if (input && document.activeElement !== input) input.value = cap > 0 ? cap : "";
    if (!output) return;
    if (!(cap > 0)) { output.textContent = "Set a cap to compare against recorded metered cost."; return; }
    var percent = Math.round(spend / cap * 100);
    output.textContent = "$" + spend.toFixed(2) + " of $" + cap.toFixed(2) + " used (" + percent + "%).";
  }
  document.addEventListener("input", function(event) {
    if (event.target.id !== "clearstack-spend-cap") return;
    var cap = Number(event.target.value);
    if (cap > 0) localStorage.setItem(budgetKey, String(cap));
    else localStorage.removeItem(budgetKey);
    syncBudget();
  });
  document.addEventListener("DOMContentLoaded", sync);
})();
</script>"""


def theme_picker():
    """Return the shared built-in and custom palette picker."""
    return """<details class=theme-picker>
  <summary>Appearance</summary>
  <div class=theme-menu>
    <label for=clearstack-theme>ClearStack theme</label>
    <select id=clearstack-theme data-clearstack-theme-select>
      <option value=midnight>Midnight</option>
      <option value=paper>Paper</option>
      <option value=dusk>Dusk</option>
      <option value=custom>Custom palette</option>
    </select>
    <fieldset>
      <label>Canvas <input type=color data-theme-token="sky-top"></label>
      <label>Horizon <input type=color data-theme-token="sky-horizon"></label>
      <label>Panel <input type=color data-theme-token="surface-strong"></label>
      <label>Text <input type=color data-theme-token="ink"></label>
      <label>Muted <input type=color data-theme-token="muted"></label>
      <label>Accent <input type=color data-theme-token="aqua"></label>
      <label>Accent text <input type=color data-theme-token="aqua-deep"></label>
      <label>Success <input type=color data-theme-token="mint"></label>
      <label>Warning <input type=color data-theme-token="amber"></label>
      <label>Danger <input type=color data-theme-token="coral"></label>
    </fieldset>
    <p class=theme-hint>Stored only in this browser. The dashboard never writes Hermes or provider settings.</p>
  </div>
</details>"""

"""Scripty: keyboard-driven script launcher.

Root: ~/Dropbox/2tech/scripty/
Config: ~/Dropbox/2tech/scripty/config.json
  Format: {launchd:{...}, groups:[{group, collapsed, scripts:[...]}]}
  (Transparently migrates the old bare-array format on first write.)

Routes:
  GET  /scripty                        — self-contained HTML UI
  GET  /scripty/config                 — JSON grouped config (read fresh)
  POST /scripty/run                    — execute a script by key
  POST /scripty/collapse               — persist collapsed state for a group
  POST /scripty/collapse-all           — set collapsed state on all groups
  POST /scripty/open-folder            — open a path in Finder (macOS open)
  GET  /scripty/launchd/scan           — list staging plists not yet in LaunchAgents
  POST /scripty/launchd/register       — copy plist to LaunchAgents + launchctl load
  POST /scripty/launchd/unregister     — launchctl unload + remove from LaunchAgents
  POST /scripty/launchd/update-schedule— update StartCalendarInterval + reload
  GET  /scripty/launchd/status         — loaded/schedule status for all launchd scripts
  GET  /scripty/launchd/logs/{name}    — last N lines of stdout/stderr logs
"""

import json
import logging
import os
import plistlib
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["scripty"])

SCRIPTY_ROOT = Path("~/Dropbox/2tech/scripty").expanduser()
CONFIG_FILE = SCRIPTY_ROOT / "config.json"

LAUNCHD_STAGING = Path("~/Dropbox/2tech/scripty/launchd/plists").expanduser()
LAUNCH_AGENTS = Path("~/Library/LaunchAgents").expanduser()
LAUNCHD_LOGS = Path("~/scripty/launchd/logs").expanduser()

# Ensure required directories exist at startup
for _d in [LAUNCHD_STAGING, LAUNCH_AGENTS, LAUNCHD_LOGS]:
    _d.mkdir(parents=True, exist_ok=True)

EXTENSION_INTERPRETERS: dict[str, list[str]] = {
    ".py": ["python3"],
    ".sh": ["bash"],
    ".zsh": ["zsh"],
    ".bash": ["bash"],
    ".rb": ["ruby"],
    ".js": ["node"],
    ".pl": ["perl"],
}

_DEFAULT_LAUNCHD_SETTINGS = {
    "staging_folder": str(LAUNCHD_STAGING),
    "launch_agents": str(LAUNCH_AGENTS),
    "logs_folder": str(LAUNCHD_LOGS),
}


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def _load_full_config() -> dict:
    """Read config.json → {launchd:{...}, groups:[...]}.
    Transparently handles the old bare-array format."""
    if not CONFIG_FILE.exists():
        return {"launchd": _DEFAULT_LAUNCHD_SETTINGS, "groups": []}
    try:
        raw = json.loads(CONFIG_FILE.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("scripty: failed to read config: %s", e)
        return {"launchd": _DEFAULT_LAUNCHD_SETTINGS, "groups": []}
    if isinstance(raw, list):
        return {"launchd": _DEFAULT_LAUNCHD_SETTINGS, "groups": raw}
    return raw


def _load_config() -> list[dict]:
    """Return the groups list (read fresh)."""
    return _load_full_config().get("groups", [])


def _atomic_write_full(full_config: dict) -> None:
    tmp = CONFIG_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(full_config, indent=2))
        os.replace(tmp, CONFIG_FILE)
    except OSError as e:
        logger.warning("scripty: failed to write config: %s", e)
        tmp.unlink(missing_ok=True)
        raise


def _atomic_write(groups: list[dict]) -> None:
    """Write groups list atomically, preserving top-level launchd settings."""
    full = _load_full_config()
    full["groups"] = groups
    _atomic_write_full(full)


def _find_entry(groups: list[dict], key: str) -> dict | None:
    for group in groups:
        for entry in group.get("scripts", []):
            if entry.get("key") == key:
                return entry
    return None


def _update_last_run(key: str, timestamp: str) -> None:
    config = _load_config()
    entry = _find_entry(config, key)
    if entry is None:
        return
    entry["last_run"] = timestamp
    try:
        _atomic_write(config)
    except OSError:
        pass


def _update_collapse(group_name: str, collapsed: bool) -> None:
    config = _load_config()
    for group in config:
        if group.get("group") == group_name:
            group["collapsed"] = collapsed
            break
    else:
        return
    try:
        _atomic_write(config)
    except OSError:
        pass


def _update_collapse_all(collapsed: bool) -> None:
    config = _load_config()
    for group in config:
        group["collapsed"] = collapsed
    try:
        _atomic_write(config)
    except OSError:
        pass


def _build_cmd(entry: dict) -> list[str]:
    if entry.get("command"):
        parts = entry["command"].split()
        file_path = (
            Path(entry["path"]).expanduser() / entry["file"]
            if entry.get("file")
            else None
        )
        if file_path and str(file_path) not in parts:
            parts.append(str(file_path))
        return parts
    file_path = Path(entry["path"]).expanduser() / entry["file"]
    ext = Path(entry["file"]).suffix.lower()
    interpreter = EXTENSION_INTERPRETERS.get(ext)
    if interpreter:
        return interpreter + [str(file_path)]
    return [str(file_path)]


# ---------------------------------------------------------------------------
# Launchd helpers
# ---------------------------------------------------------------------------


def _parse_schedule(plist_data: dict) -> tuple[str, str]:
    """Parse StartCalendarInterval → (interval, time_str). Returns ('','') if absent."""
    sci = plist_data.get("StartCalendarInterval")
    if not sci:
        return "", ""
    if isinstance(sci, list):
        sci = sci[0]
    if "Weekday" in sci:
        return "weekly", f"{sci.get('Hour', 0):02d}:{sci.get('Minute', 0):02d}"
    elif "Hour" in sci:
        return "daily", f"{sci.get('Hour', 0):02d}:{sci.get('Minute', 0):02d}"
    elif "Minute" in sci:
        return "hourly", f":{sci.get('Minute', 0):02d}"
    return "", ""


def _make_schedule(interval: str, time_str: str) -> dict:
    """Build StartCalendarInterval dict from interval + HH:MM string."""
    parts = time_str.split(":") if ":" in time_str else ["0", "0"]
    h = int(parts[0]) if parts else 0
    m = int(parts[1]) if len(parts) > 1 else 0
    if interval == "hourly":
        return {"Minute": m}
    elif interval == "daily":
        return {"Hour": h, "Minute": m}
    elif interval == "weekly":
        return {"Weekday": 1, "Hour": h, "Minute": m}
    return {}


def _get_loaded_labels() -> set[str]:
    """Run launchctl list and return all loaded service labels."""
    try:
        lc = subprocess.run(
            ["launchctl", "list"], capture_output=True, text=True, timeout=10
        )
        labels: set[str] = set()
        for line in lc.stdout.splitlines()[1:]:  # skip header
            parts = line.split("\t")
            if len(parts) >= 3:
                labels.add(parts[2].strip())
        return labels
    except Exception as e:
        logger.warning("scripty: launchctl list failed: %s", e)
        return set()


def _read_plist_safe(path: Path) -> dict:
    try:
        with open(path, "rb") as f:
            return plistlib.load(f)
    except Exception as e:
        logger.warning("scripty: failed to read plist %s: %s", path, e)
        return {}


# ---------------------------------------------------------------------------
# UI page
# ---------------------------------------------------------------------------

_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Scripty</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --bg: #F0F8FF;
    --surface: #ffffff;
    --bubble: #dce8f8;
    --border: #c8d8f0;
    --muted: #6b7a99;
    --text: #1a1a1a;
    --bright: #1a1a1a;
    --accent: #6495ED;
    --green: #3a7d44;
    --red: #c0392b;
    --yellow: #b07d2a;
    --key-bg: #dce8f8;
    --key-border: #c8d8f0;
    --focus-bg: #ffffff;
  }
  html, body { height: 100%; background: var(--bg); color: var(--text);
    font-family: "SF Mono", "Fira Code", "Cascadia Code", Consolas, monospace;
    font-size: 13px; line-height: 1.5; }

  #app { max-width: 860px; margin: 0 auto; padding: 24px 20px 80px; }

  /* Header */
  header { display: flex; align-items: baseline; gap: 16px; margin-bottom: 16px;
    border-bottom: 1px solid var(--border); padding-bottom: 14px; flex-wrap: wrap; }
  header h1 { font-size: 18px; font-weight: 600; color: var(--bright); }
  header .hint { color: var(--muted); font-size: 11px; flex: 1; }
  .header-folders { display: flex; gap: 14px; margin-left: auto; }
  .folder-link { color: var(--muted); cursor: pointer; font-size: 11px;
    white-space: nowrap; padding: 2px 4px; border-radius: 4px; }
  .folder-link:hover { color: var(--accent); background: var(--bubble); }

  /* Scan banner */
  #scan-banner:not(:empty) {
    background: #fffbe6; border: 1px solid #e8d060; border-radius: 8px;
    padding: 10px 14px; margin-bottom: 14px; font-size: 12px;
  }
  .scan-item { display: flex; align-items: center; gap: 10px; padding: 3px 0; }
  .scan-register-btn {
    font-size: 11px; padding: 3px 10px; border-radius: 6px; cursor: pointer;
    background: var(--accent); color: white; border: none; font-family: inherit;
  }
  .scan-register-btn:hover { opacity: 0.85; }

  /* Groups */
  .group-section { margin-bottom: 20px; }
  .group-header {
    display: flex; align-items: center; gap: 10px;
    padding: 5px 10px; margin-bottom: 6px;
    border-radius: 8px; cursor: pointer; outline: none; user-select: none;
    transition: background 0.1s;
  }
  .group-header:hover { background: var(--bubble); }
  .group-header.focused { background: var(--bubble); box-shadow: 0 0 0 2px rgba(100,149,237,0.25); }
  .group-arrow { font-size: 9px; color: var(--muted); width: 14px; flex-shrink: 0; }
  .group-name { font-weight: 700; font-size: 11px; color: var(--muted);
    letter-spacing: 0.08em; text-transform: uppercase; flex: 1; }
  .group-count { color: var(--muted); font-size: 11px; }
  .group-body.collapsed { display: none; }

  /* Script cards */
  .script-card {
    border: 1px solid var(--border);
    border-radius: 12px;
    margin-bottom: 8px;
    background: var(--surface);
    transition: border-color 0.1s, box-shadow 0.1s;
    outline: none;
    cursor: pointer;
  }
  .script-card:hover { border-color: #a8c0e8; box-shadow: 0 1px 4px rgba(100,149,237,0.1); }
  .script-card.focused { border-color: var(--accent); background: var(--focus-bg); box-shadow: 0 0 0 2px rgba(100,149,237,0.2); }
  .script-card.running { border-color: var(--yellow); }
  .script-card.success { border-color: var(--green); }
  .script-card.failure { border-color: var(--red); }

  .card-summary { display: flex; align-items: center; gap: 12px; padding: 10px 14px; }
  .key-badge {
    display: inline-flex; align-items: center; justify-content: center;
    min-width: 26px; height: 26px; padding: 0 6px;
    background: var(--key-bg); border: 1px solid var(--key-border);
    border-radius: 6px; font-size: 13px; font-weight: 700; color: var(--accent);
    flex-shrink: 0;
  }
  .script-name { font-weight: 600; color: var(--bright); flex: 1 1 auto; }
  .script-desc { color: var(--muted); flex: 2 1 auto; white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis; }
  .expand-wrap { display: flex; flex-direction: column; align-items: flex-end;
    flex-shrink: 0; gap: 1px; }
  .expand-btn {
    background: none; border: none; color: var(--muted); cursor: pointer;
    font-size: 11px; padding: 2px 4px; font-family: inherit;
  }
  .expand-btn:hover { color: var(--text); }
  .last-run-inline { font-size: 10px; color: var(--muted); padding-right: 4px; }

  /* Details line (permanent, under summary) */
  .details-line {
    display: flex; align-items: center; flex-wrap: wrap; gap: 14px;
    padding: 5px 14px 7px 52px;
    border-top: 1px solid var(--border);
    font-size: 11px; color: var(--muted);
  }
  .dl-item { white-space: nowrap; cursor: default; }
  .dl-item.clickable { cursor: pointer; }
  .dl-item.clickable:hover { color: var(--accent); }

  /* Inline log viewer */
  .log-viewer {
    display: none; margin: 0 14px 10px 52px;
    border: 1px solid var(--border); border-radius: 6px;
    background: #f6f8fc; overflow: hidden; font-size: 11px;
  }
  .log-viewer.open { display: block; }
  .log-section { padding: 8px 10px; }
  .log-section + .log-section { border-top: 1px solid var(--border); }
  .log-label { font-size: 10px; color: var(--muted); text-transform: uppercase;
    letter-spacing: 0.05em; margin-bottom: 4px; }
  .log-viewer pre { white-space: pre-wrap; word-break: break-all;
    max-height: 160px; overflow-y: auto; color: var(--text); }
  .log-viewer .log-stderr pre { color: var(--red); }

  /* Existing card details (⌘d dropdown, kept) */
  .card-details { padding: 0 14px 12px 52px; display: none; font-size: 12px; color: var(--muted); }
  .card-details.open { display: block; }
  .card-details table { border-collapse: collapse; }
  .card-details td { padding: 1px 12px 1px 0; vertical-align: top; }
  .card-details td:first-child { color: var(--muted); white-space: nowrap; }
  .card-details td:last-child { color: var(--text); word-break: break-all; }
  .file-list { display: flex; flex-direction: column; gap: 2px; }
  .file-tag { display: inline-block; background: var(--bubble); border: 1px solid var(--border);
    border-radius: 4px; padding: 0 5px; font-size: 11px; }

  /* Spinner */
  @keyframes spin { to { transform: rotate(360deg); } }
  .spinner { display: inline-block; width: 12px; height: 12px;
    border: 2px solid var(--border); border-top-color: var(--accent);
    border-radius: 50%; animation: spin 0.6s linear infinite; flex-shrink: 0; }

  /* Output panel */
  #output-wrap {
    position: fixed; bottom: 0; left: 0; right: 0;
    background: var(--bubble); border-top: 1px solid var(--border);
    max-height: 40vh; display: flex; flex-direction: column;
    transform: translateY(100%); transition: transform 0.2s ease;
  }
  #output-wrap.open { transform: translateY(0); }
  #output-header {
    display: flex; align-items: center; gap: 10px;
    padding: 6px 14px; border-bottom: 1px solid var(--border);
    font-size: 11px; color: var(--muted); flex-shrink: 0;
  }
  #output-title { flex: 1; color: var(--text); }
  #output-close { background: none; border: none; color: var(--muted);
    cursor: pointer; font-size: 14px; line-height: 1; padding: 0 4px; }
  #output-close:hover { color: var(--text); }
  #output-body { overflow-y: auto; padding: 10px 14px; }
  #output-body pre { white-space: pre-wrap; word-break: break-all; font-size: 12px; color: var(--text); }
  #output-body .stderr { color: var(--red); }

  /* Toast */
  #toast {
    position: fixed; top: 16px; right: 16px; z-index: 9999;
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 10px 16px; font-size: 13px;
    box-shadow: 0 4px 16px rgba(0,0,0,0.1);
    opacity: 0; transform: translateY(-8px);
    transition: opacity 0.2s, transform 0.2s;
    pointer-events: none; max-width: 340px;
  }
  #toast.show { opacity: 1; transform: translateY(0); pointer-events: auto; }
  #toast.ok { border-color: var(--green); color: var(--green); }
  #toast.err { border-color: var(--red); color: var(--red); }

  #empty { color: var(--muted); padding: 40px 0; text-align: center; }
</style>
</head>
<body>
<div id="app">
  <header>
    <h1>Scripty</h1>
    <span class="hint">key to run · ↑↓/j/k navigate · ⌘p toggle groups · ⌘d details · esc close output</span>
    <div class="header-folders">
      <span class="folder-link" id="hdr-agents">📁 LaunchAgents</span>
      <span class="folder-link" id="hdr-staging">📁 Staging</span>
    </div>
  </header>
  <div id="scan-banner"></div>
  <div id="scripts-list"><div id="empty">Loading…</div></div>
</div>

<div id="output-wrap">
  <div id="output-header">
    <span id="output-title"></span>
    <span id="output-status"></span>
    <button id="output-close" title="Close (Esc)">×</button>
  </div>
  <div id="output-body">
    <pre id="stdout-pre"></pre>
    <pre id="stderr-pre" class="stderr"></pre>
  </div>
</div>

<div id="toast"></div>

<script>
(function () {
  let groups = [];
  let flatItems = [];
  let focusIdx = 0;
  let running = false;
  let launchdStatus = {};

  // ── Key parsing ────────────────────────────────────────────────────────────
  function parseKey(keyStr) {
    let s = String(keyStr);
    let meta = false, shift = false, alt = false;
    if (s.includes('⌘')) { meta = true;  s = s.replace('⌘', ''); }
    if (s.includes('⌥')) { alt  = true;  s = s.replace('⌥', ''); }
    if (s.includes('⇧')) { shift = true; s = s.replace('⇧', ''); }
    if (!shift && s.length === 1 && s === s.toUpperCase() && s !== s.toLowerCase()) shift = true;
    return { meta, shift, alt, key: s.toLowerCase() };
  }

  const _RISKY = new Set(['⌘w','⌘t','⌘n','⌘r','⌘q','⌘z','⌘x','⌘c','⌘v','⌘a','⌘s','⌘,',
                          '⌘⇧t','⌘⇧n','⌘⇧w']);
  function warnIfRisky(keyStr, name) {
    const p = parseKey(keyStr);
    const repr = (p.meta ? '⌘' : '') + (p.shift ? '⇧' : '') + (p.alt ? '⌥' : '') + p.key;
    if (_RISKY.has(repr))
      console.warn(`[Scripty] "${name}" uses key "${keyStr}" (${repr}) which may conflict with browser/OS shortcuts.`);
  }

  function matchesKey(parsed, e) {
    if (!parsed) return false;
    return e.metaKey === parsed.meta && e.shiftKey === parsed.shift
        && e.altKey === parsed.alt && !e.ctrlKey
        && e.key.toLowerCase() === parsed.key;
  }

  // ── Navigation list ────────────────────────────────────────────────────────
  function buildFlatItems() {
    flatItems = [];
    groups.forEach((g, gi) => {
      flatItems.push({ type: 'group', gi, group: g });
      if (!g.collapsed) {
        (g.scripts || []).forEach((s, si) => {
          flatItems.push({ type: 'script', gi, si, script: s });
        });
      }
    });
  }

  // ── Load ───────────────────────────────────────────────────────────────────
  async function loadScripts() {
    const [configResult, statusResult] = await Promise.allSettled([
      fetch('/scripty/config').then(r => r.json()),
      fetch('/scripty/launchd/status').then(r => r.json()),
    ]);
    groups = configResult.status === 'fulfilled' ? configResult.value : [];
    launchdStatus = statusResult.status === 'fulfilled' ? statusResult.value : {};

    for (const g of groups) {
      for (const s of (g.scripts || [])) {
        s._parsed = parseKey(s.key || '');
        warnIfRisky(s.key || '', s.name || '');
      }
    }
    buildFlatItems();
    render();
    scanPlists();
  }

  async function loadLaunchdStatus() {
    try {
      const r = await fetch('/scripty/launchd/status');
      launchdStatus = await r.json();
    } catch (e) {
      console.warn('[Scripty] Failed to fetch launchd status:', e);
    }
  }

  // ── Scan banner ────────────────────────────────────────────────────────────
  async function scanPlists() {
    const banner = document.getElementById('scan-banner');
    try {
      const r = await fetch('/scripty/launchd/scan');
      const plists = await r.json();
      if (!plists.length) { banner.innerHTML = ''; return; }
      banner.innerHTML = plists.map(p =>
        `<div class="scan-item" data-plist="${esc(p)}">` +
        `New plist found: <strong>${esc(p)}</strong> — ` +
        `<button class="scan-register-btn">Register</button></div>`
      ).join('');
      banner.querySelectorAll('.scan-register-btn').forEach(btn => {
        const plist = btn.closest('.scan-item').dataset.plist;
        btn.addEventListener('click', () => registerPlist(plist));
      });
    } catch (e) {
      banner.innerHTML = '';
      console.warn('[Scripty] launchd scan failed:', e);
    }
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  function render() {
    buildFlatItems();
    const list = document.getElementById('scripts-list');
    if (!groups.length) {
      list.innerHTML = '<div id="empty">No scripts found in config.json</div>';
      return;
    }
    list.innerHTML = '';
    groups.forEach((g, gi) => {
      const section = document.createElement('div');
      section.className = 'group-section';

      const hdr = document.createElement('div');
      hdr.className = 'group-header';
      hdr.id = `gh-${gi}`;
      hdr.tabIndex = 0;
      const cnt = (g.scripts || []).length;
      hdr.innerHTML =
        `<span class="group-arrow">${g.collapsed ? '▶' : '▼'}</span>`
        + `<span class="group-name">${esc(g.group || 'Untitled')}</span>`
        + `<span class="group-count">${cnt} script${cnt !== 1 ? 's' : ''}</span>`;
      hdr.addEventListener('click', () => {
        const fi = flatItems.findIndex(f => f.type === 'group' && f.gi === gi);
        if (fi !== -1) focusIdx = fi;
        toggleGroup(gi);
      });
      section.appendChild(hdr);

      const body = document.createElement('div');
      body.className = 'group-body' + (g.collapsed ? ' collapsed' : '');
      (g.scripts || []).forEach((s, si) => body.appendChild(buildCard(gi, si, s)));
      section.appendChild(body);
      list.appendChild(section);
    });
    applyFocus();
  }

  // ── Card builder ───────────────────────────────────────────────────────────
  function buildCard(gi, si, s) {
    const card = document.createElement('div');
    card.className = 'script-card';
    card.id = `sc-${gi}-${si}`;
    const outputs = (s.output_files || []).map(f => `<span class="file-tag">${esc(f)}</span>`).join('');
    const inputs  = (s.input_files  || []).map(f => `<span class="file-tag">${esc(f)}</span>`).join('');
    card.innerHTML = `
      <div class="card-summary">
        <span class="key-badge">${esc(s.key)}</span>
        <span class="script-name">${esc(s.name)}</span>
        <span class="script-desc">${esc(s.description || '')}</span>
        <div class="expand-wrap">
          <button class="expand-btn" title="Toggle details (⌘d)">▸ details</button>
          <span class="last-run-inline" id="lri-${gi}-${si}">${fmtShortDate(s.last_run)}</span>
        </div>
      </div>
      <div class="card-details" id="det-${gi}-${si}">
        <table>
          <tr><td>file</td><td>${esc((s.path || '') + (s.file || ''))}</td></tr>
          ${s.run_folder ? `<tr><td>run in</td><td>${esc(s.run_folder)}</td></tr>` : ''}
          ${s.command ? `<tr><td>command</td><td>${esc(s.command)}</td></tr>` : ''}
          ${inputs  ? `<tr><td>inputs</td><td><div class="file-list">${inputs}</div></td></tr>`  : ''}
          ${outputs ? `<tr><td>outputs</td><td><div class="file-list">${outputs}</div></td></tr>` : ''}
          <tr><td>last run</td><td id="lr-${gi}-${si}">${fmtLastRun(s.last_run)}</td></tr>
        </table>
      </div>`;

    // Insert permanent details line and log viewer before the ⌘d dropdown
    const detTable = card.querySelector('.card-details');
    card.insertBefore(buildLogViewer(gi, si), detTable);
    card.insertBefore(buildDetailsLine(gi, si, s), card.querySelector('.log-viewer'));

    card.addEventListener('click', (e) => {
      if (e.target.closest('.expand-wrap') || e.target.closest('.details-line') || e.target.closest('.log-viewer')) return;
      focusCard(gi, si);
      runEntry(gi, si, s);
    });
    card.querySelector('.expand-btn').addEventListener('click', (e) => {
      e.stopPropagation();
      focusCard(gi, si);
      toggleDetails(gi, si);
    });
    return card;
  }

  // ── Details line (permanent) ───────────────────────────────────────────────
  function buildDetailsLine(gi, si, s) {
    const line = document.createElement('div');
    line.className = 'details-line';

    // 📁 output folder
    const outPath = (s.output_files || [])[0] || '';
    if (outPath) {
      line.appendChild(makeItem('📁 ' + (s.output_label || outPath), outPath,
        () => openFolder(outPath)));
    }

    // 📂 script folder
    const scriptPath = s.path || '';
    if (scriptPath) {
      line.appendChild(makeItem('📂 ' + (s.path_label || scriptPath), scriptPath,
        () => openFolder(scriptPath)));
    }

    // Launchd items (only if script has launchd config)
    const ld = s.launchd;
    if (ld) {
      const plist = ld.plist || '';
      const name  = ld.name  || '';
      const st    = launchdStatus[plist] || {};

      // 📋 logs
      if (name) {
        line.appendChild(makeItem('📋 logs', 'View last 50 lines of stdout/stderr',
          () => toggleLogs(gi, si, name)));
      }

      // ⏱ schedule
      const iv = st.interval || '';
      const tm = st.time     || '';
      const schedText = iv ? `⏱ ${iv} ${tm}` : '⏱ —';
      line.appendChild(makeItem(schedText, 'Click to edit schedule',
        () => editSchedule(plist, iv, tm)));

      // 🟢/🔴/⚪ status
      const status = st.status || 'unregistered';
      const icon = status === 'loaded' ? '🟢' : (status === 'not-loaded' ? '🔴' : '⚪');
      line.appendChild(makeItem(`${icon} ${status}`, status,
        () => toggleLaunchdStatus(plist, name, status)));
    }

    // ✓ last run
    const lrSpan = document.createElement('span');
    lrSpan.className = 'dl-item';
    lrSpan.id = `dlr-${gi}-${si}`;
    lrSpan.textContent = s.last_run ? '✓ ' + fmtDetailsDate(s.last_run) : 'never run';
    line.appendChild(lrSpan);

    return line;
  }

  function makeItem(text, title, onClick) {
    const span = document.createElement('span');
    span.className = 'dl-item clickable';
    span.textContent = text;
    if (title) span.title = title;
    span.addEventListener('click', (e) => { e.stopPropagation(); onClick(); });
    return span;
  }

  // ── Log viewer ─────────────────────────────────────────────────────────────
  function buildLogViewer(gi, si) {
    const viewer = document.createElement('div');
    viewer.className = 'log-viewer';
    viewer.id = `log-${gi}-${si}`;
    viewer.innerHTML = `
      <div class="log-section log-stdout">
        <div class="log-label">stdout</div>
        <pre></pre>
      </div>
      <div class="log-section log-stderr">
        <div class="log-label">stderr</div>
        <pre></pre>
      </div>`;
    return viewer;
  }

  async function toggleLogs(gi, si, name) {
    const viewer = document.getElementById(`log-${gi}-${si}`);
    if (!viewer) return;
    if (viewer.classList.contains('open')) {
      viewer.classList.remove('open');
      return;
    }
    try {
      const r = await fetch(`/scripty/launchd/logs/${encodeURIComponent(name)}?lines=50`);
      const data = await r.json();
      viewer.querySelector('.log-stdout pre').textContent = data.stdout || '(empty)';
      viewer.querySelector('.log-stderr pre').textContent = data.stderr || '(empty)';
    } catch (e) {
      viewer.querySelector('.log-stdout pre').textContent = 'Error loading logs: ' + e;
      viewer.querySelector('.log-stderr pre').textContent = '';
    }
    viewer.classList.add('open');
  }

  // ── Launchd actions ────────────────────────────────────────────────────────
  async function openFolder(path) {
    try {
      await fetch('/scripty/open-folder', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path }),
      });
    } catch (e) {
      console.warn('[Scripty] open-folder failed:', e);
    }
  }

  async function editSchedule(plist, currentInterval, currentTime) {
    const interval = prompt('Interval (hourly / daily / weekly):', currentInterval || 'daily');
    if (!interval) return;
    const time = prompt('Start time (HH:MM, 24h):', currentTime || '09:00');
    if (!time) return;
    try {
      const r = await fetch('/scripty/launchd/update-schedule', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plist, interval, time }),
      });
      if (!r.ok) { const e = await r.json(); showToast('Schedule update failed: ' + e.detail, 'err'); return; }
      showToast('Schedule updated', 'ok');
      await loadLaunchdStatus();
      render();
    } catch (e) {
      showToast('Schedule update failed: ' + e, 'err');
    }
  }

  async function toggleLaunchdStatus(plist, name, status) {
    if (status === 'loaded' || status === 'not-loaded') {
      if (!confirm(`Unregister "${name || plist}"?`)) return;
      try {
        const r = await fetch('/scripty/launchd/unregister', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ plist }),
        });
        if (!r.ok) { const e = await r.json(); showToast('Unregister failed: ' + e.detail, 'err'); return; }
        showToast('Unregistered ' + (name || plist), 'ok');
      } catch (e) {
        showToast('Unregister failed: ' + e, 'err');
        return;
      }
    } else {
      await registerPlist(plist);
      return;
    }
    await loadLaunchdStatus();
    render();
  }

  async function registerPlist(plist) {
    const key = prompt(`Script key for "${plist}":`);
    if (!key) return;
    const interval = prompt('Interval (hourly / daily / weekly):', 'daily');
    if (!interval) return;
    const time = prompt('Start time (HH:MM, 24h):', '09:00');
    if (!time) return;
    try {
      const r = await fetch('/scripty/launchd/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plist, script_key: key, interval, time }),
      });
      if (!r.ok) { const e = await r.json(); showToast('Register failed: ' + e.detail, 'err'); return; }
      showToast('Registered ' + plist, 'ok');
      await loadScripts();
    } catch (e) {
      showToast('Register failed: ' + e, 'err');
    }
  }

  // ── Focus helpers ──────────────────────────────────────────────────────────
  function applyFocus() {
    document.querySelectorAll('.script-card.focused, .group-header.focused')
      .forEach(el => el.classList.remove('focused'));
    const item = flatItems[focusIdx];
    if (!item) return;
    const el = item.type === 'group'
      ? document.getElementById(`gh-${item.gi}`)
      : document.getElementById(`sc-${item.gi}-${item.si}`);
    if (el) { el.classList.add('focused'); el.scrollIntoView({ block: 'nearest' }); }
  }

  function setFocus(idx) {
    focusIdx = Math.max(0, Math.min(flatItems.length - 1, idx));
    applyFocus();
  }

  function focusCard(gi, si) {
    const fi = flatItems.findIndex(f => f.type === 'script' && f.gi === gi && f.si === si);
    if (fi !== -1) setFocus(fi);
  }

  // ── Group collapse ─────────────────────────────────────────────────────────
  async function toggleGroup(gi) {
    groups[gi].collapsed = !groups[gi].collapsed;
    buildFlatItems();
    focusIdx = Math.min(focusIdx, Math.max(0, flatItems.length - 1));
    render();
    try {
      await fetch('/scripty/collapse', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ group: groups[gi].group, collapsed: groups[gi].collapsed }),
      });
    } catch (e) {
      console.warn('[Scripty] Failed to persist collapse state:', e);
    }
  }

  // ── Details (⌘d dropdown) ──────────────────────────────────────────────────
  function toggleDetails(gi, si) {
    const det = document.getElementById(`det-${gi}-${si}`);
    if (!det) return;
    det.classList.toggle('open');
    const btn = document.getElementById(`sc-${gi}-${si}`)?.querySelector('.expand-btn');
    if (btn) btn.textContent = det.classList.contains('open') ? '▾ details' : '▸ details';
  }

  // ── Run ────────────────────────────────────────────────────────────────────
  async function runEntry(gi, si, s) {
    if (running) return;
    running = true;
    const card = document.getElementById(`sc-${gi}-${si}`);
    let spinner;
    if (card) {
      spinner = document.createElement('span');
      spinner.className = 'spinner';
      const summary = card.querySelector('.card-summary');
      summary.insertBefore(spinner, summary.querySelector('.expand-wrap'));
      card.classList.add('running');
      card.classList.remove('success', 'failure');
    }
    let result;
    try {
      const r = await fetch('/scripty/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: s.key }),
      });
      result = await r.json();
    } catch (e) {
      result = { returncode: 1, stdout: '', stderr: String(e) };
    } finally {
      running = false;
      spinner?.remove();
    }
    const ok = result.returncode === 0;
    if (card) {
      card.classList.remove('running');
      card.classList.add(ok ? 'success' : 'failure');
      setTimeout(() => card.classList.remove('success', 'failure'), 3000);
    }
    if (ok && result.last_run) {
      groups[gi].scripts[si].last_run = result.last_run;
      const cell = document.getElementById(`lr-${gi}-${si}`);
      if (cell) cell.textContent = fmtLastRun(result.last_run);
      const inline = document.getElementById(`lri-${gi}-${si}`);
      if (inline) inline.textContent = fmtShortDate(result.last_run);
      const dlr = document.getElementById(`dlr-${gi}-${si}`);
      if (dlr) dlr.textContent = '✓ ' + fmtDetailsDate(result.last_run);
    }
    showToast(ok ? `✓ ${s.name}` : `✗ ${s.name} (exit ${result.returncode})`, ok ? 'ok' : 'err');
    showOutput(s.name, result);
  }

  // ── Helpers ────────────────────────────────────────────────────────────────
  function esc(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }
  function fmtLastRun(iso) {
    if (!iso) return 'Never';
    return new Date(iso).toLocaleString(undefined, {
      month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit',
    });
  }
  function fmtShortDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    return `${d.getMonth() + 1}/${d.getDate()}/${String(d.getFullYear()).slice(-2)}`;
  }
  function fmtDetailsDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    const yyyy = d.getFullYear();
    const mm   = String(d.getMonth() + 1).padStart(2, '0');
    const dd   = String(d.getDate()).padStart(2, '0');
    const hh   = String(d.getHours()).padStart(2, '0');
    const min  = String(d.getMinutes()).padStart(2, '0');
    return `${yyyy}-${mm}-${dd} ${hh}:${min}`;
  }

  // ── Output panel ───────────────────────────────────────────────────────────
  function showOutput(name, result) {
    document.getElementById('output-title').textContent = name;
    const st = document.getElementById('output-status');
    st.textContent = result.returncode === 0 ? '✓ ok' : `✗ exit ${result.returncode}`;
    st.style.color  = result.returncode === 0 ? 'var(--green)' : 'var(--red)';
    document.getElementById('stdout-pre').textContent = result.stdout || '';
    document.getElementById('stderr-pre').textContent = result.stderr || '';
    document.getElementById('output-wrap').classList.add('open');
  }
  function closeOutput() {
    document.getElementById('output-wrap').classList.remove('open');
  }
  document.getElementById('output-close').addEventListener('click', closeOutput);

  // ── Toast ──────────────────────────────────────────────────────────────────
  let toastTimer;
  function showToast(msg, type) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.className = 'show ' + type;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.className = ''; }, 3500);
  }

  // ── Expand / collapse all ──────────────────────────────────────────────────
  async function setAllCollapsed(collapsed) {
    for (const g of groups) g.collapsed = collapsed;
    buildFlatItems();
    focusIdx = Math.min(focusIdx, Math.max(0, flatItems.length - 1));
    render();
    try {
      await fetch('/scripty/collapse-all', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ collapsed }),
      });
    } catch (e) {
      console.warn('[Scripty] Failed to persist collapse-all state:', e);
    }
  }

  // ── Header folder links ────────────────────────────────────────────────────
  document.getElementById('hdr-agents').addEventListener('click',
    () => openFolder('~/Library/LaunchAgents/'));
  document.getElementById('hdr-staging').addEventListener('click',
    () => openFolder('~/Dropbox/2tech/scripty/launchd/plists/'));

  // ── Keyboard ───────────────────────────────────────────────────────────────
  document.addEventListener('keydown', (e) => {
    if (e.metaKey && !e.shiftKey && !e.altKey && !e.ctrlKey && e.key === 'd') {
      e.preventDefault();
      const item = flatItems[focusIdx];
      if (item?.type === 'script') toggleDetails(item.gi, item.si);
      return;
    }
    if (e.metaKey && !e.shiftKey && !e.altKey && !e.ctrlKey && e.key === 'p') {
      e.preventDefault();
      setAllCollapsed(groups.some(g => !g.collapsed));
      return;
    }

    if (!e.metaKey && !e.altKey && !e.ctrlKey) {
      const item = flatItems[focusIdx];
      if (e.key === 'ArrowDown' || (!e.shiftKey && e.key === 'j')) {
        e.preventDefault(); setFocus(focusIdx + 1); return;
      }
      if (e.key === 'ArrowUp' || (!e.shiftKey && e.key === 'k')) {
        e.preventDefault(); setFocus(focusIdx - 1); return;
      }
      if (e.key === 'Enter') {
        e.preventDefault();
        if (item?.type === 'group') toggleGroup(item.gi);
        else if (item?.type === 'script') runEntry(item.gi, item.si, item.script);
        return;
      }
      if (e.key === 'Escape') { closeOutput(); return; }
      if (item?.type === 'group') {
        if (e.key === 'ArrowLeft'  && !item.group.collapsed) { e.preventDefault(); toggleGroup(item.gi); return; }
        if (e.key === 'ArrowRight' &&  item.group.collapsed) { e.preventDefault(); toggleGroup(item.gi); return; }
      }
    }

    for (const g of groups) {
      for (const s of (g.scripts || [])) {
        if (matchesKey(s._parsed, e)) {
          e.preventDefault();
          const gi = groups.indexOf(g);
          const si = g.scripts.indexOf(s);
          const fi = flatItems.findIndex(f => f.type === 'script' && f.gi === gi && f.si === si);
          if (fi !== -1) setFocus(fi);
          runEntry(gi, si, s);
          return;
        }
      }
    }
  });

  loadScripts();
})();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Routes — existing
# ---------------------------------------------------------------------------


@router.get("/scripty", response_class=HTMLResponse)
def scripty_page():
    return HTMLResponse(content=_HTML)


@router.get("/scripty/config")
def scripty_config():
    return JSONResponse(content=_load_config())


class RunBody(BaseModel):
    key: str


@router.post("/scripty/run")
def scripty_run(body: RunBody):
    config = _load_config()
    entry = _find_entry(config, body.key)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"No script with key '{body.key}'")

    cmd = _build_cmd(entry)

    if entry.get("run_folder"):
        cwd = Path(entry["run_folder"]).expanduser()
    else:
        cwd = (Path(entry["path"]).expanduser() / entry["file"]).parent

    logger.info("scripty: running key=%s cmd=%s cwd=%s", body.key, cmd, cwd)
    try:
        result = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=300,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=422, detail=f"Executable not found: {e}")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=408, detail="Script timed out (300s limit)")

    last_run: str | None = None
    if result.returncode == 0:
        last_run = datetime.now(timezone.utc).isoformat()
        _update_last_run(body.key, last_run)

    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "last_run": last_run,
    }


class CollapseBody(BaseModel):
    group: str
    collapsed: bool


@router.post("/scripty/collapse")
def scripty_collapse(body: CollapseBody):
    _update_collapse(body.group, body.collapsed)
    return {"status": "ok"}


class CollapseAllBody(BaseModel):
    collapsed: bool


@router.post("/scripty/collapse-all")
def scripty_collapse_all(body: CollapseAllBody):
    _update_collapse_all(body.collapsed)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Routes — new: Finder / folder opener
# ---------------------------------------------------------------------------


class OpenFolderBody(BaseModel):
    path: str


@router.post("/scripty/open-folder")
def scripty_open_folder(body: OpenFolderBody):
    """Open a path in Finder via macOS `open`."""
    p = Path(body.path).expanduser()
    subprocess.Popen(["open", str(p)])
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Routes — new: launchd integration
# ---------------------------------------------------------------------------


class LaunchdRegisterBody(BaseModel):
    plist: str
    script_key: str = ""  # if empty, a new stub entry is appended to the launchd group
    interval: str        # hourly | daily | weekly
    time: str            # HH:MM (24h)
    name: str = ""       # log subfolder; derived from plist Label if empty


class LaunchdUnregisterBody(BaseModel):
    plist: str


class LaunchdUpdateScheduleBody(BaseModel):
    plist: str
    interval: str
    time: str


@router.get("/scripty/launchd/scan")
def launchd_scan():
    """Return .plist filenames in staging that are not yet in LaunchAgents."""
    result = []
    for plist in sorted(LAUNCHD_STAGING.glob("*.plist")):
        if not (LAUNCH_AGENTS / plist.name).exists():
            result.append(plist.name)
    return result


@router.post("/scripty/launchd/register")
def launchd_register(body: LaunchdRegisterBody):
    """Copy plist from staging → LaunchAgents with updated schedule, then launchctl load."""
    staging_plist = LAUNCHD_STAGING / body.plist
    if not staging_plist.exists():
        raise HTTPException(status_code=404, detail=f"Plist not found in staging: {body.plist}")

    plist_data = _read_plist_safe(staging_plist)
    plist_data["StartCalendarInterval"] = _make_schedule(body.interval, body.time)

    # Write updated schedule back to staging (source of truth)
    with open(staging_plist, "wb") as f:
        plistlib.dump(plist_data, f)

    # Copy to LaunchAgents
    dest = LAUNCH_AGENTS / body.plist
    shutil.copy2(staging_plist, dest)

    # Load into launchd
    lc = subprocess.run(
        ["launchctl", "load", str(dest)], capture_output=True, text=True
    )
    if lc.returncode != 0:
        logger.warning("scripty: launchctl load returned %d: %s", lc.returncode, lc.stderr)

    label = plist_data.get("Label", body.plist.replace(".plist", ""))

    # Derive log folder name: body > strip com.stevevinter. prefix from label > last label segment
    if body.name:
        name = body.name
    else:
        stripped = label.removeprefix("com.stevevinter.")
        name = stripped if stripped else label.split(".")[-1]

    # Ensure log directory exists
    (LAUNCHD_LOGS / name).mkdir(parents=True, exist_ok=True)

    # Infer script file / path from ProgramArguments
    prog_args: list[str] = plist_data.get("ProgramArguments", [])
    script_full = prog_args[-1] if prog_args else ""
    inferred_file = Path(script_full).name if script_full else ""
    inferred_path = str(Path(script_full).parent) + "/" if script_full else ""

    # Infer log overrides from plist StandardOutPath / StandardErrorPath
    log_stdout: str | None = plist_data.get("StandardOutPath") or None
    log_stderr: str | None = plist_data.get("StandardErrorPath") or None

    launchd_block: dict = {"name": name, "plist": body.plist}
    if log_stdout:
        launchd_block["log_stdout"] = log_stdout
    if log_stderr:
        launchd_block["log_stderr"] = log_stderr

    full = _load_full_config()

    if body.script_key:
        # Attach launchd block to an existing entry identified by key
        entry = _find_entry(full["groups"], body.script_key)
        if entry is not None:
            entry["launchd"] = launchd_block
    else:
        # Build a stub entry and append it to the "launchd" group (create if absent)
        stub: dict = {
            "key": "",
            "name": "",
            "description": "",
            "file": inferred_file,
            "path": inferred_path,
            "path_label": "",
            "output_label": "",
            "run_folder": None,
            "input_files": [],
            "output_files": [],
            "show_output": False,
            "last_run": None,
            "launchd": launchd_block,
        }
        groups: list[dict] = full.get("groups", [])
        launchd_group = next((g for g in groups if g.get("group") == "launchd"), None)
        if launchd_group is None:
            launchd_group = {"group": "launchd", "collapsed": False, "scripts": []}
            groups.append(launchd_group)
            full["groups"] = groups
        launchd_group.setdefault("scripts", []).append(stub)

    _atomic_write_full(full)

    return {"status": "ok", "label": label, "name": name}


@router.post("/scripty/launchd/unregister")
def launchd_unregister(body: LaunchdUnregisterBody):
    """launchctl unload then remove plist from LaunchAgents."""
    dest = LAUNCH_AGENTS / body.plist
    if not dest.exists():
        raise HTTPException(status_code=404, detail=f"Plist not registered: {body.plist}")
    subprocess.run(["launchctl", "unload", str(dest)], capture_output=True, text=True)
    dest.unlink(missing_ok=True)
    return {"status": "ok"}


@router.post("/scripty/launchd/update-schedule")
def launchd_update_schedule(body: LaunchdUpdateScheduleBody):
    """Update StartCalendarInterval in both staging and LaunchAgents, then reload."""
    schedule = _make_schedule(body.interval, body.time)

    # Update staging
    staging_plist = LAUNCHD_STAGING / body.plist
    if staging_plist.exists():
        pdata = _read_plist_safe(staging_plist)
        pdata["StartCalendarInterval"] = schedule
        with open(staging_plist, "wb") as f:
            plistlib.dump(pdata, f)

    # Update and reload LaunchAgents copy
    agents_plist = LAUNCH_AGENTS / body.plist
    if not agents_plist.exists():
        raise HTTPException(status_code=404, detail=f"Plist not registered: {body.plist}")

    pdata = _read_plist_safe(agents_plist)
    pdata["StartCalendarInterval"] = schedule
    with open(agents_plist, "wb") as f:
        plistlib.dump(pdata, f)

    subprocess.run(["launchctl", "unload", str(agents_plist)], capture_output=True, text=True)
    lc = subprocess.run(
        ["launchctl", "load", str(agents_plist)], capture_output=True, text=True
    )
    if lc.returncode != 0:
        raise HTTPException(status_code=500, detail=f"launchctl load failed: {lc.stderr}")

    return {"status": "ok"}


@router.get("/scripty/launchd/status")
def launchd_status():
    """Return loaded/schedule status for every launchd-configured script in config."""
    config = _load_config()
    loaded_labels = _get_loaded_labels()
    result: dict = {}

    for group in config:
        for script in group.get("scripts", []):
            ld = script.get("launchd")
            if not ld:
                continue
            plist_name = ld.get("plist", "")
            agents_path  = LAUNCH_AGENTS   / plist_name
            staging_path = LAUNCHD_STAGING / plist_name

            label = interval = time_str = ""
            src = agents_path if agents_path.exists() else staging_path
            if src.exists():
                pdata = _read_plist_safe(src)
                label = pdata.get("Label", "")
                interval, time_str = _parse_schedule(pdata)

            registered = agents_path.exists()
            loaded     = bool(label) and label in loaded_labels
            status_str = "loaded" if loaded else ("not-loaded" if registered else "unregistered")

            result[plist_name] = {
                "registered": registered,
                "status":     status_str,
                "interval":   interval,
                "time":       time_str,
                "label":      label,
            }

    return result


@router.get("/scripty/launchd/logs/{name}")
def launchd_logs(name: str, lines: int = 50):
    """Return last `lines` lines of stdout/stderr logs for the named script.

    Checks for log_stdout / log_stderr overrides on the matching script's
    launchd config block; falls back to the default
    ~/scripty/launchd/logs/<name>/{stdout,stderr}.log paths.
    """
    # Look up per-script log path overrides from config
    config = _load_config()
    overrides: dict[str, str | None] = {"stdout": None, "stderr": None}
    for group in config:
        for script in group.get("scripts", []):
            ld = script.get("launchd") or {}
            if ld.get("name") == name:
                overrides["stdout"] = ld.get("log_stdout")
                overrides["stderr"] = ld.get("log_stderr")
                break

    result: dict = {}
    default_dir = LAUNCHD_LOGS / name
    for kind in ("stdout", "stderr"):
        override = overrides[kind]
        log_file = Path(override).expanduser() if override else default_dir / f"{kind}.log"
        if log_file.exists():
            content = log_file.read_text(errors="replace")
            last_n = content.splitlines()[-lines:]
            result[kind] = "\n".join(last_n)
        else:
            result[kind] = ""
    return result

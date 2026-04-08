"""Scripty: keyboard-driven script launcher.

Root: ~/Dropbox/2tech/scripty/
Config: ~/Dropbox/2tech/scripty/config.json  (grouped format: [{group, collapsed, scripts:[...]}])

Routes:
  GET  /scripty          — self-contained HTML UI (no Dashy chrome)
  GET  /scripty/config   — JSON grouped config (read fresh)
  POST /scripty/run      — execute a script by key, return {returncode, stdout, stderr, last_run}
  POST /scripty/collapse — persist collapsed state for a group
"""

import json
import logging
import os
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

# Maps file extension → interpreter command
EXTENSION_INTERPRETERS: dict[str, list[str]] = {
    ".py": ["python3"],
    ".sh": ["bash"],
    ".zsh": ["zsh"],
    ".bash": ["bash"],
    ".rb": ["ruby"],
    ".js": ["node"],
    ".pl": ["perl"],
}


def _load_config() -> list[dict]:
    """Read config.json fresh from disk. Returns list of group objects."""
    if not CONFIG_FILE.exists():
        return []
    try:
        return json.loads(CONFIG_FILE.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("scripty: failed to read config: %s", e)
        return []


def _atomic_write(config: list[dict]) -> None:
    """Write config atomically: temp file → os.replace() (POSIX rename, same filesystem)."""
    tmp = CONFIG_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(config, indent=2))
        os.replace(tmp, CONFIG_FILE)
    except OSError as e:
        logger.warning("scripty: failed to write config: %s", e)
        tmp.unlink(missing_ok=True)
        raise


def _find_entry(config: list[dict], key: str) -> dict | None:
    """Return the first script entry matching key, searching across all groups."""
    for group in config:
        for entry in group.get("scripts", []):
            if entry.get("key") == key:
                return entry
    return None


def _update_last_run(key: str, timestamp: str) -> None:
    """Stamp last_run on the matching config entry and write back atomically."""
    config = _load_config()
    entry = _find_entry(config, key)
    if entry is None:
        return
    entry["last_run"] = timestamp
    try:
        _atomic_write(config)
    except OSError:
        pass  # already logged in _atomic_write


def _update_collapse(group_name: str, collapsed: bool) -> None:
    """Update collapsed state of a named group and write back atomically."""
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
    """Set collapsed state on every group and write back atomically."""
    config = _load_config()
    for group in config:
        group["collapsed"] = collapsed
    try:
        _atomic_write(config)
    except OSError:
        pass


def _build_cmd(entry: dict) -> list[str]:
    """Build the subprocess command list for a config entry."""
    if entry.get("command"):
        # Explicit command string — split naively (no shell quoting support needed)
        parts = entry["command"].split()
        # Resolve the file relative to path if command doesn't already include it
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
    # Fall back: try executing directly (relies on shebang)
    return [str(file_path)]


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

  header { display: flex; align-items: baseline; gap: 16px; margin-bottom: 24px;
    border-bottom: 1px solid var(--border); padding-bottom: 14px; }
  header h1 { font-size: 18px; font-weight: 600; color: var(--bright); }
  header .hint { color: var(--muted); font-size: 11px; }

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
  </header>
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
  let groups = [];    // grouped config from server
  let flatItems = []; // navigable items: [{type:'group'|'script', gi, si?, group?, script?}]
  let focusIdx = 0;
  let running = false;

  // ── Key parsing ────────────────────────────────────────────────────────────
  // Supported: "a"  "A"  "⇧a"  "⌘a"  "⌥a"  "⌘⇧a"
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
  // Includes group headers; script items only for expanded groups.
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
    try {
      const r = await fetch('/scripty/config');
      groups = await r.json();
    } catch (e) {
      groups = [];
    }
    for (const g of groups) {
      for (const s of (g.scripts || [])) {
        s._parsed = parseKey(s.key || '');
        warnIfRisky(s.key || '', s.name || '');
      }
    }
    buildFlatItems();
    render();
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

  function buildCard(gi, si, s) {
    const card = document.createElement('div');
    card.className = 'script-card';
    card.id = `sc-${gi}-${si}`;
    const inputs  = (s.input_files  || []).map(f => `<span class="file-tag">${esc(f)}</span>`).join('');
    const outputs = (s.output_files || []).map(f => `<span class="file-tag">${esc(f)}</span>`).join('');
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
    card.addEventListener('click', (e) => {
      if (e.target.closest('.expand-wrap')) { focusCard(gi, si); toggleDetails(gi, si); return; }
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

  // ── Group collapse ──────────────────────────────────────────────────────────
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

  // ── Details ────────────────────────────────────────────────────────────────
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
      card.querySelector('.card-summary').insertBefore(spinner, card.querySelector('.expand-btn'));
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

  // ── Output ─────────────────────────────────────────────────────────────────
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

  // ── Keyboard ───────────────────────────────────────────────────────────────
  document.addEventListener('keydown', (e) => {
    // ⌘d — toggle details for the focused script (takes priority)
    if (e.metaKey && !e.shiftKey && !e.altKey && !e.ctrlKey && e.key === 'd') {
      e.preventDefault();
      const item = flatItems[focusIdx];
      if (item?.type === 'script') toggleDetails(item.gi, item.si);
      return;
    }
    // ⌘p — toggle all groups (collapse all if any expanded, expand all if all collapsed)
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
      // ← collapse / → expand when a group header is focused
      if (item?.type === 'group') {
        if (e.key === 'ArrowLeft'  && !item.group.collapsed) { e.preventDefault(); toggleGroup(item.gi); return; }
        if (e.key === 'ArrowRight' &&  item.group.collapsed) { e.preventDefault(); toggleGroup(item.gi); return; }
      }
    }

    // Script key matching — searches ALL groups including collapsed ones
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
# Routes
# ---------------------------------------------------------------------------


@router.get("/scripty", response_class=HTMLResponse)
def scripty_page():
    """Serve the self-contained Scripty UI."""
    return HTMLResponse(content=_HTML)


@router.get("/scripty/config")
def scripty_config():
    """Return the grouped config (read fresh each call)."""
    return JSONResponse(content=_load_config())


class RunBody(BaseModel):
    key: str


@router.post("/scripty/run")
def scripty_run(body: RunBody):
    """Execute a script by key. Returns {returncode, stdout, stderr, last_run}."""
    config = _load_config()
    entry = _find_entry(config, body.key)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"No script with key '{body.key}'")

    cmd = _build_cmd(entry)

    # Determine working directory
    if entry.get("run_folder"):
        cwd = Path(entry["run_folder"]).expanduser()
    else:
        cwd = (Path(entry["path"]).expanduser() / entry["file"]).parent

    logger.info("scripty: running key=%s cmd=%s cwd=%s", body.key, cmd, cwd)
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=300,
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
    """Persist collapsed state for a group."""
    _update_collapse(body.group, body.collapsed)
    return {"status": "ok"}


class CollapseAllBody(BaseModel):
    collapsed: bool


@router.post("/scripty/collapse-all")
def scripty_collapse_all(body: CollapseAllBody):
    """Set collapsed state on all groups at once."""
    _update_collapse_all(body.collapsed)
    return {"status": "ok"}

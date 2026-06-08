"use strict";

// ── Topo assistant message (mirrors createAssistantMessage bubble pattern) ──

function createTopoAssistantMessage() {
  const msgsEl = document.getElementById("topo-messages");

  function scrollTopo() { msgsEl.scrollTop = msgsEl.scrollHeight; }

  let activeBubble  = null;
  let needNewBubble = false;

  function ensureBubble() {
    if (!activeBubble || needNewBubble) {
      activeBubble = document.createElement("div");
      activeBubble.className = "topo-bubble assistant";
      activeBubble._rawText = "";
      msgsEl.appendChild(activeBubble);
      scrollTopo();
      needNewBubble = false;
    }
    return activeBubble;
  }

  return {
    addToken(text) {
      const b = ensureBubble();
      b._rawText += text;
      b.innerHTML = renderMarkdown(b._rawText);
      scrollTopo();
    },
    afterToolCall() { needNewBubble = true; },
    finalize() {
      if (activeBubble && !activeBubble._rawText?.trim()) activeBubble.remove();
    },
  };
}

// ── Topology builder ───────────────────────────────────────────────────────

let topoMode              = false;
let topoDiscoveryId       = null;
let topoInstances         = [];
let topoActiveArea        = "All";
let topoDiscoveryComplete = false;

function enterTopologyMode() {
  if (topoMode) return;
  topoMode = true;
  // Reset commit button to disabled/clean state regardless of previous session
  const commitBtn = document.getElementById("topo-commit-btn");
  commitBtn.disabled = true;
  commitBtn.textContent = "commit to db";
  commitBtn.style.outline = "";
  commitBtn.style.outlineOffset = "";
  const diagView = document.getElementById("diagnostic-view");
  const topoEl   = document.getElementById("topo-builder");
  diagView.classList.add("topo-out");
  topoEl.setAttribute("aria-hidden", "false");
  // Double rAF ensures the browser paints before starting the transition
  requestAnimationFrame(() => requestAnimationFrame(() => {
    topoEl.classList.add("topo-in");
    // Render the graph after the panel is visible so SVG has real dimensions
    topoEl.addEventListener("transitionend", function onVisible(e) {
      if (e.target !== topoEl) return;
      if (topoInstances.length === 0) {
        _renderScanningState();
      } else {
        renderTopologyGraph(topoInstances, false);
      }
      topoEl.removeEventListener("transitionend", onVisible);
    }, { once: true });
  }));
}

function exitTopologyMode(committed = false) {
  if (!topoMode) return;
  topoMode = false;
  topoDiscoveryId = null;
  const diagView = document.getElementById("diagnostic-view");
  const topoEl   = document.getElementById("topo-builder");
  topoEl.classList.remove("topo-in");
  void diagView.offsetHeight; // reflow so transition fires
  diagView.classList.remove("topo-out");
  topoEl.addEventListener("transitionend", function onHidden(e) {
    if (e.target !== topoEl) return;
    topoEl.setAttribute("aria-hidden", "true");
    topoEl.removeEventListener("transitionend", onHidden);
    // Reset graph for next use
    document.getElementById("topo-columns").innerHTML = "";
    document.getElementById("topo-area-pills").innerHTML = "";
    document.getElementById("topo-node-detail").textContent = "";
    topoInstances = [];
    topoActiveArea = "All";
    topoDiscoveryComplete = false;
  }, { once: true });
  if (committed) refreshFaultStatus();
}

// ── Graph rendering (HTML/CSS nodes, SVG edge overlay) ────────────────────

const AREA_ORDER = ["Intake", "Treatment", "Distribution", "Unknown"];

function renderTopologyGraph(instances, revealNew) {
  const colsEl = document.getElementById("topo-columns");

  const byArea = Object.fromEntries(AREA_ORDER.map(a => [a, []]));
  for (const inst of instances) {
    const a = inst.process_area || "Unknown";
    if (!byArea[a]) byArea[a] = [];
    byArea[a].push(inst);
  }
  const activeAreas = AREA_ORDER.filter(a => byArea[a].length > 0);

  if (instances.length > 0) {
    colsEl.querySelector(".topo-scan-placeholder")?.remove();
  }

  const existingIds = new Set(
    [...colsEl.querySelectorAll(".topo-node")].map(n => n.dataset.id)
  );

  // Remove stale nodes and empty columns
  colsEl.querySelectorAll(".topo-node").forEach(el => {
    if (!instances.find(i => i.instance_id === el.dataset.id)) el.remove();
  });
  colsEl.querySelectorAll(".topo-column").forEach(col => {
    if (!activeAreas.includes(col.dataset.area)) col.remove();
  });

  activeAreas.forEach(area => {
    let colEl = colsEl.querySelector(`.topo-column[data-area="${area}"]`);
    if (!colEl) {
      colEl = document.createElement("div");
      colEl.className = "topo-column";
      colEl.dataset.area = area;
      const lbl = document.createElement("div");
      lbl.className = "topo-column-label";
      lbl.textContent = area;
      colEl.appendChild(lbl);
      colsEl.appendChild(colEl);
    }

    byArea[area].forEach(inst => {
      let nodeEl = colEl.querySelector(`[data-id="${inst.instance_id}"]`);
      if (!nodeEl) {
        nodeEl = _createNode(inst, !existingIds.has(inst.instance_id) && revealNew);
        colEl.appendChild(nodeEl);
      } else {
        nodeEl.className = `topo-node ${inst.confidence_level}`;
      }
      _applyAreaFilter(nodeEl, inst.process_area);
    });
  });

  _updateAreaPills(activeAreas);
  _updateActionBar(instances);
}

function _createNode(inst, animate) {
  const el = document.createElement("div");
  el.className = `topo-node ${inst.confidence_level}`;
  el.dataset.id = inst.instance_id;

  const circle = document.createElement("div");
  circle.className = "topo-node-circle";

  const label = document.createElement("div");
  label.className = "topo-node-label";
  label.textContent = inst.instance_id;

  const type = document.createElement("div");
  type.className = "topo-node-type";
  type.textContent = inst.equipment_type || "";

  el.append(circle, label, type);
  el.onclick = () => _selectNode(inst);

  if (animate) {
    el.classList.add("revealing");
    el.addEventListener("animationend", () => el.classList.remove("revealing"), { once: true });
  }
  return el;
}

function _svgEl(tag, attrs = {}) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}

function _applyAreaFilter(nodeEl, nodeArea) {
  nodeEl.classList.toggle("dimmed", topoActiveArea !== "All" && topoActiveArea !== nodeArea);
}

function _updateAreaPills(activeAreas) {
  const pillsEl = document.getElementById("topo-area-pills");
  const current = [...pillsEl.querySelectorAll(".topo-area-pill")].map(p => p.dataset.area);
  const wanted  = ["All", ...activeAreas];
  if (JSON.stringify(current) === JSON.stringify(wanted)) {
    // Just refresh active state
    pillsEl.querySelectorAll(".topo-area-pill").forEach(p =>
      p.classList.toggle("active", p.dataset.area === topoActiveArea)
    );
    return;
  }
  pillsEl.innerHTML = "";
  wanted.forEach(area => {
    const btn = document.createElement("button");
    btn.className = `topo-area-pill${area === topoActiveArea ? " active" : ""}`;
    btn.dataset.area = area;
    btn.textContent  = area;
    btn.onclick = () => _setAreaFilter(area);
    pillsEl.appendChild(btn);
  });
}

function _setAreaFilter(area) {
  topoActiveArea = area;
  document.querySelectorAll(".topo-area-pill").forEach(p => {
    p.classList.toggle("active", p.dataset.area === area);
  });
  document.querySelectorAll(".topo-node").forEach(nodeEl => {
    const inst = topoInstances.find(i => i.instance_id === nodeEl.dataset.id);
    if (inst) _applyAreaFilter(nodeEl, inst.process_area);
  });
}

function _selectNode(inst) {
  document.querySelectorAll(".topo-node.selected").forEach(n => n.classList.remove("selected"));
  const nodeEl = document.querySelector(`[data-id="${inst.instance_id}"]`);
  if (nodeEl) nodeEl.classList.add("selected");

  const attrs   = Object.keys(inst.attributes || {}).join(", ") || "none";
  const missing = (inst.missing_required || []).join(", ") || "—";
  document.getElementById("topo-node-detail").innerHTML =
    `<strong>${escHtml(inst.instance_id)}</strong> (${escHtml(inst.equipment_type)}) · ` +
    `<span style="color:var(--topo-${inst.confidence_level})">${inst.confidence_level} ` +
    `${(inst.confidence_score * 100).toFixed(0)}%</span> · ` +
    `attrs: ${escHtml(attrs)} · missing: ${escHtml(missing)}`;
}

function _updateActionBar(instances) {
  const v   = instances.filter(i => i.confidence_level === "verified").length;
  const inf = instances.filter(i => i.confidence_level === "inferred").length;
  const sus = instances.filter(i => i.confidence_level === "suspect").length;
  document.getElementById("topo-status-text").textContent =
    `${instances.length} instances · ${v} verified · ${inf} inferred · ${sus} suspect`;
  const flagged = instances.filter(i =>
    i.confidence_level === "suspect" ||
    (i.missing_required && i.missing_required.length > 0) ||
    i.process_area === "Unknown" ||
    i.via_legacy_pattern
  ).length;
  document.getElementById("topo-legend-stats").textContent =
    `${instances.length} · 3 areas · ${flagged} flagged`;
  document.getElementById("topo-commit-btn").disabled = !topoDiscoveryComplete || instances.length === 0;
}

// ── SSE tool result handler ────────────────────────────────────────────────

function handleTopoToolResult(toolName, result) {
  if (toolName === "topology_builder__start_discovery") {
    topoDiscoveryId = result.discovery_id;
    enterTopologyMode();
    document.getElementById("topo-status-text").textContent = "Discovery running…";
  }

  if (toolName === "topology_builder__get_discovery_progress") {
    const instances = result.instances || [];
    const hasNew = instances.length > topoInstances.length;
    topoInstances = instances;
    if (result.status === "running" && instances.length === 0) {
      _renderScanningState();
    } else if (hasNew) {
      renderTopologyGraph(instances, true);
    }
    if (result.status === "complete") {
      topoDiscoveryComplete = true;
      document.getElementById("topo-status-text").textContent =
        `Discovery complete — ${instances.length} instances found`;
      _updateActionBar(instances);
      const btn = document.getElementById("topo-commit-btn");
      btn.style.outline = "2px solid var(--topo-verified)";
      btn.style.outlineOffset = "2px";
    }
  }

  if (toolName === "topology_builder__override_instance_type") {
    renderTopologyGraph(topoInstances, false);
  }
}

function _pulseCommitAndExit() {
  const nodes = [...document.querySelectorAll(".topo-node")];
  nodes.forEach((nodeEl, idx) => {
    setTimeout(() => nodeEl.classList.add("committing"), idx * 80);
  });
  setTimeout(() => exitTopologyMode(true), nodes.length * 80 + 650);
}

// ── Topo chat send ─────────────────────────────────────────────────────────

function sendTopoMessage() {
  const topoInput = document.getElementById("topo-user-input");
  const text = topoInput.value.trim();
  if (!text || streaming) return;
  topoInput.value = "";
  appendTopoMessage("user", text);
  sendMessage(text);
}

function appendTopoMessage(role, text) {
  const el = document.createElement("div");
  el.className = `topo-bubble ${role}`;
  el.innerHTML = role === "assistant" ? renderMarkdown(text) : escHtml(text);
  const msgsEl = document.getElementById("topo-messages");
  msgsEl.appendChild(el);
  msgsEl.scrollTop = msgsEl.scrollHeight;
}

function _renderScanningState() {
  const colsEl = document.getElementById("topo-columns");
  colsEl.innerHTML = "";
  const ph = document.createElement("div");
  ph.className = "topo-scan-placeholder";
  const t1 = document.createElement("div");
  t1.className = "topo-scan-text";
  t1.textContent = "Scanning MQTT topics…";
  const t2 = document.createElement("div");
  t2.className = "topo-scan-text";
  t2.style.cssText = "animation-delay:0.6s; font-size:11px; font-family:var(--font-mono)";
  t2.textContent = "listening for equipment signals";
  ph.append(t1, t2);
  colsEl.appendChild(ph);
}

async function commitTopology() {
  if (!topoInstances.length) return;
  const btn = document.getElementById("topo-commit-btn");
  btn.disabled = true;
  btn.textContent = "committing…";
  btn.style.outline = "";
  document.getElementById("topo-status-text").textContent = "Writing to LadybugDB…";

  try {
    const resp = await fetch("/api/topology/commit", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        facility_id:   "WTP_001",
        facility_name: "Water Treatment Plant",
        instances:     topoInstances,
      }),
    });
    const result = await resp.json();
    if (result.error) {
      document.getElementById("topo-status-text").textContent = `Error: ${result.error}`;
      btn.disabled = false;
      btn.textContent = "commit to db";
    } else {
      document.getElementById("topo-status-text").textContent =
        `Committed ${result.committed_count} instances`;
      _pulseCommitAndExit();
    }
  } catch (e) {
    document.getElementById("topo-status-text").textContent = `Error: ${e.message}`;
    btn.disabled = false;
    btn.textContent = "commit to db";
  }
}

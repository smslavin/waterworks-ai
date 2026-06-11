"use strict";

// ── State ──────────────────────────────────────────────────────────────────

const messages = [];
let streaming        = false;
let thinkingEnabled  = false;
let multiAgentMode   = false;
let abortController  = null;
let faultModeMap     = {}; // { instance_id: [mode, ...] }
const _pendingActions = []; // queue of {action_id, action_type, target, value, description}

const SPECIALISTS = [
  {name: "intake",       label: "Intake",       units: ["RawWater_01", "RawWater_02"]},
  {name: "treatment",    label: "Treatment",    units: ["Clarifier_01", "Chlorine_01", "Fluoride_01", "UV_01", "UV_02"]},
  {name: "distribution", label: "Distribution", units: ["HighService_01", "HighService_02", "FinishedWater_01"]},
  {name: "historian",    label: "Historian",    units: []},
];

// Agent-detected faults: { instance_id → "anomaly" | "fault" | "critical" | "warning" }
// Cleared on new conversation. Overlaid on the simulator fault status panel.
const _agentFaults = {};

// ── DOM refs ───────────────────────────────────────────────────────────────

const messagesEl  = document.getElementById("messages");
const inputEl     = document.getElementById("user-input");
const sendBtn     = document.getElementById("send-btn");
const modelSelect = document.getElementById("model-select");
const faultTarget = document.getElementById("fault-target");
const faultMode   = document.getElementById("fault-mode");
const faultList   = document.getElementById("fault-status-list");

// ── Conversation management ────────────────────────────────────────────────

function newConversation() {
  messages.length = 0;
  messagesEl.innerHTML = "";
  Object.keys(_agentFaults).forEach(k => delete _agentFaults[k]);
  refreshFaultStatus();
}

function toggleThinking() {
  thinkingEnabled = !thinkingEnabled;
  document.getElementById("thinking-toggle").classList.toggle("active", thinkingEnabled);
}

function toggleMode() {
  multiAgentMode = !multiAgentMode;
  const btn = document.getElementById("mode-toggle");
  btn.classList.toggle("active", multiAgentMode);
  btn.textContent = multiAgentMode ? "Multi Agent" : "Single Agent";
  checkReactiveStatus();
  // Deep Reasoning is incompatible with multi-agent mode
  if (multiAgentMode && thinkingEnabled) {
    thinkingEnabled = false;
    document.getElementById("thinking-toggle").classList.remove("active");
  }
  document.getElementById("thinking-toggle").disabled = multiAgentMode;
}

// ── Action approval dialog ─────────────────────────────────────────────────

function _updateActionPill() {
  const pill  = document.getElementById("action-pill");
  const label = document.getElementById("action-pill-label");
  if (_pendingActions.length === 0) {
    pill.style.display = "none";
  } else if (_pendingActions.length === 1) {
    const a = _pendingActions[0];
    const typeLabel = (a.action_type || "").replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
    label.textContent = typeLabel ? `${typeLabel} — ${a.target || ""}` : "Action pending";
    pill.style.display = "flex";
  } else {
    label.textContent = `${_pendingActions.length} actions pending`;
    pill.style.display = "flex";
  }
}

function _loadActionIntoDialog(action) {
  const typeLabel = (action.action_type || "").replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
  document.getElementById("approval-type").textContent        = typeLabel || "—";
  document.getElementById("approval-target").textContent      = action.target || "—";
  document.getElementById("approval-description").textContent = action.description || "—";
  const valueRow = document.getElementById("approval-value-row");
  if (action.value) {
    document.getElementById("approval-value").textContent = action.value;
    valueRow.style.display = "block";
  } else {
    valueRow.style.display = "none";
  }
  const queueInfo = document.getElementById("approval-queue-info");
  if (_pendingActions.length > 1) {
    queueInfo.textContent = `1 of ${_pendingActions.length} pending — approve or deny to continue`;
    queueInfo.style.display = "block";
  } else {
    queueInfo.style.display = "none";
  }
}

function showApprovalDialog(chunk) {
  _pendingActions.push({
    action_id:   chunk.action_id,
    action_type: chunk.action_type,
    target:      chunk.target,
    value:       chunk.value,
    description: chunk.description,
  });
  _updateActionPill();
}

function reviewPendingAction() {
  if (_pendingActions.length === 0) return;
  _loadActionIntoDialog(_pendingActions[0]);
  document.getElementById("approval-overlay").classList.add("visible");
}

function _onActionDecision(action_id) {
  const idx = _pendingActions.findIndex(a => a.action_id === action_id);
  if (idx !== -1) {
    _pendingActions.splice(idx, 1);
    const overlay = document.getElementById("approval-overlay");
    if (idx === 0 && overlay.classList.contains("visible")) {
      if (_pendingActions.length > 0) {
        _loadActionIntoDialog(_pendingActions[0]);
      } else {
        overlay.classList.remove("visible");
      }
    }
  }
  _updateActionPill();
}

async function approveAction() {
  if (_pendingActions.length === 0) return;
  const action = _pendingActions.shift();
  await fetch("/api/action/respond", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({action_id: action.action_id, decision: "approved"}),
  });
  if (_pendingActions.length > 0) {
    _loadActionIntoDialog(_pendingActions[0]);
  } else {
    document.getElementById("approval-overlay").classList.remove("visible");
  }
  _updateActionPill();
}

async function denyAction() {
  if (_pendingActions.length === 0) return;
  const action = _pendingActions.shift();
  await fetch("/api/action/respond", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({action_id: action.action_id, decision: "denied"}),
  });
  if (_pendingActions.length > 0) {
    _loadActionIntoDialog(_pendingActions[0]);
  } else {
    document.getElementById("approval-overlay").classList.remove("visible");
  }
  _updateActionPill();
}

async function clearAuditLog() {
  if (!confirm("Clear the audit log? This cannot be undone.")) return;
  await fetch("/api/audit/clear", {method: "POST"});
}

// ── Model loader ───────────────────────────────────────────────────────────

async function loadModels() {
  try {
    const data = await fetch("/api/models").then(r => r.json());
    const opts = [];
    if (data.cloud?.length) {
      const g = document.createElement("optgroup");
      g.label = "Cloud";
      data.cloud.forEach(m => {
        const o = document.createElement("option");
        o.value = o.textContent = m;
        g.appendChild(o);
      });
      opts.push(g);
    }
    if (data.local?.length) {
      const g = document.createElement("optgroup");
      g.label = "Local (Ollama)";
      data.local.forEach(m => {
        const o = document.createElement("option");
        o.value = o.textContent = m;
        g.appendChild(o);
      });
      opts.push(g);
    }
    modelSelect.innerHTML = "";
    opts.forEach(o => modelSelect.appendChild(o));
    if (!modelSelect.options.length) {
      modelSelect.innerHTML = "<option>No models found</option>";
    }
  } catch {
    modelSelect.innerHTML = "<option>Error loading models</option>";
  }
}

// ── Health check ───────────────────────────────────────────────────────────

async function checkHealth() {
  const KEYS = ["aggregator","influxdb","mqtt","simulator","audit_mcp","control_mcp","memory_mcp"];
  try {
    const data = await fetch("/api/health").then(r => r.json());
    KEYS.forEach(k => {
      const el = document.getElementById(`dot-${k}`);
      if (el) el.className = "dot " + (data[k] === "ok" ? "ok" : "error");
    });
  } catch {
    KEYS.forEach(k => {
      const el = document.getElementById(`dot-${k}`);
      if (el) el.className = "dot error";
    });
  }
}

// ── Fault mode loader ──────────────────────────────────────────────────────

function _faultLabel(mode) {
  return mode.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}

async function loadFaultModes() {
  try {
    const data = await fetch("/api/fault/modes").then(r => r.json());
    if (data.error) return;
    faultModeMap = data;

    const prev = faultTarget.value;
    faultTarget.innerHTML = "";
    Object.keys(faultModeMap).forEach(id => {
      const o = document.createElement("option");
      o.value = o.textContent = id;
      faultTarget.appendChild(o);
    });
    if (prev && faultModeMap[prev]) faultTarget.value = prev;

    updateFaultModes();
  } catch { /* simulator offline — leave dropdowns empty */ }
}

function updateFaultModes() {
  const modes = (faultModeMap[faultTarget.value] || []).filter(m => m !== "normal");
  const prev  = faultMode.value;
  faultMode.innerHTML = "";
  modes.forEach(m => {
    const o = document.createElement("option");
    o.value       = m;
    o.textContent = _faultLabel(m);
    faultMode.appendChild(o);
  });
  if (prev && modes.includes(prev)) faultMode.value = prev;
}

// ── Fault status sidebar ───────────────────────────────────────────────────

async function refreshFaultStatus() {
  try {
    const data = await fetch("/api/fault/status").then(r => r.json());
    if (data.error) {
      faultList.innerHTML = `<div style="color:var(--color-error);font-size:12px">${data.error}</div>`;
      return;
    }
    faultList.innerHTML = Object.entries(data).map(([name, mode]) => {
      const injected = mode !== "normal";
      const agent    = _agentFaults[name];
      let badge, cls;
      if (injected) {
        badge = mode; cls = "fault";
      } else if (agent) {
        badge = agent; cls = "agent-fault";
      } else {
        badge = "normal"; cls = "";
      }
      const display = badge.replaceAll("_", " ");
      return `<div class="status-row" title="${name}: ${badge}">
        <span class="status-name">${name}</span>
        <span class="status-mode${cls ? " " + cls : ""}">${display}</span>
      </div>`;
    }).join("");
  } catch {
    faultList.innerHTML = `<div style="color:var(--color-text-secondary);font-size:12px">Simulator offline</div>`;
  }
}

// ── Fault injection ────────────────────────────────────────────────────────

async function injectFault() {
  await fetch("/api/fault", {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify({target: faultTarget.value, mode: faultMode.value}),
  });
  refreshFaultStatus();
}

async function clearFault() {
  await fetch("/api/fault", {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify({target: faultTarget.value, mode: "normal"}),
  });
  refreshFaultStatus();
}

// ── Message rendering ──────────────────────────────────────────────────────

function appendUserMessage(text) {
  const div = document.createElement("div");
  div.className = "message user";
  div.innerHTML = `<div class="bubble">${escHtml(text)}</div>`;
  messagesEl.appendChild(div);
  scrollToBottom();
}

function createAssistantMessage() {
  const wrap = document.createElement("div");
  wrap.className = "message assistant";

  // Tool strip — hidden until first tool call arrives
  const strip   = document.createElement("div");
  strip.className = "tool-strip";
  const chevron = document.createElement("span");
  chevron.className = "chevron";
  chevron.textContent = "▶";
  const stripLabel = document.createElement("span");
  stripLabel.textContent = "0 tool calls";
  strip.appendChild(chevron);
  strip.appendChild(stripLabel);

  const detail = document.createElement("div");
  detail.className = "tool-detail-block";
  strip.addEventListener("click", () => {
    strip.classList.toggle("open");
    detail.classList.toggle("open");
  });

  wrap.appendChild(strip);
  wrap.appendChild(detail);
  messagesEl.appendChild(wrap);
  scrollToBottom();

  // Thinking block — created lazily when first thinking_delta arrives
  let thinkingBlock   = null;
  let thinkingBodyEl  = null;
  let thinkingLabelEl = null;
  let thinkingText    = "";

  function ensureThinkingBlock() {
    if (thinkingBlock) return;
    thinkingBlock = document.createElement("div");
    thinkingBlock.className = "thinking-block";

    const hdr  = document.createElement("div");
    hdr.className = "thinking-header";
    const chev = document.createElement("span");
    chev.className = "chevron";
    chev.textContent = "▶";
    thinkingLabelEl = document.createElement("span");
    thinkingLabelEl.textContent = "Thinking…";
    hdr.appendChild(chev);
    hdr.appendChild(thinkingLabelEl);
    hdr.addEventListener("click", () => thinkingBlock.classList.toggle("open"));

    thinkingBodyEl = document.createElement("div");
    thinkingBodyEl.className = "thinking-body";

    thinkingBlock.appendChild(hdr);
    thinkingBlock.appendChild(thinkingBodyEl);
    wrap.insertBefore(thinkingBlock, strip);
    scrollToBottom();
  }

  // ── Specialist chips panel (multi-agent mode) ──────────────────────────────
  let chipPanel    = null;
  let chipEls      = {}; // name → chip element
  let synthEl      = null;

  function _statusClass(status) {
    if (!status) return "";
    const s = status.toLowerCase();
    if (s.includes("fault"))   return "fault";
    if (s.includes("anomaly")) return "anomaly";
    if (s.includes("normal"))  return "normal";
    if (s.includes("error"))   return "error-state";
    return "unknown";
  }

  // ── Regular tool strip ─────────────────────────────────────────────────────
  let toolCount    = 0;
  let activeBubble = null;
  let needNewBubble = false;

  function ensureBubble() {
    if (!activeBubble || needNewBubble) {
      activeBubble = document.createElement("div");
      activeBubble.className = "bubble";
      activeBubble.innerHTML =
        `<span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span>`;
      activeBubble._rawText = "";
      wrap.appendChild(activeBubble);
      scrollToBottom();
      needNewBubble = false;
    }
    return activeBubble;
  }

  ensureBubble();

  return {
    addToken(text) {
      const b = ensureBubble();
      b._rawText += text;
      b.innerHTML = renderMarkdown(b._rawText);
      scrollToBottom();
    },
    addToolCall(tool, args) {
      toolCount++;
      stripLabel.textContent = `${toolCount} tool call${toolCount > 1 ? "s" : ""}`;
      strip.style.display = "flex";

      const item = document.createElement("div");
      item.className = "tool-call-item";
      item.innerHTML = `<span class="tool-name">${escHtml(tool)}</span>\n${escHtml(JSON.stringify(args, null, 2))}`;
      detail.appendChild(item);

      // Next text segment gets a fresh bubble so it appears below the tool strip
      needNewBubble = true;
    },
    addToolResult(tool, result) {
      const items = detail.querySelectorAll(".tool-call-item");
      const last  = items[items.length - 1];
      if (last) {
        const r = document.createElement("span");
        r.className = "tool-result-text";
        r.textContent = `→ ${result.length > 400 ? result.slice(0, 400) + "…" : result}`;
        last.appendChild(r);
      }
      scrollToBottom();
    },
    addThinkingDelta(text) {
      ensureThinkingBlock();
      thinkingText += text;
      thinkingBodyEl.textContent = thinkingText;
      scrollToBottom();
    },
    finalizeThinking() {
      if (!thinkingBlock) return;
      if (thinkingLabelEl) thinkingLabelEl.textContent = "Claude's reasoning";
    },
    addError(text) {
      const b = ensureBubble();
      b._rawText += `\n\n[Error: ${text}]`;
      b.innerHTML = renderMarkdown(b._rawText);
      scrollToBottom();
    },

    // ── Specialist panel methods ─────────────────────────────────────────────
    initSpecialistPanel() {
      chipPanel = document.createElement("div");
      chipPanel.className = "specialist-panel";

      const title = document.createElement("div");
      title.className = "specialist-panel-title";
      title.textContent = "Multi-Agent Diagnostic";
      chipPanel.appendChild(title);

      const chipsRow = document.createElement("div");
      chipsRow.className = "specialist-chips";
      SPECIALISTS.forEach(({name, label}) => {
        const chip = document.createElement("div");
        chip.className = "specialist-chip";
        chip.dataset.specialist = name;
        chip.innerHTML = `<span class="chip-dot"></span>${label}`;
        chipsRow.appendChild(chip);
        chipEls[name] = chip;
      });
      chipPanel.appendChild(chipsRow);
      wrap.insertBefore(chipPanel, strip);
      scrollToBottom();
    },

    updateChip(name, status, confidence) {
      const chip = chipEls[name];
      if (!chip) return;
      chip.className = "specialist-chip " + _statusClass(status);
      const confStr = confidence != null ? ` ${(confidence * 100).toFixed(0)}%` : "";
      chip.innerHTML = `<span class="chip-dot"></span>${SPECIALISTS.find(s => s.name === name)?.label ?? name}${confStr}`;
    },

    showSynthesisStart() {
      if (synthEl) return;
      synthEl = document.createElement("div");
      synthEl.className = "synthesis-indicator";
      synthEl.innerHTML = `<span class="chip-dot" style="animation:blink 1.2s infinite;background:var(--color-accent)"></span>Synthesizing findings…`;
      if (chipPanel) chipPanel.appendChild(synthEl);
      needNewBubble = true;
      scrollToBottom();
    },

    removeSynthesisIndicator() {
      if (synthEl) { synthEl.remove(); synthEl = null; }
    },

    finalize() {
      wrap.querySelectorAll(".bubble").forEach(b => {
        if (!b._rawText?.trim()) b.remove();
      });
      if (synthEl) { synthEl.remove(); synthEl = null; }
    },
    getRawText() {
      return wrap.querySelectorAll(".bubble")[0]?._rawText ?? "";
    },
  };
}

function scrollToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

// ── Context pressure indicator ─────────────────────────────────────────────

function updateContextIndicator(data) {
  const pct     = (data.context_pressure || 0) * 100;
  const section = document.getElementById("context-section");
  const bar     = document.getElementById("context-bar");
  const label   = document.getElementById("context-label");
  if (!section || !bar || !label) return;
  bar.style.width      = Math.min(pct, 100) + "%";
  bar.style.background = pct >= 85 ? "var(--color-error)"
                       : pct >= 70 ? "var(--color-warn)"
                       :             "var(--color-ok)";
  const inTok = (data.input_tokens || 0).toLocaleString();
  label.textContent = `${pct.toFixed(1)}%  (${inTok} tok)`;
}

// ── Send message ───────────────────────────────────────────────────────────

function _setStreaming(active) {
  streaming = active;
  sendBtn.textContent  = active ? "Stop" : "Send";
  sendBtn.classList.toggle("stop-mode", active);
  sendBtn.disabled = false;
}

async function sendMessage(overrideText) {
  const text = (overrideText ?? inputEl.value).trim();
  if (!text || streaming) return;

  if (!overrideText) {
    inputEl.value = "";
    inputEl.style.height = "";
  }
  messages.push({role: "user", content: text});
  appendUserMessage(text);

  abortController = new AbortController();
  _setStreaming(true);

  const msg = createAssistantMessage();
  if (multiAgentMode) msg.initSpecialistPanel();
  let assistantText = "";
  let topoMsg = null;

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({
        messages,
        model:    modelSelect.value,
        thinking: thinkingEnabled,
        mode:     multiAgentMode ? "multi" : "single",
      }),
      signal: abortController.signal,
    });

    if (!response.ok) {
      msg.addError(`HTTP ${response.status}`);
      return;
    }

    const reader  = response.body.getReader();
    const decoder = new TextDecoder();
    let   buffer  = "";

    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, {stream: true});
      const lines = buffer.split("\n");
      buffer = lines.pop(); // keep incomplete trailing line

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        let chunk;
        try { chunk = JSON.parse(line.slice(6)); } catch { continue; }

        switch (chunk.type) {
          case "text":
            assistantText += chunk.text;
            msg.addToken(chunk.text);
            if (topoMode) {
              if (!topoMsg) topoMsg = createTopoAssistantMessage();
              topoMsg.addToken(chunk.text);
            }
            break;
          case "thinking_delta":
            msg.addThinkingDelta(chunk.text);
            break;
          case "thinking_stop":
            msg.finalizeThinking();
            break;
          case "tool_call":
            // In multi mode, prefix tool name with specialist label for the strip
            if (chunk.specialist) {
              const label = SPECIALISTS.find(s => s.name === chunk.specialist)?.label ?? chunk.specialist;
              msg.addToolCall(`[${label}] ${chunk.tool}`, chunk.args);
            } else {
              msg.addToolCall(chunk.tool, chunk.args);
            }
            if (topoMode && topoMsg) topoMsg.afterToolCall();
            break;
          case "tool_result":
            msg.addToolResult(chunk.tool, chunk.result);
            if (chunk.tool && chunk.tool.startsWith("topology_builder__")) {
              try { handleTopoToolResult(chunk.tool, JSON.parse(chunk.result)); } catch {}
            }
            break;
          case "action_proposed":
            showApprovalDialog(chunk);
            break;
          case "action_decision":
            _onActionDecision(chunk.action_id);
            msg.addToolResult(
              "propose_action",
              `Operator decision: ${chunk.decision}`,
            );
            break;
          case "specialist_start":
            msg.updateChip(chunk.specialist, "running", null);
            break;
          case "specialist_done":
            msg.updateChip(chunk.specialist, chunk.status, chunk.confidence);
            if (chunk.status === "Fault Detected" || chunk.status === "Anomaly Detected") {
              const label = chunk.status === "Fault Detected" ? "fault" : "anomaly";
              const spec  = SPECIALISTS.find(s => s.name === chunk.specialist);
              (spec?.units ?? []).forEach(u => { _agentFaults[u] = label; });
              refreshFaultStatus();
            }
            break;
          case "synthesis_start":
            msg.showSynthesisStart();
            break;
          case "error":
            msg.addError(chunk.error);
            break;
          case "done":
            msg.removeSynthesisIndicator();
            if (chunk.input_tokens !== undefined) updateContextIndicator(chunk);
            break;
        }
      }
    }
  } catch (err) {
    if (err.name !== "AbortError") msg.addError(err.message);
  } finally {
    msg.finalize();
    if (assistantText) {
      messages.push({role: "assistant", content: assistantText});
    }
    if (topoMsg) topoMsg.finalize();
    abortController = null;
    _setStreaming(false);
    inputEl.focus();
  }
}

// ── Input events ───────────────────────────────────────────────────────────

inputEl.addEventListener("input", () => {
  inputEl.style.height = "";
  inputEl.style.height = Math.min(inputEl.scrollHeight, 160) + "px";
});
inputEl.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});
sendBtn.addEventListener("click", () => {
  if (streaming && abortController) {
    abortController.abort();
  } else {
    sendMessage();
  }
});

// ── Reactive toggle ────────────────────────────────────────────────────────

async function checkReactiveStatus() {
  try {
    const r   = await fetch("/api/reactive");
    const d   = await r.json();
    const dot = document.getElementById("dot-reactive");
    const btn = document.getElementById("reactive-toggle-btn");
    if (!dot) return;
    const active    = d.enabled && multiAgentMode;
    dot.className   = "dot " + (active ? "ok" : "");
    btn.textContent = d.enabled ? "Disable" : "Enable";
    btn.disabled    = !multiAgentMode;
    btn.title       = multiAgentMode ? "" : "Requires Multi Agent mode";
  } catch (_) {}
}

async function toggleReactive() {
  const btn     = document.getElementById("reactive-toggle-btn");
  const current = btn.textContent.trim() === "Disable";
  btn.disabled  = true;
  try {
    await fetch("/api/reactive/toggle", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({enable: !current}),
    });
    await checkReactiveStatus();
  } finally {
    btn.disabled = false;
  }
}

// ── Reactive stream ────────────────────────────────────────────────────────

const _advisories = [];
const _warningBanners = {};

function _injectReactiveActionContext(evt) {
  const typeLabel = (evt.action_type || "").replace(/_/g, " ")
    .replace(/\b\w/g, c => c.toUpperCase());
  const div = document.createElement("div");
  div.className = "message assistant reactive-critical-msg";
  div.dataset.actionId = evt.action_id;
  div.innerHTML =
    `<div class="bubble">` +
    `<div class="reactive-critical-label">Reactive — Proposed Action</div>` +
    `<p><strong>${escHtml(typeLabel)}</strong> on <strong>${escHtml(evt.target || "")}</strong>` +
    (evt.value ? ` → <code>${escHtml(String(evt.value))}</code>` : "") + `</p>` +
    renderMarkdown(evt.description || "") +
    `</div>`;
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function connectReactiveStream() {
  const es = new EventSource("/api/events");
  es.onmessage = (e) => {
    try {
      const evt = JSON.parse(e.data);
      if      (evt.type === "reactive_advisory")        _handleAdvisory(evt);
      else if (evt.type === "reactive_warning")         _handleWarning(evt);
      else if (evt.type === "reactive_warning_update")  _handleWarningUpdate(evt);
      else if (evt.type === "reactive_critical")        _handleCritical(evt);
      else if (evt.type === "action_proposed")          { try { _injectReactiveActionContext(evt); } catch (_) {} showApprovalDialog(evt); }
      else if (evt.type === "action_decision")          _onActionDecision(evt.action_id);
    } catch (_) {}
  };
  // EventSource auto-reconnects per spec
}

function _markReactiveFault(evt, label) {
  _agentFaults[evt.instance_id] = label;
  refreshFaultStatus();
}

function _handleAdvisory(evt) {
  const [lo, hi] = evt.normal_range;
  _advisories.push(evt);
  const btn   = document.getElementById("notif-btn");
  const badge = document.getElementById("notif-badge");
  btn.style.display   = "block";
  badge.style.display = "inline";
  badge.textContent   = _advisories.length;
  const panel = document.getElementById("notif-panel");
  const item  = document.createElement("div");
  item.className = "notif-item";
  item.innerHTML =
    `<div class="notif-label">Advisory — ${escHtml(evt.instance_id)}</div>` +
    `${escHtml(evt.attribute)}: ${evt.value.toFixed(2)} (normal: ${lo}–${hi})<br>` +
    `<small>${escHtml(evt.reason)}</small>`;
  panel.prepend(item);
}

function toggleNotifPanel() {
  const panel = document.getElementById("notif-panel");
  panel.style.display = panel.style.display === "none" ? "block" : "none";
}

function _handleWarning(evt) {
  _markReactiveFault(evt, "warning");
  const [lo, hi] = evt.normal_range;
  const key     = `${evt.instance_id}_${evt.attribute}`;
  const banner  = document.getElementById("warning-banner");
  const content = document.getElementById("warning-banner-content");
  banner.classList.add("visible");
  const detail = document.createElement("div");
  detail.id        = `wd_${key}`;
  detail.className = "warning-detail";
  detail.innerHTML = "<em>Diagnostic running…</em>";
  const row = document.createElement("div");
  row.id = `wb_${key}`;
  row.innerHTML =
    `<div class="warning-banner-label">Warning — ${escHtml(evt.instance_id)} / ${escHtml(evt.attribute)}</div>` +
    `<div class="warning-expandable" onclick="this.nextElementSibling.classList.toggle('open')">` +
    `${evt.value.toFixed(2)} (normal: ${lo}–${hi}) — ${escHtml(evt.reason)} ▾</div>`;
  row.appendChild(detail);
  content.appendChild(row);
  _warningBanners[key] = detail;
}

function _handleWarningUpdate(evt) {
  const key    = `${evt.instance_id}_${evt.attribute}`;
  const detail = _warningBanners[key];
  if (detail) detail.innerHTML = renderMarkdown(evt.content);
}

function dismissWarning() {
  const banner = document.getElementById("warning-banner");
  banner.classList.remove("visible");
}

function _handleCritical(evt) {
  _markReactiveFault(evt, "critical");
  const [lo, hi] = evt.normal_range;
  const div = document.createElement("div");
  div.className = "message assistant reactive-critical-msg";
  div.innerHTML =
    `<div class="bubble">` +
    `<div class="reactive-critical-label">Critical — ${escHtml(evt.instance_id)} / ${escHtml(evt.attribute)}</div>` +
    `<p>${escHtml(evt.attribute)}: ${evt.value.toFixed(2)} (normal: ${lo}–${hi})<br>${escHtml(evt.reason)}</p>` +
    renderMarkdown(evt.content) +
    `</div>`;
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

// ── Init ───────────────────────────────────────────────────────────────────

faultTarget.addEventListener("change", updateFaultModes);

loadModels();
loadFaultModes();
checkHealth();
checkReactiveStatus();
refreshFaultStatus();
connectReactiveStream();
setInterval(checkHealth,          15_000);
setInterval(checkReactiveStatus,  15_000);
setInterval(refreshFaultStatus,    5_000);


"use strict";

// ── State ──────────────────────────────────────────────────────────────────

const messages = [];
let streaming        = false;
let thinkingEnabled  = false;
let multiAgentMode   = false;
let abortController  = null;
let faultModeMap     = {}; // { instance_id: [mode, ...] }
let _pendingActionId = null; // action_id awaiting operator decision

const SPECIALISTS = [
  {name: "intake",       label: "Intake"},
  {name: "treatment",    label: "Treatment"},
  {name: "distribution", label: "Distribution"},
  {name: "historian",    label: "Historian"},
];

// ── DOM refs ───────────────────────────────────────────────────────────────

const messagesEl  = document.getElementById("messages");
const inputEl     = document.getElementById("user-input");
const sendBtn     = document.getElementById("send-btn");
const modelSelect = document.getElementById("model-select");
const faultTarget = document.getElementById("fault-target");
const faultMode   = document.getElementById("fault-mode");
const faultList   = document.getElementById("fault-status-list");

// ── Markdown renderer ──────────────────────────────────────────────────────
// Handles tables, code blocks, inline formatting,
// headings, lists, and horizontal rules. HTML-escapes first, then parses.

function renderMarkdown(text) {
  // Ensure a blank line before and after table blocks so they parse as their
  // own block — the model often omits these newlines.
  text = text.replace(/([^|\n])\n(\|)/g, "$1\n\n$2");
  text = text.replace(/(\|[^\n]*)\n([^|\n])/g, "$1\n\n$2");

  return text
    .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")
    .replace(/```[\w]*\n?([\s\S]*?)```/g, (_, c) => `<pre><code>${c.trim()}</code></pre>`)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/^### (.+)$/gm, "<h3>$1</h3>")
    .replace(/^## (.+)$/gm,  "<h2>$1</h2>")
    .replace(/^# (.+)$/gm,   "<h1>$1</h1>")
    .replace(/^[-*] (.+)$/gm, "<li>$1</li>")
    .replace(/(<li>[\s\S]*?<\/li>)/g, "<ul>$1</ul>")
    .replace(/^---$/gm, "<hr>")
    .split(/\n\n+/)
    .map(b => {
      b = b.trim();
      if (!b) return "";
      if (/^<(h[1-3]|pre|ul|ol|hr|li)/.test(b)) return b;
      if (b.startsWith("|")) {
        const rows = b.split("\n").filter(r => r.trim().startsWith("|"));
        if (rows.length >= 2 && /^\|[-| :]+\|$/.test(rows[1].trim())) {
          const hdrs = rows[0].split("|").slice(1,-1)
            .map(c => `<th>${c.trim()}</th>`).join("");
          const body = rows.slice(2).map(r => {
            const cells = r.split("|").slice(1,-1)
              .map(c => `<td>${c.trim()}</td>`).join("");
            return `<tr>${cells}</tr>`;
          }).join("");
          return `<table><thead><tr>${hdrs}</tr></thead><tbody>${body}</tbody></table>`;
        }
      }
      return `<p>${b.replace(/\n/g, "<br>")}</p>`;
    })
    .join("\n");
}

// ── Conversation management ────────────────────────────────────────────────

function newConversation() {
  messages.length = 0;
  messagesEl.innerHTML = "";
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
  // Deep Reasoning is incompatible with multi-agent mode
  if (multiAgentMode && thinkingEnabled) {
    thinkingEnabled = false;
    document.getElementById("thinking-toggle").classList.remove("active");
  }
  document.getElementById("thinking-toggle").disabled = multiAgentMode;
}

// ── Action approval dialog ─────────────────────────────────────────────────

function showApprovalDialog(chunk) {
  _pendingActionId = chunk.action_id;
  const typeLabel = (chunk.action_type || "").replace(/_/g, " ")
    .replace(/\b\w/g, c => c.toUpperCase());
  document.getElementById("approval-type").textContent        = typeLabel || "—";
  document.getElementById("approval-target").textContent      = chunk.target || "—";
  document.getElementById("approval-description").textContent = chunk.description || "—";
  const valueRow = document.getElementById("approval-value-row");
  if (chunk.value) {
    document.getElementById("approval-value").textContent = chunk.value;
    valueRow.style.display = "block";
  } else {
    valueRow.style.display = "none";
  }
  document.getElementById("approval-overlay").classList.add("visible");
}

function _closeApprovalDialog() {
  document.getElementById("approval-overlay").classList.remove("visible");
  _pendingActionId = null;
}

async function approveAction() {
  if (!_pendingActionId) return;
  const id = _pendingActionId;
  _closeApprovalDialog();
  await fetch("/api/action/respond", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({action_id: id, decision: "approved"}),
  });
}

async function denyAction() {
  if (!_pendingActionId) return;
  const id = _pendingActionId;
  _closeApprovalDialog();
  await fetch("/api/action/respond", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({action_id: id, decision: "denied"}),
  });
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
    faultList.innerHTML = Object.entries(data).map(([name, mode]) => `
      <div class="status-row">
        <span class="status-name">${name}</span>
        <span class="status-mode${mode !== "normal" ? " fault" : ""}">${mode}</span>
      </div>`).join("");
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

function escHtml(s) {
  return String(s)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;")
    .replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

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

// ── Send message ───────────────────────────────────────────────────────────

function _setStreaming(active) {
  streaming = active;
  sendBtn.textContent  = active ? "Stop" : "Send";
  sendBtn.classList.toggle("stop-mode", active);
  sendBtn.disabled = false;
}

async function sendMessage() {
  const text = inputEl.value.trim();
  if (!text || streaming) return;

  inputEl.value = "";
  inputEl.style.height = "";
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
            _closeApprovalDialog();
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

// ── Init ───────────────────────────────────────────────────────────────────

faultTarget.addEventListener("change", updateFaultModes);

loadModels();
loadFaultModes();
checkHealth();
refreshFaultStatus();
setInterval(checkHealth,        15_000);
setInterval(refreshFaultStatus,  5_000);

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
  document.getElementById("topo-legend-stats").textContent =
    `${instances.length} · 3 areas · ${inf + sus} flagged`;
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
  // Route through the shared sendMessage — set inputEl so it reads the right text
  inputEl.value = text;
  sendMessage();
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

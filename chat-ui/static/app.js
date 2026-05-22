"use strict";

// ── State ──────────────────────────────────────────────────────────────────

const messages = [];   // [{role, content}]
let streaming  = false;

// ── DOM refs ───────────────────────────────────────────────────────────────

const messagesEl   = document.getElementById("messages");
const inputEl      = document.getElementById("user-input");
const sendBtn      = document.getElementById("send-btn");
const modelSelect  = document.getElementById("model-select");
const faultTarget  = document.getElementById("fault-target");
const faultMode    = document.getElementById("fault-mode");
const faultList    = document.getElementById("fault-status-list");

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
  try {
    const data = await fetch("/api/health").then(r => r.json());
    ["aggregator", "influxdb", "mqtt", "simulator"].forEach(k => {
      const el = document.getElementById(`dot-${k}`);
      if (el) {
        el.className = "dot " + (data[k] === "ok" ? "ok" : "error");
      }
    });
  } catch { /* health check failed silently */ }
}

// ── Fault status sidebar ───────────────────────────────────────────────────

async function refreshFaultStatus() {
  try {
    const data = await fetch("/api/fault/status").then(r => r.json());
    if (data.error) { faultList.innerHTML = `<div style="color:var(--color-error)">${data.error}</div>`; return; }
    faultList.innerHTML = Object.entries(data).map(([name, mode]) => `
      <div class="status-row">
        <span class="status-name">${name}</span>
        <span class="status-mode${mode !== 'normal' ? ' fault' : ''}">${mode}</span>
      </div>`).join("");
  } catch {
    faultList.innerHTML = `<div style="color:var(--color-text-secondary)">Simulator offline</div>`;
  }
}

// ── Fault injection ────────────────────────────────────────────────────────

async function injectFault() {
  const target = faultTarget.value;
  const mode   = faultMode.value;
  await fetch("/api/fault", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target, mode }),
  });
  refreshFaultStatus();
}

async function clearFault() {
  const target = faultTarget.value;
  await fetch("/api/fault", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target, mode: "normal" }),
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
  return div;
}

function appendAssistantMessage() {
  const div = document.createElement("div");
  div.className = "message assistant";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  div.appendChild(bubble);
  messagesEl.appendChild(div);
  scrollToBottom();
  return { container: div, bubble };
}

function appendToolBlock(tool, args, container) {
  const block = document.createElement("div");
  block.className = "tool-block";

  const argsStr = JSON.stringify(args, null, 2);
  const header  = document.createElement("div");
  header.className = "tool-header";
  header.innerHTML = `<span class="tool-chevron">▶</span><span>${escHtml(tool)}</span>`;
  header.onclick = () => {
    const body = block.querySelector(".tool-body");
    const chev = block.querySelector(".tool-chevron");
    const open = body.classList.toggle("open");
    chev.classList.toggle("open", open);
  };

  const body = document.createElement("div");
  body.className = "tool-body";
  body.innerHTML = `
    <div class="tool-label">Arguments</div>
    <div class="tool-content">${escHtml(argsStr)}</div>
    <div class="tool-label" style="margin-top:6px">Result</div>
    <div class="tool-content result-placeholder" style="color:var(--color-text-secondary)">waiting…</div>`;

  block.appendChild(header);
  block.appendChild(body);
  container.appendChild(block);
  scrollToBottom();
  return block;
}

function updateToolResult(block, result) {
  const placeholder = block.querySelector(".result-placeholder");
  if (placeholder) {
    placeholder.textContent = result;
    placeholder.classList.remove("result-placeholder");
    placeholder.style.color = "";
  }
}

function escHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function scrollToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

// ── SSE parser ─────────────────────────────────────────────────────────────

function* parseSSEChunk(buffer) {
  const lines = buffer.split("\n");
  for (const line of lines) {
    if (line.startsWith("data: ")) {
      const raw = line.slice(6).trim();
      if (raw && raw !== "[DONE]") {
        try { yield JSON.parse(raw); } catch { /* partial chunk, skip */ }
      }
    }
  }
}

// ── Send message ───────────────────────────────────────────────────────────

async function sendMessage() {
  const text = inputEl.value.trim();
  if (!text || streaming) return;

  inputEl.value = "";
  inputEl.style.height = "";

  messages.push({ role: "user", content: text });
  appendUserMessage(text);

  streaming = true;
  sendBtn.disabled = true;

  const { container: assistantEl, bubble } = appendAssistantMessage();
  let assistantText = "";
  let pendingToolBlock = null;
  const pendingToolBlocks = {};

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages, model: modelSelect.value }),
    });

    if (!response.ok) {
      bubble.textContent = `Error ${response.status}`;
      return;
    }

    const reader  = response.body.getReader();
    const decoder = new TextDecoder();
    let   buf     = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });

      for (const chunk of parseSSEChunk(buf)) {
        buf = "";  // clear after successful parse pass

        switch (chunk.type) {
          case "text":
            assistantText += chunk.text;
            bubble.textContent = assistantText;
            scrollToBottom();
            break;

          case "tool_call":
            pendingToolBlock = appendToolBlock(chunk.tool, chunk.args, assistantEl);
            pendingToolBlocks[chunk.tool] = pendingToolBlock;
            break;

          case "tool_result":
            if (pendingToolBlocks[chunk.tool]) {
              updateToolResult(pendingToolBlocks[chunk.tool], chunk.result);
            }
            break;

          case "error":
            bubble.textContent += `\n\n[Error: ${chunk.error}]`;
            scrollToBottom();
            break;

          case "done":
            if (assistantText) {
              messages.push({ role: "assistant", content: assistantText });
            }
            break;
        }
      }
    }
  } catch (err) {
    bubble.textContent = `Connection error: ${err.message}`;
  } finally {
    streaming     = false;
    sendBtn.disabled = false;
    inputEl.focus();
  }
}

// ── Auto-resize textarea ───────────────────────────────────────────────────

inputEl.addEventListener("input", () => {
  inputEl.style.height = "";
  inputEl.style.height = Math.min(inputEl.scrollHeight, 160) + "px";
});

inputEl.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

sendBtn.addEventListener("click", sendMessage);

// ── Init ───────────────────────────────────────────────────────────────────

loadModels();
checkHealth();
refreshFaultStatus();
setInterval(checkHealth,         15_000);
setInterval(refreshFaultStatus,   5_000);

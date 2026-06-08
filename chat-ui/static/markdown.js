"use strict";

function escHtml(s) {
  return String(s)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;")
    .replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

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

export function renderText(raw: string): string {
  // Ensure blank line before/after table blocks (model often omits these)
  let text = raw
    .replace(/([^|\n])\n(\|)/g, '$1\n\n$2')
    .replace(/(\|[^\n]*)\n([^|\n])/g, '$1\n\n$2')

  text = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/```[\w]*\n?([\s\S]*?)```/g, (_, c) => `<pre><code>${c.trim()}</code></pre>`)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/^#{4,} (.+)$/gm, '<h4>$1</h4>')
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    .replace(/^[-*] (.+)$/gm, '<li>$1</li>')
    .replace(/(<li>[\s\S]*?<\/li>)/g, '<ul>$1</ul>')
    .replace(/^---$/gm, '<hr>')

  return text
    .split(/\n\n+/)
    .map(b => {
      b = b.trim()
      if (!b) return ''
      if (/^<(h[1-4]|pre|ul|ol|hr|li)/.test(b)) return b
      // Blockquote: `>` was escaped to `&gt;` above
      if (b.startsWith('&gt;')) {
        const inner = b
          .split('\n')
          .map(line => line.replace(/^&gt; ?/, ''))
          .join('<br>')
        return `<blockquote>${inner}</blockquote>`
      }
      if (b.startsWith('|')) {
        const rows = b.split('\n').filter(r => r.trim().startsWith('|'))
        const [firstRow, sepRow, ...dataRows] = rows
        if (firstRow !== undefined && sepRow !== undefined && /^\|[-| :]+\|$/.test(sepRow.trim())) {
          const hdrs = firstRow.split('|').slice(1, -1)
            .map(c => `<th>${c.trim()}</th>`).join('')
          const body = dataRows.map(r => {
            const cells = r.split('|').slice(1, -1)
              .map(c => `<td>${c.trim()}</td>`).join('')
            return `<tr>${cells}</tr>`
          }).join('')
          return `<table><thead><tr>${hdrs}</tr></thead><tbody>${body}</tbody></table>`
        }
      }
      return `<p>${b.replace(/\n/g, '<br>')}</p>`
    })
    .join('\n')
}

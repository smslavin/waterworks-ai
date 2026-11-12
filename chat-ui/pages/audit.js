function toggle(idx) {
  const body = document.getElementById('body-' + idx);
  const chev = document.getElementById('chev-' + idx);
  const open = body.style.display !== 'none';
  body.style.display = open ? 'none' : 'block';
  chev.classList.toggle('open', !open);
}
function expandAll() {
  document.querySelectorAll('.session-body').forEach(b => b.style.display = 'block');
  document.querySelectorAll('.chevron').forEach(c => c.classList.add('open'));
}
function collapseAll() {
  document.querySelectorAll('.session-body').forEach(b => b.style.display = 'none');
  document.querySelectorAll('.chevron').forEach(c => c.classList.remove('open'));
}

const _FILTERS = ['hide-tools', 'reactive-only'];
function setFilter(mode) {
  _FILTERS.forEach(f => document.body.classList.remove(f));
  if (mode) document.body.classList.add(mode);
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  const activeId = mode ? 'filter-' + mode : 'filter-all';
  document.getElementById(activeId)?.classList.add('active');
  localStorage.setItem('audit-filter', mode);
}
setFilter(localStorage.getItem('audit-filter') || '');

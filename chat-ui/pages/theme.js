function applyTheme(dark) {
  document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
  document.getElementById('theme-toggle').textContent = dark ? '☀ Light mode' : '🌙 Dark mode';
}
function toggleTheme() {
  const dark = document.documentElement.getAttribute('data-theme') !== 'dark';
  localStorage.setItem('theme', dark ? 'dark' : 'light');
  applyTheme(dark);
}
applyTheme(localStorage.getItem('theme') === 'dark');

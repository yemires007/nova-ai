// apply saved theme as early as possible to avoid a flash
(function () {
  try { document.documentElement.dataset.theme = localStorage.getItem('nova-theme') || 'light'; } catch (e) {}
  document.addEventListener('DOMContentLoaded', function () {
    var btn = document.getElementById('theme-toggle');
    if (!btn) return;
    function paint() { btn.textContent = document.documentElement.dataset.theme === 'dark' ? '☀' : '🌙'; }
    paint();
    btn.addEventListener('click', function () {
      var t = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
      document.documentElement.dataset.theme = t;
      try { localStorage.setItem('nova-theme', t); } catch (e) {}
      paint();
    });
  });
})();

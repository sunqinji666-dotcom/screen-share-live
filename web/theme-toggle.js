// 同屏日夜主题切换：默认夜间，localStorage 记忆
// 用法：<script src="theme-toggle.js"></script> + <button class="icon-btn" data-theme-toggle></button>
// head 里需要防闪白：<script>document.documentElement.dataset.theme=localStorage.getItem('ssl_theme')||'dark'</script>
(function () {
  var KEY = 'ssl_theme';
  function get() { try { return localStorage.getItem(KEY) || 'dark'; } catch (_) { return 'dark'; } }
  function apply() { document.documentElement.dataset.theme = get(); }
  apply();
  function paint(btn) {
    btn.innerHTML = '<i data-lucide="' + (get() === 'dark' ? 'sun' : 'moon') + '"></i>';
  }
  function init() {
    document.querySelectorAll('[data-theme-toggle]').forEach(function (btn) {
      paint(btn);
      btn.onclick = function () {
        try { localStorage.setItem(KEY, get() === 'dark' ? 'light' : 'dark'); } catch (_) {}
        apply();
        paint(btn);
        if (window.lucide) window.lucide.createIcons({ attrs: { 'stroke-width': 1.75 } });
      };
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();

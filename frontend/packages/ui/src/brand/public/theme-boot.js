// Before the app loads: the theme this browser remembers, on <html>, so the loading splash and
// the scrollbars are already in that theme (QA 2026-11-12 V-01, V-02). A file of its own, not
// inline: the pages' Content-Security-Policy allows scripts from 'self' only. Keys:
// themeMode.ts (supportx.theme_mode) and the UI language (supportx.locale).
(function () {
  var root = document.documentElement;
  try {
    var mode = window.localStorage.getItem('supportx.theme_mode');
    if (mode === 'light' || mode === 'dark' || mode === 'high_contrast') root.dataset.theme = mode;
    var locale = window.localStorage.getItem('supportx.locale');
    if (locale === 'ar' || locale === 'ur') {
      root.lang = locale;
      root.dir = 'rtl';
    }
  } catch {
    // storage unavailable (private mode): the system's theme applies
  }
})();

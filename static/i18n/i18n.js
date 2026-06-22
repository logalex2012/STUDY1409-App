(function () {
  const SUPPORTED = { ru: 'Русский', en: 'English', es: 'Español', de: 'Deutsch', it: 'Italiano', tr: 'Türkçe' };
  let _dict = {};
  let _current = localStorage.getItem('lang') || 'ru';

  if (!SUPPORTED[_current]) _current = 'ru';

  function t(key, vars) {
    let val = _dict[key];
    if (val === undefined) val = key;
    if (vars && typeof vars === 'object') {
      for (const [k, v] of Object.entries(vars)) {
        val = String(val).replace(new RegExp(`\\{${k}\\}`, 'g'), v);
      }
    }
    return val;
  }

  function apply() {
    document.querySelectorAll('[data-i18n]').forEach(el => {
      const key = el.getAttribute('data-i18n');
      const raw = t(key);
      const placeholder = el.getAttribute('data-i18n-placeholder');
      if (placeholder !== null) {
        el.setAttribute('placeholder', raw);
      } else {
        el.textContent = raw;
      }
    });
    document.documentElement.lang = _current;
    localStorage.setItem('lang', _current);
  }

  async function load(lang) {
    _current = lang;
    try {
      const res = await fetch('/static/i18n/' + lang + '.json?v=1');
      _dict = await res.json();
    } catch {
      if (lang !== 'ru') {
        try {
          const res2 = await fetch('/static/i18n/ru.json?v=1');
          _dict = await res2.json();
        } catch {}
      }
    }
    apply();
  }

  async function setLanguage(lang) {
    if (!SUPPORTED[lang]) return;
    _current = lang;
    localStorage.setItem('lang', lang);
    await load(lang);
    document.dispatchEvent(new CustomEvent('langchange', { detail: { lang } }));
  }

  function getCurrent() { return _current; }
  function getLanguages() { return { ...SUPPORTED }; }

  window.__ = t;
  window.__lang = { setLanguage, getCurrent, getLanguages, load, apply };

  document.addEventListener('DOMContentLoaded', () => load(_current));
})();

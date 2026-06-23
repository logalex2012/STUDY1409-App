/* ── STUDY1409 — Telegram Web App integration ──────────────── */
(function () {
    var tg = window.Telegram?.WebApp;
    if (!tg) return;

    // ── Базовая инициализация ─────────────────────────────────
    tg.ready();
    tg.expand();

    document.documentElement.setAttribute('data-tg', '1');

    // ── CSS для Telegram Mini App ─────────────────────────────
    (function injectTgStyles() {
        var style = document.createElement('style');
        style.textContent = [
            '[data-tg] {',
            '  --bg-primary: var(--tg-bg, #000) !important;',
            '  --text-primary: var(--tg-text, #fff) !important;',
            '  --text-secondary: var(--tg-subtitle-text, rgba(255,255,255,0.7)) !important;',
            '  --border-color: var(--tg-section-separator, rgba(255,255,255,0.12)) !important;',
            '  --accent: var(--tg-button, #4446E1) !important;',
            '  --accent-text: var(--tg-button-text, #fff) !important;',
            '  padding-top: var(--tg-safe-top, 0px);',
            '  padding-bottom: var(--tg-safe-bottom, 0px);',
            '  min-height: 100vh;',
            '  min-height: calc(var(--tg-vh, 1vh) * 100);',
            '  box-sizing: border-box;',
            '}',
            '[data-tg] .tg-header {',
            '  padding-top: var(--tg-safe-top, 0px);',
            '}',
        ].join('\n');
        document.head.appendChild(style);
    })();

    // ── Применяем Telegram CSS-переменные ─────────────────────
    function applyTgVars() {
        var colorScheme = tg.colorScheme || 'dark';
        var theme = tg.themeParams || {};

        var root = document.documentElement;
        root.style.setProperty('--tg-safe-top', 'env(safe-area-inset-top, 0px)');
        root.style.setProperty('--tg-safe-bottom', 'env(safe-area-inset-bottom, 0px)');
        root.style.setProperty('--tg-bg', theme.bg_color || '#000');
        root.style.setProperty('--tg-text', theme.text_color || '#fff');
        root.style.setProperty('--tg-hint', theme.hint_color || '#999');
        root.style.setProperty('--tg-link', theme.link_color || '#4446E1');
        root.style.setProperty('--tg-button', theme.button_color || '#4446E1');
        root.style.setProperty('--tg-button-text', theme.button_text_color || '#fff');
        root.style.setProperty('--tg-secondary-bg', theme.secondary_bg_color || '#111');
        root.style.setProperty('--tg-header-bg', theme.header_bg_color || '#000');
        root.style.setProperty('--tg-accent-text', theme.accent_text_color || '#4446E1');
        root.style.setProperty('--tg-section-bg', theme.section_bg_color || '#111');
        root.style.setProperty('--tg-section-separator', theme.section_separator_color || '#333');
        root.style.setProperty('--tg-subtitle-text', theme.subtitle_text_color || '#999');
        root.style.setProperty('--tg-destructive-text', theme.destructive_text_color || '#e53935');

        // Синхронизируем цвет шапки TG с фоном
        try {
            tg.setHeaderColor(theme.bg_color || '#000');
            tg.setBackgroundColor(theme.bg_color || '#000');
        } catch (_) {}
    }

    applyTgVars();

    // Слушаем смену темы в TG
    tg.onEvent('themeChanged', applyTgVars);

    // ── Адаптация под клавиатуру ──────────────────────────────
    tg.onEvent('viewportChanged', function () {
        var h = tg.viewportStableHeight;
        if (h) {
            document.documentElement.style.setProperty('--tg-vh', h + 'px');
        }
    });

    // Сразу задаём высоту
    setTimeout(function () {
        var h = tg.viewportStableHeight;
        if (h) document.documentElement.style.setProperty('--tg-vh', h + 'px');
    }, 100);

    // ── Тема по умолчанию из TG colorScheme ──────────────────
    (function () {
        if (localStorage.getItem('theme')) return;
        var preferred = tg.colorScheme === 'light' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', preferred);
    })();

    // ── Аватар из Telegram ────────────────────────────────────
    (function () {
        if (localStorage.getItem('user_avatar')) return;
        var user = tg.initDataUnsafe && tg.initDataUnsafe.user;
        if (!user || !user.photo_url) return;

        localStorage.setItem('tg_avatar', user.photo_url);

        function applyAvatar(url) {
            document.querySelectorAll('#avatarImg, #avatarPreview').forEach(function (el) {
                el.src = url;
                if (el.id === 'avatarPreview') el.style.display = 'block';
            });
            var icon = document.getElementById('avatarIcon');
            if (icon) icon.style.display = 'none';
        }

        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', function () { applyAvatar(user.photo_url); });
        } else {
            applyAvatar(user.photo_url);
        }
    })();

    window._tg = tg;
    window._tgApplyVars = applyTgVars;
})();

/**
 * Вызови на каждой странице после загрузки DOM.
 *
 * @param {object} opts
 *   backButton   {boolean}  — кнопка «Назад» TG (default: true)
 *   mainButton   {object}   — { text, color, onClick }
 *   onBack       {function} — кастомный обработчик назад
 */
function initTelegramWebApp(opts) {
    opts = opts || {};
    var tg = window._tg;
    if (!tg) return;

    // ── BackButton ────────────────────────────────────────────
    if (opts.backButton !== false) {
        tg.BackButton.show();
        tg.BackButton.onClick(function () {
            if (typeof opts.onBack === 'function') {
                opts.onBack();
            } else {
                history.back();
            }
        });
    } else {
        tg.BackButton.hide();
    }

    // ── MainButton ────────────────────────────────────────────
    if (opts.mainButton) {
        var mb = opts.mainButton;
        tg.MainButton.setText(mb.text || 'Готово');
        if (mb.color) tg.MainButton.setParams({ color: mb.color });
        if (typeof mb.onClick === 'function') tg.MainButton.onClick(mb.onClick);
        tg.MainButton.show();
    }
}

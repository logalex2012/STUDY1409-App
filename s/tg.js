/* ── STUDY1409 — Telegram Web App integration ──────────────── */
(function () {
    const tg = window.Telegram?.WebApp;
    if (!tg) return;

    // ── Базовая инициализация ─────────────────────────────────
    tg.ready();
    tg.expand();

    // Пометить документ как запущенный в TG
    document.documentElement.setAttribute('data-tg', '1');

    // ── Синхронизация цвета шапки с темой приложения ─────────
    function syncColors() {
        const theme = document.documentElement.getAttribute('data-theme') || 'dark';
        const palette = {
            dark:     '#000000',
            light:    '#f5f7fa',
            stranger: '#050005',
        };
        const bg = palette[theme] || '#000000';
        try {
            tg.setHeaderColor(bg);
            tg.setBackgroundColor(bg);
        } catch (_) { /* старые версии TG не поддерживают */ }
    }

    // Применить цвета сразу
    syncColors();

    // Следить за сменой темы
    new MutationObserver(syncColors).observe(
        document.documentElement,
        { attributes: true, attributeFilter: ['data-theme'] }
    );

    // ── Тема по умолчанию из TG colorScheme ──────────────────
    // Применяем только если пользователь ещё не выбрал тему вручную
    (function applyTgTheme() {
        if (localStorage.getItem('theme')) return; // уже выбрана
        const preferred = tg.colorScheme === 'light' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', preferred);
        // Не сохраняем в localStorage — пусть TG управляет
    })();

    // ── Safe-area padding для iOS ─────────────────────────────
    document.documentElement.style.setProperty(
        '--tg-safe-top',
        'env(safe-area-inset-top, 0px)'
    );

    // ── Аватар из Telegram ────────────────────────────────────
    // Если пользователь ещё не загрузил свой аватар вручную,
    // берём photo_url из Telegram initDataUnsafe
    (function loadTgAvatar() {
        if (localStorage.getItem('user_avatar')) return; // уже есть кастомный

        const user = tg.initDataUnsafe && tg.initDataUnsafe.user;
        if (!user || !user.photo_url) return;

        // Сохраняем как «аватар из TG» — отдельный ключ, чтобы не конкурировать с ручной загрузкой
        localStorage.setItem('tg_avatar', user.photo_url);

        // Обновляем все аватарки на странице
        const applyAvatar = function (url) {
            document.querySelectorAll('#avatarImg, #avatarPreview').forEach(function (el) {
                el.src = url;
                if (el.id === 'avatarPreview') el.style.display = 'block';
            });
            var icon = document.getElementById('avatarIcon');
            if (icon) icon.style.display = 'none';
        };

        // Ждём загрузки DOM, если ещё не готов
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', function () { applyAvatar(user.photo_url); });
        } else {
            applyAvatar(user.photo_url);
        }
    })();

    // Сделать доступным глобально
    window._tg          = tg;
    window._tgSyncColors = syncColors;
})();

/**
 * Вызови на каждой странице после загрузки DOM.
 *
 * @param {object} opts
 *   backButton  {boolean}   — показать кнопку «Назад» TG (default: true)
 *   mainButton  {object}    — { text, color, onClick } для MainButton TG
 *   onThemeChange {fn}      — вызывается при смене темы TG
 */
function initTelegramWebApp(opts) {
    opts = opts || {};
    const tg = window._tg;
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
        const mb = opts.mainButton;
        tg.MainButton.setText(mb.text || 'Готово');
        if (mb.color) tg.MainButton.setParams({ color: mb.color });
        if (typeof mb.onClick === 'function') tg.MainButton.onClick(mb.onClick);
        tg.MainButton.show();
    }

    // ── Слушатель смены темы TG ───────────────────────────────
    if (typeof opts.onThemeChange === 'function') {
        tg.onEvent('themeChanged', function () {
            if (window._tgSyncColors) window._tgSyncColors();
            opts.onThemeChange(tg.colorScheme);
        });
    }
}

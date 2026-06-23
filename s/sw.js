/* ── STUDY1409 Service Worker ─────────────────────────────── */
const CACHE_VERSION = 'v2';
const CACHE_NAME    = `study1409-${CACHE_VERSION}`;

const PRECACHE_ASSETS = [
    '/s/favicon.png',
    '/s/default_avatar.png',
    '/s/manifest.json',
    '/s/fonts/fonts.css',
    '/s/lib/lucide.min.js',
    '/s/lib/qrcode.min.js',
    '/s/lib/font-awesome/all.min.css',
    '/offline',
];

// ── Install: precache static shell ───────────────────────────
self.addEventListener('install', event => {
    self.skipWaiting();
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => cache.addAll(PRECACHE_ASSETS))
    );
});

// ── Activate: remove old caches ──────────────────────────────
self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys()
            .then(keys => Promise.all(
                keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
            ))
            .then(() => self.clients.claim())
    );
});

// ── Fetch: routing strategy ───────────────────────────────────
self.addEventListener('fetch', event => {
    const { request } = event;
    const url = new URL(request.url);

    // Skip non-GET and API requests (always network)
    if (request.method !== 'GET' || url.pathname.startsWith('/api/')) return;

    // Static assets → Cache First, fall back to network
    if (url.pathname.startsWith('/s/')) {
        event.respondWith(
            caches.match(request).then(cached => {
                if (cached) return cached;
                return fetch(request).then(res => {
                    const clone = res.clone();
                    caches.open(CACHE_NAME).then(c => c.put(request, clone));
                    return res;
                });
            })
        );
        return;
    }

    // HTML pages → Network First, fall back to cache, then /offline
    event.respondWith(
        fetch(request)
            .then(res => {
                if (res.ok) {
                    const clone = res.clone();
                    caches.open(CACHE_NAME).then(c => c.put(request, clone));
                }
                return res;
            })
            .catch(() =>
                caches.match(request)
                    .then(cached => cached || caches.match('/offline'))
            )
    );
});

// ── Push: show notification ────────────────────────────────────
self.addEventListener('push', event => {
    let data = {};
    try { data = event.data ? event.data.json() : {}; } catch {}

    const title   = data.title || 'STUDY1409';
    const options = {
        body    : data.body    || '',
        icon    : '/s/favicon.png',
        badge   : '/s/favicon.png',
        tag     : data.tag     || 'study1409',
        renotify: !!data.tag,
        data    : { url: data.url || '/apps' },
        vibrate : [200, 100, 200],
    };

    event.waitUntil(self.registration.showNotification(title, options));
});

// ── Notification click: open / focus app ──────────────────────
self.addEventListener('notificationclick', event => {
    event.notification.close();
    const target = (event.notification.data && event.notification.data.url) || '/apps';

    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
            for (const c of list) {
                if ('focus' in c) {
                    c.navigate(target);
                    return c.focus();
                }
            }
            return clients.openWindow(target);
        })
    );
});

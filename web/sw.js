/* TouchLink service worker — network-first cho code, fallback cache khi offline */
var CACHE = 'touchlink-v2';
var ICONS = [
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/manifest.webmanifest'
];
self.addEventListener('install', function (e) {
  e.waitUntil(caches.open(CACHE).then(function (c) {
    return Promise.all(ICONS.map(function (a) {
      return c.add(a).catch(function () {});
    }));
  }).then(function () { return self.skipWaiting(); }));
});
self.addEventListener('activate', function (e) {
  e.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (k) { return k !== CACHE; })
      .map(function (k) { return caches.delete(k); }));
  }).then(function () { return clients.claim(); }));
});
self.addEventListener('fetch', function (e) {
  var url = new URL(e.request.url);
  if (url.pathname.startsWith('/static/icons/')) {
    e.respondWith(caches.match(e.request).then(function (r) {
      return r || fetch(e.request);
    }));
    return;
  }
  if (url.pathname.startsWith('/static/') || url.pathname === '/') {
    e.respondWith(fetch(e.request).then(function (res) {
      if (res.ok) {
        var cl = res.clone();
        caches.open(CACHE).then(function (c) { c.put(e.request, cl); });
      }
      return res;
    }).catch(function () {
      return caches.match(e.request).then(function (r) {
        return r || Response.error();
      });
    }));
  }
});

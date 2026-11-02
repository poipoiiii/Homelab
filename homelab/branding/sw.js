// 仅用于让 Chrome 判定该页面为可安装 PWA；不缓存任何资源，全部直连网络
self.addEventListener('install', function () {
  self.skipWaiting();
});

self.addEventListener('activate', function (event) {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', function () {
  // 故意不调用 respondWith，请求照常走网络，避免看板拿到旧缓存
});

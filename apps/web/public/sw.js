/* Service worker do YARD.
 *
 * Dado operacional NUNCA vem do cache: /api, /ws, /sse e /portal passam direto — tela
 * de pátio mostrando fila de ontem como se fosse agora é pior que tela fora do ar.
 * O que se guarda é a casca do app (HTML, JS/CSS com hash, ícones), para abrir rápido
 * e instalar como aplicativo.
 */
const VERSION = 'yard-v2'
const SHELL = ['/', '/manifest.webmanifest', '/icons/icon.svg', '/icons/icon-192.png', '/icons/icon-512.png']

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(VERSION).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()))
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== VERSION).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', (event) => {
  const request = event.request
  if (request.method !== 'GET') return
  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return
  if (/^\/(api|ws|sse|portal|health|ready)(\/|$)/.test(url.pathname)) return

  // Navegação: rede primeiro (versão nova do app entra logo); sem rede, a casca guardada.
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone()
          void caches.open(VERSION).then((cache) => cache.put('/', copy))
          return response
        })
        .catch(() => caches.match('/')),
    )
    return
  }

  // Asset com hash no nome e ícone: cache primeiro, é imutável.
  if (url.pathname.startsWith('/assets/') || url.pathname.startsWith('/icons/')) {
    event.respondWith(
      caches.match(request).then(
        (hit) =>
          hit ||
          fetch(request).then((response) => {
            if (response.ok) {
              const copy = response.clone()
              void caches.open(VERSION).then((cache) => cache.put(request, copy))
            }
            return response
          }),
      ),
    )
  }
})

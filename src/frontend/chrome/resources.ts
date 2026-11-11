const encoder = new TextEncoder();

function base64(bytes) {
  let binary = '';
  bytes.forEach(byte => { binary += String.fromCharCode(byte); });
  return btoa(binary);
}

/** Check a library against the SRI hash recorded in the page config,
 *  so a tampered CDN response or cache entry is never executed.
 */
async function verified(resource, text) {
  const [algorithm, expected] = resource.integrity.split('-', 2);
  if (algorithm !== 'sha384' || !expected) return false;
  const digest = await crypto.subtle.digest('SHA-384', encoder.encode(text));
  return base64(new Uint8Array(digest)) === expected;
}

/** Cache first, then the CDN. Both paths go through `verified`,
 *  so a stale or tampered cache entry is dropped and refetched instead of trusted.
 */
async function download(resource, cacheName) {
  let cache;
  if ('caches' in window) {
    try { cache = await caches.open(cacheName); } catch (error) { cache = null; }
  }
  if (cache) {
    const found = await cache.match(resource.url);
    if (found) {
      const text = await found.text();
      if (await verified(resource, text)) return text;
      await cache.delete(resource.url);
    }
  }
  const response = await fetch(resource.url, { mode: 'cors', credentials: 'omit' });
  if (!response.ok) throw new Error(`${resource.url}: HTTP ${response.status}`);
  const text = await response.text();
  if (!await verified(resource, text)) {
    throw new Error(`${resource.url}: SHA-384 integrity check failed`);
  }
  if (cache) {
    await cache.put(resource.url, new Response(text, {
      headers: {
        'Content-Type': resource.type === 'style'
          ? 'text/css; charset=utf-8' : 'text/javascript; charset=utf-8'
      }
    }));
  }
  return text;
}

async function install(resource, text) {
  // resource.type in 'style|script'
  if (resource.type === 'style') {
    // A stylesheet is inlined
    const style = document.createElement('style');
    style.dataset.tmdLibrary = resource.name;
    style.textContent = text;
    document.head.appendChild(style);
    return Promise.resolve();
  }
  // a script runs from a blob URL, which keeps the CSP at `blob:`
  //  instead of allowing each CDN host to run code directly.
  return new Promise<void>((resolve, reject) => {
    const blob = new Blob([text], { type: 'text/javascript' });
    const url = URL.createObjectURL(blob);
    const script = document.createElement('script');
    script.src = url;
    script.dataset.tmdLibrary = resource.name;
    script.onload = () => { URL.revokeObjectURL(url); resolve(); };
    script.onerror = () => { URL.revokeObjectURL(url); reject(new Error(`could not execute ${resource.name}`)); };
    document.head.appendChild(script);
  });
}

export async function loadResources(resources, cacheName) {
  for (const resource of resources) {
    if (resource.global && window[resource.global]) continue;
    await install(resource, await download(resource, cacheName));
  }
  if (typeof window.markdownit !== 'function' || !window.hljs) {
    throw new Error('renderer libraries did not expose their browser globals');
  }
}

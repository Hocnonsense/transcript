/* Serve Datavzrd reports entirely from the files embedded in this document. */
(async () => {
  "use strict";
  const registry = JSON.parse(document.getElementById("snakedone-reports").textContent);
  const origin = "https://snakedone.invalid/";
  const decoder = new TextDecoder();

  function base64Bytes(content) {
    return Uint8Array.from(atob(content), c => c.charCodeAt(0));
  }

  async function gunzip(bytes) {
    const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
    return new Uint8Array(await new Response(stream).arrayBuffer());
  }

  // Files shared by several reports are decompressed once.
  const cache = new Map();
  function materialize(hash) {
    if (!cache.has(hash)) {
      cache.set(hash, (async () => {
        const file = registry.pool[hash];
        const raw = base64Bytes(file.content);
        return {mime: file.mime, bytes: file.gzip ? await gunzip(raw) : raw};
      })());
    }
    return cache.get(hash);
  }

  async function filesFor(id) {
    const entries = Object.entries(registry.reports[id]);
    const pairs = await Promise.all(
      entries.map(async ([name, hash]) => [name, await materialize(hash)]),
    );
    return Object.fromEntries(pairs);
  }

  function resolve(path, base = origin) {
    const url = new URL(path, base);
    return url.origin === new URL(origin).origin ? url : null;
  }

  function key(url) {
    return decodeURIComponent(url.pathname.slice(1));
  }

  function decode(file) {
    return decoder.decode(file.bytes);
  }

  function blob(content, type) {
    return URL.createObjectURL(new Blob([content], {type}));
  }

  function adaptJavaScript(source) {
    // Location is not configurable in browsers. Give Datavzrd its own location
    // so links and query parameters continue to work inside an offline srcdoc.
    return source
      .replace(/\bwindow\.location\s*=(?!=)/g, "window.__snakedoneLocation.href =")
      .replace(/\bwindow\.location\b/g, "window.__snakedoneLocation")
      .replace(/\blocation\s*=\s*this\.value/g, "window.__snakedoneLocation.href = this.value");
  }

  // This function is injected before any native report script, including in
  // search dialogs. It communicates with the shell using postMessage so the
  // shell controls navigation, resource loading and nested frames.
  function bootstrap(url, id, parentId, depth, channel) {
    let shell = window;
    for (let index = 0; index < depth; index++) shell = shell.parent;
    const children = new Map();
    let sequence = 0;
    const send = message => shell.postMessage({channel, id, ...message}, "*");
    const navigate = (path, target = "_self") => send({action: "navigate", path, target});
    const address = new URL(url);
    const location = {
      get href() { return address.href; },
      set href(path) { navigate(path); },
      get search() { return address.search; },
      get hash() { return address.hash; },
      set hash(hash) { address.hash = hash; },
      get pathname() { return address.pathname; },
      get protocol() { return address.protocol; },
      get host() { return address.host; },
      get hostname() { return address.hostname; },
      get port() { return address.port; },
      get origin() { return address.origin; },
      assign: navigate,
      replace: navigate,
      reload() { navigate(address.href); },
      toString() { return address.href; },
    };
    window.__snakedoneLocation = location;
    // Datavzrd builds its controls with inline event handlers, which a
    // hash-based CSP blocks. Re-attach them as listeners instead, keeping the
    // element as `this` and preserving `return false` default prevention.
    const inlineEvents = [
      "onclick", "onchange", "oninput", "onkeyup", "onkeydown", "onsubmit",
      "ondblclick",
    ];
    const inlineSelector = inlineEvents.map(name => `[${name}]`).join(",");
    function convertInlineHandlers(element) {
      for (const name of inlineEvents) {
        if (!element.hasAttribute(name)) continue;
        const code = element.getAttribute(name);
        element.removeAttribute(name);
        const handler = new Function("event", code);
        element.addEventListener(name.slice(2), function (event) {
          if (handler.call(this, event) === false) event.preventDefault();
        });
      }
    }
    function convertInlineTree(root) {
      if (root.nodeType === 1) convertInlineHandlers(root);
      if (root.querySelectorAll) {
        for (const element of root.querySelectorAll(inlineSelector)) {
          convertInlineHandlers(element);
        }
      }
    }
    new MutationObserver(records => {
      for (const record of records) {
        for (const node of record.addedNodes) {
          if (node.nodeType === 1) convertInlineTree(node);
        }
      }
    }).observe(document.documentElement, {subtree: true, childList: true});
    convertInlineTree(document);
    // Datavzrd is a full-viewport app (`#page-container { min-height: 100vh }`),
    // which leaves a small table surrounded by empty space when embedded.
    // Relax it and report the real content height so the shell can size the frame.
    const sizing = document.createElement("style");
    // `flow-root` keeps the header spacer margin inside the container so its
    // measured height matches the visible content.
    sizing.textContent =
      "#page-container { min-height: 0 !important; display: flow-root; }";
    document.head.append(sizing);
    function reportHeight(container) {
      send({action: "resize", height: Math.ceil(container.getBoundingClientRect().height)});
    }
    const heightWatch = new MutationObserver(() => {
      const container = document.getElementById("page-container");
      if (!container) return;
      heightWatch.disconnect();
      new ResizeObserver(() => reportHeight(container)).observe(container);
      reportHeight(container);
    });
    heightWatch.observe(document.documentElement, {subtree: true, childList: true});
    function local(path) {
      if (!path || path.startsWith("#")) return false;
      try { return new URL(path, address).origin === address.origin; }
      catch { return false; }
    }
    function loadFrame(frame, path) {
      let childId = frame.dataset.snakedoneFrame;
      if (!childId) {
        childId = `${id}-${++sequence}`;
        frame.dataset.snakedoneFrame = childId;
        children.set(childId, frame);
      }
      send({action: "frame", frameId: childId, path});
    }
    const setAttribute = Element.prototype.setAttribute;
    Element.prototype.setAttribute = function (name, value) {
      if (this instanceof HTMLIFrameElement && name.toLowerCase() === "src" && local(String(value))) {
        loadFrame(this, String(value));
        return;
      }
      return setAttribute.call(this, name, value);
    };
    const frameSrc = Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype, "src");
    Object.defineProperty(HTMLIFrameElement.prototype, "src", {
      ...frameSrc,
      set(value) {
        if (local(String(value))) loadFrame(this, String(value));
        else frameSrc.set.call(this, value);
      },
    });
    document.addEventListener("click", event => {
      const anchor = event.target.closest && event.target.closest("a[href]");
      if (!anchor || anchor.hasAttribute("download")) return;
      const path = anchor.getAttribute("href");
      // Fragment links resolve against the parent document in a srcdoc frame,
      // so the default action would reload the report inside itself. Datavzrd
      // still handles them through its own listeners.
      if (!path || path.startsWith("#")) {
        event.preventDefault();
        return;
      }
      if (!local(path)) return;
      event.preventDefault();
      navigate(path, anchor.getAttribute("target") || "_self");
    }, true);
    window.addEventListener("message", event => {
      if (event.source !== shell || event.data?.channel !== channel) return;
      const message = event.data;
      if (message.action === "html") {
        const frame = children.get(message.frameId);
        if (frame) frame.srcdoc = message.html;
      } else if (message.action === "download") {
        const anchor = document.createElement("a");
        anchor.href = message.url;
        anchor.download = message.filename;
        anchor.click();
      } else if (message.action === "error") {
        const error = document.createElement("p");
        error.setAttribute("role", "alert");
        error.textContent = message.message;
        document.body.prepend(error);
      }
    });
  }

  function createReport(files, container) {
    const channel = `snakedone-datavzrd-${Math.random().toString(36).slice(2)}`;
    const urls = new Map();
    const frames = new Map();
    const report = document.createElement("iframe");
    report.className = "datavzrd-page";
    report.title = "Datavzrd report";
    report.style.cssText = "width:100%;height:480px;max-height:90vh;border:0;display:block";
    container.append(report);

    function resource(path, base) {
      const url = resolve(path, base);
      if (!url || !files[key(url)]) return path;
      const name = key(url);
      if (!urls.has(name)) {
        const file = files[name];
        let content;
        if (/javascript/.test(file.mime) || name.endsWith(".js")) {
          content = adaptJavaScript(decode(file));
        } else if (file.mime === "text/css") {
          content = rewriteCSS(decode(file), url.href);
        } else {
          content = file.bytes;
        }
        urls.set(name, blob(content, file.mime));
      }
      return urls.get(name) + url.hash;
    }

    function rewriteCSS(css, base) {
      return css.replace(/url\(\s*(['"]?)([^)'"\s]+)\1\s*\)/g,
        (match, quote, path) => path.startsWith("#") ? match : `url("${resource(path, base)}")`);
    }

    function page(address, id, parentId, depth) {
      const name = key(address);
      if (!files[name]) throw new Error(`The offline report does not contain ${name}.`);
      const html = new DOMParser().parseFromString(adaptJavaScript(decode(files[name])), "text/html");
      html.querySelectorAll("base").forEach(base => base.remove());
      html.querySelectorAll("link[href],img[src],source[src],video[src],audio[src]").forEach(element => {
        const attribute = element.hasAttribute("src") ? "src" : "href";
        element.setAttribute(attribute, resource(element.getAttribute(attribute), address.href));
        element.removeAttribute("integrity");
        element.removeAttribute("crossorigin");
      });
      html.querySelectorAll("script").forEach(element => {
        if (element.hasAttribute("src")) {
          element.setAttribute("src", resource(element.getAttribute("src"), address.href));
        } else if (element.textContent.trim()) {
          const source = adaptJavaScript(element.textContent);
          element.textContent = "";
          element.setAttribute("src", blob(source, "text/javascript"));
        }
        element.removeAttribute("integrity");
        element.removeAttribute("crossorigin");
      });
      html.querySelectorAll("style").forEach(style => { style.textContent = rewriteCSS(style.textContent, address.href); });
      html.querySelectorAll("[style]").forEach(element => {
        element.setAttribute("style", rewriteCSS(element.getAttribute("style"), address.href));
      });
      const script = html.createElement("script");
      script.src = blob(
        `(${bootstrap.toString()})(${[address.href, id, parentId, depth, channel].map(value => JSON.stringify(value)).join(",")});`,
        "text/javascript",
      );
      html.head.prepend(script);
      return "<!doctype html>\n" + html.documentElement.outerHTML;
    }

    function show(id, address) {
      const frame = frames.get(id);
      // Native downloads are files too, not pages to interpret as HTML.
      const file = files[key(address)];
      if (!file) throw new Error(`The offline report does not contain ${key(address)}.`);
      if (file.mime !== "text/html") {
        frame.window?.postMessage({channel, action: "download", url: resource(address.href, origin), filename: key(address).split("/").pop()}, "*");
        return;
      }
      frame.address = address;
      const html = page(address, id, frame.parentId, frame.depth);
      if (id === "root") report.srcdoc = html;
      else frame.owner.postMessage({channel, action: "html", frameId: id, html}, "*");
    }

    window.addEventListener("message", event => {
      const message = event.data;
      if (message?.channel !== channel || !frames.has(message.id)) return;
      const current = frames.get(message.id);
      if (message.id === "root" && event.source !== report.contentWindow) return;
      current.window = event.source;
      if (message.action === "resize") {
        // Only the top report drives the embedded frame height.
        if (message.id === "root") {
          report.style.height = `${Math.max(120, message.height)}px`;
        }
        return;
      }
      try {
        const address = resolve(message.path, current.address.href);
        if (!address) return;
        if (message.action === "frame") {
          frames.set(message.frameId, {owner: event.source, parentId: message.id, depth: current.depth + 1});
          show(message.frameId, address);
        } else if (message.action === "navigate") {
          const target = message.target === "_parent" ? current.parentId || "root" : message.target === "_top" ? "root" : message.id;
          show(target, address);
        }
      } catch (error) {
        event.source.postMessage({channel, action: "error", message: error.message}, "*");
      }
    });
    frames.set("root", {parentId: null, depth: 1});
    show("root", new URL("index.html", origin));
  }

  const selector = '[data-snakedone-report][data-snakedone-renderer="datavzrd"]';
  for (const container of document.querySelectorAll(selector)) {
    try {
      createReport(await filesFor(container.dataset.snakedoneReport), container);
    } catch (error) {
      const message = document.createElement("p");
      message.setAttribute("role", "alert");
      message.textContent = `snakedone: could not load the Datavzrd report: ${error}`;
      container.append(message);
    }
  }
})();

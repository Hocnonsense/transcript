/* Make each composed panel's label readable over whatever the chart draws
   behind it: sample the covered region, pick black or white text from its
   average brightness, compress the colours nearest that text into the middle
   luminance band, and use the adjusted patch as background.
   The CSS chip stays as a fallback when sampling is impossible (no chart,
   cross-origin image, disabled JavaScript). */
(() => {
  "use strict";
  if (!document.querySelector(".snakedone-panel-label")) return;

  function captionOf(panel) {
    const report = panel?.querySelector(
      ':scope > .snakedone-report[data-snd-renderer="label"]',
    );
    const figure = report?.querySelector(":scope > .snakedone-label");
    return figure?.querySelector(":scope > figcaption") || null;
  }

  function arrangeLabels() {
    const overlays = [];
    for (const compose of document.querySelectorAll(".snakedone-compose")) {
      const panels = [...compose.querySelectorAll(":scope > .snakedone-panel")];
      const entries = panels.map((panel) => {
        const caption = captionOf(panel);
        caption?.parentElement?.classList.remove(
          "snakedone-label-caption-header",
        );
        const label = panel.querySelector(
          ":scope > .snakedone-panel-label, " +
            ':scope > .snakedone-report[data-snd-renderer="label"] > ' +
            ".snakedone-label > figcaption > .snakedone-panel-label",
        );
        if (label) {
          for (const property of [
            "color",
            "background-image",
            "background-size",
            "background-repeat",
          ]) {
            label.style.removeProperty(property);
          }
          label.classList.remove(
            "snakedone-panel-label-inline",
            "snakedone-panel-label-header",
          );
          panel.prepend(label);
        }
        return {panel, label, caption};
      });
      const rows = new Map();
      for (const entry of entries) {
        const top = Math.round(entry.panel.getBoundingClientRect().top);
        const row = rows.get(top) || [];
        row.push(entry);
        rows.set(top, row);
      }
      for (const row of rows.values()) {
        const hasCaption = row.some((entry) => entry.label && entry.caption);
        for (const {label, caption} of row) {
          if (!label) continue;
          if (caption) {
            caption.parentElement.classList.add(
              "snakedone-label-caption-header",
            );
            label.classList.add("snakedone-panel-label-inline");
            caption.prepend(label);
          } else if (hasCaption) {
            label.classList.add("snakedone-panel-label-header");
          } else {
            overlays.push(label);
          }
        }
      }
    }
    return overlays;
  }

  let overlayLabels = arrangeLabels();

  const darkEdge = 0.35;
  const lightEdge = 0.58;
  function brightness(red, green, blue) {
    return (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255;
  }

  function pageBackground() {
    for (const element of [document.body, document.documentElement]) {
      if (!element) continue;
      const color = getComputedStyle(element).backgroundColor;
      if (color && color !== "transparent" && color !== "rgba(0, 0, 0, 0)") {
        return color;
      }
    }
    return matchMedia("(prefers-color-scheme: dark)").matches
      ? "rgb(18, 18, 18)"
      : "rgb(255, 255, 255)";
  }

  function loadImage(target) {
    if (target instanceof HTMLImageElement) return Promise.resolve(target);
    if (!(target instanceof SVGSVGElement)) return Promise.resolve(null);
    const rect = target.getBoundingClientRect();
    const clone = target.cloneNode(true);
    clone.setAttribute("width", String(rect.width));
    clone.setAttribute("height", String(rect.height));
    const xml = new XMLSerializer().serializeToString(clone);
    const url = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(xml);
    const image = new Image();
    return new Promise((resolve, reject) => {
      image.onload = () => resolve(image);
      image.onerror = reject;
      image.src = url;
    });
  }

  function makeCanvas(width, height) {
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(width));
    canvas.height = Math.max(1, Math.round(height));
    return canvas;
  }

  function tonePatch(context, width, height, useBlackText) {
    const image = context.getImageData(0, 0, width, height);
    const pixels = image.data;
    for (let index = 0; index < pixels.length; index += 4) {
      const luminance = brightness(
        pixels[index],
        pixels[index + 1],
        pixels[index + 2],
      );
      let scale;
      let offset;
      if (useBlackText && luminance < lightEdge) {
        // Keep the light band unchanged. Lift the middle and dark bands
        // into the middle band; even black stays visibly separated from text.
        const target =
          darkEdge + (luminance * (lightEdge - darkEdge)) / lightEdge;
        scale = (1 - target) / (1 - luminance);
        offset = 255 * (1 - scale);
      } else if (!useBlackText && luminance > darkEdge) {
        // Keep the dark band unchanged and mirror the operation for white text.
        const target =
          darkEdge +
          ((luminance - darkEdge) * (lightEdge - darkEdge)) / (1 - darkEdge);
        scale = target / luminance;
        offset = 0;
      } else {
        continue;
      }
      pixels[index] = pixels[index] * scale + offset;
      pixels[index + 1] = pixels[index + 1] * scale + offset;
      pixels[index + 2] = pixels[index + 2] * scale + offset;
    }
    context.putImageData(image, 0, 0);
  }

  async function adapt(label) {
    const panel = label.closest(".snakedone-panel");
    const target = panel && panel.querySelector("svg, img");
    if (!target) return;
    const labelRect = label.getBoundingClientRect();
    const targetRect = target.getBoundingClientRect();
    if (!labelRect.width || !labelRect.height || !targetRect.width) return;
    const image = await loadImage(target);
    if (!image) return;

    const chart = makeCanvas(targetRect.width, targetRect.height);
    chart.getContext("2d").drawImage(image, 0, 0, chart.width, chart.height);

    // Compose the chart (offset by its position under the label) over the page
    // background, so transparent charts and margins sample correctly.
    const patch = makeCanvas(labelRect.width, labelRect.height);
    const context = patch.getContext("2d", { willReadFrequently: true });
    context.fillStyle = pageBackground();
    context.fillRect(0, 0, patch.width, patch.height);
    context.drawImage(
      chart,
      targetRect.left - labelRect.left,
      targetRect.top - labelRect.top,
      targetRect.width,
      targetRect.height,
    );

    const sample = makeCanvas(1, 1);
    const sampleContext = sample.getContext("2d", { willReadFrequently: true });
    sampleContext.drawImage(patch, 0, 0, 1, 1);
    const [red, green, blue] = sampleContext.getImageData(0, 0, 1, 1).data;
    const useBlackText = brightness(red, green, blue) > 0.5;
    tonePatch(context, patch.width, patch.height, useBlackText);
    label.style.color = useBlackText ? "#000" : "#fff";
    label.style.backgroundImage = `url("${patch.toDataURL()}")`;
    label.style.backgroundSize = "100% 100%";
    label.style.backgroundRepeat = "no-repeat";
  }

  function refresh() {
    for (const label of overlayLabels) {
      try {
        adapt(label).catch(() => { });
      } catch (error) {
        /* keep the CSS fallback */
      }
    }
  }

  // Charts upgrade asynchronously (Vega-Lite embeds after its CDN loads), so
  // re-sample whenever a panel's contents change.
  let pending;
  const observer = new MutationObserver(() => {
    clearTimeout(pending);
    pending = setTimeout(refresh, 150);
  });
  for (const panel of document.querySelectorAll(".snakedone-panel")) {
    observer.observe(panel, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", refresh);
  } else {
    refresh();
  }
  window.addEventListener("load", refresh);
  let resizePending;
  window.addEventListener("resize", () => {
    clearTimeout(resizePending);
    resizePending = setTimeout(() => {
      overlayLabels = arrangeLabels();
      refresh();
    }, 150);
  });
  document.addEventListener("snakedone-rendered", refresh);
})();

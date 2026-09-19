import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE_NAMES = new Set([
  "MiniMaxH3ReferenceBundle",
  "MiniMaxH3ReferenceInputManager",
]);
const FILE_REFRESH_ROUTE = "/minimax_h3_reference_manager/files";

const GROUPS = [
  { count: "image_reference_count", prefix: "ref_image_", max: 9, fileKind: "image", previewKind: "image" },
  { count: "video_reference_count", prefix: "ref_video_", max: 3, fileKind: "video", previewKind: "video" },
  { count: "video_audio_reference_count", prefix: "ref_video_audio_", max: 3, audioOnly: true, paired: true, previewKind: "audio" },
  { count: "audio_reference_count", prefix: "ref_audio_", max: 3, fileKind: "audio", audioOnly: true, previewKind: "audio" },
];

function countValue(node, name, max) {
  const widget = (node.widgets || []).find((candidate) => candidate.name === name);
  const value = Number(widget?.value ?? 0);
  return Math.max(0, Math.min(max, Number.isFinite(value) ? Math.trunc(value) : 0));
}

function valueFor(node, name) {
  return (node.widgets || []).find((candidate) => candidate.name === name)?.value ?? "";
}

function audioReferencesDisabled(node) {
  const value = valueFor(node, "generate_audio_without_reference");
  return value === true || value === "true" || value === 1 || value === "1";
}

function pairedAudioByVideo(node) {
  if (audioReferencesDisabled(node)) return { entries: [], warnings: [] };
  const videoCount = countValue(node, "video_reference_count", 3);
  const selectionCount = Math.min(
    countValue(node, "video_audio_reference_count", 3),
    videoCount,
  );
  const selected = new Map();
  const warnings = [];
  for (let slot = 0; slot < selectionCount; slot += 1) {
    const source = String(valueFor(node, `ref_video_audio_${slot}`) || "");
    const match = source.match(/Video reference (\d+)/);
    const videoIndex = match ? Number(match[1]) - 1 : -1;
    if (videoIndex < 0 || videoIndex >= videoCount) {
      warnings.push(`Paired audio slot ${slot + 1}: select an enabled video reference`);
      continue;
    }
    if (selected.has(videoIndex)) {
      warnings.push(`Video ${videoIndex + 1} audio is selected more than once`);
      continue;
    }
    selected.set(videoIndex, { slot, videoIndex, source });
  }
  return {
    entries: [...selected.values()].sort((a, b) => a.videoIndex - b.videoIndex),
    warnings,
  };
}

function shortValue(value) {
  if (!value) return "—";
  const text = String(value);
  return text.split(/[\\/]/).pop() || text;
}

function fileWithoutAnnotation(value) {
  return String(value || "").replace(/\s+\[(input|output|temp)\]$/, "");
}

function previewUrl(value) {
  if (!value) return "";
  const text = String(value);
  const match = text.match(/^(.*) \[(input|output|temp)\]$/);
  const filename = match ? match[1] : text;
  const type = match ? match[2] : "input";
  return api.apiURL(`/view?filename=${encodeURIComponent(filename)}&type=${type}`);
}

function optionContains(options, value) {
  if (!value) return true;
  const text = String(value);
  const filename = fileWithoutAnnotation(text);
  return options.includes(text) || options.includes(filename) || options.includes(`${filename} [input]`);
}

function setWidgetHidden(widget, hidden, disable = true) {
  if (!widget) return;
  widget.hidden = hidden;
  if (disable) widget.disabled = hidden;
  widget.options = { ...(widget.options || {}), hidden };
}

function inactiveReferenceValues(node) {
  if (!node.properties) node.properties = {};
  if (!node.properties.h3_inactive_reference_values) {
    node.properties.h3_inactive_reference_values = {};
  }
  return node.properties.h3_inactive_reference_values;
}

function syncReferenceValue(node, spec, index, active) {
  const name = `${spec.prefix}${index}`;
  const widget = (node.widgets || []).find((candidate) => candidate.name === name);
  if (!widget) return;

  const saved = inactiveReferenceValues(node);
  if (active) {
    if (!widget.value && saved[name]) {
      widget.value = saved[name];
    }
    if (widget.value) delete saved[name];
    return;
  }

  if (widget.value) saved[name] = widget.value;
  widget.value = "";
}

function insertAfter(node, widget, anchorName) {
  const widgets = node.widgets || [];
  const widgetIndex = widgets.indexOf(widget);
  const anchorIndex = widgets.findIndex((candidate) => candidate.name === anchorName);
  if (widgetIndex < 0 || anchorIndex < 0) return;
  widgets.splice(widgetIndex, 1);
  const newAnchorIndex = widgets.findIndex((candidate) => candidate.name === anchorName);
  widgets.splice(newAnchorIndex + 1, 0, widget);
}

function createMediaElement(kind) {
  let media;
  if (kind === "image") {
    media = document.createElement("img");
    media.loading = "lazy";
    media.style.cssText = "width:100%; height:104px; object-fit:contain; background:#111; border-radius:3px;";
  } else if (kind === "video") {
    media = document.createElement("video");
    media.controls = true;
    media.preload = "metadata";
    media.style.cssText = "width:100%; height:116px; object-fit:contain; background:#111; border-radius:3px;";
  } else {
    media = document.createElement("audio");
    media.controls = true;
    media.preload = "metadata";
    media.style.cssText = "width:100%; height:32px;";
  }
  return media;
}

function ensurePreviewWidget(node, spec, index) {
  const name = `h3_reference_preview_${spec.prefix}${index}`;
  let preview = (node.widgets || []).find((candidate) => candidate.name === name);
  if (!preview && typeof node.addDOMWidget === "function" && typeof document !== "undefined") {
    const element = document.createElement("div");
    element.style.cssText = [
      "display:flex",
      "flex-direction:column",
      "gap:3px",
      "padding:3px 6px 5px",
      "box-sizing:border-box",
      "overflow:hidden",
      "background:rgba(0,0,0,.14)",
      "border-radius:3px",
    ].join(";");
    const caption = document.createElement("div");
    caption.style.cssText = "font-size:10px; color:#aaa; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;";
    const media = createMediaElement(spec.previewKind);
    element.appendChild(caption);
    element.appendChild(media);
    preview = node.addDOMWidget(name, "H3_REFERENCE_PREVIEW", element, {
      serialize: false,
      hideOnZoom: true,
      getValue() { return element.dataset.source || ""; },
      setValue(value) { element.dataset.source = value || ""; },
      getMinHeight: () => 0,
    });
    preview._h3PreviewElement = element;
    preview._h3PreviewCaption = caption;
    preview._h3PreviewMedia = media;
    preview._h3PreviewKind = spec.previewKind;
    preview._h3PreviewVisible = false;
    preview.computeSize = function (width) {
      if (!this._h3PreviewVisible) return [width, -4];
      const height = this._h3PreviewKind === "image" ? 124 : this._h3PreviewKind === "video" ? 136 : 54;
      return [width, height];
    };
  }
  if (preview) insertAfter(node, preview, `${spec.prefix}${index}`);
  return preview;
}

function previewSource(node, spec, index) {
  if (spec.paired) {
    const match = String(valueFor(node, `${spec.prefix}${index}`) || "").match(/Video reference (\d+)/);
    if (!match) return { value: "", label: `Audio from video ${index + 1}` };
    const videoIndex = Number(match[1]) - 1;
    return {
      value: valueFor(node, `ref_video_${videoIndex}`),
      label: `Audio from video ${videoIndex + 1}`,
    };
  }
  return {
    value: valueFor(node, `${spec.prefix}${index}`),
    label: `${spec.previewKind === "image" ? "Image" : spec.previewKind === "video" ? "Video" : "Audio"} ${index + 1}`,
  };
}

function updateSlotPreviews(node) {
  for (const spec of GROUPS) {
    const activeCount = countValue(node, spec.count, spec.max);
    for (let index = 0; index < spec.max; index += 1) {
      const preview = ensurePreviewWidget(node, spec, index);
      if (!preview) continue;
      const hidden = index >= activeCount || (spec.audioOnly && audioReferencesDisabled(node));
      const source = previewSource(node, spec, index);
      const visible = !hidden && Boolean(source.value);
      preview._h3PreviewVisible = visible;
      setWidgetHidden(preview, !visible, false);
      if (preview._h3PreviewCaption) {
        preview._h3PreviewCaption.textContent = visible
          ? `${source.label}: ${shortValue(source.value)}`
          : "";
      }
      if (preview._h3PreviewMedia) {
        const url = visible ? previewUrl(source.value) : "";
        if (preview._h3PreviewSourceUrl !== url) {
          preview._h3PreviewSourceUrl = url;
          preview._h3PreviewMedia.src = url;
          if (!url && typeof preview._h3PreviewMedia.load === "function") {
            preview._h3PreviewMedia.load();
          }
        }
      }
    }
  }
}

function ensureSummaryWidget(node) {
  let summary = (node.widgets || []).find(
    (candidate) => candidate.name === "h3_reference_summary",
  );
  if (!summary && typeof node.addDOMWidget === "function" && typeof document !== "undefined") {
    const element = document.createElement("div");
    element.style.cssText = [
      "padding:4px 6px",
      "border:1px solid rgba(255,255,255,.12)",
      "border-radius:3px",
      "background:rgba(0,0,0,.18)",
      "color:#c8c8c8",
      "font-size:11px",
      "line-height:1.35",
      "white-space:pre-wrap",
      "word-break:break-word",
      "box-sizing:border-box",
      "overflow:hidden",
    ].join(";");
    const details = document.createElement("div");
    element.appendChild(details);
    summary = node.addDOMWidget("h3_reference_summary", "H3_REFERENCE_SUMMARY", element, {
      serialize: false,
      getValue() { return details.textContent || ""; },
      setValue(value) { details.textContent = value || ""; },
      getMinHeight: () => 30,
      getHeight: () => Math.max(30, element.scrollHeight + 8),
    });
    summary._h3SummaryText = details;
    summary._h3SummaryElement = element;
  }
  if (!summary && typeof node.addWidget === "function") {
    summary = node.addWidget(
      "text",
      "h3_reference_summary",
      "",
      () => {},
      { multiline: true, serialize: false },
    );
  }
  if (summary) {
    summary.disabled = true;
    summary.hidden = false;
    summary.options = { ...(summary.options || {}), hidden: false, serialize: false, multiline: true };
  }
  return summary;
}

function updateSummary(node) {
  const summary = ensureSummaryWidget(node);
  if (!summary) return;

  const lines = ["Selected references:"];
  const imageCount = countValue(node, "image_reference_count", 9);
  const videoCount = countValue(node, "video_reference_count", 3);
  const noAudioReferences = audioReferencesDisabled(node);
  const audioCount = noAudioReferences ? 0 : countValue(node, "audio_reference_count", 3);

  for (let index = 0; index < imageCount; index += 1) {
    lines.push(`Image ${index + 1}: ${shortValue(valueFor(node, `ref_image_${index}`))}`);
  }
  for (let index = 0; index < videoCount; index += 1) {
    lines.push(`Video ${index + 1}: ${shortValue(valueFor(node, `ref_video_${index}`))}`);
  }
  if (noAudioReferences) {
    lines.push("Audio mode: generate new H3 audio (external audio references disabled)");
  } else {
    const paired = pairedAudioByVideo(node);
    let audioOrdinal = 0;
    for (const entry of paired.entries) {
      audioOrdinal += 1;
      const sourceFile = valueFor(node, `ref_video_${entry.videoIndex}`);
      lines.push(
        `Audio ${audioOrdinal} (paired before Video ${entry.videoIndex + 1}): ` +
        `${entry.source}${sourceFile ? ` (${shortValue(sourceFile)})` : " (not loaded)"}`,
      );
    }
    for (let index = 0; index < audioCount; index += 1) {
      audioOrdinal += 1;
      lines.push(`Audio ${audioOrdinal}: ${shortValue(valueFor(node, `ref_audio_${index}`))}`);
    }
    for (const warning of paired.warnings) lines.push(`Warning: ${warning}`);
  }
  if (node._h3ReferenceStatus) lines.push(`Status: ${node._h3ReferenceStatus}`);

  const text = lines.join("\n");
  summary.value = text;
  if (summary._h3SummaryText) summary._h3SummaryText.textContent = text;
  else if (summary._h3SummaryElement) summary._h3SummaryElement.textContent = text;
}

function syncReferenceWidgets(node) {
  const noAudioReferences = audioReferencesDisabled(node);
  for (const spec of GROUPS) {
    const countWidget = (node.widgets || []).find((candidate) => candidate.name === spec.count);
    if (countWidget && spec.audioOnly) {
      setWidgetHidden(countWidget, noAudioReferences);
    }
    let wanted = countValue(node, spec.count, spec.max);
    if (spec.paired) {
      wanted = Math.min(wanted, countValue(node, "video_reference_count", 3));
    }
    for (let index = 0; index < spec.max; index += 1) {
      const widget = (node.widgets || []).find(
        (candidate) => candidate.name === `${spec.prefix}${index}`,
      );
      if (!widget) continue;
      const hidden = index >= wanted || (spec.audioOnly && noAudioReferences);
      syncReferenceValue(node, spec, index, !hidden);
      setWidgetHidden(widget, hidden);
    }
  }

  // Remove sockets created by older versions of this node when unconnected.
  // New references are entered directly through upload widgets.
  for (let index = (node.inputs || []).length - 1; index >= 0; index -= 1) {
    const slot = node.inputs[index];
    if (!slot || slot.link) continue;
    if (GROUPS.some((spec) => slot.name?.startsWith(`${spec.prefix}`) ||
      slot.name?.startsWith(`${spec.prefix.replace(/_$/, "s.")}`))) {
      node.removeInput(index);
    }
  }

  updateSlotPreviews(node);
  updateSummary(node);
  node.setSize(node.computeSize());
  node.setDirtyCanvas(true, true);
}

function stripInactiveReferenceInputs(node, inputs) {
  if (!inputs) return;
  const noAudioReferences = audioReferencesDisabled(node);
  const videoCount = countValue(node, "video_reference_count", 3);

  for (const spec of GROUPS) {
    let activeCount = countValue(node, spec.count, spec.max);
    if (spec.paired) activeCount = Math.min(activeCount, videoCount);
    for (let index = 0; index < spec.max; index += 1) {
      if (index >= activeCount || (spec.audioOnly && noAudioReferences)) {
        delete inputs[`${spec.prefix}${index}`];
      }
    }
  }
}

function hookCountWidgets(node) {
  for (const spec of GROUPS) {
    const widget = (node.widgets || []).find((candidate) => candidate.name === spec.count);
    if (!widget || widget._h3ReferenceUploadHooked) continue;
    const callback = widget.callback;
    widget.callback = function (value) {
      if (callback) callback.call(this, value);
      syncReferenceWidgets(node);
    };
    widget._h3ReferenceUploadHooked = true;
  }
  const audioMode = (node.widgets || []).find(
    (candidate) => candidate.name === "generate_audio_without_reference",
  );
  if (audioMode && !audioMode._h3ReferenceUploadHooked) {
    const callback = audioMode.callback;
    audioMode.callback = function (value) {
      if (callback) callback.call(this, value);
      syncReferenceWidgets(node);
    };
    audioMode._h3ReferenceUploadHooked = true;
  }
}

function hookReferenceWidgets(node) {
  for (const spec of GROUPS) {
    for (let index = 0; index < spec.max; index += 1) {
      const widget = (node.widgets || []).find(
        (candidate) => candidate.name === `${spec.prefix}${index}`,
      );
      if (!widget || widget._h3ReferenceValueHooked) continue;
      const callback = widget.callback;
      widget.callback = function (value) {
        if (callback) callback.call(this, value);
        if (spec.fileKind) scheduleFileRefresh(node);
        syncReferenceWidgets(node);
      };
      widget._h3ReferenceValueHooked = true;
    }
  }
}

function ensureRefreshWidget(node) {
  let refresh = (node.widgets || []).find(
    (candidate) => candidate._h3RefreshFiles || candidate.name === "Refresh files",
  );
  if (!refresh && typeof node.addWidget === "function") {
    refresh = node.addWidget("button", "Refresh files", null, () => refreshFileOptions(node));
    refresh.options = { ...(refresh.options || {}), serialize: false };
    refresh._h3RefreshFiles = true;
  }
  if (refresh) insertAfter(node, refresh, "generate_audio_without_reference");
  return refresh;
}

function updateFileWidgetOptions(node, spec, values) {
  for (let index = 0; index < spec.max; index += 1) {
    const widget = (node.widgets || []).find(
      (candidate) => candidate.name === `${spec.prefix}${index}`,
    );
    if (!widget) continue;
    widget.options = { ...(widget.options || {}), values: [...values] };
    if (widget.value && !optionContains(values, widget.value)) {
      widget.value = "";
    }
    const saved = inactiveReferenceValues(node);
    if (saved[widget.name] && !optionContains(values, saved[widget.name])) {
      delete saved[widget.name];
    }
  }
}

async function refreshFileOptions(node) {
  if (node._h3FileRefreshPromise) return node._h3FileRefreshPromise;
  node._h3FileRefreshPromise = (async () => {
    try {
      const response = await fetch(api.apiURL(FILE_REFRESH_ROUTE), { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const files = await response.json();
      for (const spec of GROUPS) {
        if (spec.fileKind) {
          updateFileWidgetOptions(
            node,
            spec,
            Array.isArray(files[spec.fileKind]) ? files[spec.fileKind] : [""],
          );
        }
      }
      node._h3ReferenceStatus = "file list refreshed";
      syncReferenceWidgets(node);
    } catch (error) {
      node._h3ReferenceStatus = `file refresh failed: ${error.message || error}`;
      updateSummary(node);
      node.setDirtyCanvas(true, true);
    } finally {
      node._h3FileRefreshPromise = null;
    }
  })();
  return node._h3FileRefreshPromise;
}

function scheduleFileRefresh(node) {
  if (node._h3FileRefreshTimer) clearTimeout(node._h3FileRefreshTimer);
  node._h3FileRefreshTimer = setTimeout(() => {
    node._h3FileRefreshTimer = null;
    refreshFileOptions(node);
  }, 180);
}

function prepareNode(node) {
  ensureRefreshWidget(node);
  for (const spec of GROUPS) {
    for (let index = 0; index < spec.max; index += 1) {
      ensurePreviewWidget(node, spec, index);
    }
  }
  ensureSummaryWidget(node);
  hookCountWidgets(node);
  hookReferenceWidgets(node);
  syncReferenceWidgets(node);
  refreshFileOptions(node);
}

app.registerExtension({
  name: "MiniMaxH3.ReferenceManagerSlots",
  async setup() {
    if (app._h3ReferenceManagerGraphToPromptHooked || typeof app.graphToPrompt !== "function") return;
    app._h3ReferenceManagerGraphToPromptHooked = true;
    const originalGraphToPrompt = app.graphToPrompt;
    app.graphToPrompt = async function (...args) {
      const result = await originalGraphToPrompt.apply(this, args);
      const output = result?.output;
      for (const node of app.graph?._nodes || []) {
        if (!NODE_NAMES.has(node.type)) continue;
        const promptNode = output?.[String(node.id)];
        stripInactiveReferenceInputs(node, promptNode?.inputs);
      }
      return result;
    };
  },
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (!NODE_NAMES.has(nodeData.name)) return;

    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const result = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
      prepareNode(this);
      return result;
    };

    const onConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
      const result = onConfigure ? onConfigure.apply(this, arguments) : undefined;
      prepareNode(this);
      return result;
    };
  },
});

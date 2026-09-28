import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE_NAMES = new Set([
  "MiniMaxH3ReferenceBundle",
  "MiniMaxH3ReferenceInputManager",
]);
const PROMPT_GUIDE_NODE = "MiniMaxH3PromptReferenceGuide";
const FILE_REFRESH_ROUTE = "/minimax_h3_reference_manager/files";

const GROUPS = [
  { count: "image_reference_count", prefix: "ref_image_", max: 9, fileKind: "image", previewKind: "image" },
  { count: "video_reference_count", prefix: "ref_video_", max: 3, fileKind: "video", previewKind: "video" },
  { count: "video_audio_reference_count", prefix: "ref_video_audio_", max: 3, audioOnly: true, paired: true, previewKind: "audio" },
  { count: "audio_reference_count", prefix: "ref_audio_", max: 3, fileKind: "audio", audioOnly: true, previewKind: "audio" },
  {
    count: "multiframe_reference_count",
    prefix: "guide_image_",
    timePrefix: "guide_time_seconds_",
    max: 5,
    start: 1,
    fileKind: "image",
    previewKind: "image",
    label: "Guide image",
    inputManagerOnly: true,
  },
];

function referenceGroups(node) {
  return GROUPS.filter(
    (spec) => !spec.inputManagerOnly || node.type === "MiniMaxH3ReferenceInputManager",
  );
}

function slotNumber(spec, index) {
  return index + (spec.start || 0);
}

function slotWidgetName(spec, index) {
  return `${spec.prefix}${slotNumber(spec, index)}`;
}

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
  const name = slotWidgetName(spec, index);
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
  const slot = slotNumber(spec, index);
  const name = `h3_reference_preview_${spec.prefix}${slot}`;
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
  if (preview) insertAfter(node, preview, slotWidgetName(spec, index));
  return preview;
}

function previewSource(node, spec, index) {
  const slot = slotNumber(spec, index);
  if (spec.paired) {
    const match = String(valueFor(node, slotWidgetName(spec, index)) || "").match(/Video reference (\d+)/);
    if (!match) return { value: "", label: `Audio from video ${index + 1}` };
    const videoIndex = Number(match[1]) - 1;
    return {
      value: valueFor(node, `ref_video_${videoIndex}`),
      label: `Audio from video ${videoIndex + 1}`,
    };
  }
  return {
    value: valueFor(node, slotWidgetName(spec, index)),
    label: `${spec.label || (spec.previewKind === "image" ? "Image" : spec.previewKind === "video" ? "Video" : "Audio")} ${slot}`,
  };
}

function updateSlotPreviews(node) {
  for (const spec of referenceGroups(node)) {
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

function promptReferenceText(node, includeStatus = false) {
  const lines = [
    "MiniMax H3 prompt reference map",
    "Pictures: image references first, then multiframe guides.",
  ];
  const imageCount = countValue(node, "image_reference_count", 9);
  const videoCount = countValue(node, "video_reference_count", 3);
  const noAudioReferences = audioReferencesDisabled(node);
  const audioCount = noAudioReferences ? 0 : countValue(node, "audio_reference_count", 3);
  const guideCount = countValue(node, "multiframe_reference_count", 5);

  let pictureOrdinal = 0;
  for (let index = 0; index < imageCount; index += 1) {
    pictureOrdinal += 1;
    lines.push(
      `<Picture ${pictureOrdinal}> = Image reference ${index + 1}: ` +
      shortValue(valueFor(node, `ref_image_${index}`)),
    );
  }
  for (let index = 1; index <= guideCount; index += 1) {
    pictureOrdinal += 1;
    const image = shortValue(valueFor(node, `guide_image_${index}`));
    const seconds = Number(valueFor(node, `guide_time_seconds_${index}`) || 0);
    lines.push(
      `<Picture ${pictureOrdinal}> = Multiframe guide ${index}: ${image} ` +
      `at ${seconds}s (frame ${Math.round(seconds * 24)})`,
    );
  }
  if (pictureOrdinal === 0) lines.push("Pictures: none");
  for (let index = 0; index < videoCount; index += 1) {
    lines.push(
      `<Video ${index + 1}> = Video reference ${index + 1}: ` +
      shortValue(valueFor(node, `ref_video_${index}`)),
    );
  }
  if (noAudioReferences) {
    lines.push("Audio: generated by H3; do not use <Audio N> tags.");
  } else {
    const paired = pairedAudioByVideo(node);
    let audioOrdinal = 0;
    for (const entry of paired.entries) {
      audioOrdinal += 1;
      const sourceFile = valueFor(node, `ref_video_${entry.videoIndex}`);
      lines.push(
        `<Audio ${audioOrdinal}> = Audio from Video reference ${entry.videoIndex + 1}: ` +
        `${sourceFile ? shortValue(sourceFile) : "—"}`,
      );
    }
    for (let index = 0; index < audioCount; index += 1) {
      audioOrdinal += 1;
      lines.push(
        `<Audio ${audioOrdinal}> = Standalone audio reference ${index + 1}: ` +
        shortValue(valueFor(node, `ref_audio_${index}`)),
      );
    }
    if (audioOrdinal === 0) lines.push("Audio references: none");
    for (const warning of paired.warnings) lines.push(`Warning: ${warning}`);
  }
  lines.push("Use every <Picture N> exactly as listed above in the prompt.");
  if (includeStatus && node._h3ReferenceStatus) {
    lines.push(`Status: ${node._h3ReferenceStatus}`);
  }
  return lines.join("\n");
}

function updateSummary(node) {
  const summary = ensureSummaryWidget(node);
  if (!summary) return;

  const text = promptReferenceText(node, true);
  summary.value = text;
  if (summary._h3SummaryText) summary._h3SummaryText.textContent = text;
  else if (summary._h3SummaryElement) summary._h3SummaryElement.textContent = text;
}

function graphLink(linkId) {
  const links = app.graph?.links;
  if (!links || linkId == null) return null;
  return typeof links.get === "function" ? links.get(linkId) : links[linkId];
}

function promptGuideSource(node) {
  const input = (node.inputs || []).find((candidate) => candidate.name === "reference_map");
  const link = graphLink(input?.link);
  const originId = link?.origin_id ?? link?.originId;
  return originId == null ? null : app.graph?.getNodeById?.(originId);
}

function ensurePromptGuideWidget(node) {
  let widget = (node.widgets || []).find(
    (candidate) => candidate.name === "h3_prompt_reference_guide",
  );
  if (!widget && typeof node.addDOMWidget === "function" && typeof document !== "undefined") {
    const element = document.createElement("pre");
    element.style.cssText = [
      "margin:0",
      "padding:8px",
      "min-height:240px",
      "box-sizing:border-box",
      "overflow:auto",
      "white-space:pre-wrap",
      "word-break:break-word",
      "font:11px/1.45 monospace",
      "color:#ddd",
      "background:rgba(0,0,0,.24)",
      "border:1px solid rgba(255,255,255,.12)",
      "border-radius:4px",
    ].join(";");
    widget = node.addDOMWidget(
      "h3_prompt_reference_guide",
      "H3_PROMPT_REFERENCE_GUIDE",
      element,
      {
        serialize: false,
        getValue() { return element.textContent || ""; },
        setValue(value) { element.textContent = value || ""; },
        getMinHeight: () => 260,
        getHeight: () => 300,
      },
    );
    widget._h3PromptGuideElement = element;
  }
  return widget;
}

function updatePromptGuideNode(node, executedText = "") {
  const widget = ensurePromptGuideWidget(node);
  if (!widget) return;
  const source = promptGuideSource(node);
  const text = source?.type === "MiniMaxH3ReferenceInputManager"
    ? promptReferenceText(source)
    : executedText || "Connect prompt_reference_map from the Reference Manager.";
  widget.value = text;
  if (widget._h3PromptGuideElement) widget._h3PromptGuideElement.textContent = text;
  node.setSize([Math.max(node.size?.[0] || 0, 540), Math.max(node.size?.[1] || 0, 340)]);
  node.setDirtyCanvas(true, true);
}

function updateLinkedPromptGuides(source) {
  for (const node of app.graph?._nodes || []) {
    if (node.type === PROMPT_GUIDE_NODE && promptGuideSource(node) === source) {
      updatePromptGuideNode(node);
    }
  }
}

function syncReferenceWidgets(node) {
  const noAudioReferences = audioReferencesDisabled(node);
  for (const spec of referenceGroups(node)) {
    const countWidget = (node.widgets || []).find((candidate) => candidate.name === spec.count);
    if (countWidget) {
      setWidgetHidden(countWidget, Boolean(spec.audioOnly && noAudioReferences));
    }
    let wanted = countValue(node, spec.count, spec.max);
    if (spec.paired) {
      wanted = Math.min(wanted, countValue(node, "video_reference_count", 3));
    }
    for (let index = 0; index < spec.max; index += 1) {
      const widget = (node.widgets || []).find(
        (candidate) => candidate.name === slotWidgetName(spec, index),
      );
      if (!widget) continue;
      const hidden = index >= wanted || (spec.audioOnly && noAudioReferences);
      syncReferenceValue(node, spec, index, !hidden);
      setWidgetHidden(widget, hidden);
      if (spec.timePrefix) {
        const timeWidget = (node.widgets || []).find(
          (candidate) => candidate.name === `${spec.timePrefix}${slotNumber(spec, index)}`,
        );
        setWidgetHidden(timeWidget, hidden);
      }
    }
  }

  // Remove sockets created by older versions of this node when unconnected.
  // New references are entered directly through upload widgets.
  for (let index = (node.inputs || []).length - 1; index >= 0; index -= 1) {
    const slot = node.inputs[index];
    if (!slot || slot.link) continue;
    if (referenceGroups(node).some((spec) => slot.name?.startsWith(`${spec.prefix}`) ||
      slot.name?.startsWith(`${spec.prefix.replace(/_$/, "s.")}`))) {
      node.removeInput(index);
    }
  }

  updateSlotPreviews(node);
  updateSummary(node);
  updateLinkedPromptGuides(node);
  node.setSize(node.computeSize());
  node.setDirtyCanvas(true, true);
}

function stripInactiveReferenceInputs(node, inputs) {
  if (!inputs) return;
  const noAudioReferences = audioReferencesDisabled(node);
  const videoCount = countValue(node, "video_reference_count", 3);

  for (const spec of referenceGroups(node)) {
    let activeCount = countValue(node, spec.count, spec.max);
    if (spec.paired) activeCount = Math.min(activeCount, videoCount);
    for (let index = 0; index < spec.max; index += 1) {
      if (index >= activeCount || (spec.audioOnly && noAudioReferences)) {
        delete inputs[slotWidgetName(spec, index)];
        if (spec.timePrefix) {
          delete inputs[`${spec.timePrefix}${slotNumber(spec, index)}`];
        }
      }
    }
  }
}

function hookCountWidgets(node) {
  for (const spec of referenceGroups(node)) {
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
  for (const spec of referenceGroups(node)) {
    for (let index = 0; index < spec.max; index += 1) {
      const widget = (node.widgets || []).find(
        (candidate) => candidate.name === slotWidgetName(spec, index),
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
      (candidate) => candidate.name === slotWidgetName(spec, index),
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
      for (const spec of referenceGroups(node)) {
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

function restoreNamedWidgetValues(node, values) {
  if (!values || typeof values !== "object") return;
  for (const widget of node.widgets || []) {
    if (Object.prototype.hasOwnProperty.call(values, widget.name)) {
      widget.value = values[widget.name];
    }
  }
}

function prepareNode(node, namedValues) {
  ensureRefreshWidget(node);
  for (const spec of referenceGroups(node)) {
    for (let index = 0; index < spec.max; index += 1) {
      ensurePreviewWidget(node, spec, index);
    }
  }
  ensureSummaryWidget(node);
  restoreNamedWidgetValues(node, namedValues);
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
    if (nodeData.name === PROMPT_GUIDE_NODE) {
      const onNodeCreated = nodeType.prototype.onNodeCreated;
      nodeType.prototype.onNodeCreated = function () {
        const result = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
        queueMicrotask(() => updatePromptGuideNode(this));
        return result;
      };

      const onConfigure = nodeType.prototype.onConfigure;
      nodeType.prototype.onConfigure = function () {
        const result = onConfigure ? onConfigure.apply(this, arguments) : undefined;
        queueMicrotask(() => updatePromptGuideNode(this));
        return result;
      };

      const onConnectionsChange = nodeType.prototype.onConnectionsChange;
      nodeType.prototype.onConnectionsChange = function () {
        const result = onConnectionsChange ? onConnectionsChange.apply(this, arguments) : undefined;
        queueMicrotask(() => updatePromptGuideNode(this));
        return result;
      };

      const onExecuted = nodeType.prototype.onExecuted;
      nodeType.prototype.onExecuted = function (message) {
        const result = onExecuted ? onExecuted.apply(this, arguments) : undefined;
        const text = Array.isArray(message?.text) ? message.text.join("\n") : message?.text;
        updatePromptGuideNode(this, text || "");
        return result;
      };
      return;
    }
    if (!NODE_NAMES.has(nodeData.name)) return;

    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const result = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
      queueMicrotask(() => prepareNode(this));
      return result;
    };

    const onConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
      const result = onConfigure ? onConfigure.apply(this, arguments) : undefined;
      prepareNode(this, arguments[0]?.widgets_values_named);
      return result;
    };
  },
});

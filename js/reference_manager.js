import { app } from "../../scripts/app.js";

const NODE_NAME = "MiniMaxH3ReferenceBundle";

const GROUPS = [
  { count: "image_reference_count", prefix: "ref_image_", max: 9 },
  { count: "video_reference_count", prefix: "ref_video_", max: 3 },
  { count: "video_audio_reference_count", prefix: "ref_video_audio_", max: 3 },
  { count: "audio_reference_count", prefix: "ref_audio_", max: 3 },
];

function countValue(node, name, max) {
  const widget = (node.widgets || []).find((candidate) => candidate.name === name);
  const value = Number(widget?.value ?? 0);
  return Math.max(0, Math.min(max, Number.isFinite(value) ? Math.trunc(value) : 0));
}

function valueFor(node, name) {
  return (node.widgets || []).find((candidate) => candidate.name === name)?.value ?? "";
}

function shortValue(value) {
  if (!value) return "—";
  const text = String(value);
  return text.split(/[\\/]/).pop() || text;
}

function previewUrl(value) {
  if (!value) return "";
  return `/view?filename=${encodeURIComponent(String(value))}&type=input`;
}

function addPreview(container, label, value, kind) {
  if (!value) return;
  const url = previewUrl(value);
  if (!url) return;

  const item = document.createElement("div");
  item.style.cssText = "display:flex; flex-direction:column; gap:3px; min-width:92px; max-width:180px;";
  const caption = document.createElement("div");
  caption.textContent = `${label}: ${shortValue(value)}`;
  caption.style.cssText = "font-size:10px; color:#aaa; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;";
  item.appendChild(caption);

  let media;
  if (kind === "image") {
    media = document.createElement("img");
    media.loading = "lazy";
    media.alt = shortValue(value);
    media.style.cssText = "width:100%; height:92px; object-fit:contain; background:#111; border-radius:3px;";
  } else if (kind === "video") {
    media = document.createElement("video");
    media.controls = true;
    media.preload = "metadata";
    media.style.cssText = "width:100%; height:104px; object-fit:contain; background:#111; border-radius:3px;";
  } else {
    media = document.createElement("audio");
    media.controls = true;
    media.preload = "metadata";
    media.style.cssText = "width:100%; height:30px;";
  }
  media.src = url;
  item.appendChild(media);
  container.appendChild(item);
}

function updateMediaPreview(node) {
  const summary = (node.widgets || []).find(
    (candidate) => candidate.name === "h3_reference_summary",
  );
  const container = summary?._h3SummaryMedia;
  if (!container || typeof document === "undefined") return;
  container.replaceChildren();
  container.style.cssText = [
    "display:grid",
    "grid-template-columns:repeat(auto-fill,minmax(105px,1fr))",
    "gap:6px",
    "margin-top:6px",
    "max-height:230px",
    "overflow:auto",
  ].join(";");

  const imageCount = countValue(node, "image_reference_count", 9);
  const videoCount = countValue(node, "video_reference_count", 3);
  const videoAudioCount = countValue(node, "video_audio_reference_count", 3);
  const audioCount = countValue(node, "audio_reference_count", 3);
  for (let index = 0; index < imageCount; index += 1) {
    addPreview(container, `Image ${index + 1}`, valueFor(node, `ref_image_${index}`), "image");
  }
  for (let index = 0; index < videoCount; index += 1) {
    addPreview(container, `Video ${index + 1}`, valueFor(node, `ref_video_${index}`), "video");
  }
  for (let index = 0; index < videoAudioCount; index += 1) {
    const source = valueFor(node, `ref_video_audio_${index}`);
    const sourceMatch = String(source).match(/Video reference (\d+)/);
    const sourceIndex = sourceMatch ? Number(sourceMatch[1]) - 1 : -1;
    const sourceFile = sourceIndex >= 0 ? valueFor(node, `ref_video_${sourceIndex}`) : "";
    addPreview(container, `Audio ${index + 1}`, sourceFile, "audio");
  }
  for (let index = 0; index < audioCount; index += 1) {
    addPreview(container, `Audio ${index + 1}`, valueFor(node, `ref_audio_${index}`), "audio");
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
    const media = document.createElement("div");
    element.appendChild(details);
    element.appendChild(media);
    summary = node.addDOMWidget("h3_reference_summary", "H3_REFERENCE_SUMMARY", element, {
      serialize: false,
      getValue() { return details.textContent || ""; },
      setValue(value) { details.textContent = value || ""; },
      getMinHeight: () => 30,
      getHeight: () => Math.max(30, element.scrollHeight + 8),
    });
    summary._h3SummaryText = details;
    summary._h3SummaryMedia = media;
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
    summary._h3ReferenceSummary = true;
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
  const videoAudioCount = countValue(node, "video_audio_reference_count", 3);
  const audioCount = countValue(node, "audio_reference_count", 3);

  for (let index = 0; index < imageCount; index += 1) {
    lines.push(`Image ${index + 1}: ${shortValue(valueFor(node, `ref_image_${index}`))}`);
  }
  for (let index = 0; index < videoCount; index += 1) {
    lines.push(`Video ${index + 1}: ${shortValue(valueFor(node, `ref_video_${index}`))}`);
  }
  for (let index = 0; index < videoAudioCount; index += 1) {
    const source = valueFor(node, `ref_video_audio_${index}`);
    const sourceMatch = String(source).match(/Video reference (\d+)/);
    const sourceIndex = sourceMatch ? Number(sourceMatch[1]) - 1 : -1;
    const sourceFile = sourceIndex >= 0 ? valueFor(node, `ref_video_${sourceIndex}`) : "";
    const sourceText = source ? `${source}${sourceFile ? ` (${shortValue(sourceFile)})` : " (not loaded)"}` : "—";
    lines.push(`Video audio ${index + 1}: ${sourceText}`);
  }
  for (let index = 0; index < audioCount; index += 1) {
    lines.push(`Audio ${index + 1}: ${shortValue(valueFor(node, `ref_audio_${index}`))}`);
  }

  const text = lines.join("\n");
  summary.value = text;
  if (summary._h3SummaryText) summary._h3SummaryText.textContent = text;
  else if (summary._h3SummaryElement) summary._h3SummaryElement.textContent = text;
  updateMediaPreview(node);
}

function syncReferenceWidgets(node) {
  for (const spec of GROUPS) {
    const wanted = countValue(node, spec.count, spec.max);
    for (let index = 0; index < spec.max; index += 1) {
      const widget = (node.widgets || []).find(
        (candidate) => candidate.name === `${spec.prefix}${index}`,
      );
      if (!widget) continue;
      // Upload combo remains a real widget; only the selected number of slots
      // is shown to the user.
      const hidden = index >= wanted;
      widget.hidden = hidden;
      widget.disabled = hidden;
      // Node 2.0 renders visibility from widget.options.hidden.
      if (widget.options) widget.options.hidden = hidden;
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

  updateSummary(node);
  node.setSize(node.computeSize());
  node.setDirtyCanvas(true, true);
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
        updateSummary(node);
        node.setSize(node.computeSize());
        node.setDirtyCanvas(true, true);
      };
      widget._h3ReferenceValueHooked = true;
    }
  }
}

function renameSourceVideoInput(node) {
  if (!node) return false;
  let changed = false;
  for (const input of node.inputs || []) {
    if (input?.name === "video" && input.label === "Reference video file") {
      input.label = "Source motion video";
      changed = true;
    }
  }
  // A subgraph can expose the same input through its definition/input node.
  for (const input of node.subgraph?.inputs || []) {
    if (input?.name === "video" && input.label === "Reference video file") {
      input.label = "Source motion video";
      changed = true;
    }
  }
  if (changed) node.setDirtyCanvas?.(true, true);
  return changed;
}

function renameSourceVideoInputs() {
  const graph = app.graph;
  for (const node of graph?._nodes || []) renameSourceVideoInput(node);
}

app.registerExtension({
  name: "MiniMaxH3.ReferenceManagerSlots",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE_NAME) return;

    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const result = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
      ensureSummaryWidget(this);
      hookCountWidgets(this);
      hookReferenceWidgets(this);
      syncReferenceWidgets(this);
      return result;
    };

    const onConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
      const result = onConfigure ? onConfigure.apply(this, arguments) : undefined;
      ensureSummaryWidget(this);
      hookCountWidgets(this);
      hookReferenceWidgets(this);
      syncReferenceWidgets(this);
      return result;
    };
  },
  async nodeCreated(node) {
    renameSourceVideoInput(node);
  },
  async afterConfigureGraph() {
    renameSourceVideoInputs();
  },
});

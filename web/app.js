"use strict";

(() => {
  const rules = globalThis.forensicsRules;
  const $ = (id) => document.getElementById(id);
  const state = { file: null, base64: null, objectURL: null, report: null, selected: null, busy: false, busyKind: null, regionalBusy: false, status: null, generation: 0, investigation: null, activeJob: null, cancelRequested: false, monitoring: false, agentSelected: null, ledgerKey: null, guide: { sourceKey: null, selectedId: null, follow: true, disconnected: false }, savedRuns: new Set() };
  const MAX_BYTES = 20 * 1024 * 1024;
  const SVG_NS = "http://www.w3.org/2000/svg";
  const form = $("experiment-form");
  const controls = Array.from(form.querySelectorAll("input, select, button"));
  const numeric = (value) => typeof value === "number" && Number.isFinite(value);
  const numberFormats = new Map();
  const numberText = (value, digits = 3) => {
    if (!numeric(value)) return "Chưa có dữ liệu";
    if (!numberFormats.has(digits)) numberFormats.set(digits, new Intl.NumberFormat("vi-VN", { minimumFractionDigits: digits, maximumFractionDigits: digits, useGrouping: false }));
    return numberFormats.get(digits).format(value);
  };
  const scoreText = (value) => numberText(value, 3);
  const bytesText = (bytes) => !numeric(bytes) ? "—" : bytes < 1024 ? `${bytes} B` : bytes < 1024 ** 2 ? `${numberText(bytes / 1024, 1)} KiB` : `${numberText(bytes / 1024 ** 2, 2)} MiB`;
  const dimensions = (item) => numeric(item?.width) && numeric(item?.height) ? `${item.width} × ${item.height}` : "— × —";
  const announce = (message) => { $("live-status").textContent = message; };
  const el = (tag, text, className) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (className) node.className = className; return node; };
  const svgEl = (tag, attributes, text) => { const node = document.createElementNS(SVG_NS, tag); Object.entries(attributes || {}).forEach(([key, value]) => node.setAttribute(key, value)); if (text !== undefined) node.textContent = text; return node; };
  const adaptiveMode = () => form.elements.workflow_mode.value === "adaptive";
  const toolNames = { baseline: "Ảnh gốc · B-Free", jpeg_q85_r1: "JPEG Q85 · 1 vòng", jpeg_q85_r3: "JPEG Q85 · 3 vòng", "resize_s0.9_r1": "Đổi cỡ 90% · 1 vòng", "combined_q95_s0.9_r3": "Đổi cỡ 90% → JPEG Q95 · 3 vòng", trufor: "TruFor kiểm tra từng vùng", finish: "Kết thúc phân tích" };
  const toolName = (name) => toolNames[name] || name || "Công cụ chưa xác định";
  const elapsedText = (value) => {
    if (!numeric(value)) return "—";
    const seconds = Math.round(value);
    return seconds < 60 ? `${seconds} giây` : `${Math.floor(seconds / 60)} phút ${seconds % 60} giây`;
  };
  const variantName = (item) => item.round === 0 || item.id === "original" ? "Ảnh gốc" : numeric(item.round) ? `Vòng ${item.round}` : translate(item.label || item.id);
  const statusNames = { running: "ĐANG CHẠY", complete: "HOÀN TẤT", error: "GẶP LỖI", cancelled: "ĐÃ DỪNG", available: "sẵn sàng", ready: "sẵn sàng", unavailable: "chưa khả dụng", configured: "đã cấu hình", partial: "kết quả chưa đủ", unknown: "chưa xác định" };
  // Localize the presentation only. Research payloads, prompts and exports remain immutable.
  const messages = new Map(Object.entries({
    "Local model installed; selected actions are constrained and budgeted.": "Đã cài mô hình trên máy. AI chỉ được chọn công cụ cho phép và phải tuân thủ giới hạn lượt gọi.",
    "Install the pinned local planner with scripts/install-planner.py.": "Cài mô hình chọn phép thử bằng scripts/install-planner.py.",
    "B-Free repository and weights are not configured.": "Chưa cấu hình mã nguồn và trọng số B-Free.",
    "Set BFREE_REPO and install the official B-Free checkpoint to enable AI scoring.": "Chưa cấu hình B-Free: cần đặt BFREE_REPO và cài trọng số chính thức để đo điểm AI.",
    "An analysis is already running. Please wait for it to finish.": "Một thí nghiệm khác đang chạy. Hãy chờ hoàn tất rồi thử lại.",
    "Request exceeds upload limit.": "Yêu cầu vượt quá giới hạn tải lên.",
    "Configured; model dependencies and weights are checked when scanning.": "Đã cấu hình. Thư viện và trọng số sẽ được kiểm tra khi chạy.",
    "Set TRUFOR_REPO and install its pretrained model to enable regional evidence.": "Cần cấu hình TRUFOR_REPO và cài trọng số TruFor để kiểm tra từng vùng.",
    "At least one inference failed; inspect per-image errors.": "Có lượt suy luận gặp lỗi. Hãy xem chi tiết lỗi của từng ảnh.",
    "Processing-sensitive evidence": "Kết quả nhạy với quá trình xử lý",
    "Elevated scores persist in selected tests": "Điểm cao duy trì trong các phép thử đã chọn",
    "Low scores in selected tests": "Điểm thấp trong các phép thử đã chọn",
    "Insufficient robustness evidence": "Chưa đủ dữ liệu đánh giá độ ổn định",
    "Detector scores are model evidence, not calibrated probabilities or proof of origin.": "Điểm số là phản hồi của mô hình, chưa phải xác suất đã được hiệu chuẩn hay bằng chứng xác định nguồn gốc.",
    "Perturbations of one image are correlated and are not independent corroboration.": "Các biến thể từ cùng một ảnh có tương quan, không phải bằng chứng xác nhận độc lập.",
    "The agent selects a subset of tests. Untested transformations and generators may behave differently.": "AI chỉ chọn một số phép thử. Các phép biến đổi và mô hình tạo ảnh chưa được kiểm tra có thể cho kết quả khác.",
    "Low AI scores do not establish authenticity. TruFor does not localize AI generation.": "Điểm AI thấp không đủ để khẳng định ảnh là thật. TruFor không định vị vùng do AI tạo.",
    "Planner action weights are relative selection preferences, not confidence estimates.": "Trọng số hành động thể hiện mức ưu tiên lựa chọn tương đối, không phải độ tin cậy của kết luận.",
    "Some tools failed; missing results were not replaced with zero scores.": "Một số phép thử gặp lỗi. Kết quả thiếu không được thay bằng điểm 0.",
    "Image measurements ready; detector evidence incomplete": "Đã đo ảnh, nhưng kết quả mô hình chưa đầy đủ",
    "Compression and resizing were measured. No authenticity conclusion is available until a configured detector successfully scores every image.": "Đã đo tác động của nén và đổi kích thước, nhưng mô hình chưa chấm điểm thành công mọi ảnh. Chưa đủ kết quả để diễn giải về nguồn gốc.",
    "Detector evidence changes under processing": "Kết quả mô hình thay đổi sau xử lý",
    "Elevated scores persist across these transformations": "Điểm cao duy trì qua các phép biến đổi",
    "Scores stay below the configured threshold": "Điểm số không vượt ngưỡng đã đặt",
    "All tested versions remain above the configured threshold. This supports consistency of the detector response, but does not prove that the image is AI-generated.": "Tất cả phiên bản đã thử đều trên ngưỡng đã đặt. Phản hồi mô hình nhất quán trong các phép thử này, nhưng chưa chứng minh ảnh do AI tạo.",
    "This detector did not raise a persistent AI-generation signal in the tested versions. Low scores do not establish that an image is authentic.": "Mô hình không ghi nhận tín hiệu ảnh AI duy trì trong các phiên bản đã thử. Điểm thấp không đủ để khẳng định ảnh là thật.",
    "A detector score is model evidence, not a calibrated probability of authenticity.": "Điểm số là phản hồi của mô hình, chưa phải xác suất đã được hiệu chuẩn về tính xác thực của ảnh.",
    "Derivatives of one image are correlated; persistence is not independent corroboration.": "Các biến thể của cùng một ảnh có tương quan; sự ổn định không phải bằng chứng xác nhận độc lập.",
    "JPEG quality is an encoder setting, not a measurement of prior compression.": "Chất lượng JPEG là thiết lập của bộ mã hóa, không đo được mức nén ảnh đã trải qua.",
    "Single-pass controls start from the original at each round's target size; JPEG-only controls may be identical.": "Đối chứng một lượt bắt đầu từ ảnh gốc, đổi trực tiếp về kích thước đích của mỗi vòng. Các đối chứng chỉ nén JPEG có thể trùng nhau.",
    "At least one image has a side below 224 px. Small images and padding can alter detector behavior.": "Có ảnh với một cạnh dưới 224 điểm ảnh. Ảnh nhỏ và phần đệm có thể làm thay đổi phản hồi mô hình.",
    "One or more model runs failed. Missing values are not zero scores.": "Có lượt chạy mô hình gặp lỗi. Giá trị thiếu không phải điểm 0.",
    "EXIF orientation was applied before processing.": "Đã áp dụng hướng xoay EXIF trước khi xử lý.",
    "Transparency was composited on white before analysis.": "Vùng trong suốt đã được ghép lên nền trắng trước khi phân tích.",
    "Optional TruFor scan evaluates manipulation anomalies, not AI origin.": "TruFor là bước bổ sung đánh giá dấu hiệu chỉnh sửa bất thường, không xác định nguồn gốc AI.",
    "TruFor generated a manipulation anomaly map and localization reliability map. Output dimensions and numeric ranges were checked.": "TruFor đã tạo bản đồ bất thường do chỉnh sửa và bản đồ độ tin cậy định vị. Kích thước và miền giá trị đầu ra đã được kiểm tra.",
    "TruFor returned a validated manipulation anomaly map and localization reliability map.": "TruFor đã trả về bản đồ bất thường do chỉnh sửa và bản đồ độ tin cậy định vị. Đầu ra đã qua bước kiểm tra hợp lệ.",
    "TruFor localizes manipulation anomalies; it does not identify AI-generated pixels.": "TruFor định vị dấu hiệu chỉnh sửa bất thường, không xác định điểm ảnh do AI tạo.",
    "The displayed score is not an independently calibrated probability.": "Điểm hiển thị chưa phải xác suất được hiệu chuẩn độc lập.",
    "Fixed scale: blue 0 → cyan → yellow → red 1; higher values indicate stronger manipulation anomalies.": "Thang cố định: xanh dương 0 → xanh lơ → vàng → đỏ 1. Giá trị cao hơn thể hiện dấu hiệu chỉnh sửa bất thường mạnh hơn.",
    "Black 0 → white 1; lighter pixels indicate greater estimated localization reliability.": "Đen 0 → trắng 1. Vùng sáng hơn có độ tin cậy định vị ước tính cao hơn.",
    "No valid regional evidence was produced.": "Chưa tạo được kết quả kiểm tra vùng hợp lệ.",
    "Scoring the original image": "Đang đo điểm ảnh gốc",
    "Preparing image": "Đang chuẩn bị ảnh",
    "Planner choosing the next step from observed evidence": "AI đang chọn bước tiếp theo từ kết quả đã có",
    "Investigation complete": "Phân tích hoàn tất",
    "Investigation failed": "Phiên phân tích gặp lỗi",
    "Server stopped before this investigation completed.": "Máy chủ đã dừng trước khi phiên phân tích hoàn tất.",
    "Investigation not found.": "Không tìm thấy phiên phân tích.",
    "Active investigation not found.": "Không tìm thấy phiên phân tích đang chạy.",
    "Analysis not found.": "Không tìm thấy thí nghiệm.",
    "The recorded example is not installed.": "Chưa có ví dụ đã lưu trên máy.",
    "Invalid recorded example.": "Ví dụ đã lưu không hợp lệ.",
    "Another model request is already running. Try again when it finishes.": "Một yêu cầu mô hình khác đang chạy. Hãy thử lại sau khi hoàn tất.",
    "Choose a nonempty image smaller than 20 MiB.": "Hãy chọn ảnh có dữ liệu và dung lượng dưới 20 MiB.",
    "Use a JPEG, PNG, WebP, TIFF, or BMP image.": "Hãy dùng ảnh JPEG, PNG, WebP, TIFF hoặc BMP.",
    "Use a single-frame image.": "Hãy dùng ảnh chỉ có một khung hình.",
    "The shortest image side must be at least 16 pixels.": "Cạnh ngắn nhất của ảnh phải từ 16 điểm ảnh trở lên.",
    "Image exceeds the 20 megapixel analysis limit.": "Ảnh vượt giới hạn phân tích 20 triệu điểm ảnh.",
    "The file could not be decoded as a supported image.": "Không đọc được tệp dưới dạng ảnh được hỗ trợ.",
    "Not found": "Không tìm thấy tài nguyên.",
  }));
  function translate(value) {
    if (typeof value !== "string" || !value) return "";
    if (messages.has(value)) return messages.get(value);
    let match;
    if ((match = value.match(/^B-Free scored the normalized original ([\d.]+) at a fixed threshold of 0\.5 \(strictly greater is elevated\)\.$/))) return `B-Free chấm ảnh gốc đã chuẩn hóa ${numberText(Number(match[1]), 4)}. Ngưỡng cố định là 0,5; chỉ điểm lớn hơn ngưỡng mới thuộc nhóm cao.`;
    if ((match = value.match(/^Across the original and (\d+) selected perturbation tests, scores ranged from ([\d.]+) to ([\d.]+); (\d+) perturbations changed the threshold decision relative to the original\.$/))) return `Tính cả ảnh gốc và ${match[1]} phép thử đã chọn, điểm số nằm trong khoảng ${numberText(Number(match[2]), 4)} đến ${numberText(Number(match[3]), 4)}. Có ${match[4]} biến thể đổi kết quả phân loại theo ngưỡng so với ảnh gốc.`;
    if ((match = value.match(/^TruFor returned a local-manipulation score of ([\d.]+)\. Its maps address manipulation anomalies, not AI origin\.$/))) return `TruFor trả về điểm chỉnh sửa cục bộ ${numberText(Number(match[1]), 4)}. Bản đồ phản ánh dấu hiệu chỉnh sửa bất thường, không xác định nguồn gốc AI.`;
    if ((match = value.match(/^(\d+) of (\d+) derivatives cross the configured ([\d.]+) threshold relative to the original\. Treat this image as inconclusive and inspect its provenance\.$/))) return `${match[1]} trong ${match[2]} biến thể đổi phía so với ảnh gốc tại ngưỡng ${numberText(Number(match[3]), 2)}. Chưa thể kết luận nguồn gốc ảnh; cần kiểm tra thêm thông tin xuất xứ.`;
    if ((match = value.match(/^Source mode (.+) converted to RGB; no ICC profile conversion applied\.$/))) return `Ảnh nguồn ở chế độ ${match[1]} đã được chuyển sang RGB; không áp dụng chuyển đổi hồ sơ màu ICC.`;
    if ((match = value.match(/^B-Free could not load: (.+)$/))) return `Không tải được B-Free. Chi tiết kỹ thuật: ${match[1]}`;
    if ((match = value.match(/^Running (\S+)$/))) return `Đang chạy: ${toolName(match[1])}`;
    if ((match = value.match(/^Investigation stopped: (.+)$/))) return `Phiên đã dừng: ${({ cancelled: "theo yêu cầu", "planner failed": "mô hình chọn phép thử gặp lỗi", "original detector failed": "phép đo ảnh gốc gặp lỗi", "budget exhausted": "đã hết lượt gọi" })[match[1]] || match[1]}`;
    // Preserve unrecognized diagnostics verbatim; never infer a translated scientific claim.
    return value;
  }
  const errorText = (value) => {
    const original = String(value || "Không thể hoàn tất yêu cầu.");
    const translated = translate(original);
    if (translated !== original || /[À-ỹ]/u.test(original)) return translated;
    return `Không thể hoàn tất thao tác. Chi tiết kỹ thuật: ${original}`;
  };

  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const activeAnimations = new Set();
  const seenEvidence = new Set();
  const seenDecisions = new Set();
  let animatedRun = null;
  function reveal(node, delay = 0) {
    if (!node || reducedMotion.matches || typeof node.animate !== "function") return;
    const animation = node.animate([{ opacity: 0, transform: "translateY(4px)" }, { opacity: 1, transform: "translateY(0)" }], { duration: 240, delay, easing: "cubic-bezier(.2,.7,.2,1)", fill: "backwards" });
    activeAnimations.add(animation);
    animation.finished.catch(() => {}).finally(() => activeAnimations.delete(animation));
  }
  reducedMotion.addEventListener("change", () => { if (reducedMotion.matches) activeAnimations.forEach((animation) => animation.cancel()); });
  const scrollTo = (node, block = "nearest") => node.scrollIntoView({ behavior: reducedMotion.matches ? "instant" : "smooth", block });
  function setPreview(image, url) {
    if (image.src === url) return;
    image.onload = () => reveal(image);
    image.src = url;
  }

  function setInvestigationURL(runID) {
    const url = new URL(location.href);
    url.searchParams.delete("example");
    if (runID) url.searchParams.set("investigation", runID); else { url.searchParams.delete("investigation"); if (url.hash.startsWith("#agent-evidence-")) url.hash = ""; }
    history.replaceState(null, "", url);
  }

  function showError(message) {
    $("alert").textContent = message ? errorText(message) : "";
    $("alert").hidden = !message;
    if (message) scrollTo($("alert"));
  }

  function sameOriginURL(value) {
    if (typeof value !== "string" || !value) return null;
    try {
      const url = new URL(value, location.origin);
      return url.origin === location.origin && ["http:", "https:"].includes(url.protocol) ? url.href : null;
    } catch { return null; }
  }

  async function request(path, data) {
    const options = data ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) } : {};
    const response = await fetch(path, options);
    let payload;
    try { payload = await response.json(); } catch { throw new Error(`Không đọc được phản hồi từ máy chủ (${response.status}).`); }
    if (!response.ok) {
      const detail = typeof payload.error === "string" ? payload.error : typeof payload.message === "string" ? payload.message : `Yêu cầu thất bại (${response.status}).`;
      throw new Error(errorText(detail));
    }
    return payload;
  }

  function renderGuide() {
    const adaptive = adaptiveMode();
    const report = adaptive ? state.investigation : state.report;
    const model = ForensicsGuide.build({ report, adaptive, hasImage: !!state.base64, busy: state.busy, busyKind: state.busyKind, saved: !!report && state.savedRuns.has(report.run_id), availability: state.status, disconnected: state.guide.disconnected, cancelRequested: state.cancelRequested });
    const navigation = state.guide;
    if (navigation.sourceKey !== model.sourceKey) {
      $("source-controls").open = !report;
      navigation.sourceKey = model.sourceKey;
      navigation.selectedId = null;
      navigation.follow = true;
    }
    document.body.classList.toggle("has-guide-result", !!report);
    const following = model.steps.find((item) => item.id === model.initialStepId) || model.steps[0];
    if (navigation.follow || !model.steps.some((item) => item.id === navigation.selectedId)) navigation.selectedId = following.id;
    const index = model.steps.findIndex((item) => item.id === navigation.selectedId);
    const current = model.steps[index];
    const signature = model.steps.map((item) => `${item.id}:${item.kind}:${item.title}`).join("|");
    if ($("guide-stages").dataset.signature !== signature) {
      $("guide-stages").dataset.signature = signature;
      $("guide-stages").replaceChildren(...model.steps.map((item, i) => {
        const li = el("li");
        const button = el("button", `${i + 1}. ${item.label}`);
        button.setAttribute("aria-label", button.textContent);
        button.type = "button"; button.dataset.guideStep = item.id; button.dataset.stepNumber = String(i + 1); button.title = item.title;
        button.addEventListener("click", () => chooseGuideStep(item.id)); li.append(button); return li;
      }));
    }
    document.querySelectorAll("[data-guide-step]").forEach((button) => {
      button.setAttribute("aria-current", button.dataset.guideStep === current.id ? "step" : "false");
    });
    const setText = (id, text) => { if ($(id).textContent !== text) $(id).textContent = text; };
    setText("guide-origin", model.origin);
    setText("guide-footnote", adaptive ? "AI chọn phép thử từ các kết quả đo. Lời dẫn này được tạo từ chính các phép đo đó." : "Bạn chọn thiết lập phép thử. Lời dẫn được tạo từ các kết quả đo thực tế của phiên này.");
    setText("guide-step-label", `BƯỚC ${index + 1} / ${model.steps.length}${navigation.follow && report?.status === "running" ? " · ĐANG THEO DÕI" : ""}`);
    setText("guide-step-title", current.title);
    setText("guide-step-text", current.text);
    $("guide-narration").hidden = current.kind === "finding";
    $("guide-step-text").hidden = !!current.lesson && current.kind !== "intro";
    $("guide-flow").hidden = !current.flow;
    $("guide-flow").replaceChildren(...(current.flow || []).map((text) => el("li", text)));
    $("guide-model").hidden = !current.model;
    setText("guide-model-name", current.model?.name || "");
    setText("guide-model-text", current.model?.text || "");
    $("guide-lesson").hidden = !current.lesson;
    for (const key of ["purpose", "action", "meaning"]) setText(`guide-${key}`, current.lesson?.[key] || "");
    const transformation = current.transformation;
    $("guide-transformation").hidden = !transformation || !transformation.from || !transformation.to;
    setText("guide-transform-from", transformation?.from || "");
    setText("guide-transform-name", transformation?.name || "");
    setText("guide-transform-to", transformation?.to || "");
    setText("guide-transform-history", transformation?.history || "");
    $("guide-map-legends").hidden = !current.legends?.length;
    $("guide-map-legends").replaceChildren(...(current.legends || []).map((text) => el("li", translate(text))));
    $("viewer").dataset.lessonKind = current.kind;
    $("guide-finding").hidden = current.kind !== "finding";
    if (current.kind === "finding") { setText("guide-finding-title", current.title); setText("guide-finding-text", current.text); }
    const score = ["baseline", "perturbation", "finding"].includes(current.kind) && numeric(current.score);
    $("guide-score-comparison").hidden = !score;
    if (score) {
      setText("guide-baseline-label", "Điểm B-Free ảnh gốc");
      const measuredScore = (value) => Math.abs(value - model.threshold) < .001 ? numberText(value, 6) : scoreText(value);
      const group = (value) => value > model.threshold ? "Trên mốc" : "Bằng hoặc dưới mốc";
      setText("guide-baseline-score", numeric(current.baselineScore) ? measuredScore(current.baselineScore) : "Chưa đo");
      setText("guide-baseline-decision", numeric(current.baselineScore) ? group(current.baselineScore) : "");
      setText("guide-current-label", current.kind === "baseline" ? "Vị trí so với ngưỡng" : "Điểm B-Free ảnh đang xem");
      setText("guide-current-score", current.kind === "baseline" ? current.decision : measuredScore(current.score));
      setText("guide-current-decision", current.kind === "baseline" ? "" : current.decision || "");
      setText("guide-score-note", `Mốc chia nhóm ${numberText(model.threshold, 3)}: chỉ điểm lớn hơn mốc mới thuộc nhóm có tín hiệu AI.`);
    }
    $("guide-scale").hidden = !score || current.kind !== "baseline";
    $("viewer-evidence").hidden = !score && $("guide-transformation").hidden;
    if (score) {
      $("guide-score-marker").style.left = `${current.score * 100}%`;
      $("guide-threshold-marker").style.left = `${model.threshold * 100}%`;
      $("guide-scale-track").setAttribute("aria-valuenow", String(current.score));
      $("guide-scale-track").setAttribute("aria-valuetext", `${current.score}; ${current.decision || ""}; mốc ${model.threshold}`);
      setText("guide-scale-note", `Vạch mảnh là mốc ${numberText(model.threshold, 3)}; chấm tròn là điểm đang xem. Đây là tín hiệu mô hình, không phải % ảnh do AI tạo.`);
    }
    $("narrator-regional").hidden = current.kind !== "regional" || !current.maps;
    for (const [id, value] of [["guide-region-overlay", current.maps?.overlay], ["guide-region-reliability", current.maps?.reliability]]) {
      const url = sameOriginURL(value); $(id).closest("figure").hidden = !url;
      if (url) setPreview($(id), url); else $(id).removeAttribute("src");
    }
    const preview = current.previewId;
    if (preview && (adaptive ? state.agentSelected : state.selected) !== preview) {
      if (adaptive) selectAgentObservation(preview); else selectVariant(preview);
    }
    document.querySelectorAll(".guide-highlight").forEach((node) => node.classList.remove("guide-highlight"));
    if (current.kind !== "intro" && current.kind !== "status") $(current.targetId)?.classList.add("guide-highlight");
    $("guide-actions").hidden = model.steps.length < 2;
    $("guide-prev").disabled = index <= 0;
    $("guide-next").disabled = index >= model.steps.length - 1;
    $("guide-next").textContent = current.nextLabel + (index < model.steps.length - 1 ? " →" : "");
    $("guide-replay").hidden = !report || !model.steps.some((item) => ["baseline", "perturbation", "regional"].includes(item.kind));
    $("guide-follow").hidden = navigation.follow || report?.status !== "running";
    $("guide-panel").dataset.stage = current.kind;
    $("agent-overview").hidden = !adaptive || !state.investigation;
    $("research-details").hidden = !report;
  }

  function chooseGuideStep(id) {
    state.guide.selectedId = id;
    state.guide.follow = false;
    renderGuide();
  }

  function stepGuide(delta) {
    const buttons = Array.from(document.querySelectorAll("[data-guide-step]"));
    const index = buttons.findIndex((button) => button.dataset.guideStep === state.guide.selectedId);
    const next = buttons[index + delta];
    if (next) chooseGuideStep(next.dataset.guideStep);
  }

  function reviewPreview(id) {
    if (adaptiveMode()) selectAgentObservation(id); else selectVariant(id);
    chooseGuideStep(id);
  }

  function readConfig() {
    return {
      quality: Number($("quality").value), scale: Number($("scale").value) / 100,
      rounds: Number($("rounds").value), mode: form.elements.mode.value,
      order: $("order").value, operation: $("operation").value,
      threshold: Number($("threshold").value) / 100,
    };
  }

  function updateConfig() {
    const config = readConfig();
    $("quality-value").textContent = String(config.quality);
    $("scale-value").textContent = `${Math.round(config.scale * 100)}%`;
    $("threshold-value").textContent = numberText(config.threshold, 2);
    $("threshold-summary").textContent = numberText(config.threshold, 2);
    const jpegOff = config.operation === "resize";
    const scaleOff = config.operation === "jpeg";
    $("quality-field").classList.toggle("disabled-field", jpegOff);
    $("scale-field").classList.toggle("disabled-field", scaleOff);
    $("quality").disabled = state.busy || jpegOff;
    $("scale").disabled = state.busy || scaleOff;
    $("order").disabled = state.busy || config.operation !== "combined";
    $("order-field").classList.toggle("disabled-field", config.operation !== "combined");
    $("mode-help").textContent = config.mode === "cumulative"
      ? "Mỗi vòng xử lý ảnh từ kết quả vòng trước, giữ lại tác động tích lũy."
      : "Mỗi vòng bắt đầu từ ảnh gốc, đổi trực tiếp về kích thước đích rồi nén JPEG một lần. Đối chứng chỉ nén JPEG có thể trùng nhau.";
    const roundLabels = Array.from({ length: config.rounds }, (_, i) => `V${i + 1}`);
    $("sequence").textContent = config.mode === "cumulative" ? `Gốc → ${roundLabels.join(" → ")}` : `Gốc → { ${roundLabels.join(", ")} }`;
    const parts = [`${config.rounds} vòng`];
    if (!jpegOff) parts.push(`Q${config.quality}`);
    if (!scaleOff) parts.push(`${Math.round(config.scale * 100)}% mỗi vòng`);
    $("sequence-detail").textContent = parts.join(" · ");
    if (!state.busy) {
      $("run-label").textContent = "Phân tích ảnh";
      $("run-button").disabled = !state.base64 || (adaptiveMode() && (!state.status?.planner?.available || !state.status?.bfree?.available));
      $("run-help").textContent = !state.file ? "Chọn ảnh để bắt đầu phân tích." : adaptiveMode() ? !state.status?.planner?.available ? "Cần cài mô hình chọn phép thử để phân tích thích ứng." : !state.status?.bfree?.available ? "Cần cấu hình B-Free để bắt đầu phân tích." : "AI có thể dừng trước khi dùng hết số lượt cho phép." : state.report ? "Thiết lập này áp dụng cho lần chạy tiếp theo." : "Ảnh gốc và các biến thể sẽ được đo trong cùng phiên.";
    }
    if (!state.investigation) $("agent-tool-count").textContent = `0 / ${$("agent-budget").value}`;
    $("allow-regional").disabled = state.busy || state.status?.trufor?.available !== true;
  }

  function updateApproach() {
    const adaptive = adaptiveMode();
    $("fixed-settings").hidden = adaptive;
    $("agent-settings").hidden = !adaptive;
    $("agent-overview").hidden = !adaptive;
    $("agent-record").hidden = !adaptive;
    $("fixed-evidence-panel").hidden = adaptive;
    $("fixed-regional-panel").hidden = adaptive;
    $("trajectory-panel").hidden = adaptive;
    $("measurements-panel").hidden = adaptive || !state.report;
    $("preview-title").textContent = "Ảnh đang được giải thích";
    $("variant-select").setAttribute("aria-label", adaptive ? "Chọn phép thử đã có kết quả" : "Chọn vòng xử lý");
    clearResults(true);
    viewer.reset();
    if (adaptive && state.investigation) renderInvestigation(state.investigation);
    else if (!adaptive && state.report) renderReport(state.report);
    updateConfig();
    state.guide.sourceKey = null;
    renderGuide();
    reveal(adaptive ? $("agent-settings") : $("fixed-settings"));
  }

  function updateRegionalButton() {
    const available = state.status?.trufor?.available === true;
    $("regional-button").disabled = !available || !state.report || state.busy || state.regionalBusy;
    if (!state.regionalBusy) {
      $("regional-button").textContent = state.report?.regional?.status === "complete" ? "Kiểm tra từng vùng lại ↗" : "Kiểm tra từng vùng ↗";
    }
  }

  function setBusy(busy, kind = "experiment") {
    state.busy = busy;
    state.busyKind = busy ? kind : null;
    document.body.classList.toggle("is-busy", busy);
    document.body.dataset.busyKind = busy ? kind : "";
    controls.forEach((control) => { control.disabled = busy; });
    $("run-button").disabled = busy || !state.base64;
    $("run-label").textContent = busy ? { experiment: "Đang chạy thí nghiệm…", investigation: "Đang phân tích…", regional: "Đang kiểm tra ảnh gốc…", example: "Đang mở ví dụ…", saved: "Đang mở phiên đã lưu…" }[kind] : "Chạy thí nghiệm";
    $("run-arrow").hidden = busy;
    $("run-spinner").hidden = !busy;
    $("run-help").textContent = busy ? kind === "investigation" ? "Mô hình đang xử lý trên máy. Theo dõi kết quả đo và các phép thử AI chọn trong nhật ký phân tích." : "Đang thu thập kết quả từ mô hình trên máy. Quá trình có thể mất vài phút." : "";
    form.setAttribute("aria-busy", String(busy));
    updateConfig();
    updateRegionalButton();
    renderGuide();
  }

  function setModelState(key, info) {
    const available = info?.available === true;
    const badge = $(`${key}-badge`);
    badge.textContent = available ? "SẴN SÀNG" : "CHƯA CẤU HÌNH";
    badge.classList.toggle("ready", available);
    badge.classList.toggle("offline", !available);
    if (key === "bfree") {
      $("bfree-status").textContent = available ? "Sẵn sàng đo phản hồi của mô hình phát hiện ảnh AI." : `${translate(info?.reason) || "Chưa cấu hình trọng số mô hình."} Vẫn có thể biến đổi ảnh và đo sai khác điểm ảnh.`;
    } else {
      $("regional-status").textContent = available ? "Chạy thí nghiệm trước, sau đó kiểm tra từng vùng trên ảnh gốc." : translate(info?.reason) || "Chưa cấu hình TruFor. Cần trọng số mô hình để tạo bản đồ vùng.";
    }
  }

  async function loadStatus() {
    try {
      state.status = await request("/api/status");
      setModelState("bfree", state.status.bfree);
      setModelState("trufor", state.status.trufor);
      const planner = state.status.planner;
      $("planner-badge").textContent = planner?.available ? "ĐÃ CÀI" : "CHƯA CÀI";
      $("planner-badge").classList.toggle("ready", planner?.available === true);
      $("planner-badge").classList.toggle("offline", planner?.available !== true);
      $("planner-status").textContent = translate(planner?.reason) || "Chưa cấu hình mô hình chọn phép thử.";
      updateRegionalButton();
      updateConfig();
      renderGuide();
    } catch {
      showError("Không kết nối được với máy chủ trên máy này. Khởi động máy chủ rồi tải lại trang để kiểm tra mô hình.");
      $("bfree-status").textContent = "Không kết nối được với máy chủ trên máy này. Hãy khởi động máy chủ rồi tải lại trang.";
      $("regional-status").textContent = "Chưa thể kiểm tra mô hình khi chưa kết nối được với máy chủ.";
      ["bfree-badge", "trufor-badge"].forEach((id) => { $(id).textContent = "MẤT KẾT NỐI"; $(id).classList.add("offline"); });
      $("planner-badge").textContent = "MẤT KẾT NỐI";
      $("planner-badge").classList.add("offline");
      $("planner-status").textContent = "Khởi động máy chủ rồi tải lại trang để kiểm tra mô hình chọn phép thử.";
      updateConfig();
    }
  }

  function emptyChart(message, detail) {
    const empty = el("div", undefined, "chart-empty");
    const glyph = el("span", "⌁", "empty-chart-glyph"); glyph.setAttribute("aria-hidden", "true");
    empty.append(glyph, el("p", message), el("small", detail));
    $("score-chart").replaceChildren(empty);
  }

  function clearResults(preserveRecords = false) {
    if (!preserveRecords) {
      setInvestigationURL(null);
      state.report = null;
      state.investigation = null;
      state.agentSelected = null;
      state.ledgerKey = null;
      state.guide = { sourceKey: null, selectedId: null, follow: true, disconnected: false };
      $("agent-state").textContent = "SẴN SÀNG";
      $("agent-current-step").textContent = "Chọn ảnh, đặt giới hạn lượt gọi rồi bắt đầu phân tích.";
      $("agent-conclusion").hidden = true;
      $("agent-error").hidden = true;
      $("agent-maps").hidden = true;
      $("agent-observations").replaceChildren(el("p", "Kết quả sẽ xuất hiện khi mỗi phép thử hoàn tất.", "agent-empty"));
      $("agent-decisions").replaceChildren(el("p", "Phép đo đầu tiên là bắt buộc. Các bước tiếp theo được chọn dựa trên kết quả đã có.", "agent-empty"));
      $("agent-tool-count").textContent = `0 / ${$("agent-budget").value}`;
      $("agent-planner-count").textContent = "0";
      $("agent-runtime").textContent = "—";
      ["agent-export-csv", "agent-export-json"].forEach((id) => { $(id).hidden = true; $(id).removeAttribute("href"); });
      ["agent-run-id", "agent-source-hash", "agent-planner-name"].forEach((id) => { $(id).textContent = "—"; });
    }
    state.selected = null;
    $("measurements-panel").hidden = true;
    $("regional-results").hidden = true;
    $("regional-images").replaceChildren();
    $("regional-warnings").replaceChildren();
    $("result-image").hidden = true;
    $("result-image").removeAttribute("src");
    $("result-empty").hidden = false;
    $("result-dimensions").textContent = "CHƯA ĐO";
    $("result-size").textContent = "—";
    $("result-label").textContent = "Kết quả";
    $("result-note").textContent = "";
    viewer.refresh();
    $("variant-select").replaceChildren(el("option", adaptiveMode() ? "Sau khi có kết quả" : "Sau khi chạy thí nghiệm"));
    $("variant-select").disabled = true;
    $("preview-tag").textContent = state.file ? "ĐÃ CHỌN ẢNH" : "ĐANG CHỜ ẢNH";
    $("metric-original").textContent = "—";
    $("metric-original-help").textContent = "Đang chờ phép đo";
    $("metric-range").textContent = "—";
    $("metric-flips").textContent = "—";
    $("metric-threshold-help").textContent = "So với ảnh gốc · ngưỡng > 0,50";
    $("evidence-tag").textContent = "CHƯA PHẢI KẾT LUẬN";
    $("summary-title").textContent = "Đặt câu hỏi, giữ sự thận trọng.";
    $("summary-text").textContent = "Mô hình có phản hồi ổn định khi ảnh được nén lại hoặc đổi kích thước? Công cụ ghi nhận sự thay đổi, chưa đủ để xác định nguồn gốc ảnh.";
    $("warnings-details").hidden = true;
    $("warnings").replaceChildren();
    emptyChart("Kết quả đo thực tế sẽ hiện ở đây.", "Chọn ảnh và chạy thí nghiệm để kiểm tra độ ổn định của điểm số.");
    $("step-measure").classList.remove("current");
    $("step-region").classList.remove("current");
    if (state.status) { setModelState("bfree", state.status.bfree); setModelState("trufor", state.status.trufor); }
    updateRegionalButton();
    renderGuide();
  }

  async function chooseFile(file, allowBusy = false) {
    if (!file || (state.busy && !allowBusy)) return false;
    showError("");
    if (file.size > MAX_BYTES) { showError("Ảnh vượt quá 20 MiB. Hãy chọn tệp có dung lượng nhỏ hơn."); return; }
    if (!/\.(jpe?g|png|webp)$/i.test(file.name) && !["image/jpeg", "image/png", "image/webp"].includes(file.type)) { showError("Hãy chọn ảnh JPEG, PNG hoặc WebP."); return; }
    const generation = ++state.generation;
    const previousURL = state.objectURL;
    const objectURL = URL.createObjectURL(file);
    let previewSize;
    try {
      previewSize = await new Promise((resolve, reject) => {
        const image = new Image();
        image.onload = () => resolve({ width: image.naturalWidth, height: image.naturalHeight });
        image.onerror = () => reject(new Error("Trình duyệt không đọc được ảnh. Hãy chọn tệp JPEG, PNG hoặc WebP hợp lệ."));
        image.src = objectURL;
      });
      if (previewSize.width * previewSize.height > 20_000_000) throw new Error("Ảnh vượt quá 20 triệu điểm ảnh. Hãy thu nhỏ ảnh trước khi phân tích.");
      if (Math.min(previewSize.width, previewSize.height) < 16) throw new Error("Chiều rộng và chiều cao của ảnh phải từ 16 điểm ảnh trở lên.");
      const base64 = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(",")[1]);
        reader.onerror = () => reject(new Error("Không đọc được tệp đã chọn."));
        reader.readAsDataURL(file);
      });
      if (generation !== state.generation) { URL.revokeObjectURL(objectURL); return; }
      if (previousURL) URL.revokeObjectURL(previousURL);
      state.file = file; state.base64 = base64; state.objectURL = objectURL;
      clearResults();
      viewer.reset();
      setPreview($("original-image"), objectURL);
      $("original-image").hidden = false;
      $("original-empty").hidden = true;
      $("original-dimensions").textContent = dimensions(previewSize);
      $("original-format").textContent = (file.type.split("/")[1] || file.name.split(".").pop()).toUpperCase();
      $("original-size").textContent = bytesText(file.size);
      $("file-name").textContent = file.name;
      $("file-name").title = file.name;
      $("file-meta").textContent = `${dimensions(previewSize)} px · ${bytesText(file.size)}`;
      $("file-detail").hidden = false;
      $("file-state").textContent = "ĐÃ CHỌN";
      $("dropzone").classList.add("has-file");
      $("upload-title").textContent = "Ảnh đã sẵn sàng";
      $("upload-subtitle").replaceChildren(document.createTextNode("Thả ảnh khác hoặc "), el("u", "chọn tệp"));
      $("step-transform").classList.add("current");
      $("run-button").disabled = state.busy;
      updateConfig();
      renderGuide();
      reveal($("file-detail"));
      announce(`Đã chọn ${file.name}, ${previewSize.width} × ${previewSize.height} điểm ảnh. Sẵn sàng chạy thí nghiệm.`);
      return true;
    } catch (error) {
      URL.revokeObjectURL(objectURL);
      if (generation === state.generation) showError(error.message);
      return false;
    }
  }

  function clearFile() {
    if (state.busy) return;
    state.generation++;
    if (state.objectURL) URL.revokeObjectURL(state.objectURL);
    state.file = null; state.base64 = null; state.objectURL = null;
    $("image-file").value = "";
    $("original-image").hidden = true;
    $("original-image").removeAttribute("src");
    $("original-empty").hidden = false;
    $("original-dimensions").textContent = "— × —";
    $("original-format").textContent = "ẢNH NGUỒN";
    $("original-size").textContent = "Tệp đầu vào chưa thay đổi";
    $("file-detail").hidden = true;
    $("file-state").textContent = "CHƯA CHỌN ẢNH";
    $("dropzone").classList.remove("has-file");
    $("upload-title").textContent = "Thả ảnh vào đây";
    $("upload-subtitle").replaceChildren(document.createTextNode("hoặc "), el("u", "chọn tệp ảnh"));
    $("step-transform").classList.remove("current");
    $("run-button").disabled = true;
    clearResults(); viewer.reset(); updateConfig(); showError("");
    $("image-file").focus();
    announce("Đã bỏ ảnh đã chọn.");
  }

  function renderChart() {
    const report = state.report;
    const variants = report.variants || [];
    const available = variants.filter((variant) => numeric(variant.score) && variant.score >= 0 && variant.score <= 1);
    if (!available.length) { emptyChart("Chưa có điểm số từ mô hình.", "Đã có ảnh biến đổi và phép đo điểm ảnh. Cần cấu hình trọng số B-Free để đo điểm AI."); return; }
    const width = Math.max(300, Math.min(1100, $("score-chart").clientWidth || 680));
    const height = 170, left = 40, right = 22, top = 18, bottom = 28;
    const plotWidth = width - left - right, plotHeight = height - top - bottom;
    const x = (index) => left + index * plotWidth / Math.max(variants.length - 1, 1);
    const y = (score) => top + (1 - score) * plotHeight;
    const svg = svgEl("svg", { viewBox: `0 0 ${width} ${height}`, class: "score-svg", role: "img", "aria-label": `Điểm AI của B-Free: ${variants.map((v) => `${variantName(v)}: ${scoreText(v.score)}`).join("; ")}.` });
    [0, 0.25, 0.5, 0.75, 1].forEach((tick) => {
      svg.append(svgEl("line", { x1: left, x2: width - right, y1: y(tick), y2: y(tick), stroke: "#e6ebe0", "stroke-width": 1 }));
      svg.append(svgEl("text", { x: left - 10, y: y(tick) + 3, "text-anchor": "end", fill: "#687777", "font-size": 10, "font-family": "monospace" }, numberText(tick, 2)));
    });
    const threshold = numeric(report.config?.threshold) ? report.config.threshold : 0.5;
    svg.append(svgEl("line", { x1: left, x2: width - right, y1: y(threshold), y2: y(threshold), stroke: "#b59b6d", "stroke-width": 1, "stroke-dasharray": "4 4" }));
    svg.append(svgEl("text", { x: left + 6, y: Math.max(12, y(threshold) - 6), "text-anchor": "start", fill: "#946b35", "font-size": 10, "font-family": "sans-serif" }, `ngưỡng ${numberText(threshold, 2)}`));
    const selectedIndex = variants.findIndex((variant) => variant.id === state.selected);
    if (selectedIndex >= 0) svg.append(svgEl("rect", { x: x(selectedIndex) - 18, y: top - 8, width: 36, height: plotHeight + 16, rx: 5, fill: "#e4f1ea" }));
    let previous = null;
    variants.forEach((variant, index) => {
      svg.append(svgEl("text", { x: x(index), y: height - 8, "text-anchor": "middle", fill: "#687777", "font-size": 10, "font-family": "sans-serif" }, variant.round === 0 ? "Gốc" : `V${variant.round ?? index}`));
      if (!numeric(variant.score) || variant.score < 0 || variant.score > 1) { previous = null; return; }
      const point = { x: x(index), y: y(variant.score) };
      if (previous) svg.append(svgEl("line", { x1: previous.x, x2: point.x, y1: previous.y, y2: point.y, stroke: "#1d807f", "stroke-width": 2 }));
      previous = point;
    });
    variants.forEach((variant, index) => {
      if (!numeric(variant.score) || variant.score < 0 || variant.score > 1) return;
      // Each measured point selects its derivative in the viewer.
      const label = `${variantName(variant)}: ${numberText(variant.score, 4)}`;
      const point = svgEl("g", { class: "point", tabindex: "0", role: "button", "aria-label": `Xem ${label}`, "aria-pressed": String(variant.id === state.selected) });
      point.append(svgEl("circle", { class: "hit", cx: x(index), cy: y(variant.score), r: 14, fill: "transparent" }));
      point.append(svgEl("circle", { class: "dot", cx: x(index), cy: y(variant.score), r: variant.id === state.selected ? 6 : 4, fill: variant.id === state.selected ? "#1d807f" : "#fffefa", stroke: "#1d807f", "stroke-width": 2 }));
      point.append(svgEl("title", {}, label));
      point.addEventListener("click", () => reviewPreview(variant.id));
      point.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); reviewPreview(variant.id); } });
      svg.append(point);
    });
    $("score-chart").replaceChildren(svg);
  }

  function selectVariant(id) {
    const variant = state.report?.variants?.find((item) => item.id === id);
    if (!variant) return;
    state.selected = variant.id;
    $("variant-select").value = variant.id;
    const preview = sameOriginURL(variant.preview_url);
    $("result-image").hidden = !preview;
    $("result-empty").hidden = !!preview;
    if (preview) {
      setPreview($("result-image"), preview);
      $("result-image").alt = `${variantName(variant)}, ${dimensions(variant)} điểm ảnh`;
    }
    $("result-dimensions").textContent = `${dimensions(variant)} PX`;
    $("result-size").textContent = bytesText(variant.bytes);
    $("result-label").textContent = ForensicsGuide.previewLabel(variant);
    $("result-note").textContent = numeric(variant.score) ? `Điểm AI ${scoreText(variant.score)}` : "";
    for (const row of $("measurements-body").rows) row.classList.toggle("selected", row.dataset.variant === id);
    renderChart();
    viewer.refresh();
  }

  function renderMeasurements(report) {
    const threshold = numeric(report.config?.threshold) ? report.config.threshold : 0.5;
    const rows = report.variants.map((variant) => {
      const row = el("tr"); row.dataset.variant = variant.id;
      const first = el("td");
      const button = el("button", variantName(variant), "row-variant-button"); button.type = "button";
      button.addEventListener("click", () => reviewPreview(variant.id)); first.append(button);
      let psnr = "Chưa có dữ liệu";
      if (numeric(variant.psnr_db)) psnr = `${numberText(variant.psnr_db, 2)} dB`;
      else if (variant.mse === 0) psnr = "∞ (trùng tham chiếu)";
      const scoreCell = el("td", scoreText(variant.score), numeric(variant.score) ? "score-cell" : undefined);
      if (variant.error) scoreCell.title = errorText(variant.error);
      row.append(first, scoreCell, el("td", numeric(variant.score) ? variant.score > threshold ? "Trên ngưỡng" : "Bằng / dưới ngưỡng" : "Chưa đo"), el("td", dimensions(variant)), el("td", psnr), el("td", numberText(variant.mse, 3)), el("td", bytesText(variant.bytes)));
      return row;
    });
    $("measurements-body").replaceChildren(...rows);
    const config = report.config || {};
    const operation = { combined: "Nén + đổi kích thước", jpeg: "Nén JPEG", resize: "Đổi kích thước" }[config.operation] || "Biến đổi ảnh";
    const mode = config.mode === "independent" ? "Đối chứng một lượt" : "Xử lý nối tiếp";
    const parts = [mode, operation];
    if (config.operation !== "resize" && numeric(config.quality)) parts.push(`JPEG Q${config.quality}`);
    if (config.operation !== "jpeg" && numeric(config.scale)) parts.push(`${Math.round(config.scale * 100)}% mỗi vòng`);
    if (config.operation === "combined") parts.push(config.order === "jpeg-resize" ? "JPEG → đổi cỡ" : "Đổi cỡ → JPEG");
    parts.push(`ngưỡng > ${numberText(threshold, 2)}`);
    $("record-config").textContent = parts.join(" · ");
    $("run-id").textContent = report.run_id || "Chưa có dữ liệu";
    $("source-hash").textContent = report.image?.sha256 || "Chưa có dữ liệu";
    $("detector-name").textContent = `${report.detector?.name || "B-Free"} · ${statusNames[report.detector?.status] || "chưa xác định"}`;
    for (const [id, value] of [["export-csv", report.exports?.csv_url], ["export-json", report.exports?.json_url]]) {
      const url = sameOriginURL(value); $(id).hidden = !url; if (url) $(id).href = url;
    }
    $("measurements-panel").hidden = false;
  }

  function renderReport(report) {
    const variants = report.variants || [];
    if (!variants.length) throw new Error("Máy chủ không trả về ảnh biến thể.");
    state.report = report;
    const scores = variants.map((v) => v.score).filter((v) => numeric(v) && v >= 0 && v <= 1);
    $("preview-tag").textContent = rules.completionTag(Math.max(0, variants.length - 1), scores.length, variants.length);
    $("trajectory-title").textContent = rules.trajectoryTitle(report.config?.mode);
    $("original-dimensions").textContent = dimensions(report.image);
    $("original-format").textContent = (report.image?.format || "ẢNH NGUỒN").toUpperCase();
    $("original-size").textContent = bytesText(report.image?.bytes);
    $("variant-select").replaceChildren(...variants.map((variant) => { const option = el("option", variantName(variant)); option.value = variant.id; return option; }));
    $("variant-select").disabled = false;
    const baseline = variants.find((v) => v.id === "original" || v.round === 0) || variants[0];
    $("metric-original").textContent = numeric(baseline.score) ? scoreText(baseline.score) : "—";
    $("metric-original-help").textContent = numeric(baseline.score) ? "Phản hồi mô hình · từ 0 đến 1" : "Mô hình chưa khả dụng";
    $("metric-range").textContent = scores.length ? `${scoreText(Math.min(...scores))}–${scoreText(Math.max(...scores))}` : "—";
    $("metric-flips").textContent = numeric(report.summary?.flip_count) ? String(report.summary.flip_count) : "—";
    $("metric-threshold-help").textContent = `So với ảnh gốc · ngưỡng > ${numberText(report.config?.threshold ?? 0.5, 2)}`;
    $("evidence-tag").textContent = scores.length ? "PHẢN HỒI MÔ HÌNH" : "CHỈ CÓ PHÉP ĐO ẢNH";
    $("summary-title").textContent = translate(report.summary?.title) || "Đã ghi lại thí nghiệm.";
    $("summary-text").textContent = translate(report.summary?.text) || "Hãy xem từng phép đo và giới hạn của mô hình trước khi diễn giải kết quả.";
    const warnings = Array.isArray(report.summary?.warnings) ? report.summary.warnings : [];
    $("warnings").replaceChildren(...warnings.map((warning) => el("li", translate(warning))));
    $("warnings-count").textContent = `(${warnings.length})`;
    $("warnings-details").hidden = !warnings.length;
    renderMeasurements(report);
    selectVariant(variants[variants.length - 1].id);
    $("step-measure").classList.add("current");
    $("regional-results").hidden = true;
    const recommended = report.summary?.regional_scan_recommended;
    if (state.status?.trufor?.available) {
      $("regional-status").textContent = recommended
        ? "Kết quả đo cho thấy nên kiểm tra thêm. Có thể tạo bản đồ bất thường và độ tin cậy định vị trên ảnh gốc."
        : "Bước bổ sung: kiểm tra dấu hiệu chỉnh sửa cục bộ và độ tin cậy của bản đồ trên ảnh gốc.";
    } else if (report.regional?.message) $("regional-status").textContent = translate(report.regional.message);
    if (!scores.length && report.detector?.reason) $("bfree-status").textContent = `${translate(report.detector.reason)} Đã ghi lại kết quả biến đổi ảnh.`;
    if (report.regional?.heatmap_url || report.regional?.reliability_url || report.regional?.overlay_url) renderRegionalResult(report.regional);
    updateRegionalButton();
    reveal($("fixed-evidence-panel"));
    reveal($("measurements-panel"), 60);
    renderGuide();
    announce(`Thí nghiệm hoàn tất. Đã ghi ${variants.length} phiên bản ảnh và ${scores.length} điểm số từ mô hình.`);
  }

  function renderRegionalResult(result) {
    $("regional-status").textContent = (result.status === "error" ? errorText(result.message) : translate(result.message)) || "Đã hoàn tất kiểm tra từng vùng.";
    const maps = [["heatmap_url", "Bất thường do chỉnh sửa · TruFor"], ["reliability_url", "Độ tin cậy định vị · TruFor"], ["overlay_url", "Bản đồ bất thường chồng lên ảnh"]];
    const figures = [];
    for (const [key, caption] of maps) {
      const url = sameOriginURL(result[key]); if (!url) continue;
      const figure = el("figure"); const link = el("a"); link.href = url; link.target = "_blank"; link.rel = "noopener noreferrer"; link.setAttribute("aria-label", `Mở ảnh đầy đủ: ${caption}`);
      const image = el("img"); image.src = url; image.alt = caption; link.append(image);
      const captionElement = el("figcaption", caption);
      const legend = key === "heatmap_url" ? result.heatmap_legend : key === "reliability_url" ? result.reliability_legend : null;
      if (legend) captionElement.append(el("small", translate(legend)));
      figure.append(link, captionElement); figures.push(figure);
    }
    $("regional-images").replaceChildren(...figures);
    const score = numeric(result.score) ? `Điểm chỉnh sửa toàn ảnh của TruFor: ${scoreText(result.score)}. ` : "";
    $("regional-result-text").textContent = `${score}${translate(result.message)}`;
    const warnings = Array.isArray(result.warnings) ? result.warnings : [];
    $("regional-warnings").replaceChildren(...warnings.map((warning) => el("li", translate(warning))));
    $("regional-warnings").hidden = !warnings.length;
    $("regional-results").hidden = !figures.length && !warnings.length && !numeric(result.score);
    if (figures.length) $("step-region").classList.add("current");
    reveal($("regional-results"));
    renderGuide();
  }

  function evidenceLinks(ids) {
    const links = el("span", undefined, "evidence-links");
    for (const id of ids || []) {
      if (!/^E\d+$/.test(id)) continue;
      const link = el("a", id); link.href = `#agent-evidence-${id}`; link.setAttribute("aria-label", `Xem kết quả ${id}`); links.append(link);
    }
    return links;
  }

  function selectAgentObservation(id) {
    const item = state.investigation?.observations?.find((entry) => entry.id === id && entry.preview_url);
    if (!item) return;
    state.agentSelected = item.id;
    $("variant-select").value = item.id;
    const preview = sameOriginURL(item.preview_url);
    $("result-image").hidden = !preview;
    $("result-empty").hidden = !!preview;
    if (preview) { setPreview($("result-image"), preview); $("result-image").alt = `${item.id}: ${toolName(item.tool)}, ${dimensions(item)} điểm ảnh`; }
    $("result-dimensions").textContent = `${dimensions(item)} PX`;
    $("result-size").textContent = `${toolName(item.tool)}`;
    $("result-label").textContent = ForensicsGuide.previewLabel(item);
    $("result-note").textContent = numeric(item.score) ? `Điểm ${scoreText(item.score)}` : "";
    document.querySelectorAll(".evidence-card").forEach((card) => { card.classList.toggle("selected", card.dataset.evidence === id); });
    viewer.refresh();
  }

  function renderAgentLedger(report) {
    const observations = report.observations || [];
    if (animatedRun !== report.run_id) { seenEvidence.clear(); seenDecisions.clear(); animatedRun = report.run_id; }
    const cards = observations.map((item) => {
      const card = el("article", undefined, "evidence-card"); card.id = `agent-evidence-${item.id}`; card.dataset.evidence = item.id;
      const heading = el("div", undefined, "evidence-card-heading"); heading.append(el("span", item.id, "evidence-id"), el("h4", toolName(item.tool))); card.append(heading);
      const kind = item.score_kind === "local_manipulation" ? "CHỈNH SỬA CỤC BỘ" : "DẤU HIỆU ẢNH AI";
      const reading = el("div", undefined, "evidence-reading"); reading.append(el("strong", scoreText(item.score)), el("span", numeric(item.score) ? kind : "CHƯA CÓ ĐIỂM HỢP LỆ")); card.append(reading);
      if (numeric(item.delta_from_original)) {
        const delta = `${item.delta_from_original >= 0 ? "+" : ""}${numberText(item.delta_from_original, 4)}`;
        card.append(el("p", `${delta} so với ảnh gốc · ${item.decision_changed ? "đổi kết quả phân loại" : "giữ kết quả phân loại"}`, item.decision_changed ? "evidence-change changed" : "evidence-change"));
      }
      if (item.tool === "baseline") card.append(el("p", "Phép đo đầu tiên bắt buộc, được tính vào giới hạn lượt gọi.", "evidence-detail"));
      if (item.tool === "trufor") card.append(el("p", "Đánh giá khác với B-Free. Cần đọc cùng bản đồ độ tin cậy định vị bên dưới.", "evidence-detail"));
      const detail = [];
      if (numeric(item.width)) detail.push(`${dimensions(item)} px`);
      if (numeric(item.psnr_db)) detail.push(`PSNR ${numberText(item.psnr_db, 2)} dB`);
      else if (item.mse === 0) detail.push("PSNR ∞");
      if (numeric(item.runtime_seconds)) detail.push(elapsedText(item.runtime_seconds));
      if (detail.length) card.append(el("p", detail.join(" · "), "evidence-detail"));
      if (item.error) card.append(el("p", errorText(item.error), "evidence-error"));
      if (sameOriginURL(item.preview_url)) {
        const button = el("button", "Đối chiếu ảnh ↗", "evidence-preview"); button.type = "button";
        button.addEventListener("click", () => { reviewPreview(item.id); scrollTo($("preview-title"), "start"); }); card.append(button);
      }
      return card;
    });
    $("agent-observations").replaceChildren(...(cards.length ? cards : [el("p", "Kết quả sẽ xuất hiện khi mỗi phép thử hoàn tất.", "agent-empty")]));
    cards.forEach((card, index) => { if (!seenEvidence.has(card.id)) reveal(card, Math.min(index * 45, 135)); seenEvidence.add(card.id); });
    const decisions = (report.decisions || []).map((choice) => {
      const card = el("article", undefined, "decision-card");
      card.dataset.decision = String(choice.step);
      card.append(el("span", `LỰA CHỌN ${choice.step}`, "micro-label"), el("h4", toolName(choice.action)));
      const context = el("p", "Kết quả đã có: ", "decision-context"); context.append(evidenceLinks(choice.evidence_ids)); card.append(context);
      card.append(el("p", `AI trên máy đã chọn${numeric(choice.runtime_seconds) ? ` trong ${elapsedText(choice.runtime_seconds)}` : ""}.`, "evidence-detail"));
      if (choice.action !== "finish" && report.status !== "running" && !observations.some((item) => item.tool === choice.action)) card.append(el("p", "Phiên đã dừng trước khi thực hiện phép thử được chọn này.", "evidence-change changed"));
      const details = el("details", undefined, "decision-options"); details.append(el("summary", "Các hành động được phép"));
      const list = el("ul"); for (const action of choice.offered_actions || []) list.append(el("li", toolName(action))); details.append(list); card.append(details);
      return card;
    });
    $("agent-decisions").replaceChildren(...(decisions.length ? decisions : [el("p", report.status === "running" ? "Phép đo đầu tiên là bắt buộc. Các bước tiếp theo được chọn dựa trên kết quả đã có." : "Chưa ghi nhận quyết định chọn phép thử.", "agent-empty")]));
    decisions.forEach((card, index) => { if (!seenDecisions.has(card.dataset.decision)) reveal(card, Math.min(index * 45, 135)); seenDecisions.add(card.dataset.decision); });
    const region = observations.find((item) => item.tool === "trufor" && (item.heatmap_url || item.reliability_url));
    $("agent-maps").hidden = !region;
    if (region) {
      const figures = [];
      for (const [key, caption, legendKey] of [["heatmap_url", "Bất thường do chỉnh sửa", "heatmap_legend"], ["reliability_url", "Độ tin cậy định vị", "reliability_legend"], ["overlay_url", "Bản đồ chồng lên ảnh", null]]) {
        const url = sameOriginURL(region[key]); if (!url) continue;
        const figure = el("figure"); const link = el("a"); link.href = url; link.target = "_blank"; link.rel = "noopener noreferrer";
        link.setAttribute("aria-label", `Mở ảnh đầy đủ: ${caption}`);
        const image = el("img"); image.src = url; image.alt = `${caption} của TruFor trên ảnh gốc`; link.append(image);
        const label = el("figcaption", `${region.id} · ${caption}`);
        const legend = legendKey && region.detector_evidence?.[legendKey]; if (legend) label.append(el("small", translate(legend)));
        figure.append(link, label); figures.push(figure);
      }
      $("agent-regional-images").replaceChildren(...figures);
      $("step-region").classList.add("current");
    }
  }

  function renderInvestigation(report) {
    state.investigation = report;
    const running = report.status === "running";
    const observations = report.observations || [];
    $("agent-state").textContent = statusNames[report.status || "running"] || "CHƯA RÕ TRẠNG THÁI";
    $("agent-state").classList.toggle("agent-failed", report.status === "error");
    $("agent-current-step").textContent = state.cancelRequested && running ? "Đã yêu cầu dừng. Hệ thống sẽ hoàn tất lượt đang chạy trước khi dừng." : translate(report.current_step) || "Đang chuẩn bị phân tích";
    $("agent-progress-dot").classList.toggle("working", running);
    $("agent-progress-dot").closest(".agent-progress").classList.toggle("is-active", running);
    $("agent-tool-count").textContent = `${report.model_tool_calls || 0} / ${report.config?.budget || $("agent-budget").value}`;
    $("agent-planner-count").textContent = String(report.planner_calls || 0);
    $("agent-runtime").textContent = elapsedText(report.runtime_seconds);
    $("cancel-investigation").hidden = !running;
    $("cancel-investigation").disabled = state.cancelRequested;
    $("cancel-investigation").textContent = state.cancelRequested ? "Đã yêu cầu dừng" : "Dừng sau lượt đang chạy";
    $("agent-run-id").textContent = report.run_id || "—";
    $("agent-source-hash").textContent = report.image?.sha256 || "—";
    $("agent-planner-name").textContent = report.planner?.name || state.status?.planner?.name || "Mô hình chọn phép thử trên máy";
    if (report.image) $("original-dimensions").textContent = dimensions(report.image);
    $("preview-tag").textContent = "CÁC NHÁNH THỬ RIÊNG";
    const ledgerKey = JSON.stringify([report.run_id, report.status, observations, report.decisions]);
    if (ledgerKey !== state.ledgerKey) { renderAgentLedger(report); state.ledgerKey = ledgerKey; }
    const previews = observations.filter((item) => sameOriginURL(item.preview_url));
    $("variant-select").replaceChildren(...(previews.length ? previews.map((item) => { const option = el("option", `${item.id} · ${toolName(item.tool)}`); option.value = item.id; return option; }) : [el("option", "Đang chờ phép đo")]));
    $("variant-select").disabled = !previews.length;
    if (previews.length) selectAgentObservation(previews.some((item) => item.id === state.agentSelected) ? state.agentSelected : previews[previews.length - 1].id);
    const summary = report.summary;
    $("agent-conclusion").hidden = !summary;
    if (summary) {
      $("agent-summary-title").textContent = translate(summary.title) || "Kết quả đã ghi nhận";
      $("agent-facts").replaceChildren(...(summary.facts || []).map((fact) => { const paragraph = el("p", translate(fact.text)); paragraph.append(evidenceLinks(fact.evidence_ids)); return paragraph; }));
      $("agent-stop").textContent = rules.stopReasonText(summary.stop_reason);
      $("agent-warnings").replaceChildren(...(summary.warnings || []).map((warning) => el("li", translate(warning))));
    }
    const error = report.error || report.planner_error;
    $("agent-error").hidden = !error;
    $("agent-error").textContent = error ? errorText(error) : "";
    for (const [id, value] of [["agent-export-csv", report.exports?.csv_url], ["agent-export-json", report.exports?.json_url]]) {
      const url = sameOriginURL(value); $(id).hidden = !url; if (url) $(id).href = url;
    }
    if (observations.length) $("step-measure").classList.add("current");
    renderGuide();
  }

  async function pollInvestigation() {
    if (!state.activeJob || state.monitoring) return;
    const job = state.activeJob;
    state.monitoring = true;
    state.guide.disconnected = false;
    renderGuide();
    $("resume-investigation").hidden = true;
    showError("");
    let previousStep = "";
    try {
      while (state.activeJob === job && state.generation === job.generation) {
        const report = await request(job.url);
        if (state.activeJob !== job || state.generation !== job.generation) return;
        if (!["running", "complete", "error", "cancelled"].includes(report.status)) throw new Error("Máy chủ trả về trạng thái phân tích chưa xác định.");
        renderInvestigation(report);
        if (report.current_step !== previousStep) { announce(translate(report.current_step) || "Đã cập nhật phiên phân tích."); previousStep = report.current_step; }
        if (report.status !== "running") {
          state.activeJob = null;
          $("cancel-investigation").hidden = true;
          setBusy(false);
          reveal($("agent-conclusion"));
          announce(`${report.status === "complete" ? "Phân tích hoàn tất" : report.status === "cancelled" ? "Đã dừng phân tích" : "Phiên phân tích kết thúc do lỗi"}. Đã ghi nhận ${report.observations?.length || 0} phép đo.`);
          return;
        }
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
    } catch (error) {
      if (state.activeJob === job) {
        showError(`Tạm dừng theo dõi: ${errorText(error.message)} Máy chủ có thể vẫn đang xử lý. Hãy kết nối lại để xem kết quả hiện tại.`);
        state.guide.disconnected = true;
        renderGuide();
        $("resume-investigation").hidden = false;
        $("agent-current-step").textContent = "Kết nối bị gián đoạn. Cần kết nối lại để biết trạng thái phân tích hiện tại.";
        announce("Tạm dừng theo dõi. Hãy kết nối lại để kiểm tra phiên đang chạy.");
      }
    } finally { state.monitoring = false; }
  }

  async function startInvestigation() {
    if (!state.base64 || state.busy) return;
    const generation = state.generation;
    state.guide = { sourceKey: null, selectedId: null, follow: true, disconnected: false };
    state.investigation = null; state.agentSelected = null; state.ledgerKey = null; state.cancelRequested = false;
    clearResults(true);
    setBusy(true, "investigation"); showError("");
    renderInvestigation({ status: "running", current_step: "Đang gửi ảnh tới máy chủ trên máy này", config: { budget: Number($("agent-budget").value) }, observations: [], decisions: [] });
    $("cancel-investigation").hidden = true;
    try {
      const response = await request("/api/investigate", { filename: state.file.name, image_base64: state.base64, budget: Number($("agent-budget").value), allow_regional: $("allow-regional").checked && state.status?.trufor?.available === true });
      if (generation !== state.generation) return;
      const url = sameOriginURL(response.status_url);
      if (!url || !/^[a-f0-9]{32}$/.test(response.run_id || "")) throw new Error("Máy chủ trả về mã phiên phân tích không hợp lệ.");
      state.activeJob = { id: response.run_id, url, generation };
      setInvestigationURL(response.run_id);
      await pollInvestigation();
    } catch (error) {
      showError(error.message || "Không thể bắt đầu phân tích.");
      renderInvestigation({ status: "error", current_step: "Không thể bắt đầu phân tích", config: { budget: Number($("agent-budget").value) }, observations: [], decisions: [], error: error.message });
      setBusy(false);
    }
  }

  async function cancelInvestigation() {
    const job = state.activeJob;
    if (!job || state.cancelRequested) return;
    $("cancel-investigation").disabled = true;
    try {
      await request(`/api/investigations/${job.id}/cancel`, {});
      if (state.activeJob !== job) return;
      state.cancelRequested = true;
      renderGuide();
      $("cancel-investigation").textContent = "Đã yêu cầu dừng";
      $("agent-current-step").textContent = "Đã yêu cầu dừng. Hệ thống sẽ hoàn tất lượt đang chạy trước khi dừng.";
      announce("Đã yêu cầu dừng. Hệ thống sẽ hoàn tất lượt đang chạy trước khi dừng.");
      if (!state.monitoring) pollInvestigation();
    } catch (error) { showError(`Không gửi được yêu cầu dừng: ${errorText(error.message)}`); $("cancel-investigation").disabled = false; }
  }

  async function loadInvestigation(runID) {
    if (!/^[a-f0-9]{32}$/.test(runID)) { showError("Mã phiên phân tích đã lưu không hợp lệ."); return; }
    form.elements.workflow_mode.value = "adaptive"; updateApproach();
    setBusy(true, "saved");
    $("run-label").textContent = "Đang mở phiên phân tích…";
    try {
      const report = await request(`/api/investigations/${runID}`);
      state.savedRuns.add(runID);
      renderInvestigation(report);
      const preview = sameOriginURL(report.preview_url);
      if (preview) {
        setPreview($("original-image"), preview); $("original-image").hidden = false; $("original-empty").hidden = true;
        $("original-size").textContent = bytesText(report.image?.bytes);
        $("original-format").textContent = "ẢNH GỐC ĐÃ LƯU";
      }
      $("file-name").textContent = report.image?.name || "Phiên phân tích đã lưu";
      $("file-name").title = report.image?.name || "Phiên phân tích đã lưu";
      $("file-meta").textContent = `${dimensions(report.image)} px · ảnh nguồn đã lưu`;
      $("file-detail").hidden = false;
      $("file-state").textContent = "PHIÊN ĐÃ LƯU";
      $("agent-budget").value = String(report.config?.budget || 4);
      $("allow-regional").checked = report.config?.allow_regional !== false;
      setInvestigationURL(runID);
      if (report.status === "running") {
        state.activeJob = { id: runID, url: `/api/investigations/${runID}`, generation: state.generation };
        await pollInvestigation();
      } else { setBusy(false); announce("Đã mở phiên phân tích. Đây là kết quả đã lưu; chưa có lượt suy luận mới."); }
    } catch (error) { setBusy(false); showError(`Không mở được phiên đã lưu: ${errorText(error.message)}`); }
  }

  async function loadExample() {
    if (state.busy) return;
    form.elements.workflow_mode.value = "fixed"; updateApproach();
    showError(""); setBusy(true, "example");
    $("run-label").textContent = "Đang mở ví dụ…";
    $("run-help").textContent = "Đang tải ảnh mẫu chính thức cùng kết quả đo thực tế đã lưu.";
    try {
      const example = await request("/api/example");
      const binary = atob(example.image_base64);
      const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
      const filename = example.filename || "official-demo.png";
      const file = new File([bytes], filename, { type: /\.jpe?g$/i.test(filename) ? "image/jpeg" : /\.webp$/i.test(filename) ? "image/webp" : "image/png" });
      const ready = await chooseFile(file, true);
      if (!ready) throw new Error("Không tải được ảnh ví dụ đã lưu.");
      const config = example.report.config || {};
      for (const key of ["quality", "rounds", "order", "operation"]) if (config[key] !== undefined) $(key).value = String(config[key]);
      if (numeric(config.scale)) $("scale").value = String(config.scale * 100);
      if (numeric(config.threshold)) $("threshold").value = String(config.threshold * 100);
      if (["cumulative", "independent"].includes(config.mode)) form.elements.mode.value = config.mode;
      state.savedRuns.add(example.report.run_id);
      renderReport(example.report);
      $("preview-tag").textContent = "KẾT QUẢ MẪU ĐÃ LƯU";
      if (!state.status?.bfree?.available) $("bfree-status").textContent = "Đang xem điểm B-Free đã lưu từ lần chạy trước. B-Free trên máy này chưa cấu hình, nên lần chạy mới sẽ chỉ có phép đo ảnh.";
      $("file-state").textContent = "VÍ DỤ";
      announce("Đã mở ví dụ được kiểm chứng. Đây là kết quả đã lưu trên ảnh mẫu chính thức, chưa có lượt suy luận mới.");
    } catch (error) { showError(error.message || "Ví dụ đã lưu hiện không khả dụng."); }
    finally { setBusy(false); }
  }

  async function runExperiment(event) {
    event.preventDefault();
    if (adaptiveMode()) return startInvestigation();
    if (!state.base64 || state.busy) return;
    setInvestigationURL(null);
    showError(""); clearResults(); setBusy(true);
    announce("Đã bắt đầu thí nghiệm. Đang tạo biến thể và thu thập phản hồi mô hình.");
    const payload = { filename: state.file.name, image_base64: state.base64, ...readConfig() };
    try {
      const report = await request("/api/analyze", payload);
      renderReport(report);
    } catch (error) {
      state.report = { run_id: `failed-${state.generation}`, variants: [], config: payload, detector: { status: "error" } };
      showError(error.message || "Thí nghiệm gặp lỗi. Hãy kiểm tra máy chủ trên máy rồi thử lại.");
      announce("Không thể hoàn tất thí nghiệm.");
    } finally { setBusy(false); }
  }

  async function runRegional() {
    if (!state.report || state.regionalBusy || state.busy) return;
    const runID = state.report.run_id;
    state.regionalBusy = true;
    setBusy(true, "regional");
    updateRegionalButton();
    $("regional-button").textContent = "Đang kiểm tra ảnh gốc…";
    $("regional-status").textContent = "TruFor đang kiểm tra ảnh gốc. Quá trình có thể mất vài phút.";
    $("regional-results").hidden = true;
    announce("Đã bắt đầu kiểm tra từng vùng.");
    try {
      const result = await request("/api/regional", { run_id: runID });
      if (state.report?.run_id !== runID) return;
      state.report.regional = result;
      renderRegionalResult(result);
      announce(translate(result.message) || "Đã hoàn tất kiểm tra từng vùng.");
    } catch (error) {
      if (state.report?.run_id === runID) {
        $("regional-status").textContent = errorText(error.message) || "Kiểm tra từng vùng gặp lỗi. Hãy kiểm tra máy chủ rồi thử lại.";
        announce("Không thể hoàn tất kiểm tra từng vùng.");
      }
    } finally { state.regionalBusy = false; setBusy(false); updateRegionalButton(); }
  }

  // Viewer: side by side, split slider, or a browser-computed difference map, with zoom and pan shared by both images.
  const viewer = (() => {
    const stage = $("viewer-stage");
    const frames = [$("original-stage"), $("result-stage")];
    const canvas = $("diff-canvas");
    const wide = window.matchMedia("(min-width: 1180px)");
    const zoomSteps = [1, 1.5, 2, 3, 4, 6, 8];
    const MAX_DIFF_SIDE = 2048;
    let view = "side", zoomIndex = 0, pan = { x: 0, y: 0 }, drag = null, diffKey = null, diffJob = 0;
    const zoom = () => zoomSteps[zoomIndex];
    // Dark = near-identical pixels, bright = large difference. Stops: ink, teal, amber, ivory.
    const ramp = (() => {
      const stops = [[0, [15, 31, 38]], [0.35, [29, 128, 127]], [0.7, [242, 196, 109]], [1, [255, 251, 232]]];
      const table = new Uint8ClampedArray(256 * 3);
      for (let i = 0; i < 256; i++) {
        const t = i / 255;
        const upper = stops.findIndex(([position]) => position >= t);
        const [p1, c1] = stops[Math.max(upper, 1)], [p0, c0] = stops[Math.max(upper, 1) - 1];
        const f = (t - p0) / (p1 - p0);
        for (let k = 0; k < 3; k++) table[i * 3 + k] = c0[k] + (c1[k] - c0[k]) * f;
      }
      return table;
    })();

    function clampPan() {
      const box = frames[0].getBoundingClientRect();
      const limitX = (zoom() - 1) * box.width / 2, limitY = (zoom() - 1) * box.height / 2;
      pan.x = Math.max(-limitX, Math.min(limitX, pan.x));
      pan.y = Math.max(-limitY, Math.min(limitY, pan.y));
    }
    function applyTransform() {
      clampPan();
      for (const frame of frames) {
        frame.style.setProperty("--zoom", String(zoom()));
        frame.style.setProperty("--pan-x", `${pan.x}px`);
        frame.style.setProperty("--pan-y", `${pan.y}px`);
        frame.classList.toggle("zoomed", zoom() > 1);
        frame.classList.toggle("pixelated", zoom() >= 2);
      }
      stage.classList.toggle("zoomed-stage", zoom() > 1);
      $("zoom-reset").textContent = zoom() === 1 ? "Vừa khung" : `${Math.round(zoom() * 100)}%`;
      $("zoom-out").disabled = zoomIndex === 0;
      $("zoom-in").disabled = zoomIndex === zoomSteps.length - 1;
    }
    function setZoom(index) {
      const next = Math.max(0, Math.min(zoomSteps.length - 1, index));
      if (next === zoomIndex) return;
      const ratio = zoomSteps[next] / zoom();
      pan = { x: pan.x * ratio, y: pan.y * ratio };
      zoomIndex = next;
      if (zoomIndex === 0) pan = { x: 0, y: 0 };
      applyTransform();
    }

    async function computeDiff() {
      const original = $("original-image"), result = $("result-image");
      const ready = view === "diff" && !original.hidden && !result.hidden && original.getAttribute("src") && result.getAttribute("src");
      canvas.hidden = !ready;
      if (!ready) return;
      const gain = Number($("diff-gain").value) || 8;
      const key = `${original.src}|${result.src}|${gain}`;
      if (key === diffKey) return;
      const job = ++diffJob;
      try { await Promise.all([original.decode(), result.decode()]); } catch { return; }
      if (job !== diffJob || view !== "diff") return;
      const shrink = Math.min(1, MAX_DIFF_SIDE / Math.max(result.naturalWidth, result.naturalHeight));
      const width = Math.max(1, Math.round(result.naturalWidth * shrink)), height = Math.max(1, Math.round(result.naturalHeight * shrink));
      canvas.width = width; canvas.height = height;
      const context = canvas.getContext("2d", { willReadFrequently: true });
      context.imageSmoothingEnabled = true; context.imageSmoothingQuality = "high";
      context.drawImage(original, 0, 0, width, height);
      const reference = context.getImageData(0, 0, width, height).data;
      context.clearRect(0, 0, width, height);
      context.drawImage(result, 0, 0, width, height);
      const frame = context.getImageData(0, 0, width, height), pixels = frame.data;
      for (let i = 0; i < pixels.length; i += 4) {
        const difference = (Math.abs(pixels[i] - reference[i]) + Math.abs(pixels[i + 1] - reference[i + 1]) + Math.abs(pixels[i + 2] - reference[i + 2])) / 3;
        const level = Math.min(255, Math.round(difference * gain)) * 3;
        pixels[i] = ramp[level]; pixels[i + 1] = ramp[level + 1]; pixels[i + 2] = ramp[level + 2]; pixels[i + 3] = 255;
      }
      context.putImageData(frame, 0, 0);
      diffKey = key;
      canvas.setAttribute("aria-label", `Bản đồ khác biệt hiển thị, khuếch đại ×${gain}`);
    }

    function updateNav() {
      const select = $("variant-select");
      $("variant-prev").disabled = select.disabled || select.selectedIndex <= 0;
      $("variant-next").disabled = select.disabled || select.selectedIndex >= select.options.length - 1;
    }
    function refresh() { updateNav(); computeDiff(); }
    function setView(next) {
      view = next;
      stage.dataset.view = next;
      document.querySelectorAll(".view-switch button").forEach((button) => button.setAttribute("aria-checked", String(button.dataset.view === next)));
      $("split-range").hidden = next !== "slider";
      $("diff-tools").hidden = next !== "diff";
      applyTransform();
      refresh();
    }
    function step(delta) {
      const select = $("variant-select");
      const index = select.selectedIndex + delta;
      if (select.disabled || index < 0 || index >= select.options.length) return;
      select.selectedIndex = index;
      select.dispatchEvent(new Event("change"));
    }
    function reset() { zoomIndex = 0; pan = { x: 0, y: 0 }; diffKey = null; applyTransform(); refresh(); }

    document.querySelectorAll(".view-switch button").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
    $("zoom-in").addEventListener("click", () => setZoom(zoomIndex + 1));
    $("zoom-out").addEventListener("click", () => setZoom(zoomIndex - 1));
    $("zoom-reset").addEventListener("click", () => setZoom(0));
    $("split-range").addEventListener("input", (event) => stage.style.setProperty("--split", `${event.target.value}%`));
    $("diff-gain").addEventListener("change", () => computeDiff());
    $("variant-prev").addEventListener("click", () => step(-1));
    $("variant-next").addEventListener("click", () => step(1));
    for (const frame of frames) {
      frame.addEventListener("wheel", (event) => {
        // Zoom with the wheel only where the viewer has its own pane, or on a trackpad pinch.
        if (!wide.matches && !event.ctrlKey) return;
        event.preventDefault();
        setZoom(zoomIndex + (event.deltaY < 0 ? 1 : -1));
      }, { passive: false });
      frame.addEventListener("dblclick", () => setZoom(zoomIndex === 0 ? 2 : 0));
      frame.addEventListener("pointerdown", (event) => {
        if (zoom() === 1) return;
        drag = { id: event.pointerId, x: event.clientX - pan.x, y: event.clientY - pan.y, frame };
        frame.setPointerCapture(event.pointerId);
        frame.classList.add("panning");
      });
      frame.addEventListener("pointermove", (event) => {
        if (!drag || drag.id !== event.pointerId) return;
        pan = { x: event.clientX - drag.x, y: event.clientY - drag.y };
        applyTransform();
      });
      const end = (event) => { if (drag?.id === event.pointerId) { drag.frame.classList.remove("panning"); drag = null; } };
      frame.addEventListener("pointerup", end);
      frame.addEventListener("pointercancel", end);
    }
    document.addEventListener("keydown", (event) => {
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return;
      if (event.target.closest?.("input, select, textarea, dialog, [role=button]")) return;
      if (event.key === "ArrowLeft") step(-1);
      else if (event.key === "ArrowRight") step(1);
      else return;
      event.preventDefault();
    });
    window.addEventListener("resize", applyTransform);
    applyTransform();
    return { refresh, reset };
  })();

  // One place for every interpretation rule; panels link into the matching section.
  const guide = $("guide-dialog");
  function openGuide(sectionID) {
    if (!guide.open) guide.showModal();
    const section = sectionID && $(sectionID);
    if (section) {
      section.scrollIntoView({ block: "start", behavior: reducedMotion.matches ? "instant" : "smooth" });
      section.classList.remove("flash"); void section.offsetWidth; section.classList.add("flash");
    }
  }
  $("guide-open").addEventListener("click", () => openGuide());
  $("guide-close").addEventListener("click", () => guide.close());
  guide.addEventListener("click", (event) => { if (event.target === guide) guide.close(); });
  document.querySelectorAll("[data-guide]").forEach((button) => button.addEventListener("click", () => openGuide(button.dataset.guide)));

  $("guide-prev").addEventListener("click", () => stepGuide(-1));
  $("guide-next").addEventListener("click", () => stepGuide(1));
  $("guide-replay").addEventListener("click", () => { const first = $("guide-stages").querySelector("button"); if (first) chooseGuideStep(first.dataset.guideStep); });
  $("guide-follow").addEventListener("click", () => { state.guide.follow = true; renderGuide(); });
  $("research-details").addEventListener("toggle", () => { if ($("research-details").open && state.report && !adaptiveMode()) renderChart(); });
  document.addEventListener("click", (event) => { if (event.target.closest?.(".evidence-links a")) $("research-details").open = true; });
  form.addEventListener("submit", runExperiment);
  form.addEventListener("input", (event) => { if (event.target.id !== "image-file") updateConfig(); });
  form.addEventListener("change", (event) => { if (event.target.name === "workflow_mode") updateApproach(); else if (event.target.id !== "image-file") updateConfig(); });
  $("image-file").addEventListener("change", (event) => chooseFile(event.target.files[0]));
  $("clear-file").addEventListener("click", clearFile);
  $("variant-select").addEventListener("change", (event) => reviewPreview(event.target.value));
  $("cancel-investigation").addEventListener("click", cancelInvestigation);
  $("resume-investigation").addEventListener("click", pollInvestigation);
  $("regional-button").addEventListener("click", runRegional);
  $("example-button").addEventListener("click", loadExample);
  for (const type of ["dragenter", "dragover"]) $("dropzone").addEventListener(type, (event) => { event.preventDefault(); if (!state.busy) $("dropzone").classList.add("dragover"); });
  for (const type of ["dragleave", "drop"]) $("dropzone").addEventListener(type, (event) => { event.preventDefault(); $("dropzone").classList.remove("dragover"); });
  $("dropzone").addEventListener("drop", (event) => chooseFile(event.dataTransfer.files[0]));
  window.addEventListener("beforeunload", () => { if (state.objectURL) URL.revokeObjectURL(state.objectURL); });
  window.addEventListener("resize", () => { if (state.report && !adaptiveMode()) renderChart(); });
  const initialQuery = new URLSearchParams(location.search);
  updateApproach();
  loadStatus();
  if (initialQuery.has("investigation")) loadInvestigation(initialQuery.get("investigation"));
  else if (initialQuery.get("example") === "1") loadExample();
})();

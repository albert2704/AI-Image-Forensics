"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const state = {
    file: null, base64: null, objectURL: null, width: null, height: null,
    report: null, investigation: null, selectedId: null, busy: false, busyKind: null,
    status: null, generation: 0, activeJob: null, cancelRequested: false, monitoring: false,
    savedRuns: new Set(), example: false, savedInvestigation: false, regionalBusy: false,
    ledgerKey: null, disconnected: false, failed: false, model: null, view: "side", lastStageId: null,
  };
  const MAX_BYTES = 20 * 1024 * 1024;
  const SVG_NS = "http://www.w3.org/2000/svg";
  const form = $("experiment-form");
  const numeric = (value) => typeof value === "number" && Number.isFinite(value);
  const numberFormats = new Map();
  const numberText = (value, digits = 3) => {
    if (!numeric(value)) return "Chưa có dữ liệu";
    if (!numberFormats.has(digits)) numberFormats.set(digits, new Intl.NumberFormat("vi-VN", { minimumFractionDigits: digits, maximumFractionDigits: digits, useGrouping: true }));
    return numberFormats.get(digits).format(value);
  };
  const scoreText = (value) => numberText(value, 3);
  const bytesText = (bytes) => !numeric(bytes) ? "—" : bytes < 1024 ? `${bytes} B` : bytes < 1024 ** 2 ? `${numberText(bytes / 1024, 1)} KiB` : `${numberText(bytes / 1024 ** 2, 2)} MiB`;
  const dimensions = (item) => numeric(item?.width) && numeric(item?.height) ? `${item.width} × ${item.height}` : null;
  const announce = (message) => { $("live-status").textContent = message; };
  const el = (tag, text, className) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (className) node.className = className; return node; };
  const svgEl = (tag, attributes, text) => { const node = document.createElementNS(SVG_NS, tag); Object.entries(attributes || {}).forEach(([key, value]) => node.setAttribute(key, value)); if (text !== undefined) node.textContent = text; return node; };
  const adaptiveMode = () => form.elements.workflow_mode.value === "adaptive";
  const toolNames = { baseline: "Ảnh gốc · B-Free", "jpeg_q85_r1": "JPEG Q85 · 1 vòng", "jpeg_q85_r3": "JPEG Q85 · 3 vòng", "resize_s0.9_r1": "Đổi cỡ 90% · 1 vòng", "combined_q95_s0.9_r3": "Đổi cỡ 90% → JPEG Q95 · 3 vòng", trufor: "TruFor kiểm tra từng vùng", finish: "Kết thúc phân tích" };
  const toolName = (name) => toolNames[name] || name || "Công cụ chưa xác định";
  const elapsedText = (value) => {
    if (!numeric(value)) return "—";
    const seconds = Math.round(value);
    return seconds < 60 ? `${seconds} giây` : `${Math.floor(seconds / 60)} phút ${seconds % 60} giây`;
  };
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
  const sameOriginURL = (value) => {
    if (typeof value !== "string" || !value) return null;
    try {
      const url = new URL(value, location.origin);
      return url.origin === location.origin && ["http:", "https:"].includes(url.protocol) ? url.href : null;
    } catch { return null; }
  };

  function showError(message) {
    $("alert").textContent = message ? errorText(message) : "";
    $("alert").hidden = !message;
    if (message) $("alert").scrollIntoView({ block: "nearest" });
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

  function setInvestigationURL(runID) {
    const url = new URL(location.href);
    url.searchParams.delete("example");
    if (runID) url.searchParams.set("investigation", runID); else url.searchParams.delete("investigation");
    history.replaceState(null, "", url);
  }

  function readConfig() {
    return {
      quality: Number($("quality").value), scale: Number($("scale").value) / 100,
      rounds: Number($("rounds").value), mode: form.elements.mode.value,
      order: $("order").value, operation: $("operation").value,
      threshold: Number($("threshold").value) / 100,
    };
  }
  const chipConfig = () => adaptiveMode() ? { ...readConfig(), workflow: "adaptive", budget: Number($("agent-budget").value) } : readConfig();
  const hasSource = () => !!(state.file || state.report || state.investigation);
  const isSaved = () => state.example || state.savedInvestigation || (state.report && state.savedRuns.has(state.report.run_id)) || (state.investigation && state.savedRuns.has(state.investigation.run_id));
  const savedLabel = () => state.example ? "ví dụ đã lưu" : state.savedInvestigation ? "phiên đã lưu" : "";
  const sourceName = () => state.file?.name || state.report?.image?.name || state.investigation?.image?.name || "";
  const sourceDimensions = () => {
    if (numeric(state.width) && numeric(state.height)) return { width: state.width, height: state.height };
    const image = state.report?.image || state.investigation?.image;
    return numeric(image?.width) && numeric(image?.height) ? { width: image.width, height: image.height } : null;
  };
  const originalImageURL = () => state.objectURL || sameOriginURL(state.investigation?.preview_url) || sameOriginURL((state.report?.variants || []).find((item) => item.id === "original")?.preview_url);
  const regionalFor = (model) => model.stops.find((item) => item.kind === "regional") || null;

  function renderHeader() {
    const file = hasSource();
    $("file-chip").classList.toggle("has-file", file);
    $("file-chip-thumb").hidden = !file;
    $("file-chip-change").hidden = !file;
    $("other-file").hidden = !file;
    $("file-chip").setAttribute("aria-label", file ? "Đổi ảnh đã chọn" : "Chọn ảnh");
    $("file-chip-name").textContent = file ? sourceName() || "Ảnh đã chọn" : "Chưa chọn ảnh";
    const thumb = originalImageURL();
    if (thumb) { $("file-chip-image").src = thumb; $("file-chip-image").alt = `Ảnh thu nhỏ của ${sourceName()}`; } else { $("file-chip-image").removeAttribute("src"); $("file-chip-image").alt = ""; }
    const dims = sourceDimensions();
    const saved = savedLabel();
    const meta = [dims ? dimensions(dims) : null, saved].filter(Boolean).join(" · ");
    $("file-chip-meta").hidden = !meta;
    $("file-chip-meta").textContent = meta;
    $("file-chip-config").hidden = !file;
    $("file-chip-config").textContent = `${ForensicsGuide.configChip(chipConfig(), true)} · Đổi`;
    $("config-chip-text").textContent = ForensicsGuide.configChip(chipConfig());
    $("file-state").textContent = file ? saved ? saved.toUpperCase() : "ĐÃ CHỌN" : "CHƯA CHỌN ẢNH";
    $("file-detail").hidden = !file;
    $("file-name").textContent = file ? sourceName() : "";
    $("file-name").title = file ? sourceName() : "";
    $("file-meta").textContent = file ? [dimensions(dims), saved || (state.file ? bytesText(state.file.size) : null)].filter(Boolean).join(" · ") : "";
  }

  function runningAnswer() {
    const config = readConfig();
    if (state.busyKind === "example") return { tone: "info", title: "Đang mở ví dụ đã lưu", detail: "Đang đọc ảnh mẫu và kết quả đo đã lưu; không chạy suy luận mới." };
    if (state.busyKind === "saved") return { tone: "info", title: "Đang mở phiên đã lưu", detail: "Đang đọc lại ảnh và phép đo đã lưu; không chạy suy luận mới." };
    if (state.disconnected) return { tone: "warn", title: "Tạm dừng theo dõi", detail: "Kết nối bị gián đoạn. Máy chủ có thể vẫn đang xử lý; dùng Kết nối lại trong cửa sổ Nhật ký để xem trạng thái mới nhất." };
    if (adaptiveMode()) {
      const investigation = state.investigation || {};
      const total = Number(investigation.config?.budget || $("agent-budget").value) || 4;
      const done = (investigation.observations || []).length;
      return {
        tone: "info",
        title: state.cancelRequested ? "Đang dừng sau lượt hiện tại" : done ? `Đang đo · ${done} trên ${total} phép đo xong` : "Đang chuẩn bị phép đo",
        detail: state.cancelRequested ? "Hệ thống sẽ hoàn tất lượt đang chạy trước khi dừng; các phép đo đã xong được giữ lại." : translate(investigation.current_step) || "Câu trả lời hiện khi các phép đo xong.",
      };
    }
    return { tone: "info", title: `Đang xử lý ảnh gốc và ${config.rounds} bản sao`, detail: `Câu trả lời hiện khi đo ảnh gốc và ${config.rounds} bản sao.` };
  }

  function renderAnswer(model) {
    const config = readConfig();
    let answer;
    if (model.stage === "empty" || model.stage === "ready") {
      answer = {
        tone: "dashed",
        title: adaptiveMode()
          ? "Câu trả lời sẽ hiện ở đây sau khi đo ảnh gốc và các phép thử Qwen chọn."
          : `Câu trả lời sẽ hiện ở đây sau khi đo ảnh gốc và ${config.rounds} bản sao.`,
        detail: "",
      };
    } else if (model.stage === "running" || (!model.answer && model.stage !== "complete" && model.stage !== "partial" && model.stage !== "error")) {
      answer = runningAnswer();
    } else {
      answer = model.answer || (model.stage === "error"
        ? { tone: "danger", title: "Không hoàn tất được lần chạy này.", detail: "Máy chủ trả lỗi; chưa có điểm nào để so sánh. Hãy xem thông báo phía trên." }
        : { tone: "warn", title: "Chưa đủ phép đo để trả lời.", detail: "Cần ít nhất một điểm hợp lệ của ảnh gốc và một bản sao." });
    }
    $("answer").dataset.tone = answer.tone;
    $("answer-title").textContent = answer.title;
    $("answer-detail").textContent = answer.detail || "";
  }

  function trackStops(model) {
    return model.stops.filter((item) => item.kind !== "regional" && item.kind !== "summary");
  }

  function renderTrack(model) {
    const stops = trackStops(model);
    const chart = $("track-chart");
    const width = Math.max(280, chart.clientWidth || 600);
    const height = 96, top = 10, bottom = 7;
    const x = (index) => stops.length ? (index + .5) * width / stops.length : width / 2;
    const y = (score) => top + (1 - score) * (height - top - bottom);
    const svg = svgEl("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-hidden": "true" });
    svg.append(svgEl("line", { x1: .5, x2: .5, y1: 0, y2: height - 1, stroke: "#e4e4da", "stroke-width": 1 }));
    svg.append(svgEl("line", { x1: 0, x2: width, y1: height - 1, y2: height - 1, stroke: "#e4e4da", "stroke-width": 1 }));
    svg.append(svgEl("line", { x1: 0, x2: width, y1: y(model.threshold), y2: y(model.threshold), stroke: "#b59b6d", "stroke-width": 1, "stroke-dasharray": "4 4" }));
    svg.append(svgEl("text", { x: width - 2, y: Math.max(10, y(model.threshold) - 6), "text-anchor": "end", fill: "#946b35", "font-size": 10.5, "font-family": "sans-serif" }, `ngưỡng ${numberText(model.threshold, 2)}`));
    let previous = null, previousIndex = -1;
    stops.forEach((item, index) => {
      if (item.state !== "measured" || !numeric(item.score)) { previous = null; previousIndex = -1; return; }
      if (previous && previousIndex === index - 1) svg.append(svgEl("line", { x1: previous.x, x2: x(index), y1: previous.y, y2: y(item.score), stroke: "#1d807f", "stroke-width": 2 }));
      previous = { x: x(index), y: y(item.score) }; previousIndex = index;
    });
    stops.forEach((item, index) => {
      if (item.state !== "measured" || !numeric(item.score)) return;
      const selected = item.id === state.selectedId;
      svg.append(svgEl("circle", { cx: x(index), cy: y(item.score), r: selected ? 7 : 4.5, fill: selected ? "#fffefa" : "#1d807f", stroke: "#1d807f", "stroke-width": selected ? 2.4 : 1.6 }));
    });
    chart.replaceChildren(svg);

    const counts = model.counts;
    const measured = stops.some((item) => item.state === "measured");
    const countsNode = $("track-counts");
    countsNode.hidden = !measured;
    countsNode.replaceChildren(el("strong", String(counts.weak)), document.createTextNode(" tín hiệu yếu · "), el("strong", String(counts.strong)), document.createTextNode(" tín hiệu mạnh"));
    $("track-hint").textContent = model.stage === "empty" || model.stage === "ready" ? "Mỗi mốc là một bản sao. Điểm hiện khi đo xong."
      : model.stage === "running" ? adaptiveMode() ? "Cập nhật mỗi phép đo xong" : "Đang đo ảnh gốc và các bản sao"
        : "Bấm một mốc để xem";

    const buttons = stops.map((item) => {
      const button = el("button", undefined, "stop");
      button.type = "button";
      button.dataset.stopId = item.id;
      button.setAttribute("aria-pressed", String(item.id === state.selectedId));
      button.classList.toggle("selected", item.id === state.selectedId);
      button.classList.toggle("pending", item.state === "pending");
      button.classList.toggle("failed", item.state === "failed");
      const slot = item.id.startsWith("slot-");
      button.classList.toggle("slot", slot);
      button.disabled = slot || model.stage === "empty" || model.stage === "ready";
      const thumb = el("span", undefined, "stop-thumb");
      const url = sameOriginURL(item.thumb);
      if (url) { const image = el("img"); image.src = url; image.alt = ""; thumb.append(image); } else thumb.classList.add("placeholder");
      const score = el("span", undefined, "stop-score");
      if (item.state === "measured" && numeric(item.score)) score.textContent = scoreText(item.score);
      else if (item.state === "failed") score.textContent = "Chưa đo";
      else if (slot) score.textContent = "—";
      else if (model.stage === "running") { const spinner = el("span", undefined, "spinner-sm"); spinner.setAttribute("aria-hidden", "true"); score.append(spinner, document.createTextNode(item.id === currentPendingId(model) ? "đang đo" : "đang chờ")); }
      else score.textContent = "–";
      const label = el("span", undefined, "stop-label");
      label.append(document.createTextNode(item.label));
      if (numeric(item.width) && item.kind !== "summary") {
        label.append(document.createTextNode(" · "));
        const dims = el("span", undefined, "stop-dims");
        dims.append(document.createTextNode(String(item.width)), el("sup", "2"));
        label.append(dims);
      }
      if (item.changed) label.append(el("span", "đổi nhóm", "stop-change"));
      button.append(thumb, score, label);
      const description = [item.label, item.state === "measured" && numeric(item.score) ? scoreText(item.score) : item.state === "failed" ? "chưa đo" : slot ? "chưa chọn" : "đang chờ", item.changed ? "đổi nhóm" : null].filter(Boolean).join(", ");
      button.setAttribute("aria-label", description);
      button.title = description;
      if (!button.disabled) button.addEventListener("click", () => selectStop(item.id));
      return button;
    });
    $("track-stops").replaceChildren(...buttons);
  }

  function currentPendingId(model) {
    const pending = model.stops.find((item) => item.state === "pending" && !item.id.startsWith("slot-"));
    return pending?.id || null;
  }

  function renderRegionalCard(model) {
    const regional = regionalFor(model);
    const selected = !!regional && state.selectedId === "regional";
    $("regional-card").hidden = !selected;
    $("track-row").classList.toggle("has-regional", selected);
    $("track-card").classList.toggle("is-dimmed", selected);
    if (!selected) return;
    const url = sameOriginURL(regional.thumb);
    $("regional-image").hidden = !url;
    if (url) { $("regional-image").src = url; $("regional-image").alt = regional.lesson?.title || "Bản đồ bất thường TruFor trên ảnh gốc"; }
    $("regional-select").classList.toggle("selected", selected);
    $("regional-name").textContent = "vùng chỉnh sửa";
    $("regional-meta").textContent = regional.state === "measured" && numeric(regional.score) ? `TruFor · ${scoreText(regional.score)} · ảnh gốc` : "TruFor · ảnh gốc";
  }

  function setImage(node, url) {
    if (!url) { node.hidden = true; node.removeAttribute("src"); return; }
    if (node.getAttribute("src") !== url) node.src = url;
    node.hidden = false;
  }
  function setPlaceholder(node, title, detail, spinning = false) {
    node.replaceChildren();
    if (spinning) { const spinner = el("span", undefined, "spinner-sm"); spinner.setAttribute("aria-hidden", "true"); node.append(spinner); }
    node.append(el("span", title));
    if (detail) node.append(el("small", detail));
  }
  function stageStopFor(model) {
    const selected = model.stops.find((item) => item.id === state.selectedId) || null;
    if (selected?.kind !== "summary") return selected;
    const measured = model.stops.filter((item) => item.kind === "copy" && item.state === "measured");
    return measured.at(-1) || model.stops.find((item) => item.kind === "baseline") || selected;
  }

  function renderStage(model) {
    const body = $("stage-body");
    $("stage").dataset.mode = model.stage;
    const selected = model.stops.find((item) => item.id === state.selectedId) || null;
    const stop = stageStopFor(model);
    const regional = selected?.kind === "regional" ? selected : null;
    const empty = model.stage === "empty";
    const ready = model.stage === "ready";
    const originalURL = originalImageURL();
    if (state.lastStageId !== stop?.id) { viewer.reset(); state.lastStageId = stop?.id || null; }
    $("dropzone").hidden = !empty;
    $("original-image").alt = sourceName() ? `Ảnh gốc ${sourceName()}` : "Ảnh gốc đã tải lên";
    $("map-legend-left").hidden = true;
    $("map-legend-right").hidden = true;
    $("original-chip").textContent = "Ảnh gốc";
    $("stage-tools").hidden = true;
    $("stage-view").hidden = false;
    if (empty) {
      body.dataset.mode = "empty";
      body.dataset.view = "side";
      $("stage-title").textContent = "Ảnh gốc";
      $("stage-hint").textContent = "";
      setImage($("original-image"), null); setImage($("result-image"), null);
      viewer.applyView();
      return;
    }
    if (ready) {
      body.dataset.mode = "ready";
      $("stage-title").textContent = "Ảnh gốc";
      $("stage-hint").textContent = "Bản sao sẽ hiện sau khi đo";
      setImage($("original-image"), originalURL);
      $("original-empty").hidden = !!originalURL;
      setImage($("result-image"), null);
      $("result-empty").hidden = false;
      setPlaceholder($("result-empty"), "Bản sao", "Ảnh sau nén và đổi kích thước sẽ hiện ở đây");
      viewer.applyView();
      return;
    }
    const running = model.stage === "running";
    let mode = "side", title = "Ảnh gốc", hint = "", left = originalURL, right = null;
    $("result-chip").textContent = stop?.label || "Bản sao";
    if (regional) {
      mode = "regional"; title = "TruFor · ảnh gốc"; hint = "Bản đồ bất thường · Độ tin cậy định vị";
      const evidence = regionalEvidence();
      left = sameOriginURL(evidence?.overlay_url) || sameOriginURL(evidence?.heatmap_url) || originalURL;
      right = sameOriginURL(evidence?.reliability_url);
      $("map-legend-left").hidden = false; $("map-legend-right").hidden = false;
      $("map-legend-left").textContent = "xanh dương 0 → đỏ 1 · dấu hiệu chỉnh sửa";
      $("map-legend-right").textContent = "đen 0 → trắng 1 · độ tin cậy";
      $("stage-tools").hidden = false; $("stage-view").hidden = true;
    } else if (stop?.kind === "baseline") {
      mode = "single"; title = "Ảnh gốc"; hint = numeric(stop.score) ? `B-Free ${scoreText(stop.score)}` : running ? "Đang đo" : "Chưa có điểm";
      $("stage-tools").hidden = running; $("stage-view").hidden = true;
    } else if (stop) {
      mode = "side"; title = `Ảnh gốc → ${stop.label}`;
      right = sameOriginURL(stop.thumb);
      hint = running ? right ? `Đã đo · ${scoreText(stop.score)}` : "Chưa có kết quả đo" : stop.state === "failed" ? "Chưa đo" : "";
      $("stage-tools").hidden = running || !right; $("stage-view").hidden = false;
    }
    body.dataset.mode = mode;
    $("stage-title").textContent = title;
    $("stage-hint").textContent = hint;
    setImage($("original-image"), left);
    $("original-empty").hidden = !!left;
    setImage($("result-image"), right);
    $("result-empty").hidden = !!right;
    if (!right) {
      const pending = stop && stop.state === "pending";
      setPlaceholder($("result-empty"), pending ? "Đang chờ đo" : "Chưa có ảnh", pending ? "Bản sao này chưa có trong kết quả đo." : "Không có ảnh cho mốc này.", pending);
    }
    $("original-chip").textContent = regional ? "TruFor" : "Ảnh gốc";
    $("original-chip").hidden = !!regional;
    $("result-chip").hidden = !!regional;
    viewer.refresh();
  }

  function regionalEvidence() {
    if (state.report?.regional) return state.report.regional;
    return (state.investigation?.observations || []).find((item) => item.tool === "trufor") || null;
  }

  function railParagraph(label, text) {
    const paragraph = el("p");
    if (label) paragraph.append(el("strong", label), document.createTextNode(" "));
    paragraph.append(document.createTextNode(text));
    return paragraph;
  }
  function railList(items, className = "") {
    const list = el("ul", undefined, className);
    items.forEach((text) => list.append(el("li", text)));
    return list;
  }

  function setRail({ eyebrow = "", title = "", body = [], detail = "", note = "" } = {}) {
    $("rail-eyebrow").textContent = eyebrow;
    $("rail-eyebrow").hidden = !eyebrow;
    $("rail-title").textContent = title || "Thí nghiệm";
    $("rail-title").hidden = !title;
    $("rail-body").replaceChildren(...body);
    $("rail-body").hidden = !body.length;
    $("rail-detail").textContent = detail;
    $("rail-detail").hidden = !detail;
    $("rail-note").textContent = note;
    $("rail-note").hidden = !note;
    $("rail-steps").hidden = true;
    $("rail-progress").hidden = true;
    $("rail-actions").hidden = true;
    $("rail-run-wrap").hidden = true;
    $("rail-cancel").hidden = true;
  }

  function experimentSteps(config) {
    if (adaptiveMode()) {
      const budget = Number($("agent-budget").value) || 4;
      return [
        { lead: "B-Free đo ảnh gốc.", text: "Điểm này là mốc so sánh." },
        { lead: `Qwen chọn tối đa ${Math.max(0, budget - 1)} phép thử.`, text: "Mỗi phép thử là một nhánh riêng, bắt đầu từ ảnh gốc." },
        { lead: "Đo lại và so sánh.", text: "Xem mô hình còn phát hiện được ảnh AI không." },
      ];
    }
    const scale = Math.round(config.scale * 100);
    const operation = config.operation === "jpeg" ? `nén JPEG Q${config.quality}` : config.operation === "resize" ? `thu nhỏ ${scale}%` : `thu nhỏ ${scale}% rồi nén JPEG Q${config.quality}`;
    return [
      { lead: "B-Free đo ảnh gốc.", text: "Điểm này là mốc so sánh." },
      { lead: `Tạo ${config.rounds} bản sao.`, text: config.mode === "cumulative" ? `Mỗi vòng ${operation}, như khi đăng lên mạng.` : `Mỗi bản sao ${operation} trực tiếp từ ảnh gốc, như khi đăng lên mạng.` },
      { lead: "Đo lại và so sánh.", text: "Xem mô hình còn phát hiện được ảnh AI không." },
    ];
  }

  function renderSteps(config) {
    const steps = experimentSteps(config);
    $("rail-steps").replaceChildren(...steps.map((step, index) => {
      const item = el("li");
      item.append(el("span", String(index + 1), "step-number"));
      const text = el("span");
      text.append(el("strong", step.lead), document.createTextNode(` ${step.text}`));
      item.append(text);
      return item;
    }));
    $("rail-eyebrow").textContent = `THÍ NGHIỆM GỒM ${steps.length} BƯỚC`;
    $("rail-eyebrow").hidden = false;
    $("rail-steps").hidden = false;
  }

  function canRun() {
    if (!state.base64 || state.busy) return false;
    if (adaptiveMode()) return !!(state.status?.bfree?.available && state.status?.planner?.available);
    return true;
  }
  function runHelp() {
    if (!state.base64) return "Chọn ảnh để bắt đầu phân tích.";
    if (state.busy) return "Đang thu thập kết quả từ mô hình trên máy. Quá trình có thể mất vài phút.";
    if (adaptiveMode()) {
      if (!state.status?.planner?.available) return "Cần cài mô hình chọn phép thử để phân tích thích ứng.";
      if (!state.status?.bfree?.available) return "Cần cấu hình B-Free để bắt đầu phân tích.";
      return "AI có thể dừng trước khi dùng hết số lượt cho phép.";
    }
    if (!state.status?.bfree?.available) return "B-Free chưa sẵn sàng: vẫn đo được ảnh nhưng không có điểm AI.";
    return "Ảnh gốc và các bản sao sẽ được đo trong cùng phiên.";
  }

  function renderRunBlock() {
    $("rail-run-wrap").hidden = false;
    $("rail-run").disabled = !canRun();
    $("rail-run-label").textContent = state.busy ? "Đang chạy…" : "Phân tích ảnh";
    $("rail-run-spinner").hidden = !state.busy;
    $("rail-help").textContent = runHelp();
    $("rail-example").hidden = state.busy || !!state.report || !!state.investigation;
  }

  function progressRows(model) {
    const config = readConfig();
    const dims = sourceDimensions();
    const rows = model.stops.filter((item) => item.kind !== "summary" && !item.id.startsWith("slot-"));
    return rows.map((item) => {
      const row = el("li");
      row.classList.toggle("done", item.state === "measured");
      row.classList.toggle("current", item.state === "pending" && item.id === currentPendingId(model));
      const mark = el("span", undefined, "progress-mark");
      if (item.state === "measured") mark.textContent = "✓";
      else if (item.state === "pending" && item.id === currentPendingId(model)) mark.append(el("span", undefined, "spinner-sm"));
      row.append(mark);
      const label = el("span", undefined, "progress-label");
      if (item.kind === "baseline") {
        label.append(el("strong", "B-Free"), document.createTextNode(" đo ảnh gốc"));
      } else if (item.kind === "regional") {
        label.append(el("strong", "TruFor"), document.createTextNode(" · kiểm tra từng vùng"));
      } else if (adaptiveMode()) {
        label.append(el("strong", item.label), document.createTextNode(numeric(item.width) ? ` · ${item.width}²` : ""));
      } else {
        const round = item.id === "original" ? 0 : Number(item.id.split("-")[1]);
        const target = dims && round ? Math.round(dims.width * config.scale ** round) : null;
        const parts = [];
        if (config.operation !== "jpeg" && target) parts.push(`thu nhỏ ${target}²`);
        if (config.operation !== "resize") parts.push(`JPEG Q${config.quality}`);
        if (!parts.length) parts.push("bản sao");
        label.append(el("strong", `Vòng ${round}`), document.createTextNode(` · ${parts.join(" + ")}`));
      }
      const value = el("span", undefined, "progress-value");
      value.textContent = item.state === "measured" && numeric(item.score) ? scoreText(item.score) : item.state === "pending" ? item.id === currentPendingId(model) ? "đang đo" : "đang chờ" : "Chưa đo";
      row.append(label, value);
      return row;
    });
  }

  function renderProgress(model) {
    $("rail-progress").replaceChildren(...progressRows(model));
    $("rail-progress").hidden = false;
    $("rail-eyebrow").textContent = "TIẾN TRÌNH";
    $("rail-eyebrow").hidden = false;
    $("rail-title").hidden = true;
    $("rail-note").textContent = adaptiveMode()
      ? "Lượt đầu có thể lâu hơn vì cần nạp mô hình. Các phép đo đã xong được giữ lại nếu bạn dừng."
      : "Lượt đầu có thể lâu hơn vì cần nạp mô hình. Máy chủ trả kết quả một lần nên lần chạy này không thể dừng giữa chừng.";
    $("rail-note").hidden = false;
    $("rail-cancel").hidden = !adaptiveMode() || !state.busy || state.busyKind !== "investigation" || state.cancelRequested;
    $("rail-cancel").disabled = state.cancelRequested;
    $("rail-cancel").textContent = "Dừng sau lượt đang chạy";
  }

  function setActions(back, next) {
    $("rail-actions").hidden = !back && !next;
    $("rail-back").hidden = !back;
    $("rail-back").textContent = back?.label || "";
    $("rail-back").disabled = !back;
    $("rail-next").hidden = !next;
    $("rail-next").textContent = next?.label || "";
    $("rail-next").disabled = !next;
    $("rail-back").onclick = back ? back.action : null;
    $("rail-next").onclick = next ? next.action : null;
  }

  function linearNavigation(model) {
    const baseline = model.stops.find((item) => item.kind === "baseline");
    const copies = model.stops.filter((item) => item.kind === "copy" && !item.id.startsWith("slot-") && !item.id.startsWith("pending-"));
    const summary = model.stops.find((item) => item.kind === "summary");
    return [baseline, ...copies, summary].filter(Boolean);
  }

  function renderRail(model) {
    if (model.stage === "empty" || model.stage === "ready") {
      setRail({});
      renderSteps(readConfig());
      renderRunBlock();
      return;
    }
    if (model.stage === "running") {
      setRail({});
      renderProgress(model);
      return;
    }
    const selected = model.stops.find((item) => item.id === state.selectedId);
    if (!selected) { setRail({ eyebrow: "TÓM TẮT", title: "Chưa có mốc nào để xem." }); return; }
    const lesson = selected.lesson || {};
    const body = [];
    if (selected.kind === "summary") {
      (lesson.body || []).forEach((part) => body.push(railParagraph(part.label, part.text)));
      const summary = adaptiveMode() ? state.investigation?.summary : state.report?.summary;
      const warnings = Array.isArray(summary?.warnings) ? summary.warnings : [];
      if (warnings.length) {
        body.push(el("p", "Giới hạn của lần chạy này"));
        body.push(railList(warnings.map((warning) => translate(warning))));
      }
      const exports = exportsFor();
      const links = el("p");
      links.append(document.createTextNode("Tải kết quả: "));
      const available = [];
      for (const [label, url] of [["CSV ↓", exports.csv], ["JSON ↓", exports.json]]) {
        const safe = sameOriginURL(url);
        if (!safe) continue;
        const link = el("a", label); link.href = safe; link.download = ""; link.style.textDecoration = "underline";
        available.push(link);
      }
      available.forEach((link, index) => { if (index) links.append(document.createTextNode(" · ")); links.append(link); });
      if (available.length) body.push(links);
    } else if (selected.kind === "regional") {
      const evidence = regionalEvidence();
      const action = (lesson.body || [])[0];
      if (action) body.push(railParagraph(action.label, action.text));
      const warnings = Array.isArray(evidence?.warnings) ? evidence.warnings : [];
      if (warnings.length) body.push(railParagraph("Đọc cùng nhau:", warnings.map((warning) => translate(warning)).join(" ")));
    } else {
      (lesson.body || []).forEach((part) => body.push(railParagraph(part.label, part.text)));
    }
    setRail({ eyebrow: lesson.eyebrow || "", title: lesson.title || "", body, detail: lesson.detail || "", note: "" });
    const linear = linearNavigation(model);
    const index = linear.findIndex((item) => item.id === selected.id);
    let back = null, next = null;
    if (selected.kind === "regional") {
      const copies = model.stops.filter((item) => item.kind === "copy" && item.state === "measured");
      back = copies.at(-1) ? { label: `← ${copies.at(-1).label}`, action: () => selectStop(copies.at(-1).id) } : null;
      const summary = model.stops.find((item) => item.kind === "summary");
      if (summary) next = { label: "Tóm tắt →", action: () => selectStop(summary.id) };
    } else if (selected.kind === "summary") {
      const previous = linear[linear.length - 2];
      if (previous) back = { label: `← ${previous.label}`, action: () => selectStop(previous.id) };
    } else {
      const previous = index > 0 ? linear[index - 1] : null;
      if (previous) back = { label: `← ${previous.label}`, action: () => selectStop(previous.id) };
      const following = linear[index + 1];
      if (following?.kind === "copy") next = { label: `${following.label} →`, action: () => selectStop(following.id) };
      else {
        const summary = model.stops.find((item) => item.kind === "summary");
        const regional = regionalFor(model);
        if (summary && regional) next = { label: "Tóm tắt →", action: () => selectStop(summary.id) };
        else if (!regional && state.status?.trufor?.available) next = { label: "Kiểm tra riêng →", action: () => runRegional() };
        else if (summary) next = { label: "Tóm tắt →", action: () => selectStop(summary.id) };
      }
    }
    setActions(back, next);
  }

  function exportsFor() {
    if (adaptiveMode()) return { csv: state.investigation?.exports?.csv_url, json: state.investigation?.exports?.json_url };
    return { csv: state.report?.exports?.csv_url, json: state.report?.exports?.json_url };
  }

  function selectStop(id, options = {}) {
    if (!state.model) return;
    if (!state.model.stops.some((item) => item.id === id)) return;
    state.selectedId = id;
    renderAll();
    if (!options.silent) {
      const stop = state.model.stops.find((item) => item.id === id);
      announce(`Đang xem ${stop?.label || id}.`);
    }
  }

  function renderFollowups(model) {
    const source = adaptiveMode() ? state.investigation : state.report;
    $("technical-row").hidden = !source || state.busy;
    if ($("technical-row").hidden) return;
    $("followup-jpeg").hidden = adaptiveMode();
    $("followup-scale").hidden = adaptiveMode();
    const regional = regionalFor(model);
    const busyTitle = "Đang chạy một lần phân tích khác. Chờ hoàn tất rồi thử tiếp.";
    const hasBytes = !!state.base64 || !!originalImageURL();
    const derivedNote = !state.base64 && originalImageURL() ? " Dùng ảnh gốc đã chuẩn hóa được lưu cho phiên này." : "";
    $("followup-jpeg").disabled = state.busy || !hasBytes;
    $("followup-jpeg").title = $("followup-jpeg").disabled ? (hasBytes ? busyTitle : "Cần ảnh nguồn để chạy lại.") : `Chạy lại với chỉ nén JPEG Q${readConfig().quality}, giữ ${readConfig().rounds} vòng.${derivedNote}`;
    $("followup-scale").disabled = state.busy || !hasBytes;
    $("followup-scale").title = $("followup-scale").disabled ? (hasBytes ? busyTitle : "Cần ảnh nguồn để chạy lại.") : `Chạy lại với thu nhỏ 95% và nén JPEG Q${readConfig().quality}.${derivedNote}`;
    const truforReady = adaptiveMode() ? !!regional : state.status?.trufor?.available === true && !!state.report && !state.regionalBusy;
    $("followup-trufor").disabled = state.busy || !truforReady;
    $("followup-trufor").title = $("followup-trufor").disabled
      ? adaptiveMode() ? "Phiên thích ứng chỉ có TruFor khi AI chọn phép thử này." : "Cần TruFor và một thí nghiệm đã chạy để kiểm tra từng vùng."
      : regional || state.report?.regional?.status === "complete" ? "Mở kiểm tra TruFor đã có cho phiên này." : "Chạy TruFor trên ảnh gốc của phiên này; điểm TruFor tách riêng khỏi B-Free.";
    const exports = exportsFor();
    $("export-csv").hidden = !sameOriginURL(exports.csv);
    $("export-json").hidden = !sameOriginURL(exports.json);
    if (sameOriginURL(exports.csv)) $("export-csv").href = exports.csv;
    if (sameOriginURL(exports.json)) $("export-json").href = exports.json;
    $("download-csv").hidden = $("export-csv").hidden;
    $("download-json").hidden = $("export-json").hidden;
    $("download-csv").disabled = $("export-csv").hidden;
    $("download-json").disabled = $("export-json").hidden;
  }

  function renderPhoneBar(model) {
    const actions = $("rail-actions");
    const visible = !actions.hidden && (state.model?.stops.some((item) => item.id === state.selectedId));
    $("phone-bar").hidden = !visible;
    if (!visible) return;
    const back = $("rail-back"), next = $("rail-next");
    $("phone-back").hidden = back.hidden;
    $("phone-back").textContent = "←";
    $("phone-back").onclick = () => back.click();
    $("phone-next").hidden = next.hidden;
    $("phone-next").textContent = next.textContent;
    $("phone-next").onclick = () => next.click();
  }

  function renderAll() {
    const running = state.busy && state.busyKind !== "regional";
    const fixedVisible = state.report && !(state.busy && state.busyKind === "experiment");
    const model = ForensicsGuide.stopModel({
      report: adaptiveMode() ? null : fixedVisible ? state.report : null,
      investigation: adaptiveMode() ? state.investigation : null,
      config: { ...readConfig(), budget: Number($("agent-budget").value) },
      adaptive: adaptiveMode(),
      busy: running,
      hasFile: hasSource(),
      saved: isSaved(),
      availability: state.status,
      selectedId: state.selectedId,
      failed: state.failed,
      cancelRequested: state.cancelRequested,
      disconnected: state.disconnected,
    });
    state.model = model;
    if (!model.stops.some((item) => item.id === state.selectedId)) state.selectedId = model.selectedId;
    if (!state.selectedId) state.selectedId = model.selectedId;
    syncControls();
    updateConfig();
    renderHeader();
    renderAnswer(model);
    renderTrack(model);
    renderRegionalCard(model);
    renderStage(model);
    renderRail(model);
    renderTechnical();
    renderFollowups(model);
    renderPhoneBar(model);
  }

  function syncControls() {
    const busy = state.busy;
    form.querySelectorAll("input, select, button").forEach((control) => { control.disabled = busy; });
    const config = readConfig();
    const jpegOff = config.operation === "resize";
    const scaleOff = config.operation === "jpeg";
    $("quality-field").classList.toggle("disabled-field", jpegOff);
    $("scale-field").classList.toggle("disabled-field", scaleOff);
    $("quality").disabled = busy || jpegOff;
    $("scale").disabled = busy || scaleOff;
    $("order").disabled = busy || config.operation !== "combined";
    $("order-field").classList.toggle("disabled-field", config.operation !== "combined");
    $("allow-regional").disabled = busy || state.status?.trufor?.available !== true;
    $("settings-clear").disabled = busy || !hasSource();
    $("image-file").disabled = busy;
    $("other-file").disabled = busy;
    $("rail-run").disabled = busy || !canRun();
  }

  function updateConfig() {
    const config = readConfig();
    $("quality-value").textContent = String(config.quality);
    $("scale-value").textContent = `${Math.round(config.scale * 100)}%`;
    $("threshold-value").textContent = numberText(config.threshold, 2);
    $("threshold-summary").textContent = numberText(config.threshold, 2);
    $("mode-help").textContent = config.mode === "cumulative"
      ? "Mỗi vòng xử lý ảnh từ kết quả vòng trước, giữ lại tác động tích lũy."
      : "Mỗi vòng bắt đầu từ ảnh gốc, đổi trực tiếp về kích thước đích rồi nén JPEG một lần. Đối chứng chỉ nén JPEG có thể trùng nhau.";
    const roundLabels = Array.from({ length: config.rounds }, (_, i) => `V${i + 1}`);
    $("sequence").textContent = config.mode === "cumulative" ? `Gốc → ${roundLabels.join(" → ")}` : `Gốc → { ${roundLabels.join(", ")} }`;
    const parts = [`${config.rounds} vòng`];
    if (config.operation !== "resize") parts.push(`Q${config.quality}`);
    if (config.operation !== "jpeg") parts.push(`${Math.round(config.scale * 100)}% mỗi vòng`);
    $("sequence-detail").textContent = parts.join(" · ");
    $("config-chip-text").textContent = ForensicsGuide.configChip(chipConfig());
    $("file-chip-config").textContent = `${ForensicsGuide.configChip(chipConfig(), true)} · Đổi`;
    $("agent-tool-count").textContent = state.investigation ? `${state.investigation.model_tool_calls || 0} / ${state.investigation.config?.budget || $("agent-budget").value}` : `0 / ${$("agent-budget").value}`;
  }

  function setBusy(busy, kind = "experiment") {
    state.busy = busy;
    state.busyKind = busy ? kind : null;
    document.body.classList.toggle("is-busy", busy);
    document.body.dataset.busyKind = busy ? kind : "";
    form.setAttribute("aria-busy", String(busy));
  }

  function setModelState(key, info) {
    const available = info?.available === true;
    const badge = $("bfree-badge") && key === "bfree" ? $("bfree-badge") : $("trufor-badge");
    badge.textContent = available ? "SẴN SÀNG" : "CHƯA CẤU HÌNH";
    badge.classList.toggle("ready", available);
    badge.classList.toggle("offline", !available);
    if (key === "bfree") $("bfree-status").textContent = available ? "Sẵn sàng đo phản hồi của mô hình phát hiện ảnh AI." : `${translate(info?.reason) || "Chưa cấu hình trọng số mô hình."} Vẫn có thể biến đổi ảnh và đo sai khác điểm ảnh.`;
    else $("trufor-status").textContent = available ? "Sẵn sàng kiểm tra dấu hiệu chỉnh sửa trên ảnh gốc." : translate(info?.reason) || "Chưa cấu hình TruFor. Cần trọng số mô hình để tạo bản đồ vùng.";
    if (key === "trufor") $("regional-status").textContent = available ? "Chạy thí nghiệm trước, sau đó kiểm tra từng vùng trên ảnh gốc." : translate(info?.reason) || "Chưa cấu hình TruFor.";
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
      renderAll();
    } catch {
      showError("Không kết nối được với máy chủ trên máy này. Khởi động máy chủ rồi tải lại trang để kiểm tra mô hình.");
      $("bfree-status").textContent = "Không kết nối được với máy chủ trên máy này. Hãy khởi động máy chủ rồi tải lại trang.";
      $("trufor-status").textContent = "Chưa thể kiểm tra mô hình khi chưa kết nối được với máy chủ.";
      ["bfree-badge", "trufor-badge"].forEach((id) => { $(id).textContent = "MẤT KẾT NỐI"; $(id).classList.add("offline"); });
      $("planner-badge").textContent = "MẤT KẾT NỐI";
      $("planner-badge").classList.add("offline");
      $("planner-status").textContent = "Khởi động máy chủ rồi tải lại trang để kiểm tra mô hình chọn phép thử.";
      renderAll();
    }
  }

  async function chooseFile(file, allowBusy = false) {
    if (!file || (state.busy && !allowBusy)) return false;
    showError("");
    if (file.size > MAX_BYTES) { showError("Ảnh vượt quá 20 MiB. Hãy chọn tệp có dung lượng nhỏ hơn."); return false; }
    if (!/\.(jpe?g|png|webp)$/i.test(file.name) && !["image/jpeg", "image/png", "image/webp"].includes(file.type)) { showError("Hãy chọn ảnh JPEG, PNG hoặc WebP."); return false; }
    const generation = ++state.generation;
    const previousURL = state.objectURL;
    const objectURL = URL.createObjectURL(file);
    try {
      const size = await new Promise((resolve, reject) => {
        const image = new Image();
        image.onload = () => resolve({ width: image.naturalWidth, height: image.naturalHeight });
        image.onerror = () => reject(new Error("Trình duyệt không đọc được ảnh. Hãy chọn tệp JPEG, PNG hoặc WebP hợp lệ."));
        image.src = objectURL;
      });
      if (size.width * size.height > 20_000_000) throw new Error("Ảnh vượt quá 20 triệu điểm ảnh. Hãy thu nhỏ ảnh trước khi phân tích.");
      if (Math.min(size.width, size.height) < 16) throw new Error("Chiều rộng và chiều cao của ảnh phải từ 16 điểm ảnh trở lên.");
      const base64 = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(",")[1]);
        reader.onerror = () => reject(new Error("Không đọc được tệp đã chọn."));
        reader.readAsDataURL(file);
      });
      if (generation !== state.generation) { URL.revokeObjectURL(objectURL); return false; }
      if (previousURL) URL.revokeObjectURL(previousURL);
      state.file = file; state.base64 = base64; state.objectURL = objectURL;
      state.width = size.width; state.height = size.height;
      state.report = null; state.investigation = null; state.selectedId = null;
      state.example = false; state.savedInvestigation = false; state.failed = false;
      state.disconnected = false; state.cancelRequested = false;
      if (!allowBusy) setInvestigationURL(null);
      $("image-file").value = "";
      if ($("settings-dialog").open) $("settings-dialog").close();
      renderAll();
      announce(`Đã chọn ${file.name}, ${size.width} × ${size.height} điểm ảnh. Sẵn sàng chạy thí nghiệm.`);
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
    state.width = null; state.height = null;
    state.report = null; state.investigation = null; state.selectedId = null;
    state.example = false; state.savedInvestigation = false; state.failed = false;
    state.disconnected = false; state.cancelRequested = false;
    $("image-file").value = "";
    setInvestigationURL(null);
    renderAll();
    announce("Đã bỏ ảnh đã chọn.");
  }

  function renderMeasurements() {
    const report = state.report;
    $("measurements-panel").hidden = adaptiveMode() || !report;
    if (!report || adaptiveMode()) return;
    const threshold = numeric(report.config?.threshold) ? report.config.threshold : .5;
    const rows = (report.variants || []).map((variant) => {
      const row = el("tr"); row.dataset.variant = variant.id;
      const first = el("td");
      const button = el("button", variant.round === 0 ? "Ảnh gốc" : `Vòng ${variant.round}`, "row-variant-button"); button.type = "button";
      button.addEventListener("click", () => { const id = variant.id; selectStop(id); });
      first.append(button);
      let psnr = "Chưa có dữ liệu";
      if (numeric(variant.psnr_db)) psnr = `${numberText(variant.psnr_db, 2)} dB`;
      else if (variant.mse === 0) psnr = "∞ (trùng tham chiếu)";
      const scoreCell = el("td", numeric(variant.score) ? scoreText(variant.score) : "Chưa đo", numeric(variant.score) ? "score-cell" : undefined);
      if (variant.error) scoreCell.title = errorText(variant.error);
      row.append(first, scoreCell, el("td", numeric(variant.score) ? variant.score > threshold ? "Trên ngưỡng" : "Bằng / dưới ngưỡng" : "Chưa đo"), el("td", dimensions(variant) || "—"), el("td", psnr), el("td", numberText(variant.mse, 3)), el("td", bytesText(variant.bytes)));
      row.classList.toggle("selected", variant.id === state.selectedId);
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
    const warnings = Array.isArray(report.summary?.warnings) ? report.summary.warnings : [];
    $("warnings").replaceChildren(...warnings.map((warning) => el("li", translate(warning))));
    $("warnings-count").textContent = warnings.length ? `(${warnings.length})` : "";
    $("warnings-details").hidden = !warnings.length;
  }

  function evidenceLinks(ids) {
    const links = el("span", undefined, "evidence-links");
    for (const id of ids || []) {
      if (!/^E\d+$/.test(id)) continue;
      const link = el("a", id); link.href = `#agent-evidence-${id}`; link.setAttribute("aria-label", `Xem kết quả ${id}`); links.append(link);
    }
    return links;
  }

  function renderLedger() {
    const investigation = state.investigation;
    const observations = investigation?.observations || [];
    if (!investigation) {
      $("agent-state").textContent = "SẴN SÀNG";
      $("agent-state").classList.remove("agent-failed");
      $("agent-current-step").textContent = "Chọn ảnh, đặt giới hạn lượt gọi rồi bắt đầu phân tích.";
      $("agent-tool-count").textContent = `0 / ${$("agent-budget").value}`;
      $("agent-planner-count").textContent = "0";
      $("agent-runtime").textContent = "—";
      $("agent-conclusion").hidden = true;
      $("agent-error").hidden = true;
      $("agent-maps").hidden = true;
      $("agent-observations").replaceChildren(el("p", "Kết quả sẽ xuất hiện khi mỗi phép thử hoàn tất.", "agent-empty"));
      $("agent-decisions").replaceChildren(el("p", "Phép đo đầu tiên là bắt buộc. Các bước tiếp theo được chọn dựa trên kết quả đã có.", "agent-empty"));
      ["agent-run-id", "agent-source-hash", "agent-planner-name"].forEach((id) => { $(id).textContent = "—"; });
      return;
    }
    $("agent-state").textContent = statusNames[investigation.status || "running"] || "CHƯA RÕ TRẠNG THÁI";
    $("agent-state").classList.toggle("agent-failed", investigation.status === "error");
    $("agent-current-step").textContent = state.cancelRequested && investigation.status === "running" ? "Đã yêu cầu dừng. Hệ thống sẽ hoàn tất lượt đang chạy trước khi dừng." : translate(investigation.current_step) || "Đang chuẩn bị phân tích";
    $("agent-tool-count").textContent = `${investigation.model_tool_calls || 0} / ${investigation.config?.budget || $("agent-budget").value}`;
    $("agent-planner-count").textContent = String(investigation.planner_calls || 0);
    $("agent-runtime").textContent = elapsedText(investigation.runtime_seconds);
    $("agent-run-id").textContent = investigation.run_id || "—";
    $("agent-source-hash").textContent = investigation.image?.sha256 || "—";
    $("agent-planner-name").textContent = investigation.planner?.name || state.status?.planner?.name || "Mô hình chọn phép thử trên máy";
    const cards = observations.map((item) => {
      const card = el("article", undefined, "evidence-card"); card.id = `agent-evidence-${item.id}`; card.dataset.evidence = item.id;
      const heading = el("div", undefined, "evidence-card-heading"); heading.append(el("span", item.id, "evidence-id"), el("h4", toolName(item.tool))); card.append(heading);
      const kind = item.score_kind === "local_manipulation" ? "CHỈNH SỬA CỤC BỘ" : "DẤU HIỆU ẢNH AI";
      const reading = el("div", undefined, "evidence-reading"); reading.append(el("strong", numeric(item.score) ? scoreText(item.score) : "Chưa đo"), el("span", numeric(item.score) ? kind : "CHƯA CÓ ĐIỂM HỢP LỆ")); card.append(reading);
      if (numeric(item.delta_from_original)) {
        const delta = `${item.delta_from_original >= 0 ? "+" : ""}${numberText(item.delta_from_original, 4)}`;
        card.append(el("p", `${delta} so với ảnh gốc · ${item.decision_changed ? "đổi kết quả phân loại" : "giữ kết quả phân loại"}`, item.decision_changed ? "evidence-change changed" : "evidence-change"));
      }
      if (item.tool === "baseline") card.append(el("p", "Phép đo đầu tiên bắt buộc, được tính vào giới hạn lượt gọi.", "evidence-detail"));
      if (item.tool === "trufor") card.append(el("p", "Đánh giá khác với B-Free. Cần đọc cùng bản đồ độ tin cậy định vị.", "evidence-detail"));
      const detail = [];
      if (numeric(item.width)) detail.push(`${dimensions(item)} px`);
      if (numeric(item.psnr_db)) detail.push(`PSNR ${numberText(item.psnr_db, 2)} dB`);
      else if (item.mse === 0) detail.push("PSNR ∞");
      if (numeric(item.runtime_seconds)) detail.push(elapsedText(item.runtime_seconds));
      if (detail.length) card.append(el("p", detail.join(" · "), "evidence-detail"));
      if (item.error) card.append(el("p", errorText(item.error), "evidence-error"));
      if (sameOriginURL(item.preview_url)) {
        const button = el("button", "Đối chiếu ảnh ↗", "evidence-preview"); button.type = "button";
        button.addEventListener("click", () => { selectStop(item.tool === "trufor" ? "regional" : item.id); });
        card.append(button);
      }
      card.classList.toggle("selected", item.id === state.selectedId || item.tool === "trufor" && state.selectedId === "regional");
      return card;
    });
    $("agent-observations").replaceChildren(...(cards.length ? cards : [el("p", "Kết quả sẽ xuất hiện khi mỗi phép thử hoàn tất.", "agent-empty")]));
    const decisions = (investigation.decisions || []).map((choice) => {
      const card = el("article", undefined, "decision-card");
      card.dataset.decision = String(choice.step);
      card.append(el("span", `LỰA CHỌN ${choice.step}`, "micro-label"), el("h4", toolName(choice.action)));
      const context = el("p", "Kết quả đã có: ", "decision-context"); context.append(evidenceLinks(choice.evidence_ids)); card.append(context);
      card.append(el("p", `AI trên máy đã chọn${numeric(choice.runtime_seconds) ? ` trong ${elapsedText(choice.runtime_seconds)}` : ""}.`, "evidence-detail"));
      if (choice.action !== "finish" && investigation.status !== "running" && !observations.some((item) => item.tool === choice.action)) card.append(el("p", "Phiên đã dừng trước khi thực hiện phép thử được chọn này.", "evidence-change changed"));
      return card;
    });
    $("agent-decisions").replaceChildren(...(decisions.length ? decisions : [el("p", investigation.status === "running" ? "Phép đo đầu tiên là bắt buộc. Các bước tiếp theo được chọn dựa trên kết quả đã có." : "Chưa ghi nhận quyết định chọn phép thử.", "agent-empty")]));
    const summary = investigation.summary;
    $("agent-conclusion").hidden = !summary;
    if (summary) {
      $("agent-summary-title").textContent = translate(summary.title) || "Kết quả đã ghi nhận";
      $("agent-facts").replaceChildren(...(summary.facts || []).map((fact) => { const paragraph = el("p", translate(fact.text)); paragraph.append(evidenceLinks(fact.evidence_ids)); return paragraph; }));
      const reasons = { budget_exhausted: "Đã dùng hết số lượt gọi mô hình cho phép.", planner_finished: "AI đã chọn kết thúc phân tích.", cancelled: "Đã dừng theo yêu cầu của bạn.", planner_failed: "Mô hình chọn phép thử gặp lỗi; các kết quả đã có vẫn được giữ lại.", original_detector_failed: "Phép đo ảnh gốc gặp lỗi." };
      $("agent-stop").textContent = reasons[summary.stop_reason] || `Đã dừng: ${summary.stop_reason || "chưa rõ lý do"}.`;
      $("agent-warnings").replaceChildren(...(summary.warnings || []).map((warning) => el("li", translate(warning))));
    }
    const error = investigation.error || investigation.planner_error;
    $("agent-error").hidden = !error;
    $("agent-error").textContent = error ? errorText(error) : "";
    const region = observations.find((item) => item.tool === "trufor" && (item.heatmap_url || item.reliability_url));
    $("agent-maps").hidden = !region;
    if (region) {
      const figures = [];
      for (const [key, caption, legendKey] of [["heatmap_url", "Bất thường do chỉnh sửa", "heatmap_legend"], ["reliability_url", "Độ tin cậy định vị", "reliability_legend"], ["overlay_url", "Bản đồ chồng lên ảnh", null]]) {
        const url = sameOriginURL(region[key]); if (!url) continue;
        const figure = el("figure"); const link = el("a"); link.href = url; link.target = "_blank"; link.rel = "noopener noreferrer";
        link.setAttribute("aria-label", `Mở ảnh đầy đủ: ${caption}`);
        const image = el("img"); image.loading = "lazy"; image.src = url; image.alt = `${caption} của TruFor trên ảnh gốc`; link.append(image);
        const label = el("figcaption", `${region.id} · ${caption}`);
        const legend = legendKey && region.detector_evidence?.[legendKey]; if (legend) label.append(el("small", translate(legend)));
        figure.append(link, label); figures.push(figure);
      }
      $("agent-regional-images").replaceChildren(...figures);
    }
    $("ledger-panel").hidden = !state.investigation;
  }

  function renderRegionalPanel() {
    const evidence = regionalEvidence();
    const available = state.status?.trufor?.available === true;
    $("regional-panel").hidden = !evidence && !available;
    if (!evidence) {
      $("regional-status").textContent = available ? "Chưa có kiểm tra TruFor cho phiên này. Dùng nút Kiểm tra từng vùng để chạy trên ảnh gốc." : translate(state.status?.trufor?.reason) || "Chưa cấu hình TruFor.";
      $("regional-images").replaceChildren();
      $("regional-result-text").textContent = "";
      $("regional-warnings").replaceChildren();
      $("regional-warnings").hidden = true;
      return;
    }
    $("regional-status").textContent = evidence.status === "error" ? errorText(evidence.message) : translate(evidence.message) || "Đã hoàn tất kiểm tra từng vùng.";
    const figures = [];
    for (const [key, caption] of [["heatmap_url", "Bất thường do chỉnh sửa · TruFor"], ["reliability_url", "Độ tin cậy định vị · TruFor"], ["overlay_url", "Bản đồ bất thường chồng lên ảnh"]]) {
      const url = sameOriginURL(evidence[key]); if (!url) continue;
      const figure = el("figure"); const link = el("a"); link.href = url; link.target = "_blank"; link.rel = "noopener noreferrer"; link.setAttribute("aria-label", `Mở ảnh đầy đủ: ${caption}`);
      const image = el("img"); image.loading = "lazy"; image.src = url; image.alt = caption; link.append(image);
      const captionNode = el("figcaption", caption);
      const legend = key === "heatmap_url" ? evidence.heatmap_legend : key === "reliability_url" ? evidence.reliability_legend : null;
      if (legend) captionNode.append(el("small", translate(legend)));
      figure.append(link, captionNode); figures.push(figure);
    }
    $("regional-images").replaceChildren(...figures);
    const score = numeric(evidence.score) ? `Điểm chỉnh sửa toàn ảnh của TruFor: ${scoreText(evidence.score)}. ` : "";
    $("regional-result-text").textContent = `${score}${translate(evidence.message)} Điểm này tách riêng khỏi đường điểm B-Free.`;
    const warnings = Array.isArray(evidence.warnings) ? evidence.warnings : [];
    $("regional-warnings").replaceChildren(...warnings.map((warning) => el("li", translate(warning))));
    $("regional-warnings").hidden = !warnings.length;
  }

  function renderTechnical() {
    renderMeasurements();
    renderLedger();
    renderRegionalPanel();
    const exports = exportsFor();
    for (const [id, value] of [["export-csv", exports.csv], ["export-json", exports.json]]) {
      const url = sameOriginURL(value); $(id).hidden = !url; if (url) $(id).href = url;
    }
    $("measurements-open").disabled = !(state.report || state.investigation);
    $("ledger-open").disabled = !(state.investigation || state.report);
  }

  async function ensureSource() {
    if (state.base64) return true;
    const url = originalImageURL();
    if (!url) return false;
    try {
      const response = await fetch(url);
      if (!response.ok) return false;
      const bytes = new Uint8Array(await response.blob().arrayBuffer());
      let binary = "";
      for (const byte of bytes) binary += String.fromCharCode(byte);
      state.base64 = btoa(binary);
      state.derivedSource = true;
      return true;
    } catch { return false; }
  }

  async function runExperiment(event) {
    if (event) event.preventDefault();
    if (adaptiveMode()) return startInvestigation();
    if (state.busy) return;
    if (!state.base64 && !(await ensureSource())) { showError("Chưa có ảnh nguồn cho phiên này. Hãy chọn lại ảnh để chạy thử tiếp."); return; }
    const config = readConfig();
    const filename = sourceName() || "image";
    const previous = state.report;
    state.selectedId = null;
    setBusy(true, "experiment");
    showError("");
    announce("Đã bắt đầu thí nghiệm. Đang tạo biến thể và thu thập phản hồi mô hình.");
    renderAll();
    try {
      const report = await request("/api/analyze", { filename, image_base64: state.base64, ...config });
      state.report = report; state.example = false; state.savedInvestigation = false; state.failed = false;
      state.width = report.image?.width ?? state.width;
      state.height = report.image?.height ?? state.height;
      setInvestigationURL(null);
      setBusy(false);
      renderAll();
      const scores = (report.variants || []).filter((item) => numeric(item.score)).length;
      announce(`Thí nghiệm hoàn tất. Đã ghi ${(report.variants || []).length} phiên bản ảnh và ${scores} điểm số từ mô hình.`);
    } catch (error) {
      state.report = previous;
      state.failed = !previous;
      setBusy(false);
      showError(error.message || "Thí nghiệm gặp lỗi. Hãy kiểm tra máy chủ trên máy rồi thử lại.");
      announce("Không thể hoàn tất thí nghiệm.");
      renderAll();
    }
  }

  async function runRegional() {
    if (state.regionalBusy || state.busy) return;
    const existing = regionalEvidence();
    if (existing && sameOriginURL(existing.overlay_url || existing.heatmap_url)) { selectStop("regional"); announce("Đang xem kiểm tra TruFor đã có cho phiên này."); return; }
    if (!state.report || adaptiveMode()) return;
    const runID = state.report.run_id;
    state.regionalBusy = true;
    setBusy(true, "regional");
    $("regional-status").textContent = "TruFor đang kiểm tra ảnh gốc. Quá trình có thể mất vài phút.";
    renderAll();
    announce("Đã bắt đầu kiểm tra từng vùng.");
    try {
      const result = await request("/api/regional", { run_id: runID });
      if (state.report?.run_id !== runID) return;
      state.report.regional = result;
      state.selectedId = "regional";
      setBusy(false);
      renderAll();
      announce(translate(result.message) || "Đã hoàn tất kiểm tra từng vùng.");
    } catch (error) {
      if (state.report?.run_id === runID) {
        showError(`Kiểm tra từng vùng gặp lỗi: ${errorText(error.message)}`);
        announce("Không thể hoàn tất kiểm tra từng vùng.");
        setBusy(false);
        renderAll();
      }
    } finally { state.regionalBusy = false; }
  }

  // Viewer: shared zoom and pan, split slider, browser-computed difference map.
  const viewer = (() => {
    const body = $("stage-body");
    const frames = [$("original-stage"), $("result-stage")];
    const canvas = $("diff-canvas");
    const mobile = window.matchMedia("(max-width: 760px)");
    const zoomSteps = [1, 1.5, 2, 3, 4, 6, 8];
    const MAX_DIFF_SIDE = 2048;
    let view = "side", zoomIndex = 0, pan = { x: 0, y: 0 }, drag = null, diffKey = null, diffJob = 0;
    const zoom = () => zoomSteps[zoomIndex];
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
      $("zoom-reset").textContent = zoom() === 1 ? "Mặc định" : `${Math.round(zoom() * 100)}%`;
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
      const ready = body.dataset.view === "diff" && !original.hidden && !result.hidden && original.getAttribute("src") && result.getAttribute("src");
      canvas.hidden = !ready;
      if (!ready) return;
      const gain = Number($("diff-gain").value) || 8;
      const key = `${original.src}|${result.src}|${gain}`;
      if (key === diffKey) return;
      const job = ++diffJob;
      try { await Promise.all([original.decode(), result.decode()]); } catch { return; }
      if (job !== diffJob || body.dataset.view !== "diff") return;
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
    function applyView() {
      const compare = body.dataset.mode === "side";
      const current = compare ? mobile.matches ? "slider" : view : "side";
      body.dataset.view = current;
      document.querySelectorAll("#stage-view button").forEach((button) => button.setAttribute("aria-checked", String(button.dataset.view === view)));
      $("split-range").hidden = !compare || current !== "slider";
      $("split-handle").hidden = !compare || current !== "slider";
      $("diff-tools").hidden = !compare || current !== "diff";
      applyTransform();
    }
    function setView(next) { if (!mobile.matches) view = next; applyView(); computeDiff(); }
    function reset() { zoomIndex = 0; pan = { x: 0, y: 0 }; diffKey = null; applyTransform(); computeDiff(); }
    function refresh() { applyView(); computeDiff(); }
    document.querySelectorAll("#stage-view button").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
    $("zoom-in").addEventListener("click", () => setZoom(zoomIndex + 1));
    $("zoom-out").addEventListener("click", () => setZoom(zoomIndex - 1));
    $("zoom-reset").addEventListener("click", () => setZoom(0));
    $("split-range").addEventListener("input", (event) => body.style.setProperty("--split", `${event.target.value}%`));
    $("diff-gain").addEventListener("change", () => computeDiff());
    for (const frame of frames) {
      frame.addEventListener("wheel", (event) => {
        if (window.innerWidth < 1180 && !event.ctrlKey) return;
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
    window.addEventListener("resize", applyView);
    applyTransform();
    return { applyView, refresh, reset };
  })();

  // Dialogs and navigation
  const guide = $("guide-dialog");
  function openGuide(sectionID) {
    if (!guide.open) guide.showModal();
    const section = sectionID && $(sectionID);
    if (section) {
      section.scrollIntoView({ block: "start", behavior: "smooth" });
      section.classList.remove("flash"); void section.offsetWidth; section.classList.add("flash");
    }
  }
  function openDialog(dialog) { if (!dialog.open) dialog.showModal(); }
  $("guide-open").addEventListener("click", () => openGuide());
  $("guide-close").addEventListener("click", () => guide.close());
  guide.addEventListener("click", (event) => { if (event.target === guide) guide.close(); });
  document.addEventListener("click", (event) => {
    const target = event.target.closest?.("[data-guide]");
    if (target) openGuide(target.dataset.guide);
  });
  const settings = $("settings-dialog");
  function openSettings() { openDialog(settings); }
  $("file-chip").addEventListener("click", openSettings);
  $("config-chip").addEventListener("click", openSettings);
  $("settings-close").addEventListener("click", () => settings.close());
  $("settings-done").addEventListener("click", () => settings.close());
  settings.addEventListener("click", (event) => { if (event.target === settings) settings.close(); });
  const technical = $("technical-dialog");
  $("technical-close").addEventListener("click", () => technical.close());
  technical.addEventListener("click", (event) => { if (event.target === technical) technical.close(); });
  $("measurements-open").addEventListener("click", () => { openDialog(technical); (adaptiveMode() || !state.report ? $("ledger-panel") : $("measurements-panel")).scrollIntoView({ block: "start" }); });
  $("ledger-open").addEventListener("click", () => { openDialog(technical); $("ledger-panel").scrollIntoView({ block: "start" }); });

  $("other-file").addEventListener("click", () => $("image-file").click());
  $("image-file").addEventListener("change", (event) => chooseFile(event.target.files[0]));
  $("settings-clear").addEventListener("click", clearFile);
  $("rail-example").addEventListener("click", loadExample);
  form.addEventListener("submit", runExperiment);
  form.addEventListener("input", (event) => { if (event.target.id !== "image-file") { updateConfig(); renderAll(); } });
  form.addEventListener("change", (event) => {
    if (event.target.name === "workflow_mode") { state.selectedId = null; state.view = "side"; updateConfig(); renderAll(); }
    else if (event.target.id !== "image-file") { updateConfig(); renderAll(); }
  });
  $("rail-cancel").addEventListener("click", cancelInvestigation);
  $("regional-select").addEventListener("click", () => selectStop("regional"));
  $("followup-jpeg").addEventListener("click", async () => {
    if (state.busy) return;
    if (!(await ensureSource())) { showError("Chưa có ảnh nguồn cho phiên này. Hãy chọn lại ảnh để chạy thử tiếp."); return; }
    $("operation").value = "jpeg";
    updateConfig();
    runExperiment();
  });
  $("followup-scale").addEventListener("click", async () => {
    if (state.busy) return;
    if (!(await ensureSource())) { showError("Chưa có ảnh nguồn cho phiên này. Hãy chọn lại ảnh để chạy thử tiếp."); return; }
    $("operation").value = readConfig().operation === "resize" ? "resize" : "combined";
    $("scale").value = "95";
    updateConfig();
    runExperiment();
  });
  $("followup-trufor").addEventListener("click", () => {
    if (state.busy) return;
    if (adaptiveMode()) { const regional = regionalFor(state.model); if (regional) selectStop("regional"); return; }
    runRegional();
  });
  $("download-csv").addEventListener("click", () => $("export-csv").click());
  $("download-json").addEventListener("click", () => $("export-json").click());
  $("phone-back").addEventListener("click", () => $("rail-back").click());
  $("phone-next").addEventListener("click", () => $("rail-next").click());
  for (const id of ["dropzone", "settings-dropzone"]) {
    const zone = $(id);
    for (const type of ["dragenter", "dragover"]) zone.addEventListener(type, (event) => { event.preventDefault(); if (!state.busy) zone.classList.add("dragover"); });
    for (const type of ["dragleave", "drop"]) zone.addEventListener(type, (event) => { event.preventDefault(); zone.classList.remove("dragover"); });
    zone.addEventListener("drop", (event) => chooseFile(event.dataTransfer.files[0]));
  }

  document.addEventListener("keydown", (event) => {
    if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return;
    if (event.target.closest?.("input, select, textarea, dialog, [contenteditable]")) return;
    if (!state.model) return;
    const stops = state.model.stops.filter((item) => !item.id.startsWith("slot-"));
    const index = stops.findIndex((item) => item.id === state.selectedId);
    if (index < 0) return;
    let next = null;
    if (event.key === "ArrowLeft") next = stops[index - 1];
    else if (event.key === "ArrowRight") next = stops[index + 1];
    else return;
    if (next) {
      event.preventDefault();
      selectStop(next.id, { silent: true });
      document.querySelector(`[data-stop-id="${next.id}"]`)?.focus();
      announce(`Đang xem ${next.label}.`);
    }
  });

  function setWorkflowMode(mode) {
    form.elements.workflow_mode.value = mode;
    $("fixed-settings").hidden = mode === "adaptive";
    $("agent-settings").hidden = mode !== "adaptive";
  }
  async function loadExample() {
    if (state.busy) return;
    setWorkflowMode("fixed");
    state.selectedId = null;
    showError(""); setBusy(true, "example"); renderAll();
    announce("Đang mở ví dụ đã lưu.");
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
      state.report = example.report;
      state.example = true;
      state.savedInvestigation = false;
      state.selectedId = null;
      setBusy(false);
      renderAll();
      announce("Đã mở ví dụ được kiểm chứng. Đây là kết quả đã lưu trên ảnh mẫu chính thức, chưa có lượt suy luận mới.");
    } catch (error) {
      setBusy(false);
      showError(error.message || "Ví dụ đã lưu hiện không khả dụng.");
      renderAll();
    }
  }

  async function loadInvestigation(runID) {
    if (!/^[a-f0-9]{32}$/.test(runID)) { showError("Mã phiên phân tích đã lưu không hợp lệ."); return; }
    setWorkflowMode("adaptive");
    state.selectedId = null;
    setBusy(true, "saved");
    renderAll();
    try {
      const report = await request(`/api/investigations/${runID}`);
      state.savedRuns.add(runID);
      state.savedInvestigation = true;
      state.example = false;
      state.report = null;
      state.investigation = report;
      state.width = report.image?.width ?? null;
      state.height = report.image?.height ?? null;
      $("agent-budget").value = String(report.config?.budget || 4);
      $("allow-regional").checked = report.config?.allow_regional !== false;
      setInvestigationURL(runID);
      if (report.status === "running") {
        state.activeJob = { id: runID, url: `/api/investigations/${runID}`, generation: state.generation };
        setBusy(true, "investigation");
        await pollInvestigation();
      } else {
        setBusy(false);
        renderAll();
        announce("Đã mở phiên phân tích. Đây là kết quả đã lưu; chưa có lượt suy luận mới.");
      }
    } catch (error) { setBusy(false); showError(`Không mở được phiên đã lưu: ${errorText(error.message)}`); renderAll(); }
  }

  async function pollInvestigation() {
    if (!state.activeJob || state.monitoring) return;
    const job = state.activeJob;
    state.monitoring = true;
    state.disconnected = false;
    showError("");
    let previousStep = "";
    try {
      while (state.activeJob === job && state.generation === job.generation) {
        const report = await request(job.url);
        if (state.activeJob !== job || state.generation !== job.generation) return;
        if (!["running", "complete", "error", "cancelled"].includes(report.status)) throw new Error("Máy chủ trả về trạng thái phân tích chưa xác định.");
        state.investigation = report;
        state.savedInvestigation = true;
        state.savedRuns.add(report.run_id);
        renderAll();
        if (report.current_step !== previousStep) { announce(translate(report.current_step) || "Đã cập nhật phiên phân tích."); previousStep = report.current_step; }
        if (report.status !== "running") {
          state.activeJob = null;
          setBusy(false);
          renderAll();
          announce(`${report.status === "complete" ? "Phân tích hoàn tất" : report.status === "cancelled" ? "Đã dừng phân tích" : "Phiên phân tích kết thúc do lỗi"}. Đã ghi nhận ${report.observations?.length || 0} phép đo.`);
          return;
        }
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
    } catch (error) {
      if (state.activeJob === job) {
        showError(`Tạm dừng theo dõi: ${errorText(error.message)} Máy chủ có thể vẫn đang xử lý. Hãy tải lại trang để xem kết quả hiện tại.`);
        state.disconnected = true;
        renderAll();
        announce("Tạm dừng theo dõi. Hãy tải lại trang để kiểm tra phiên đang chạy.");
      }
    } finally { state.monitoring = false; }
  }

  async function startInvestigation() {
    if (!state.base64 || state.busy) return;
    const generation = state.generation;
    const budget = Number($("agent-budget").value);
    state.investigation = { status: "running", current_step: "Đang gửi ảnh tới máy chủ trên máy này", config: { budget }, observations: [], decisions: [] };
    state.selectedId = null;
    state.cancelRequested = false;
    state.savedInvestigation = false;
    state.example = false;
    setBusy(true, "investigation");
    showError("");
    renderAll();
    try {
      const response = await request("/api/investigate", { filename: sourceName() || "image", image_base64: state.base64, budget, allow_regional: $("allow-regional").checked && state.status?.trufor?.available === true });
      if (generation !== state.generation) return;
      const url = sameOriginURL(response.status_url);
      if (!url || !/^[a-f0-9]{32}$/.test(response.run_id || "")) throw new Error("Máy chủ trả về mã phiên phân tích không hợp lệ.");
      state.activeJob = { id: response.run_id, url, generation };
      setInvestigationURL(response.run_id);
      await pollInvestigation();
    } catch (error) {
      showError(error.message || "Không thể bắt đầu phân tích.");
      state.investigation = { status: "error", current_step: "Không thể bắt đầu phân tích", config: { budget }, observations: [], decisions: [], error: error.message };
      setBusy(false);
      renderAll();
    }
  }

  async function cancelInvestigation() {
    const job = state.activeJob;
    if (!job || state.cancelRequested) return;
    $("rail-cancel").disabled = true;
    try {
      await request(`/api/investigations/${job.id}/cancel`, {});
      if (state.activeJob !== job) return;
      state.cancelRequested = true;
      renderAll();
      announce("Đã yêu cầu dừng. Hệ thống sẽ hoàn tất lượt đang chạy trước khi dừng.");
      if (!state.monitoring) pollInvestigation();
    } catch (error) { showError(`Không gửi được yêu cầu dừng: ${errorText(error.message)}`); renderAll(); }
  }

  window.addEventListener("beforeunload", () => { if (state.objectURL) URL.revokeObjectURL(state.objectURL); });
  window.addEventListener("resize", () => { if (state.model) { renderTrack(state.model); renderPhoneBar(state.model); } });
  const initialQuery = new URLSearchParams(location.search);
  setWorkflowMode("fixed");
  updateConfig();
  renderAll();
  loadStatus();
  if (initialQuery.has("investigation")) loadInvestigation(initialQuery.get("investigation"));
  else if (initialQuery.get("example") === "1") loadExample();
})();

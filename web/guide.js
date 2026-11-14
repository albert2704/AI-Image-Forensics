"use strict";

((root) => {
  const validScore = (item) => !item?.error && typeof item?.score === "number" && Number.isFinite(item.score) && item.score >= 0 && item.score <= 1;
  const format = (value) => new Intl.NumberFormat("vi-VN", { minimumFractionDigits: 3, maximumFractionDigits: 3 }).format(value);
  const dimensions = (item) => Number.isFinite(item?.width) && Number.isFinite(item?.height) ? `${item.width} × ${item.height}` : null;
  const labels = { baseline: "Ảnh gốc", jpeg_q85_r1: "Nén một lần", jpeg_q85_r3: "Nén ba lần", "resize_s0.9_r1": "Thu nhỏ", "combined_q95_s0.9_r3": "Thu nhỏ + nén", trufor: "Vùng chỉnh sửa" };
  const card = (id, kind, title, text, extra = {}) => ({ id, kind, title, text, label: labels[id] || title, evidenceIds: [], previewId: null, targetId: "original-figure", score: null, baselineScore: null, lesson: null, ...extra });
  const isBaseline = (item, adaptive) => adaptive ? item.tool === "baseline" : item.id === "original" || item.round === 0;
  const decision = (score, threshold) => score > threshold ? "Trên mốc" : "Bằng hoặc dưới mốc";
  const plannerRole = "Qwen chọn phép thử tiếp theo từ các điểm đã đo. Nó không xem ảnh; lời dẫn ở đây được tính từ bản ghi kết quả.";
  const flow = ["Ảnh gốc", "B-Free đo", "Xử lý bản sao", "B-Free đo lại", "So sánh"];

  function operationsFor(item, source) {
    const operations = Array.isArray(item.operations) ? item.operations : [];
    const resizing = operations.filter((operation) => operation.type === "resize");
    const encoding = operations.filter((operation) => operation.type === "jpeg");
    const qualities = [...new Set(encoding.map((operation) => operation.quality).filter(Number.isFinite))];
    const details = [];
    if (dimensions(source) && dimensions(item)) details.push(`${dimensions(source)} → ${dimensions(item)} điểm ảnh`);
    if (resizing.length) details.push(`Đổi kích thước ${resizing.length} lần trong bước này`);
    if (encoding.length) details.push(`Nén JPEG ${encoding.length} lần${qualities.length ? ` · chất lượng ${qualities.map((value) => `${value}/100`).join(", ")}` : ""}`);
    const name = resizing.length && encoding.length ? "Thu nhỏ + nén JPEG" : resizing.length ? "Đổi kích thước" : encoding.length ? "Nén JPEG" : "Xử lý bản sao";
    return { name, details, jpeg: encoding.length > 0 };
  }

  function overview(adaptive, previewId = null) {
    return card("overview", "overview", "Ta đang kiểm tra điều gì?", "Ta kiểm tra độ ổn định của mô hình phát hiện ảnh AI khi cùng một ảnh được nén hoặc đổi kích thước.", {
      label: "Mục tiêu", previewId, flow,
      lesson: {
        purpose: "Cùng một ảnh, mô hình có giữ nguyên câu trả lời sau khi nén hoặc thu nhỏ?",
        action: "Giữ ảnh gốc, tạo bản sao đã xử lý, rồi cho B-Free đo cả hai.",
        meaning: "So sánh kết quả để biết mô hình nhạy với những thay đổi này đến đâu.",
      },
      model: { name: adaptive ? "Ai làm gì?" : "Bạn chọn phép thử", text: adaptive ? "B-Free chấm điểm ảnh. Qwen chọn phép thử từ điểm số, không xem ảnh. TruFor là kiểm tra vùng chỉnh sửa bổ sung." : "B-Free chấm điểm ảnh theo các phép thử bạn chọn. TruFor có thể kiểm tra vùng chỉnh sửa riêng." },
    });
  }

  function finishModel(steps, extra) {
    for (let i = 0; i < steps.length; i++) {
      const next = steps[i + 1];
      steps[i].nextLabel = !next ? "Đã xem hết" : next.kind === "baseline" ? "Xem B-Free đo ảnh gốc" : next.kind === "perturbation" ? `Xem ${next.label.toLocaleLowerCase("vi-VN")}` : next.kind === "regional" ? "Xem vùng chỉnh sửa" : next.kind === "finding" ? "Rút ra điều gì?" : "Xem bước tiếp theo";
    }
    return { steps, ...extra };
  }

  function build(input = {}) {
    const { report, adaptive = true, hasImage = false, busy = false, busyKind, saved = false, availability, disconnected = false, cancelRequested = false } = input;
    const origin = saved ? "Kết quả đã lưu · không chạy suy luận mới" : report ? "Phép đo của phiên này" : "Ảnh được xử lý trên máy này";
    if (!report) {
      const ready = overview(adaptive);
      ready.id = "intro"; ready.kind = "intro";
      ready.title = hasImage ? "Ảnh đã sẵn sàng cho thí nghiệm" : "Bắt đầu từ một ảnh";
      ready.text = hasImage ? "Bấm Phân tích ảnh để đo ảnh gốc và thử các bản sao đã xử lý." : "Chọn một ảnh hoặc mở ví dụ đã lưu để đi qua từng bước của thí nghiệm.";
      const unavailable = availability && (!availability.bfree?.available || adaptive && !availability.planner?.available);
      if (hasImage && unavailable) ready.text = "Mô hình cần cho chế độ này chưa sẵn sàng. Mở Thiết lập nâng cao; chế độ tự chọn vẫn xử lý ảnh nhưng không tạo điểm AI khi thiếu mô hình.";
      const reopening = ["example", "saved"].includes(busyKind);
      const pending = card("waiting", "status", reopening ? "Đang mở kết quả đã lưu" : "Đang chuẩn bị phép đo", reopening ? "Đọc lại ảnh và phép đo đã lưu; không chạy suy luận mới." : "Đang chuẩn bị đo ảnh gốc bằng B-Free. Lượt đầu có thể lâu hơn vì cần nạp mô hình.");
      return finishModel([busy ? pending : ready], { origin, sourceKey: "upload", finding: null, threshold: 0.5, initialStepId: busy ? "waiting" : "intro" });
    }

    const threshold = adaptive ? 0.5 : Number.isFinite(report.config?.threshold) ? report.config.threshold : 0.5;
    const items = adaptive ? report.observations || [] : [...(report.variants || []), ...(report.regional?.status === "complete" ? [{ ...report.regional, id: "regional", tool: "trufor", score_kind: "local_manipulation" }] : [])];
    const aiItems = items.filter((item) => item.tool !== "trufor" && (adaptive ? item.score_kind === "ai_generation" || item.tool === "baseline" : true));
    const baseline = aiItems.find((item) => isBaseline(item, adaptive));
    const baselineValid = validScore(baseline);
    const successful = aiItems.filter(validScore);
    const derivatives = successful.filter((item) => !isBaseline(item, adaptive));
    const failed = items.filter((item) => item.error || item.tool !== "trufor" && !validScore(item));
    const steps = baselineValid ? [overview(adaptive, baseline.id)] : [];

    for (const [index, item] of items.entries()) {
      const regional = item.tool === "trufor";
      const original = isBaseline(item, adaptive);
      const label = regional ? "Vùng chỉnh sửa" : original ? "Ảnh gốc" : adaptive ? labels[item.tool] || "Bản sao" : `Vòng ${item.round ?? index}`;
      const common = { label, evidenceIds: [item.id], previewId: regional ? baselineValid ? baseline.id : null : item.id, targetId: original ? "original-figure" : regional ? "narrator-regional" : "result-figure", baselineScore: baselineValid ? baseline.score : null };
      if (!validScore(item)) {
        steps.push(card(item.id, "status", `${label}: chưa có điểm hợp lệ`, "Lượt đo chưa tạo được kết quả hợp lệ. Phần thiếu được giữ trống, không thay bằng điểm 0.", common));
        continue;
      }
      if (regional) {
        const evidence = item.detector_evidence || item;
        steps.push(card(item.id, "regional", "Ảnh có dấu hiệu chỉnh sửa ở đâu?", `TruFor trả về điểm chỉnh sửa ${format(item.score)}. Điểm này tách riêng với B-Free.`, {
          ...common, score: item.score,
          lesson: { purpose: "Kiểm tra vùng có dấu hiệu chỉnh sửa là một câu hỏi bổ sung.", action: "TruFor phân tích ảnh gốc để tạo bản đồ bất thường và độ tin cậy định vị.", meaning: "Vùng được tô màu gợi ý dấu hiệu chỉnh sửa, không xác định điểm ảnh do AI tạo." },
          model: { name: "TruFor · kiểm tra vùng chỉnh sửa", text: "Mô hình tìm các dấu vết và sự không nhất quán trong ảnh. Chỉnh sửa thông thường cũng có thể để lại dấu vết." },
          maps: { overlay: item.overlay_url || item.heatmap_url, reliability: item.reliability_url },
          legends: [evidence.heatmap_legend, evidence.reliability_legend].filter((value) => typeof value === "string" && value),
        }));
        continue;
      }
      const currentDecision = decision(item.score, threshold);
      if (original) {
        steps.push(card(item.id, "baseline", "B-Free đánh giá ảnh gốc thế nào?", `Điểm ảnh gốc là ${format(item.score)}: ${currentDecision.toLocaleLowerCase("vi-VN")} ${format(threshold)}.`, {
          ...common, score: item.score, decision: currentDecision,
          lesson: { purpose: "Cần một phép đo ban đầu làm mốc so sánh cho các bản sao.", action: "B-Free dùng mô hình đã huấn luyện để chấm ảnh gốc; ảnh tải lên không dùng để huấn luyện lại.", meaning: "Điểm gần 1 là tín hiệu AI mạnh hơn theo mô hình, không phải xác suất nguồn gốc ảnh." },
          model: { name: "B-Free · phát hiện ảnh AI", text: "Mô hình đã học các mẫu từ ảnh thật và ảnh AI. Nó đưa ra điểm cho toàn ảnh." },
        }));
        continue;
      }
      const changed = baselineValid && (item.score > threshold) !== (baseline.score > threshold);
      const previous = aiItems[aiItems.indexOf(item) - 1];
      const chained = !adaptive && report.config?.mode !== "independent" && previous && !isBaseline(previous, adaptive);
      const source = chained ? previous : baseline || report.image;
      const operations = operationsFor(item, source);
      const history = adaptive ? "Phép thử này là một nhánh riêng bắt đầu từ ảnh gốc." : chained ? "Vòng này tiếp tục xử lý ảnh của vòng trước." : "Bản sao này được xử lý trực tiếp từ ảnh gốc.";
      const comparison = baselineValid ? `Điểm đổi từ ${format(baseline.score)} thành ${format(item.score)}; ${changed ? "mô hình đã đổi nhóm đánh giá" : "mô hình vẫn giữ cùng nhóm đánh giá"}.` : `Bản sao được ${format(item.score)}; thiếu điểm gốc để so sánh.`;
      steps.push(card(item.id, "perturbation", operations.name, `${comparison} ${history}`, {
        ...common, score: item.score, decision: currentDecision, changed,
        lesson: { purpose: "Ảnh khi chia sẻ có thể bị nén hoặc đổi kích thước; ta thử tác động đó trên một bản sao.", action: operations.details.length ? operations.details.join(". ") + "." : "Đã xử lý bản sao theo điều kiện của lần chạy này.", meaning: !baselineValid ? "Cần điểm gốc hợp lệ để biết mô hình còn phát hiện được ảnh AI không." : changed ? "Ảnh vẫn có cùng nguồn gốc; câu trả lời của mô hình đã đổi." : "Ảnh vẫn có cùng nguồn gốc; mô hình giữ cùng nhóm trong phép thử này." },
        transformation: { ...operations, from: dimensions(source), to: dimensions(item), history },
      }));
    }

    const running = adaptive && report.status === "running";
    if (running) {
      const text = disconnected ? "Kết nối theo dõi bị gián đoạn. Máy chủ có thể vẫn đang xử lý. Dùng Kết nối lại để biết trạng thái mới nhất." : cancelRequested ? "Đã yêu cầu dừng. Mô hình sẽ hoàn tất lượt đang chạy trước khi dừng; các phép đo đã có vẫn được giữ." : !items.length ? "B-Free đang đọc ảnh gốc. Chưa có điểm để diễn giải." : plannerRole;
      steps.push(card("running", "status", disconnected ? "Cần kết nối lại" : cancelRequested ? "Đang chờ dừng an toàn" : !items.length ? "Đang đo ảnh gốc" : "Đang chọn và chạy phép thử", text, { label: "Đang chạy", targetId: "guide-panel" }));
    }

    let finding = null;
    if (!running) {
      const flips = baselineValid ? derivatives.filter((item) => (item.score > threshold) !== (baseline.score > threshold)) : [];
      const partial = adaptive && report.status !== "complete" || failed.length > 0;
      const stopped = adaptive && report.status === "cancelled" ? "Bạn đã dừng phiên. " : adaptive && report.status === "error" ? "Phiên gặp lỗi và đã dừng. " : "";
      let title = "Chưa đủ phép đo để đánh giá độ ổn định";
      let text = "Cần điểm hợp lệ của ảnh gốc và ít nhất một bản sao đã xử lý. Các lượt thiếu hoặc lỗi không được dùng để kết luận.";
      let meaning = "Chưa thể đánh giá độ ổn định khi thiếu điểm so sánh.";
      if (baselineValid && derivatives.length) {
        title = flips.length ? "Xử lý ảnh đã làm đổi câu trả lời" : baseline.score > threshold ? "Tín hiệu cao vẫn giữ qua các phép thử" : "Chưa thấy tín hiệu cao trong các phép thử";
        text = flips.length ? `${flips.length} trong ${derivatives.length} bản sao đổi phía so với ảnh gốc tại mốc ${format(threshold)}.` : `Ảnh gốc và ${derivatives.length} bản sao đã đo đều ${baseline.score > threshold ? "trên" : "bằng hoặc dưới"} mốc ${format(threshold)}.`;
        meaning = flips.length ? "Ảnh vẫn có cùng nguồn gốc; câu trả lời của mô hình đã đổi." : "Mô hình giữ cùng nhóm trong các phép thử này; điều đó chưa xác nhận nguồn gốc ảnh.";
      }
      const representative = flips[0] || derivatives.at(-1) || (baselineValid ? baseline : null);
      finding = card("finding", "finding", title, `${stopped}${text}${partial ? " Đây là kết quả một phần." : ""} Điểm cao hay thấp đều chưa xác nhận nguồn gốc ảnh.`, {
        label: "Bài học", evidenceIds: successful.map((item) => item.id), targetId: "guide-finding", previewId: representative?.id || null, score: representative?.score ?? null, baselineScore: baselineValid ? baseline.score : null,
        decision: representative ? decision(representative.score, threshold) : null, partial, flips: baselineValid && derivatives.length ? flips.length : null,
        lesson: { purpose: "Ta đang đánh giá độ ổn định của B-Free qua những phép xử lý đã thử.", action: baselineValid ? `Đã đo ảnh gốc và ${derivatives.length} bản sao có điểm hợp lệ.` : "Chưa có phép đo ảnh gốc hợp lệ.", meaning },
      });
      steps.push(finding);
    }
    const interrupted = adaptive && ["error", "cancelled"].includes(report.status);
    const initialStepId = running ? disconnected || cancelRequested ? "running" : [...steps].reverse().find((step) => ["baseline", "perturbation", "regional"].includes(step.kind))?.id || "running" : baselineValid && !interrupted ? "overview" : finding.id;
    return finishModel(steps, { origin, sourceKey: `${adaptive ? "adaptive" : "fixed"}:${report.run_id || "pending"}`, finding, threshold, initialStepId });
  }
  function previewLabel(item) {
    if (item.tool === "baseline" || item.id === "original" || item.round === 0) return "Ảnh gốc";
    const operations = item.operations || [];
    const resize = operations.some((operation) => operation.type === "resize");
    const jpeg = operations.some((operation) => operation.type === "jpeg");
    return resize && jpeg ? "Bản đổi cỡ + nén" : resize ? "Bản đổi kích thước" : jpeg ? "Bản nén JPEG" : "Bản sao đã xử lý";
  }
  const valid = (item) => !item?.error && typeof item?.score === "number" && Number.isFinite(item.score) && item.score >= 0 && item.score <= 1;
  const isRegional = (item) => item?.tool === "trufor" || item?.score_kind === "local_manipulation" || item?.kind === "regional";
  const percent = (value) => Math.round((Number.isFinite(value) ? value : 0) * 100);
  const psnrText = (value) => new Intl.NumberFormat("vi-VN", { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(value);
  const quality = (value) => Number.isFinite(value) ? `Q${value}` : "";
  const toolLabels = { "jpeg_q85_r1": "Nén một lần", "jpeg_q85_r3": "Nén ba lần", "resize_s0.9_r1": "Thu nhỏ", "resize_s0.9_r3": "Thu nhỏ hai lần", "combined_q95_s0.9_r3": "Thu nhỏ + nén" };
  const toolShorts = { baseline: "Gốc", "jpeg_q85_r1": "JPEG", "jpeg_q85_r3": "JPEG×3", "resize_s0.9_r1": "Thu nhỏ", "resize_s0.9_r3": "Thu nhỏ×2", "combined_q95_s0.9_r3": "Kết hợp" };

  function configChip(config = {}, compact = false) {
    if (config.workflow === "adaptive") {
      const budget = Number.isFinite(config.budget) ? config.budget : 4;
      return compact ? `Qwen chọn phép thử · ${budget} lượt` : `Qwen chọn phép thử · tối đa ${budget} lượt`;
    }
    const rounds = Number.isFinite(config.rounds) ? config.rounds : 3;
    const operation = config.operation === "jpeg" ? `Chỉ nén JPEG ${quality(config.quality)}`
      : config.operation === "resize" ? `Chỉ thu nhỏ ${percent(config.scale)}%`
        : `Thu nhỏ ${percent(config.scale)}% + JPEG ${quality(config.quality)}`;
    const mode = config.mode === "independent" ? "đối chứng một lượt" : "nối tiếp";
    return compact ? `${operation} · ${rounds} vòng` : `${operation} · ${rounds} vòng ${mode}`;
  }

  function plannedStops(config = {}) {
    const rounds = Number.isFinite(config.rounds) ? config.rounds : 3;
    return ["original", ...Array.from({ length: Math.max(0, rounds) }, (_, index) => `round-${index + 1}`)];
  }

  function trackCounts(items = [], threshold = .5) {
    let weak = 0, strong = 0;
    for (const item of items) {
      if (isRegional(item) || item.kind === "summary" || !valid(item)) continue;
      if (item.score > threshold) strong++;
      else weak++;
    }
    return { weak, strong };
  }

  function operationLabel(item = {}, source = null) {
    const operations = Array.isArray(item.operations) ? item.operations : [];
    const resizing = operations.filter((operation) => operation.type === "resize");
    const encoding = operations.filter((operation) => operation.type === "jpeg");
    const qualities = [...new Set(encoding.map((operation) => operation.quality).filter(Number.isFinite))];
    const name = resizing.length && encoding.length ? "Thu nhỏ + nén JPEG" : resizing.length ? "Thu nhỏ" : encoding.length ? "Nén JPEG" : "Xử lý bản sao";
    const detail = [];
    if (Number.isFinite(item?.width)) detail.push(Number.isFinite(source?.width) ? `${source.width}² → ${item.width}²` : `${item.width}²`);
    if (qualities.length) detail.push(`JPEG ${qualities.map((value) => `Q${value}`).join("/")}`);
    const short = [];
    if (resizing.length) short.push(Number.isFinite(item?.width) ? `thu nhỏ ${item.width}²` : "thu nhỏ");
    if (encoding.length) short.push(qualities.length ? `JPEG Q${qualities.join("/")}` : "JPEG");
    if (!short.length) short.push("bản sao");
    return { name, short: short.join(" + "), detail: detail.join(" · "), dimensions: Number.isFinite(item?.width) ? item.width : null, quality: qualities.length ? qualities[0] : null, jpeg: encoding.length > 0 };
  }
  function answerFor(items = [], threshold = .5, mode = "fixed", status = "complete", reason = "") {
    const adaptive = mode === "adaptive";
    const noun = adaptive ? "phép thử" : "bản sao";
    const caution = "Điểm số chưa phải kết luận về nguồn gốc ảnh.";
    const prefix = status === "cancelled" ? "Phiên đã dừng. " : status === "error" ? "Phiên gặp lỗi. " : status === "partial" ? "Kết quả một phần. " : "";
    const lead = reason ? `${reason} ` : "";
    const scored = items.filter((item) => !isRegional(item) && item.kind !== "summary" && valid(item));
    const baseline = scored.find((item) => item.kind === "baseline" || item.id === "original" || item.tool === "baseline" || item.round === 0);
    if (!baseline) {
      return { tone: status === "error" ? "danger" : "warn", title: `${prefix}Chưa có điểm ảnh gốc.`, detail: `${lead}Chưa thể so sánh vì thiếu điểm hợp lệ của ảnh gốc. ${caution}` };
    }
    const copies = scored.filter((item) => item !== baseline);
    if (!copies.length) {
      return { tone: "warn", title: `${prefix}Chưa đủ ${noun} để so sánh.`, detail: `${lead}Ảnh gốc được ${format(baseline.score)}; cần ít nhất một ${noun} có điểm hợp lệ. ${caution}` };
    }
    const changed = copies.filter((item) => typeof item.changed === "boolean" ? item.changed : (item.score > threshold) !== (baseline.score > threshold));
    const flips = changed.length, total = copies.length;
    let tone = "info";
    let title;
    if (!flips) title = `Không. Cả ${total} ${noun} giữ nguyên nhóm.`;
    else if (flips === total) {
      tone = "warn";
      title = baseline.score > threshold ? `Có. Cả ${total} ${noun} xuống dưới ngưỡng.` : `Có. Cả ${total} ${noun} vượt ngưỡng.`;
    } else {
      tone = "warn";
      title = `Có. ${flips} trong ${total} ${noun} đổi nhóm.`;
    }
    let detail;
    if (flips) {
      const first = changed[0];
      const rising = first.score > baseline.score;
      const when = adaptive ? `Ở phép thử «${first.label || "đã chọn"}», ` : `Sau ${Number.isFinite(first.round) ? first.round : 1} vòng, `;
      detail = `${when}điểm ${rising ? "tăng" : "rơi"} từ ${format(baseline.score)} ${rising ? "lên" : "xuống"} ${format(first.score)}.`;
    } else {
      const scores = scored.map((item) => item.score);
      detail = `Điểm cao nhất ${format(Math.max(...scores))}, thấp nhất ${format(Math.min(...scores))}; mô hình giữ nguyên nhóm.`;
    }
    return { tone, title: `${prefix}${title}`, detail: `${lead}${detail} ${caution}` };
  }

  function lessonFor(step, eyebrow, title, detail, tone) {
    if (!step?.lesson && !title) return null;
    return {
      eyebrow, title: title || step?.title || "",
      body: step?.lesson ? [
        { label: "Ta làm gì:", text: step.lesson.action },
        { label: "Nghĩa là:", text: step.lesson.meaning },
      ] : [],
      detail: detail || null, tone: tone || "info",
    };
  }
  const stop = (fields) => ({ id: null, kind: "copy", label: "", short: "", score: null, width: null, height: null, thumb: null, changed: false, state: "pending", lesson: null, ...fields });
  const plannedFixedStops = (config) => plannedStops(config).map((id, index) => stop({
    id, kind: index === 0 ? "baseline" : "copy", label: index === 0 ? "Ảnh gốc" : `Vòng ${index}`, short: index === 0 ? "Gốc" : `V${index}`,
  }));

  // One ordered stop list drives the track, the stage, the rail and prev/next.
  function stopModel(input = {}) {
    const { report = null, investigation = null, config = {}, adaptive = false, busy = false, cancelRequested = false, disconnected = false, saved = false, availability, selectedId = null, failed = false } = input;
    const source = adaptive ? investigation : report;
    const threshold = Number.isFinite(source?.config?.threshold) ? source.config.threshold : adaptive ? .5 : Number.isFinite(config.threshold) ? config.threshold : .5;
    const guide = build({ report: source, adaptive, hasImage: !!input.hasFile, busy, saved, availability, disconnected, cancelRequested });
    const steps = new Map(guide.steps.map((step) => [step.id, step]));
    const stops = [];

    if (adaptive) {
      const observations = investigation?.observations || [];
      const measured = observations.filter((item) => !isRegional(item));
      const baseline = measured.find((item) => item.tool === "baseline");
      const baselineValid = valid(baseline);
      measured.forEach((item, index) => {
        const isBaseline = item === baseline;
        const validItem = valid(item);
        const score = validItem ? item.score : null;
        const changed = !isBaseline && validItem && baselineValid && (score > threshold) !== (baseline.score > threshold);
        const label = isBaseline ? "Ảnh gốc" : toolLabels[item.tool] || "Phép thử";
        const step = steps.get(item.id);
        const detail = Number.isFinite(item.width) ? `${item.width}²${Number.isFinite(item.psnr_db) ? ` · PSNR ${psnrText(item.psnr_db)} dB` : ""}` : null;
        stops.push(stop({
          id: item.id, kind: isBaseline ? "baseline" : "copy", label, short: isBaseline ? "Gốc" : toolShorts[item.tool] || "Thử", score,
          width: Number.isFinite(item.width) ? item.width : null, height: Number.isFinite(item.height) ? item.height : null,
          thumb: item.preview_url || null, changed, state: validItem ? "measured" : "failed",
          lesson: lessonFor(step, isBaseline ? "ẢNH GỐC" : `PHÉP THỬ · ${label.toUpperCase()}`, isBaseline ? null : changed ? "Phép thử này đã làm mô hình đổi nhóm đánh giá." : "Phép thử này giữ nguyên nhóm đánh giá.", detail, changed ? "warn" : "info"),
          error: item.error || null,
        }));
      });
      if (investigation?.status === "running") {
        const action = /^Running (\S+)$/.exec(investigation.current_step || "")?.[1];
        if (action && action !== "finish" && action !== "trufor" && !observations.some((item) => item.tool === action)) {
          stops.push(stop({ id: `pending-${action}`, label: toolLabels[action] || "Phép thử", short: toolShorts[action] || "Thử" }));
        }
        const budget = Number.isFinite(investigation.config?.budget) ? investigation.config.budget : Number.isFinite(config.budget) ? config.budget : 4;
        for (let index = observations.length + (stops.some((item) => item.id.startsWith("pending-")) ? 1 : 0); index < budget; index++) {
          stops.push(stop({ id: `slot-${index}`, label: "Chưa chọn", short: "Chờ" }));
        }
      }
    } else if (report?.variants?.length) {
      const variants = report.variants;
      const baseline = variants.find((item) => item.id === "original" || item.round === 0) || variants[0];
      const baselineValid = valid(baseline);
      const chainedMode = report.config?.mode !== "independent";
      variants.forEach((item, index) => {
        const isBaseline = item === baseline;
        const validItem = valid(item);
        const score = validItem ? item.score : null;
        const previous = variants[index - 1];
        const sourceItem = chainedMode && !isBaseline && previous && previous.round > 0 ? previous : baseline;
        const operation = isBaseline ? null : operationLabel(item, sourceItem);
        const step = steps.get(item.id);
        const changed = !isBaseline && validItem && baselineValid && (score > threshold) !== (baseline.score > threshold);
        const dimensions = isBaseline ? Number.isFinite(item.width) ? `${item.width}²` : null : Number.isFinite(item.width) && Number.isFinite(sourceItem?.width) ? `${sourceItem.width}² → ${item.width}²` : Number.isFinite(item.width) ? `${item.width}²` : null;
        const psnr = Number.isFinite(item.psnr_db) ? `PSNR ${psnrText(item.psnr_db)} dB` : item.mse === 0 ? "PSNR ∞" : null;
        stops.push(stop({
          id: item.id, kind: isBaseline ? "baseline" : "copy", label: isBaseline ? "Ảnh gốc" : `Vòng ${item.round ?? index}`,
          short: isBaseline ? "Gốc" : `V${item.round ?? index}`, score,
          width: Number.isFinite(item.width) ? item.width : null, height: Number.isFinite(item.height) ? item.height : null,
          thumb: item.preview_url || null, changed, state: validItem ? "measured" : "failed",
          lesson: lessonFor(step,
            isBaseline ? "ẢNH GỐC" : `VÒNG ${item.round ?? index} · ${(operation?.name || "Bản sao").toUpperCase()}`,
            isBaseline ? null : changed ? (index === 1 ? `${operation?.name || "Bản sao"} đã đủ để mô hình đổi nhóm đánh giá.` : `Vòng ${item.round ?? index} đã làm mô hình đổi nhóm đánh giá.`) : "Bản sao này giữ nguyên nhóm đánh giá.",
            [dimensions, psnr].filter(Boolean).join(" · ") || null, changed ? "warn" : "info"),
          error: item.error || null,
        }));
      });
    } else {
      stops.push(...plannedFixedStops(config));
    }

    const regionalResult = adaptive ? (investigation?.observations || []).find(isRegional) : report?.regional?.status === "complete" || report?.regional?.status === "error" ? report.regional : null;
    if (regionalResult) {
      const maps = regionalResult.overlay_url || regionalResult.heatmap_url || regionalResult.reliability_url;
      const regionalStep = adaptive ? steps.get(regionalResult.id) : steps.get("regional");
      const score = Number.isFinite(regionalResult.score) ? regionalResult.score : null;
      stops.push(stop({
        id: "regional", kind: "regional", label: "Vùng chỉnh sửa", short: "TruFor", score, thumb: maps || null,
        state: score === null && !maps ? "failed" : "measured",
        lesson: lessonFor(regionalStep, "KIỂM TRA BỔ SUNG · TRUFOR", "Ảnh có dấu hiệu chỉnh sửa ở đâu?",
          score === null ? null : `TruFor · ${format(score)}`, "info"),
      }));
    }
    if (guide.finding) {
      stops.push(stop({
        id: "summary", kind: "summary", label: "Tóm tắt", short: "Tóm tắt", state: guide.finding.partial ? "failed" : "measured",
        lesson: { eyebrow: "TÓM TẮT", title: guide.finding.title, body: [{ label: "Điều ta quan sát được:", text: guide.finding.text }], detail: null, tone: guide.finding.partial ? "warn" : "info" },
      }));
    }

    const measured = stops.filter((item) => item.state === "measured" && !isRegional(item) && item.kind !== "summary");
    const hasFailure = stops.some((item) => item.state === "failed");
    const status = adaptive ? investigation?.status : null;
    const stage = failed ? "error"
      : busy ? "running"
        : !source ? (input.hasFile ? "ready" : "empty")
          : status === "error" ? "error"
            : status === "cancelled" || hasFailure ? "partial"
              : !measured.length ? "partial" : "complete";
    const existing = stops.find((item) => item.id === selectedId);
    const pending = stops.find((item) => item.state === "pending" && !item.id.startsWith("slot-"));
    const firstChanged = stops.find((item) => item.changed);
    const chosen = existing || (busy && pending) || firstChanged || (source ? measured[0] : null) || null;
    const ended = !!source && !busy;
    return {
      mode: adaptive ? "adaptive" : "fixed", stage, stops, threshold, counts: trackCounts(stops, threshold),
      selectedId: chosen?.id || null,
      answer: ended ? answerFor(stops, threshold, adaptive ? "adaptive" : "fixed", stage === "error" ? "error" : stage === "partial" ? (status === "cancelled" ? "cancelled" : "partial") : "complete", reasonForSummary(source, adaptive)) : null,
    };
  }

  function reasonForSummary(source, adaptive) {
    if (!adaptive || !source?.summary?.stop_reason) return "";
    return { cancelled: "Phiên đã dừng theo yêu cầu của bạn.", planner_finished: "AI đã chọn kết thúc phân tích.", budget_exhausted: "Đã dùng hết số lượt gọi mô hình cho phép.", planner_failed: "Mô hình chọn phép thử gặp lỗi.", original_detector_failed: "Phép đo ảnh gốc gặp lỗi." }[source.summary.stop_reason] || "";
  }

  const api = { build, previewLabel, configChip, plannedStops, answerFor, trackCounts, operationLabel, stopModel };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ForensicsGuide = api;
})(typeof window === "undefined" ? globalThis : window);

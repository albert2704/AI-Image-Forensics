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
      const source = !adaptive && report.config?.mode !== "independent" ? aiItems[aiItems.indexOf(item) - 1] || baseline || report.image : baseline || report.image;
      const operations = operationsFor(item, source);
      const history = adaptive ? "Phép thử này là một nhánh riêng bắt đầu từ ảnh gốc." : report.config?.mode === "independent" ? "Bản sao này được xử lý trực tiếp từ ảnh gốc." : "Vòng này tiếp tục xử lý ảnh của vòng trước.";
      const comparison = baselineValid ? `Điểm đổi từ ${format(baseline.score)} thành ${format(item.score)}; ${changed ? "mô hình đã đổi nhóm đánh giá" : "mô hình vẫn giữ cùng nhóm đánh giá"}.` : `Bản sao được ${format(item.score)}; thiếu điểm gốc để so sánh.`;
      steps.push(card(item.id, "perturbation", operations.name, `${comparison} ${history}`, {
        ...common, score: item.score, decision: currentDecision, changed,
        lesson: { purpose: "Ảnh khi chia sẻ có thể bị nén hoặc đổi kích thước; ta thử tác động đó trên một bản sao.", action: operations.details.length ? operations.details.join(". ") + "." : "Đã xử lý bản sao theo điều kiện của lần chạy này.", meaning: !baselineValid ? "Cần điểm gốc hợp lệ để biết mô hình có đổi câu trả lời." : changed ? "Ảnh vẫn có cùng nguồn gốc; câu trả lời của mô hình đã đổi." : "Ảnh vẫn có cùng nguồn gốc; mô hình giữ cùng nhóm trong phép thử này." },
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
  const api = { build, previewLabel };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ForensicsGuide = api;
})(typeof window === "undefined" ? globalThis : window);

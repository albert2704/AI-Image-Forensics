"use strict";

// Presentation rules with no DOM access. tests/test_ui_rules.cjs runs them under Node.
(function (root) {
  function completionTag(rounds, scored, total) {
    const complete = total > 0 && scored === total;
    return complete ? `HOÀN TẤT ${rounds} VÒNG` : `ĐÃ ĐO ${scored}/${total} ẢNH`;
  }

  function trajectoryTitle(mode) {
    return mode === "independent" ? "Điểm AI theo từng điều kiện riêng lẻ" : "Điểm AI qua các vòng xử lý";
  }

  const STOP_REASONS = {
    budget_exhausted: "Đã dùng hết số lượt gọi công cụ cho phép.",
    planner_finished: "AI đã chọn kết thúc phân tích.",
    cancelled: "Đã dừng theo yêu cầu của bạn.",
    planner_failed: "Mô hình chọn phép thử gặp lỗi; các kết quả đã có vẫn được giữ lại.",
    original_detector_failed: "Phép đo ảnh gốc gặp lỗi.",
  };

  function stopReasonText(reason) {
    return STOP_REASONS[reason] || `Đã dừng: ${reason || "chưa rõ lý do"}.`;
  }

  const rules = { completionTag, trajectoryTitle, stopReasonText };
  if (typeof module === "object" && module.exports) module.exports = rules;
  else root.forensicsRules = rules;
})(typeof globalThis === "undefined" ? this : globalThis);

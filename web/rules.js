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

  const rules = { completionTag, trajectoryTitle };
  if (typeof module === "object" && module.exports) module.exports = rules;
  else root.forensicsRules = rules;
})(typeof globalThis === "undefined" ? this : globalThis);

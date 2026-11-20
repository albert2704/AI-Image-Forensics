const assert = require("node:assert");
const { completionTag, trajectoryTitle, stopReasonText } = require("../web/rules.js");

assert.equal(completionTag(3, 4, 4), "HOÀN TẤT 3 VÒNG");
assert.equal(completionTag(3, 2, 4), "ĐÃ ĐO 2/4 ẢNH");
assert.equal(completionTag(3, 0, 4), "ĐÃ ĐO 0/4 ẢNH");
assert.equal(completionTag(0, 1, 1), "HOÀN TẤT 0 VÒNG");
assert.equal(completionTag(0, 0, 0), "ĐÃ ĐO 0/0 ẢNH");

assert.equal(trajectoryTitle("cumulative"), "Điểm AI qua các vòng xử lý");
assert.equal(trajectoryTitle("independent"), "Điểm AI theo từng điều kiện riêng lẻ");
assert.equal(trajectoryTitle(undefined), "Điểm AI qua các vòng xử lý");

assert.match(stopReasonText("budget_exhausted"), /công cụ/);
assert.match(stopReasonText("planner_finished"), /kết thúc/);
assert.match(stopReasonText("cancelled"), /yêu cầu/);
assert.match(stopReasonText("planner_failed"), /giữ lại/);
assert.match(stopReasonText("original_detector_failed"), /ảnh gốc/);
assert.equal(stopReasonText("mystery"), "Đã dừng: mystery.");
assert.equal(stopReasonText(undefined), "Đã dừng: chưa rõ lý do.");

console.log("ui rules ok");

const assert = require("node:assert");
const { completionTag, trajectoryTitle } = require("../web/rules.js");

assert.equal(completionTag(3, 4, 4), "HOÀN TẤT 3 VÒNG");
assert.equal(completionTag(3, 2, 4), "ĐÃ ĐO 2/4 ẢNH");
assert.equal(completionTag(3, 0, 4), "ĐÃ ĐO 0/4 ẢNH");
assert.equal(completionTag(0, 1, 1), "HOÀN TẤT 0 VÒNG");

assert.equal(trajectoryTitle("cumulative"), "Điểm AI qua các vòng xử lý");
assert.equal(trajectoryTitle("independent"), "Điểm AI theo từng điều kiện riêng lẻ");
assert.equal(trajectoryTitle(undefined), "Điểm AI qua các vòng xử lý");

console.log("ui rules ok");

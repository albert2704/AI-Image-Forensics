const assert = require("node:assert/strict");
const test = require("node:test");
const { build, previewLabel } = require("../web/guide.js");
const ai = (id, tool, score, extra = {}) => ({ id, tool, score, score_kind: "ai_generation", ...extra });
const original = (score) => ai("E1", "baseline", score);
const resized = (score, extra) => ai("E2", "resize_s0.9_r1", score, extra);
const investigation = (observations, extra = {}) => ({ run_id: "run", status: "complete", observations, ...extra });
const finding = (report, options = {}) => build({ report, ...options }).finding;

test("guide explains a threshold change and points at measured changing evidence", () => {
  const report = investigation([original(.98), resized(.27), ai("E3", "jpeg_q85_r1", .9)]);
  const result = build({ report });
  assert.equal(result.finding.flips, 1);
  assert.equal(result.finding.previewId, "E2");
  assert.equal(result.finding.score, .27);
  assert.match(result.finding.title, /đổi câu trả lời/);
  assert.equal(result.steps.find((s) => s.id === "E2").changed, true);
  assert.match(result.steps.find((s) => s.id === "E2").text, /nhánh riêng bắt đầu từ ảnh gốc/);
});

test("high stable evidence and low stable evidence have different plain findings", () => {
  const high = finding(investigation([original(.9), resized(.8)]));
  const low = finding(investigation([original(.2), resized(.1)]));
  assert.match(high.title, /Tín hiệu cao vẫn giữ/);
  assert.match(low.title, /Chưa thấy tín hiệu cao/);
  assert.equal(high.flips, 0);
  assert.equal(low.flips, 0);
  assert.match(low.text, /chưa xác nhận nguồn gốc/);
});

test("fixed mode honors its custom threshold and treats equality as below", () => {
  const report = { run_id: "fixed", config: { threshold: .8, mode: "independent" }, variants: [{ id: "original", round: 0, score: .8 }, { id: "round-1", round: 1, score: .81 }] };
  const result = build({ report, adaptive: false });
  assert.equal(result.threshold, .8);
  assert.equal(result.finding.flips, 1);
  assert.match(result.steps.find((s) => s.id === "original").text, /bằng hoặc dưới/);
  assert.match(result.steps.find((s) => s.id === "round-1").text, /trực tiếp từ ảnh gốc/);
});

test("regional score never enters AI threshold comparisons or finding evidence", () => {
  const report = investigation([original(.1), { id: "E2", tool: "trufor", score_kind: "local_manipulation", score: .99, overlay_url: "/runs/run/overlay.png", reliability_url: "/runs/run/reliability.png" }]);
  const result = build({ report });
  assert.equal(result.finding.flips, null);
  assert.match(result.finding.title, /Chưa đủ phép đo/);
  assert.deepEqual(result.finding.evidenceIds, ["E1"]);
  assert.equal(result.steps.find((s) => s.id === "E2").kind, "regional");
  assert.equal(result.steps.find((s) => s.id === "E2").targetId, "narrator-regional");
  assert.match(result.steps.find((s) => s.id === "E2").lesson.meaning, /không xác định điểm ảnh do AI tạo/);
});

test("recorded fixed report includes actual regional maps as a separate step", () => {
  const result = build({ adaptive: false, saved: true, report: { run_id: "fixed", variants: [{ id: "original", round: 0, score: .9 }, { id: "round-1", round: 1, score: .8 }], regional: { status: "complete", score: .01, heatmap_url: "/map.png", reliability_url: "/confidence.png" } } });
  const regional = result.steps.find((s) => s.kind === "regional");
  assert.equal(regional.maps.overlay, "/map.png");
  assert.deepEqual(result.finding.evidenceIds, ["original", "round-1"]);
  assert.match(result.origin, /Kết quả đã lưu/);
  assert.match(result.origin, /không chạy suy luận mới/);
});

test("missing, nonfinite, invalid, and failed scores cannot create a successful test", () => {
  for (const score of [null, undefined, NaN, Infinity, -1, 1.1, "0.9"]) {
    const result = build({ report: investigation([original(.9), resized(score)]) });
    assert.equal(result.finding.flips, null);
    assert.equal(result.steps.find((s) => s.id === "E2").kind, "status");
    assert.equal(result.finding.partial, true);
  }
  const result = build({ report: investigation([original(.9), resized(.2, { error: "model failed" })]) });
  assert.equal(result.finding.flips, null);
  assert.equal(result.steps.find((s) => s.id === "E2").score, null);
  assert.deepEqual(result.finding.evidenceIds, ["E1"]);
});

test("baseline-only completion never claims robustness", () => {
  for (const score of [.1, .9]) {
    const result = finding(investigation([original(score)]));
    assert.match(result.title, /Chưa đủ phép đo/);
    assert.equal(result.flips, null);
  }
});

test("failed baseline prevents derivative-only comparison", () => {
  const result = finding(investigation([original(null), resized(.2)]));
  assert.match(result.title, /Chưa đủ phép đo/);
  assert.equal(result.flips, null);
  assert.equal(result.baselineScore, null);
});

test("cancelled and errored investigations retain partial observations honestly", () => {
  const cancelled = finding(investigation([original(.9), resized(.2)], { status: "cancelled" }));
  const errored = finding(investigation([original(.9), resized(.2)], { status: "error" }));
  assert.equal(cancelled.partial, true);
  assert.match(cancelled.text, /Bạn đã dừng phiên/);
  assert.equal(cancelled.flips, 1);
  assert.match(errored.text, /Phiên gặp lỗi/);
  assert.match(errored.text, /kết quả một phần/);
});

test("live or disconnected monitoring never produces a completed finding", () => {
  const report = investigation([original(.9)], { status: "running" });
  const live = build({ report });
  const disconnected = build({ report, disconnected: true });
  assert.equal(live.finding, null);
  assert.equal(disconnected.finding, null);
  assert.match(disconnected.steps.at(-1).text, /Máy chủ có thể vẫn đang xử lý/);
  assert.match(build({ report, cancelRequested: true }).steps.at(-1).text, /hoàn tất lượt đang chạy/);
});

test("empty upload and missing-model states do not manufacture results", () => {
  const empty = build();
  assert.equal(empty.steps.length, 1);
  assert.equal(empty.steps[0].score, null);
  assert.equal(empty.finding, null);
  const unavailable = build({ hasImage: true, availability: { bfree: { available: false }, planner: { available: true } } });
  assert.match(unavailable.steps[0].text, /chưa sẵn sàng/);
  assert.equal(unavailable.steps[0].score, null);
});

test("narration leaves report data intact", () => {
  const report = investigation([original(.9), resized(.2)]);
  const before = JSON.stringify(report);
  build({ report, saved: true });
  assert.equal(JSON.stringify(report), before);
});


test("completed evidence starts with the experiment overview before showing scores", () => {
  const result = build({ report: investigation([original(.9), resized(.2)]), saved: true });
  const intro = result.steps.find((step) => step.id === result.initialStepId);
  assert.equal(intro.kind, "overview");
  assert.equal(intro.score, null);
  assert.match(intro.lesson.purpose, /cùng một ảnh/i);
  assert.match(intro.lesson.action, /bản sao/);
  assert.match(intro.model.text, /Qwen.*không xem ảnh/);
  assert.match(intro.nextLabel, /B-Free đo ảnh gốc/);
  assert.deepEqual(intro.flow, ["Ảnh gốc", "B-Free đo", "Xử lý bản sao", "B-Free đo lại", "So sánh"]);
});

test("stopped or failed evidence initially shows its partial outcome", () => {
  for (const status of ["cancelled", "error"]) {
    const result = build({ report: investigation([original(.9), resized(.2)], { status }) });
    assert.equal(result.initialStepId, "finding");
    assert.equal(result.finding.partial, true);
  }
  assert.equal(build({ report: investigation([original(null), resized(.2)]) }).initialStepId, "finding");
  assert.equal(build({ report: investigation([original(.9)], { status: "running" }) }).initialStepId, "E1");
});

test("a resize lesson explains the recorded dimensional change and unchanged origin", () => {
  const base = { ...original(.98), width: 1024, height: 1024 };
  const copy = resized(.27, { width: 922, height: 922, operations: [{ type: "resize", width: 922, height: 922, round: 1 }] });
  const result = build({ report: investigation([base, copy]) });
  const step = result.steps.find((entry) => entry.id === "E2");
  assert.equal(step.transformation.from, "1024 × 1024");
  assert.equal(step.transformation.to, "922 × 922");
  assert.match(step.lesson.action, /1024 × 1024 → 922 × 922/);
  assert.match(step.lesson.meaning, /cùng nguồn gốc.*mô hình đã đổi/);
  assert.equal(step.decision, "Bằng hoặc dưới mốc");
  assert.equal(previewLabel(copy), "Bản đổi kích thước");
});

test("JPEG settings come from actual operations and are not confidence percentages", () => {
  const copy = ai("E2", "jpeg_q85_r3", .8, { operations: [{ type: "jpeg", quality: 85 }, { type: "jpeg", quality: 85 }, { type: "jpeg", quality: 85 }] });
  const step = build({ report: investigation([original(.9), copy]) }).steps.find((entry) => entry.id === "E2");
  assert.match(step.lesson.action, /Nén JPEG 3 lần/);
  assert.match(step.lesson.action, /85\/100/);
  assert.doesNotMatch(step.lesson.action, /85%/);
  const unknown = build({ report: investigation([original(.9), ai("E2", "jpeg_q85_r3", .8)]) }).steps.find((entry) => entry.id === "E2");
  assert.doesNotMatch(unknown.lesson.action, /85|3 lần/);
});

test("cumulative fixed transformations use previous image dimensions but compare baseline score", () => {
  const variants = [
    { id: "original", round: 0, score: .9, width: 1024, height: 1024 },
    { id: "round-1", round: 1, score: .8, width: 922, height: 922, operations: [{ type: "resize" }] },
    { id: "round-2", round: 2, score: .2, width: 829, height: 829, operations: [{ type: "resize" }] },
  ];
  const cumulative = build({ adaptive: false, report: { run_id: "fixed", variants, config: { mode: "cumulative" } } }).steps.find((step) => step.id === "round-2");
  const independent = build({ adaptive: false, report: { run_id: "fixed", variants, config: { mode: "independent" } } }).steps.find((step) => step.id === "round-2");
  assert.equal(cumulative.transformation.from, "922 × 922");
  assert.equal(independent.transformation.from, "1024 × 1024");
  assert.equal(cumulative.baselineScore, .9);
  assert.match(cumulative.transformation.history, /vòng trước/);
});

test("baseline lesson explains pretrained detection and strict threshold without arbitrary bands", () => {
  const baseline = build({ report: investigation([original(.5), resized(.50000001)]) }).steps.find((step) => step.id === "E1");
  const derivative = build({ report: investigation([original(.5), resized(.50000001)]) }).steps.find((step) => step.id === "E2");
  assert.match(baseline.lesson.action, /đã huấn luyện.*không dùng để huấn luyện lại/);
  assert.match(baseline.lesson.meaning, /không phải xác suất/);
  assert.equal(baseline.decision, "Bằng hoặc dưới mốc");
  assert.equal(derivative.decision, "Trên mốc");
  assert.equal(derivative.changed, true);
  assert.match(baseline.nextLabel, /Xem thu nhỏ/);
});

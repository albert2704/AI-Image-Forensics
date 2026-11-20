# Guided investigation verification

Verified locally on 31 October 2026.

The interface teaches an investigation through report-derived lessons. Completed valid reports begin with the experiment overview. Qwen still selects tools from measurements; replay does not start new inference.

## Automated checks

- All 118 Python tests passed with `python -m unittest discover -s tests` on the PR branch based on the updated main branch. The server tests required localhost socket access outside the execution sandbox.
- All 18 guide behavior tests passed with `node --test tests/test_guide.cjs`.
- `node tests/test_ui_rules.cjs`, both JavaScript syntax checks, markup nesting, unique IDs, renderer-reference checks, and `git diff --check` passed.
- Separate Codex reviewers ran domain and integration probes. The domain probe covered 512 frozen-input combinations and actual cumulative and independent pipeline reports. The integration probe checked guide rendering, source disclosures, manual selection during polling, static module contents, security headers, and committed-demo write rejection. Neither reviewer reported a verified finding.

An earlier baseline run showed a floating-point equality failure in the unchanged frequency-feature test. Later full suites passed without a change to that test or implementation.

## Browser checks

The working checkout with installed local model assets completed these real-model checks before PR preparation:

- A fresh adaptive upload measured 0.988232 on the official B-Free demo and 0.793440 after the JPEG test selected by Qwen.
- Manual mode completed a resize and JPEG round. Its finding matched the measured threshold change.
- Saved replay selected the original, resized copy, actual TruFor maps, combined test, and finding. The resize lesson displayed 1024 × 1024 to 922 × 922 and scores 0.988 to 0.272. Regional evidence stayed separate.
- A fresh completed investigation opened the overview with scores hidden until the baseline lesson. A cancelled investigation opened its partial, insufficient-evidence finding.
- Keyboard navigation, exports, source reset, and missing-model behavior were checked. No browser warnings or errors were recorded.

The final PR branch was also served on a separate localhost port against the updated main branch:

- The committed read-only example loaded without installed detector weights.
- The browser loaded `rules.js`, `guide.js`, and `app.js` in that order.
- The second cumulative round displayed its actual input dimensions, 922 × 922, and output dimensions, 829 × 829. Its score comparison retained the original baseline.
- The recent demo-path and presentation fixes remained in place. Server tests and an independent HTTP probe confirmed HTTP 409 for regional writes to the committed example.
- No browser warnings or errors were recorded.

## Teaching and layout

A separate reader reviewed the actual rendered walkthrough before inspecting its implementation. The page explicitly covered the experiment's purpose, why it alters copies, model roles, score interpretation, and the limits of the finding. This establishes content coverage, not proof that a first-time visitor understands it.

The desktop browser displayed the recorded transformation and paired scores beside the image comparison and lesson. The screenshots show the [overview](../output/verification/teaching-ui-overview.jpg) and [resize explanation](../output/verification/teaching-ui-resize.jpg).

The browser accepted a 390-pixel viewport setting but continued to render its desktop width. The override was reset. The phone layout has responsive CSS but was not visually verified.

## Review limits

The available Codex reviews ran inside the existing environment. Automatic approval rejected separate DeepSeek and Grok CLI reviews because they would send private source code to those external services without authorization. No code was sent through those rejected actions. Cross-model review remains pending; these checks do not establish merge readiness.

Detector algorithms, weights, study protocols, and recorded benchmark results were unchanged. These checks establish interface behavior, not detector accuracy.

## Review follow-up

Three behavioural findings from the DeepSeek review were fixed after the checks above:

- **Live completion keeps its place.** `state.guide.running` records whether a run was streaming, and a completed run now opens on the finding instead of rewinding to the experiment overview. Opening a saved result or the committed example still starts at the overview, because those reports carry no running status. This was verified by reading the transition and by the guide unit tests; no browser session was rerun for it.
- **A failed experiment is no longer stored as a report.** `state.failed` replaces the fabricated empty report, so a failure keeps the settings pane open, leaves the technical pane hidden and keeps the regional button disabled instead of pointing it at a run id that does not exist.
- **Landmarks restored.** Both disclosures keep `role="region"` and their previous accessible names, so screen-reader landmark navigation still finds the source settings and the measured results.

Automated state at this follow-up: 118 Python tests, 19 guide tests, the UI rules check, and both JavaScript syntax checks pass. The transition behaviour above still needs a browser check on a machine with detector weights before merge.

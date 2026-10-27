# Adaptive investigation UI verification

Verified on 18 October 2026 using the actual local application at `http://127.0.0.1:8765`, the Codex browser, B-Free, and the installed local Qwen planner. No detector scores or decisions were mocked for these checks. The existing Mobbin-informed layout in `UI_RESEARCH.md` was retained.

## Implemented interaction

- Explicit choice between a fixed experiment and adaptive investigation. Each keeps its own result record until the source changes.
- A 2–6 model-tool call limit, an optional regional scan, planner installation status, and an explanation that the original B-Free measurement consumes one call.
- One-second polling of the asynchronous investigation endpoint, a visible current step, model-tool and planner-call counts, and cancellation after the current call. Controls for changing the source, mode, or budget stay locked during model work.
- Evidence IDs, measured scores, changes relative to the original, threshold-decision changes, pixel dimensions, PSNR, and direct image comparison. Adaptive tests appear as separate branches; the fixed experiment trajectory chart is hidden in this mode.
- Planner choices show the evidence available at selection time and the offered action list. Action weights are not shown as confidence. A tool selected immediately before cancellation is explicitly identified if it never ran.
- The grounded summary cites measured observations. Terminal errors retain valid evidence and expose the failure rather than substituting scores. JSON and CSV downloads use backend artifacts.
- TruFor observations use a separate local-manipulation label and pair anomaly maps with reliability maps and their supplied legends.
- `?investigation=<run_id>` reopens a stored investigation without inference and reconnects monitoring if a run is still active. A newly started run updates the URL. A saved source must be selected again before starting a fresh run.
- Connection failures pause monitoring and expose a retry action while retaining the active-job lock and stop control. This recovery branch was code-inspected; a forced connection failure was not injected during the shared model run.

## Actual browser checks

| Check | Evidence and outcome |
|---|---|
| Fixed-mode regression | Opened the recorded official example; original and derivative images, actual score trajectory, CSV/JSON links, and anomaly/reliability maps remained available. |
| Real adaptive run | `441d4791c61843e099f51f5e1d11e922`: official `img0002.png`, budget 4, regional disabled. Completed in about 28 seconds using 3 model-tool calls and 3 planner calls. |
| Observed choices and values | Original 0.9882; planner selected three JPEG Q85 rounds, score 0.7934; then one 90% resize, score 0.2719; then Finish. UI showed changes −0.1948 and −0.7163, one threshold-decision change, and citations to E1–E3. |
| Cancellation | `d6c47fe286d74abaa2a3c1baf9ab069e`: requested stop during processing. Reached CANCELLED after 1/4 model-tool calls, retained the original measurement, and restored controls. |
| Real failure display | Reopened `a014802c6dc641689f89ca15eef07f92`, the retained FP16 planner failure. UI showed ERROR, the non-finite-logit failure, original evidence, and insufficient robustness evidence. The later successful run used the corrected backend precision. |
| Saved-result access | Reopened the completed investigation through its URL. Displayed the saved original, evidence, summary, decisions, and exports without launching a new detector call. |
| Evidence navigation | Evidence citations target the corresponding observation card; comparison controls select the appropriate original or derivative. |
| Mobile | At 390 × 844 pixels, measured document width was 390 pixels, all three real scores were present, the fixed trajectory was hidden, and summary/preview/cards remained usable. |
| Clearing the source | Removed a saved source: original hidden, evidence cards removed, exports and summary hidden, run button disabled. No stale result remained attached to a new source. |
| Browser errors | No JavaScript console errors in the completed investigation session. |
| Syntax | `node --check web/app.js` passed. |

## Scope and artifacts

This pass validates interface behavior and fidelity to backend measurements, not detector accuracy or agent decision quality. No additional large-image TruFor inference was launched for adaptive UI QA. Existing genuine TruFor maps were checked in fixed mode; the adaptive map renderer follows the same backend artifact fields.

A later screenshot refresh after the report wording correction was not completed because the in-app browser surface was unavailable. The previously validated screenshots remain the visual record; no additional browser pass is claimed. Saved-run and export endpoints were checked separately by HTTP after the server restart.

- `output/verification/agent-desktop.jpg`: actual completed investigation, desktop.
- `output/verification/agent-mobile.jpg`: actual completed investigation, 390-pixel viewport.
- Completed report: `output/runs/441d4791c61843e099f51f5e1d11e922/investigation.json`.
- Cancelled report: `output/runs/d6c47fe286d74abaa2a3c1baf9ab069e/investigation.json`.
- Retained failure: `output/runs/a014802c6dc641689f89ca15eef07f92/investigation.json`.

The temporary mobile viewport override was reset after verification.

## Vietnamese interface and motion — 20 October 2026

The website now presents its controls, model states, live steps, saved-result summaries, uncertainty statements, image descriptions, chart labels, and TruFor legends in Vietnamese. Numeric presentation uses Vietnamese decimal commas; exports retain the original machine-readable values and schema. KiB/MiB labels match the binary byte divisor. Classification remains strictly greater than the configured threshold, and the Qwen counter identifies calls rather than successful choices. Unknown technical diagnostics retain their exact text under a Vietnamese explanation.

Motion is limited to a brief entrance, upload/control feedback, image changes, newly received evidence/decision cards, and an indeterminate indicator during a live investigation. Scores are never animated or simulated. Existing evidence does not replay its entrance on every poll. CSS animation and transitions are disabled under `prefers-reduced-motion`; JavaScript reveals and smooth scrolling also honor that preference, and active reveals are cancelled if it changes.

Verified in the actual local browser:

- Reopened investigation `441d4791c61843e099f51f5e1d11e922`; Vietnamese summaries retain the actual 0.9882, 0.7934, and 0.2719 readings and one changed threshold decision. Expanded uncertainty statements were translated.
- Opened the recorded fixed example; all four scores, the chart, measurement table, export links, and the saved TruFor anomaly/reliability legends render in Vietnamese. No new TruFor inference was required.
- Completed live investigation `e591b8f52f1a4c578550e2e86bfd3ffb` on official `img0002.png`, budget 2, regional disabled. The run used 2 model-tool calls and 1 Qwen call in about 28 seconds, returning original 0.9882 and JPEG Q85 × 3 score 0.7934. Live controls locked, Vietnamese status appeared, and the activity animation stopped on completion.
- Reopened the retained planner failure `a014802c6dc641689f89ca15eef07f92`. The error state and explanation appeared in Vietnamese, with the original evidence and exact technical error retained.
- Desktop viewport 1280 pixels and phone viewport 390 × 844 had no document-level horizontal overflow. The phone layout stacks image previews and metrics for readable Vietnamese text. The temporary viewport override was reset.
- No JavaScript console errors were recorded during these checks. `node --check web/app.js` passed. Thirteen focused assertions passed for number/unit formatting, strict-threshold wording, saved-message translation, and reduced-motion skip/cancellation logic. Reduced-motion behavior was checked through the actual source with a simulated media-query preference; the operating system preference was not changed.

Updated visual records:

- `output/verification/vietnamese-desktop.jpg`
- `output/verification/vietnamese-mobile.jpg`

These checks validate presentation and interaction, not detector accuracy. Only website presentation code was changed; the frozen model, planner, experiment, and benchmark modules remain untouched by this localization work.

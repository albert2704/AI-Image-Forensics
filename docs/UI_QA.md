# Browser verification

Verified on 15 October 2026 against the actual local server at `http://127.0.0.1:8765` with the configured B-Free and TruFor integrations. Browser interactions used the Codex in-app browser. No detector responses were mocked.

| Check | Result |
| --- | --- |
| JavaScript syntax | `node --check web/app.js` passes. |
| Initial state | Upload required before running; scores absent; model availability visible. |
| Real file upload | Official B-Free `demo_images/img0000.png` loaded through the file chooser; dimensions 835 × 1256 and source preview displayed. |
| Actual experiment | Three cumulative rounds completed. Displayed original/R1/R2/R3 scores: 0.003 / 0.004 / 0.003 / 0.003. Real pixel dimensions, byte sizes, MSE and PSNR populated. Loading state cleared. |
| Recorded example | `?example=1` loads the labeled official recorded demonstration. Measured scores 0.988232 / 0.098620 / 0.020876 / 0.002742 appear in the chart and table. Three derivatives differ from the original threshold decision. |
| Existing regional evidence | Original-image manipulation anomaly, reliability and overlay images display separately, with appropriate labels and legends. |
| Fresh regional request | “Run regional scan again” invoked the actual `/api/regional` endpoint. The busy state disabled the action; completion restored it and displayed all three maps and score 0.032. Server confirmed POST 200 and all three image GET 200 responses. |
| JSON download | Browser download completed; parsed run ID `89c31f6991c74f058d51a1b126b84cc4`, four variants and the expected score trajectory. |
| CSV download | Browser download completed; five lines including the header and the four expected variant rows. |
| Desktop layout | Visually inspected at the browser’s default 1280-pixel width. Source/result comparison, chart, measurement table and regional maps render correctly. |
| Phone layout | Visually inspected at 390 × 844. Document width equals viewport width (390 px); the measurements table uses its own horizontal scrolling container. Viewport override reset afterward. |
| Console | No browser errors or warnings recorded during upload, analysis, example loading, export and completed regional inference. |

Screenshots are JPEG because that is the browser capture format: `output/verification/ui-desktop.jpg` and `output/verification/ui-mobile.jpg`. Both final captures show the completed regional state, including actual maps. The mobile score chart uses its measured display width so tick labels remain readable at the narrower viewport.

The official images are demonstration fixtures, not a held-out benchmark. These checks establish interface and integration behavior, not detector accuracy or calibration.

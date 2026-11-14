# Guided investigation verification

Verified locally on 31 October 2026.

The interface presents actual detector records as a sequence of explanations. Qwen continues to select tools. The guide builds its wording from measured evidence and does not request new model inference when replaying a result.

## Automated checks

- All 83 Python tests passed with `.venv/bin/python -m unittest discover -s tests`.
- All 12 guide behavior tests passed with `node --test tests/test_guide.cjs`.
- `node --check web/app.js`, `node --check web/guide.js`, and `git diff --check` passed.
- A separate reviewer checked score validity, threshold decisions, regional-score separation, navigation, and review selection during polling. No verified correctness findings remained. The reviewer used the inherited Codex model; a review across different model families was unavailable.

An initial baseline run had an exact floating-point equality failure in the unchanged frequency-feature test, with a maximum difference of 6.94e-18. The final full suite passed without a change to that test or the frequency implementation.

## Browser checks

- A fresh upload of the official B-Free `img0002.png` completed adaptive investigation `60a1fc7c528e46da9cf7598f6afa6556`. B-Free measured 0.988232 on the original and 0.793440 after the JPEG test selected by Qwen. The guide displayed the matching image and score.
- Manual mode completed run `6c0068b676764661b8429931830af6aa` with one resize and JPEG round. The guide reported the measured threshold change. Technical details, CSV and JSON links, and the optional regional action remained available.
- Saved investigation `88f169c0186e448886b99fbeaab1481e` opened with an explicit saved-results label. Replay selected the original, resized image, regional maps, combined test, and final finding without new inference. The finding selected a measured derivative that changed the threshold decision.
- The original stage highlighted the original figure. The resized stage highlighted the processed figure and displayed 0.272. The regional stage displayed actual 1024-pixel TruFor overlay and reliability images while hiding the B-Free score comparison.
- Keyboard activation of Back and Next selected the corresponding guide stage and image. Opening source controls and then changing guide stages preserved the disclosure state. Clearing the source reopened upload controls and removed old scores and findings.
- Live cancellation of investigation `78afb92293504e9c96aa9bc13c9a2689` retained the completed baseline measurement. The guide stated that the run was stopped and had insufficient robustness evidence.
- A temporary server without detector configuration disabled adaptive analysis. Manual image processing produced no AI scores and an insufficient-evidence finding.
- No browser warnings or errors were recorded during these checks.

## Layout evidence and limits

The actual 972-pixel browser viewport displayed the image comparison beside the guide, with source controls and technical records collapsed. The screenshot is `output/verification/guided-ui-desktop.jpg`.

The browser's viewport capability accepted a 390-pixel setting but continued to report and render 972 pixels, including in a fresh tab. The override was reset. The phone layout has responsive CSS but was not visually verified in this session.

The model algorithms, checkpoints, study protocols, and recorded benchmark results were not changed. These checks establish interface behavior, not detector accuracy.

## Teaching refinement after user feedback

The user reported that completing the first guided flow still did not explain the whole process. The revised page starts completed reports at an overview rather than at a score-based conclusion.

- The overview explains the experiment and shows the sequence from original image through B-Free, copy processing, another B-Free measurement, and comparison.
- Each measured step explains its purpose, recorded action, and meaning. Model roles appear where they are relevant.
- The image area shows recorded transformation dimensions and score groups beside the images. The score ruler appears at the baseline lesson. Stage navigation has visible labels and action-specific Next buttons.
- For fixed cumulative processing, transformation dimensions start from the previous variant. Score comparisons still use the original baseline.
- All 18 guide tests passed. JavaScript syntax, markup nesting, unique IDs, renderer references, and diff checks passed. Backend logic was unchanged from the previously passing Python suite.
- A full browser walkthrough of saved investigation `88f169c0186e448886b99fbeaab1481e` displayed overview, baseline, resize, regional scan, combined processing, and finding. The resize lesson displayed the actual 1024 × 1024 to 922 × 922 change and scores 0.988 to 0.272. The regional score stayed separate.
- A real fresh upload completed investigation `22c1c01cefa8470ca7889e0876dd56e8` and returned to the overview with scores hidden until their lesson. No browser warnings or errors were recorded.
- Reopening cancelled investigation `78afb92293504e9c96aa9bc13c9a2689` started at its partial, insufficient-evidence finding.
- A separate reader evaluated the actual rendered walkthrough before reading the implementation. The content explicitly answered the five comprehension questions about purpose, copies, model roles, scores, and conclusions. This checks content coverage, not whether a real visitor understands it.
- A separate final code probe passed for overview-first defaults, manual review during polling and completion, evidence visibility, regional separation, cancellation, source disclosures, and navigation.

The updated screenshots are `output/verification/teaching-ui-overview.jpg` and `output/verification/teaching-ui-resize.jpg`. The browser's phone-viewport limitation described above remains.

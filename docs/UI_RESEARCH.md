# UI research and design rationale

The interface is a local scientific workbench for comparing detector measurements under image transformations. Mobbin references were searched and visually inspected on 15 October 2026. The search destination was `code`, with the task intent “Build a local image forensics assistant for comparing detector evidence across image transformations.”

## Inspected references

- [Higgsfield — editing workspace](https://mobbin.com/screens/73d5ba0d-57b7-4468-901c-ad060319ff66). The inspected preview places a portrait in the main canvas, a compact relighting control panel beside it, and a prominent processing action at the bottom of that panel. The useful pattern is a stable relationship between the source preview and its processing controls. This workbench puts upload and experiment controls in one sidebar and keeps measurements adjacent.
- [Magnific — editing workspace](https://mobbin.com/screens/7e4ff51f-2eee-4468-8962-1072825d901e). The inspected preview gives most of the canvas to a photograph, with a compact enhancement panel and a visible strip of image variants. The adapted pattern is to keep source identity visible while navigating derivatives. This implementation uses a labeled round selector and clickable measurement rows instead of many tiny thumbnails.
- [Higgsfield — Compare flow](https://mobbin.com/flows/0abe24ce-0bf2-4700-af65-a1d5e96005f3). Three inspected previews show the original editing canvas followed by comparison states with a vertical divider at different positions. The adapted principle is persistent comparison without losing processing context. The prototype uses two explicitly labeled images because resized derivatives have different native dimensions and a wipe could imply pixel correspondence that the display does not guarantee.
- [Magnific — Preview an image flow](https://mobbin.com/flows/0e6d84f1-676a-4956-862a-14034e88a4e1). Three inspected previews show linked source/result image nodes, a side-by-side preview modal, and a single-image enlarged preview. The adapted principle is progressive inspection: source and selected derivative first, optional regional maps afterward. Each regional map links to its full-size local artifact.

No Mobbin screenshot or branded visual asset is embedded in the prototype. These are behavioral and layout references; the ivory, ink and muted teal visual treatment is original to this implementation. No `ai_usage_notice` was returned by these searches.

## Research-specific decisions

1. **Availability before inference.** Model status is visible before a run. Without configured weights the UI still supports image transformations and pixel measurements, but shows missing AI scores as unavailable.
2. **No fabricated evidence.** Empty states contain no invented detector scores, charts or heatmaps. A separately labeled “Recorded official demo” loads genuine previously measured outputs from an official demonstration image, including the actual score trajectory and same-image TruFor maps; it does not imply a fresh inference run. Charts render only finite measured scores returned by the backend. Missing points are not connected across gaps.
3. **Experiment identity survives interaction.** Settings apply to the next run; the result record retains the executed configuration, run ID and source hash. CSV and JSON exports point to server-produced artifacts.
4. **Control and cumulative treatments are distinct.** The mode label “Single-pass control” explains matched final size with fresh processing from the original. Cumulative processing starts from the previous output.
5. **Regional maps retain their meaning.** TruFor output is labeled “manipulation anomaly,” with reliability shown separately. It is not presented as an AI-generation segmentation map.
6. **Uncertainty is part of the result.** The UI explains that scores are not calibrated truth probabilities, correlated derivatives are not independent evidence, and forensic anomalies can arise from ordinary editing.
7. **Accessible operation.** Native form controls, an accessible file input, keyboard-focus treatment, a skip link, live status announcements, responsive layout and textual measurements accompany the visual chart. No third-party fonts, analytics or remote image assets are required.

## Validation scope

JavaScript syntax and actual browser/API integration are verified separately during project validation. Offline model behavior is a required path. Successful UI rendering does not validate either detector’s research performance.

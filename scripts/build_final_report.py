"""Build the completed research report from frozen measured result artifacts."""
from pathlib import Path
import json
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image

from report_assets import markdown_image

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "output/benchmark"
OUTPUT = ROOT / "output/pdf/AI_Image_Forensics_Research_Report.pdf"
DEMO_ID = "441d4791c61843e099f51f5e1d11e922"
LABELS = {
    "baseline": "Original", "jpeg_q85_r1": "JPEG Q85 x1", "jpeg_q85_r3": "JPEG Q85 x3",
    "resize_s0.9_r1": "Resize 90% x1", "resize_s0.9_r3": "Resize 90% x3",
    "combined_q95_s0.9_r1": "Resize + Q95 x1", "combined_q95_s0.9_r3": "Resize + Q95 x3",
    "reverse_q95_s0.9_r3": "Q95 + resize x3", "independent_q95_s0.9_r3": "Matched single pass",
}


def read(path):
    return json.loads(Path(path).read_text())


def pct(value):
    return "Not estimable" if value is None else f"{100*value:.1f}%"


def build():
    protocol = read(STUDY / "protocol.json")
    summaries = {name: read(STUDY / "results" / name / "summary.json") for name in ["bfree", "frequency"]}
    if any(summary["protocol_hash"] != protocol["protocol_hash"] for summary in summaries.values()):
        raise ValueError("Detector summary belongs to another protocol.")
    test = {name: summary["splits"]["test"] for name, summary in summaries.items()}
    if not all(t["coverage"]["complete"] for t in test.values()):
        raise ValueError("The report requires complete held-out predictions for both detectors.")
    agent = read(ROOT / "output/agent-evaluation/summary.json")
    agent_protocol = read(ROOT / "output/agent-evaluation/protocol.json")
    if agent["protocol_hash"] != agent_protocol["protocol_hash"] or agent_protocol["study_protocol_hash"] != protocol["protocol_hash"]:
        raise ValueError("Agent summary belongs to another protocol or detector study.")
    if not all(row["complete"] for row in agent["policies"].values()):
        raise ValueError("The report requires all prespecified policy episodes.")
    demo = read(ROOT / "output/runs" / DEMO_ID / "investigation.json")
    primary = test["bfree"]["paired_vs_baseline"]["jpeg_q85_r3"]
    base = test["bfree"]["conditions"]["baseline"]["metrics"]
    after = test["bfree"]["conditions"]["jpeg_q85_r3"]["metrics"]
    interval = primary["balanced_accuracy_delta_ci95"]
    primary_text = f"B-Free balanced accuracy changed from {pct(base['balanced_accuracy'])} on originals to {pct(after['balanced_accuracy'])} after three JPEG quality-85 encodes. The paired change was {100*primary['balanced_accuracy_delta']:+.1f} percentage points (95% group-bootstrap interval {100*interval[0]:+.1f} to {100*interval[1]:+.1f})."
    if interval == [0.0, 0.0]:
        primary_text += " This interval is degenerate because no observed group changed the endpoint; it does not establish zero uncertainty on new data."
    measured = test["bfree"]["conditions"]
    secondary_text = (
        f"One Q85 encode gave B-Free balanced accuracy of {pct(measured['jpeg_q85_r1']['metrics']['balanced_accuracy'])}; three gave {pct(after['balanced_accuracy'])}. The primary baseline-to-round-3 contrast includes the first encode and cannot attribute its entire change to repetition alone. "
        f"For B-Free, resizing alone changed balanced accuracy to {pct(measured['resize_s0.9_r1']['metrics']['balanced_accuracy'])} after one round and {pct(measured['resize_s0.9_r3']['metrics']['balanced_accuracy'])} after three. "
        f"Three resize-then-Q95 rounds reached {pct(measured['combined_q95_s0.9_r3']['metrics']['balanced_accuracy'])}, compared with {pct(measured['independent_q95_s0.9_r3']['metrics']['balanced_accuracy'])} for one resize/JPEG pass at the same final dimensions. "
        f"Reversing the repeated operation order reached {pct(measured['reverse_q95_s0.9_r3']['metrics']['balanced_accuracy'])}. Resizing rounds differ in final dimensions; the matched-size arm helps isolate processing history. These secondary comparisons are descriptive."
    )
    frequency_primary = test["frequency"]["paired_vs_baseline"]["jpeg_q85_r3"]
    frequency_flips = sum(frequency_primary["flips"].values())
    frequency_text = f"The frequency comparator had {frequency_flips} threshold changes among {frequency_primary['counts']['paired_sources']} paired originals and Q85 round-3 images, with mean absolute score change {frequency_primary['score_delta']['mean_absolute']:.6f}."
    if frequency_primary["balanced_accuracy_delta_ci95"] == [0.0, 0.0]:
        frequency_text += " Its paired bootstrap interval collapses to [0, 0] because the observed groups contain no balanced-accuracy changes. This degenerate interval cannot establish zero population uncertainty or rule out changes on new images."
    result_table = [["Condition", "B-Free bAcc", "B-Free AUC", "FFT/DCT bAcc", "FFT/DCT AUC"]]
    for condition in protocol["conditions"]:
        key = condition["name"]
        first, second = (test[name]["conditions"][key]["metrics"] for name in ["bfree", "frequency"])
        result_table.append([LABELS[key], pct(first["balanced_accuracy"]), f"{first['auroc']:.3f}", pct(second["balanced_accuracy"]), f"{second['auroc']:.3f}"])
    policy_table = [["Policy", "Episodes", "Mean calls", "Changes found", "Discovery recall"]]
    policy_checks = []
    for key, label in [("fixed", "Fixed workflow"), ("rule", "Rule baseline"), ("local_llm", "Local Qwen")]:
        row = agent["policies"][key]
        policy_table.append([label, str(row["episodes"]), f"{row['mean_detector_tool_calls']:.2f}", f"{row['discovered_unstable_sources']}/{row['reference_unstable_sources']}", pct(row["instability_discovery_recall"])])
        policy_checks.append(f"{label}: {row['failed_episodes']} failed episodes; {row['valid_action_episodes']}/{row['episodes']} valid-action episodes; {row['budget_compliant_episodes']}/{row['episodes']} budget-compliant episodes; {row['valid_evidence_reference_episodes']}/{row['episodes']} with valid evidence references.")
    qwen, fixed, rule = (agent["policies"][key] for key in ["local_llm", "fixed", "rule"])
    policy_interpretation = (
        f"Only {qwen['reference_unstable_sources']} of the {agent['selected_sources']} selected sources had reference-catalog instability, so the discovery-recall denominator is very small. "
        f"Local Qwen found {qwen['discovered_unstable_sources']}/{qwen['reference_unstable_sources']} reference events using {qwen['mean_detector_tool_calls']:.2f} mean calls; the fixed workflow found {fixed['discovered_unstable_sources']}/{fixed['reference_unstable_sources']} using {fixed['mean_detector_tool_calls']:.2f}, and the rule policy found {rule['discovered_unstable_sources']}/{rule['reference_unstable_sources']} using {rule['mean_detector_tool_calls']:.2f}. "
        "The measured pilot provides no observed discovery or tool-call advantage for the language-model policy. A larger, more challenging preregistered policy study is needed before making a benefit claim."
    )
    demo_table = [["Evidence", "Measured test", "B-Free score", "Change from original"]]
    for item in demo["observations"]:
        demo_table.append([item["id"], LABELS[item["tool"]], f"{item['score']:.4f}", "-" if item.get("delta_from_original") is None else f"{item['delta_from_original']:+.4f}"])
    chapters = [
        ("Research report", [
            ("Evaluating AI-Generated Image Detection Under Repeated Compression and Resizing", "title"),
            ("A local image-forensics assistant, a frozen detector benchmark, and a bounded language-model investigation policy", "subtitle"),
            ("Completed pilot | 18 October 2026 | Reproducible measurements and research limitations", "meta"),
            ("Abstract", "heading"),
            ("This project studies how repeated image processing changes AI-generation detector evidence. A local prototype integrates B-Free for whole-image generation scores and TruFor for distinct local-manipulation maps. A controlled pilot contains 320 released images: 160 real photographs and 160 generated images across four generators, grouped by matched source/prompt. A 64/64/192 training/validation/test split prevents matched pairs from crossing splits. Nine prespecified image conditions yield 1,728 held-out predictions per detector. B-Free is compared with a train-only FFT/DCT logistic-regression baseline.", "body"),
            (primary_text, "callout"),
            ("A small local Qwen model selects allowed investigation tools from observed measurements, under a four-call default budget. Its factual report is calculated from evidence records rather than generated freely. A separate 24-source score-replay experiment compares fixed, rule-based and language-model policies. The contribution is a reproducible measurement and investigation system; the study does not establish universal detection accuracy, calibrated authenticity probabilities or superiority of an AI agent.", "body"),
            ("Research questions", "heading"),
            ("RQ1: How do repeated JPEG compression, repeated resizing, processing order and matched-size single-pass controls change detector discrimination and fixed-threshold decisions? RQ2: Can a bounded observation-driven policy identify processing-sensitive evidence while making fewer tool calls than a fixed workflow? RQ3: How can the interface communicate measured evidence and uncertainty without conflating generation detection with manipulation localization?", "body"),
        ]),
        ("Dataset and experimental design", [
            ("A documented, grouped pilot", "heading"),
            ("The data come from the official Synthbuster release and the real RAISE-1k subset distributed for B-Free's extended Synthbuster evaluation. Four generators were selected before scoring: DALL-E 3, Adobe Firefly, Midjourney v5 and Stable Diffusion XL. Each contributes 40 generated images matched to 40 distinct real photographs by the common RAISE filename stem. A real photograph is used once. SHA-256-ranked selection with fixed seed 20261018 creates 160 groups. Each generator stratum contributes 8 training, 8 validation and 24 test groups: 64, 64 and 192 images overall. [5, 6]", "body"),
            ("The acquisition script retrieves only selected ZIP members using HTTP byte ranges, verifies original ZIP CRC values, and records source URLs and file hashes. Selection is frozen before downloads and missing files are not silently replaced. Original release bytes are retained. The full manifest, source metadata, license files and selection plan are available with the project. Synthbuster uses CC BY-NC-SA 4.0; RAISE carries scientific/research and noncommercial terms.", "body"),
            ("The real release has already been resized to approximately one megapixel, while synthetic files retain different delivered dimensions. These are released originals, not uniformly pristine camera/generator outputs. Content, generator, dimension and prior-processing differences may affect absolute classification performance. Within-source processing changes are therefore the central result. Synthbuster was used in upstream B-Free research: project-held-out test images are not claimed to be unseen during all upstream model development.", "callout"),
            ("Prespecified conditions", "heading"),
            ([["Arm", "Operations and final observation"], ["Original", "RGB-normalized lossless baseline; no experimental distortion."], ["JPEG x1 / x3", "Quality 85, 4:2:0; score after one or three cumulative encodes."], ["Resize x1 / x3", "LANCZOS; 90% per round, score after round 1 or 3."], ["Resize + JPEG x1 / x3", "90% resize then quality-95 JPEG at each round."], ["Reversed order x3", "Quality-95 JPEG then 90% resize, repeated three times."], ["Matched single pass", "Start from original; resize directly to round-3 dimensions and JPEG once."]], "table"),
            ("At round r, target dimensions equal round(original dimension x 0.9^r). Cumulative arms use the previous decoded image. Independent controls use the original at the matched final dimensions. A JPEG-then-resize result is stored as PNG to avoid an extra unplanned JPEG encode. Every derivative remains associated with its original source and matched group.", "body"),
        ]),
        ("Models, measurements and statistical analysis", [
            ("Detector and classical baseline", "heading"),
            ("B-Free uses the official pretrained DINOv2-based implementation and its native normalization and embedding-view aggregation. The adapter retains the raw logit and its sigmoid. The fixed positive rule is score > 0.5, equivalent to logit > 0; equality is negative. The official checkpoint and source revision are hashed. Four integration samples were checked against upstream reference logits. The MPS run differed from the CPU check by at most 0.000035 logit units, with identical decisions. No B-Free fitting or threshold tuning uses this pilot. [1, 2]", "body"),
            ("The comparator uses 79 features: 16 radial FFT log-power averages and 63 mean absolute block-DCT AC coefficients. Normalized RGB images are converted to luminance and resized to 256 x 256. Mean and standard deviation are fitted on training originals only. A fixed L2 logistic regression (penalty coefficient 0.01) is fitted by deterministic Newton optimization. Its features, optimizer and threshold are frozen; validation images are reserved and unused. This small baseline is an interpretable comparison, not a strong state-of-the-art detector or fallback for missing inference.", "body"),
            ("TruFor uses its official inference code to produce a local-manipulation score, anomaly map and reliability map. These address a different task from generation detection. Its maps are demonstrated in the prototype but no pixel-level localization accuracy is evaluated because the pilot provides image-level origin labels. [3, 4]", "body"),
            ("Endpoints and uncertainty", "heading"),
            ("The primary endpoint is the paired balanced-accuracy difference between three JPEG quality-85 encodes and the original at the fixed threshold. A 95% percentile interval uses 5,000 bootstrap samples of complete matched groups, retaining both real and generated sources and their paired conditions. The test set contains 96 matched groups treated as sampling units; between-group independence is an assumption. Other conditions, AUROC, average precision, TPR/FPR, confusion counts, score shifts and flips are descriptive secondary outcomes. No multiple-comparison significance claims are made.", "body"),
            ("Brier score, NLL and ten-bin positive-class ECE are exported as descriptive calibration diagnostics; sigmoid outputs are not asserted to be calibrated probabilities. AUROC assigns half credit to ties and AP groups equal scores. Failures remain missing and are journaled. Derivatives never become independent samples. Distortion is measured with RGB MSE and PSNR against the original resized directly to each derivative's dimensions; zero MSE implies infinite PSNR, represented as null with an explicit convention.", "body"),
            ("Execution and audit", "heading"),
            ("A frozen protocol hashes the manifest, normalized pixels, model checkpoint, preprocessing implementation, conditions and software versions before inference. An append-only prediction/failure journal and content-addressed score cache support exact resume without silently changing the study. B-Free test inference uses Apple MPS in float32. The frequency baseline uses NumPy. Model training provenance and all measured predictions are retained.", "body"),
        ]),
        ("Held-out detector results", [
            ("Complete nine-condition comparison", "heading"),
            (f"Each table cell is measured on the same 192 held-out images (96 real, 96 generated; 24 generated images per family). Each detector completed {test['bfree']['coverage']['actual_predictions']:,} test predictions. Recorded failure attempts: B-Free {summaries['bfree']['failure_attempts']}; FFT/DCT {summaries['frequency']['failure_attempts']}. Balanced accuracy (bAcc) uses the fixed 0.5 threshold; AUC is AUROC.", "body"),
            (result_table, "table"),
            (primary_text, "callout"),
            (frequency_text, "body"),
            ("Interpretation", "heading"),
            (secondary_text, "body"),
            ("AUROC measures ranking; balanced accuracy measures the frozen operating point. A threshold-performance change can reflect a score shift with little loss of ranking. Use the paired statistics for magnitude, and treat secondary intervals as descriptive.", "body"),
            ("These values apply to this small, balanced released-data pilot, with possible upstream exposure and class-processing confounds. They do not establish performance on arbitrary internet uploads or unknown generators. Stable averages and high individual scores do not verify an image's origin.", "body"),
        ]),
        ("Robustness across conditions", [
            (str(STUDY / "figures/detector_robustness.png"), "figure"),
            ("Figure 1. Measured balanced accuracy and AUROC on the common 192-image test set. These are nine conditions on the same sources, not independent experiments. The FFT/DCT comparator was fitted only on training originals.", "caption"),
            (str(STUDY / "figures/paired_balanced_accuracy_changes.png"), "figure_small"),
            ("Figure 2. Paired changes from original balanced accuracy, with 95% group-bootstrap intervals. Only JPEG quality-85 round 3 is the prespecified primary endpoint; other intervals are descriptive.", "caption"),
        ]),
        ("An observation-driven forensics assistant", [
            ("Finite tools, actual language-model choices", "heading"),
            ("The application performs one mandatory original B-Free measurement, then supplies its observations and the remaining budget to a local Qwen2.5-1.5B-Instruct model. The model chooses among one JPEG Q85 pass, three JPEG Q85 passes, one 90% resize, three resize/Q95 rounds, optional TruFor, and finish. Every perturbation branch starts from the original; repeated operations occur within that branch. Only the branch's final image is scored. [7]", "body"),
            ([["Stage", "Responsibility"], ["Observe", "Read image dimensions and actual model measurements."], ["Choose", "Qwen scores the tokens for offered numbered actions."], ["Validate", "Dispatcher enforces the allowlist, no repeats, and call budget."], ["Execute", "Run the chosen detector tool and record evidence with an ID."], ["Reassess", "Feed the new observations back; stop or select another tool."], ["Explain", "Compute a factual report from cited measurement records."]], "table"),
            ("This is constrained next-token action selection: the highest-logit allowed digit selects a tool. It is not a hardcoded score-routing loop, nor free-form command generation. The default cap is four detector-tool attempts including the original, adjustable from two to six. Failures consume budget. Cancellation takes effect between calls. A fixed policy and a rule policy remain explicitly separate comparators. There is no rule fallback when the language model fails.", "body"),
            ("The planner sees numeric observations, not image pixels, filenames, embedded metadata text or ground-truth labels. No arbitrary code, shell or network tool is available. Model action weights describe relative preference over the offered actions, not forensic confidence. The audit trace retains observed evidence, offered actions, chosen action, prompt/policy hashes, model hashes, runtime and device. Action ordering is fixed and possible positional bias is unmeasured.", "body"),
            ("Grounded uncertainty in the UI", "heading"),
            ("The report builder calculates score ranges, decision changes and successful-test counts directly from evidence E1, E2 and so on. It does not ask the model to invent a final rationale. If no perturbation succeeds, the result says robustness evidence is insufficient. The interface separates fixed trajectories from adaptive branches, shows actual manipulation/reliability maps when available, and exports JSON/CSV. B-Free and TruFor are never merged into one authenticity score.", "body"),
        ]),
        ("Policy comparison and observed behavior", [
            ("A separate 24-source replay pilot", "heading"),
            ("Three matched real/generated test groups per generator were selected by a fixed SHA-256 ranking before policy scoring. The 24-source subset compares a fixed four-call sequence, an explicit rule baseline and local Qwen under the same four-call budget. Each policy receives only observations for tools it selects. Recorded B-Free scores are replayed to avoid redundant inference; newly measured planner runtime is separate from recorded detector time. TruFor is disabled for matched replay because the benchmark does not include regional observations.", "body"),
            ("The reference event is a threshold change in any of the four available perturbation branches. Discovery recall is the fraction of reference-unstable images on which the policy observes at least one change. It is not image-authenticity accuracy. A four-call budget includes the original and therefore cannot exhaust all four perturbations.", "body"),
            (policy_table, "table"),
            (" ".join(policy_checks), "body"),
            ("Interpretation and limits", "heading"),
            (policy_interpretation, "body"),
            ("The comparison describes tool-use cost and discovery within a finite catalog. The small sample supports no inferential superiority claim, and failure to find a change is not evidence of general robustness. Budget compliance, valid actions and evidence-reference validity are checked structurally; they do not establish human-rated explanation quality. Qwen used the same three-test sequence for all 24 images.", "body"),
            ("Real end-to-end example", "heading"),
            (demo_table, "table"),
            (f"The official B-Free img0002 example was used for integration, separately from the benchmark. Qwen chose three JPEG passes, then a resize, then finish, using {demo['model_tool_calls']} of four model calls in {demo['runtime_seconds']:.1f} seconds including initial planner loading. The report correctly identified one threshold change. This is an illustrative execution, not representative runtime or a policy-quality estimate.", "body"),
        ]),
        ("Regional evidence and validity limits", [
            ("Manipulation maps answer a different question", "heading"),
            ("TruFor was run on the official 256 x 256 tampered2 example. It returned an actual manipulation score of 0.998346 and the maps below. No pixel-accuracy metric was calculated. The same integration also ran TruFor on the B-Free img0002 original, obtaining 0.032239 despite B-Free's 0.988232 AI-generation score. Fully generated content can lack a localized inconsistency; the outputs address different tasks. [2, 4]", "body"),
            ("regional_demo", "regional"),
            ("Figure 3. Official TruFor example: source, manipulation-anomaly map, localization reliability, and overlay. Anomaly uses a fixed blue-to-red 0-1 scale; reliability uses black-to-white. Neither map is AI-pixel attribution.", "caption"),
            ("Threats to validity", "heading"),
            ("The pilot has four known generator families, no newly held-out generator family, a small training set and source-dependent preprocessing. Related groups can still share scene properties across splits; grouped selection does not guarantee semantic independence. Upstream research exposure is possible. The bootstrapped interval reflects group sampling variation within this design, not every source of model or dataset uncertainty.", "body"),
            ("Repeated encoding at fixed quality may stabilize, while screenshots, mixed generated/real content, different encoders, prior compression and severe resizing may behave differently. Very small images can alter detector padding/cropping behavior. The local planner is small and does not visually inspect content. It can stop early, choose redundant scientific tests or overlook a useful branch despite valid dispatch. The deterministic report protects measurement grounding but cannot fix a poor investigation strategy.", "body"),
            ("Next research steps", "heading"),
            ("Expand the dataset with independent sources and new generator families; repeat the study with controlled release formats and dimensions; evaluate policy repetitions and action-order randomization; compare latency in full end-to-end runs; and separately evaluate regional localization with masks and human review. Threshold calibration, if introduced, must use validation data and be frozen before new test evaluation.", "body"),
        ]),
        ("Reproduction and references", [
            ("Run the prototype and inspect the evidence", "heading"),
            ("Start with bash scripts/start-with-models.sh and open http://127.0.0.1:8765. The fixed mode runs explicit transformations; Adaptive investigation uses the local Qwen model. Images and outputs remain on this machine. Each saved run contains source bytes, hashes, measured evidence and exports. The browser has no public deployment or account layer.", "body"),
            ("Reproduce acquisition with scripts/acquire_benchmark.py; freeze a new study with python -m forensics.benchmark freeze; execute with its run subcommand and a configured detector. The delivered output/benchmark/protocol.json is immutable and identifies the completed pilot. Exact commands are documented in README.md and docs/BENCHMARK_PROTOCOL.md. Re-run tests with .venv/bin/python -m unittest discover -s tests -v.", "body"),
            (f"Detector study hash: {protocol['protocol_hash']}. Agent evaluation hash: {agent['protocol_hash']}. Detailed results: output/benchmark/results/*/predictions.csv and summary.json; output/agent-evaluation/episodes.jsonl and summary.json. Editable narrative: docs/RESEARCH_WRITEUP.md. Figures are exported as PNG and PDF.", "reference"),
            ("References", "heading"),
            ("[1] Guillaro et al. A Bias-Free Training Paradigm for More General AI-generated Image Detection. arXiv:2412.17671. https://arxiv.org/abs/2412.17671", "reference"),
            ("[2] GRIP-UNINA. B-Free official code and released evaluation data. Revision c6a9f898782fb466b29af01f21960b67415afb0e. https://github.com/grip-unina/B-Free", "reference"),
            ("[3] Guillaro et al. TruFor: Leveraging All-Round Clues for Trustworthy Image Forgery Detection and Localization. CVPR 2023. https://openaccess.thecvf.com/content/CVPR2023/html/Guillaro_TruFor_Leveraging_All-Round_Clues_for_Trustworthy_Image_Forgery_Detection_and_CVPR_2023_paper.html", "reference"),
            ("[4] GRIP-UNINA. TruFor official implementation. Revision ae54475df6f41a491d7615100feb19263dec13f7. https://github.com/grip-unina/TruFor", "reference"),
            ("[5] Synthbuster official dataset release, Zenodo record 10066460. https://zenodo.org/records/10066460", "reference"),
            ("[6] RAISE dataset, University of Trento; subset distributed with B-Free extended Synthbuster. https://loki.disi.unitn.it/RAISE/", "reference"),
            ("[7] Qwen Team. Qwen2.5-1.5B-Instruct model card. Revision 989aa7980e4cf806f80c7fef2b1adb7bc71aa306. https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct", "reference"),
            ("[8] ForgeryVCR. Related tool-driven forensics architecture; its implementation is not a dependency of this prototype. https://github.com/youqiwong/ForgeryVCR", "reference"),
            ("[9] Mobbin UI research: Higgsfield editing and Magnific preview patterns. https://mobbin.com/screens/73d5ba0d-57b7-4468-901c-ad060319ff66 and https://mobbin.com/screens/7e4ff51f-2eee-4468-8962-1072825d901e", "reference"),
        ]),
    ]
    render(chapters)


def render(chapters):
    ink, teal, muted = colors.HexColor("#162839"), colors.HexColor("#087d88"), colors.HexColor("#52616e")
    styles = {}
    for name, size, leading in [("body", 9.7, 13.3), ("heading", 13, 17), ("title", 27, 31),
                                ("subtitle", 15, 20), ("meta", 9, 13), ("callout", 10.2, 14),
                                ("reference", 8.1, 11), ("caption", 8.4, 11)]:
        styles[name] = ParagraphStyle(name=name, fontName="Helvetica-Bold" if name in {"heading", "title", "subtitle"} else "Helvetica",
            fontSize=size, leading=leading, textColor=teal if name in {"heading", "subtitle"} else muted if name in {"meta", "caption"} else ink,
            spaceAfter=8 if name == "body" else 6 if name in {"reference", "caption"} else 10, spaceBefore=4 if name == "heading" else 0,
            borderPadding=8 if name == "callout" else 0, backColor=colors.HexColor("#edf5f5") if name == "callout" else None,
            splitLongWords=True, keepWithNext=name in {"heading", "title", "subtitle"})
    cell_style = ParagraphStyle("cell", parent=styles["body"], fontSize=8.3, leading=11, spaceAfter=0)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(OUTPUT), pagesize=(595.28, 841.89), leftMargin=45, rightMargin=45, topMargin=58, bottomMargin=46,
                            title="Evaluating AI-Generated Image Detection Under Repeated Compression and Resizing", author="AI Image Forensics Project")
    story, markdown = [], []
    for index, (chapter, items) in enumerate(chapters):
        if index:
            story.append(PageBreak())
            story.append(Paragraph(escape(chapter), styles["subtitle"]))
        markdown.append(f"\n## {chapter}\n")
        for content, kind in items:
            if kind == "table":
                cols = len(content[0])
                widths = ([125, 380] if cols == 2 else [50, 170, 100, 185] if cols == 4 else [145, 90, 90, 90, 90])
                table = Table([[Paragraph(escape(str(cell)), cell_style) for cell in row] for row in content], colWidths=widths, repeatRows=1, hAlign="LEFT")
                table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e7f0f0")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 7), ("LINEBELOW", (0, 0), (-1, -1), .35, colors.HexColor("#d8e0e3"))]))
                story.extend([table, Spacer(1, 12)])
                markdown.extend(["| " + " | ".join(map(str, row)) + " |" for row in content[:1]])
                markdown.append("| " + " | ".join(["---"] * cols) + " |")
                markdown.extend("| " + " | ".join(map(str, row)) + " |" for row in content[1:])
                markdown.append("")
            elif kind in {"figure", "figure_small"}:
                width = 485 if kind == "figure" else 400
                from PIL import Image as PILImage
                with PILImage.open(content) as image:
                    height = width * image.height / image.width
                figure = Image(content, width=width, height=height)
                figure.keepWithNext = True
                story.append(figure)
                markdown.append(markdown_image("Measured figure", content, ROOT))
            elif kind == "regional":
                regional = read(ROOT / "output/model-verification/trufor-small-reference-check.json")
                files = [ROOT / "external/TruFor/test_docker/images/tampered2.png", Path(regional["heatmap_path"]), Path(regional["reliability_path"]), Path(regional["overlay_path"])]
                grid = Table([[Image(str(path), width=116, height=116) for path in files],
                              [Paragraph(label, styles["caption"]) for label in ["Source", "Anomaly", "Reliability", "Overlay"]]], colWidths=[126]*4)
                grid.keepWithNext = True
                story.extend([grid, Spacer(1, 8)])
                markdown.extend(markdown_image(label, path, ROOT) for path, label in zip(files, ["Source", "Anomaly", "Reliability", "Overlay"]))
            else:
                story.append(Paragraph(escape(content), styles[kind]))
                markdown.append(("### " if kind == "heading" else "# " if kind == "title" else "") + content + "\n")

    def furniture(canvas, document):
        canvas.setStrokeColor(colors.HexColor("#d6e0e4"))
        canvas.line(45, 806, 550, 806)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(muted)
        canvas.drawString(45, 817, "AI IMAGE FORENSICS  /  CONTROLLED PILOT")
        canvas.drawString(45, 28, "Measured evidence. Bounded tools. Explicit uncertainty.")
        canvas.drawRightString(550, 28, str(document.page))
    doc.build(story, onFirstPage=furniture, onLaterPages=furniture)
    (ROOT / "docs/RESEARCH_WRITEUP.md").write_text("\n".join(markdown), encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    build()

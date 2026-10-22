<div align="center">

# Documentation

### Operate the workspace. Understand the methods. Evaluate the evidence.

**Non-contact Fatigue Detection System**

[Product overview](../README.md) &nbsp; | &nbsp; [Operations guide](guides/operations.md) &nbsp; | &nbsp; [Find a topic](#find-a-topic) &nbsp; | &nbsp; [Read the evidence](#read-the-evidence)

</div>

---

## Choose your starting point

| Explore the product | Run the system | Investigate the design |
| :--- | :--- | :--- |
| [Product README](../README.md) | [Operations & Validation Guide](guides/operations.md) | [System overview](technical/system_overview_technical_report.md) |
| Capabilities, first installation, platform readiness, and core technical principles | Launch, camera troubleshooting, tuning, BLE calibration, replay, packaging, and acceptance checks | Inputs, outputs, architecture, algorithms, and known limitations |

The product README, this index, and the operations guide are in **English**. Most technical reports, historical records, plans, and supplementary tool guides remain in **Traditional Chinese**. A report's presence does not mean its experiments or proposed features describe the current release.

## Find a topic

### Architecture and analysis

| Topic | Reference | Reading context |
| :--- | :--- | :--- |
| Current macOS source and installed runtime audit | [REA audit and fixes](technical/macos_rea_audit_2026-10-22.md), [module and contract inventory](technical/macos_rea_module_inventory_2026-10-22.md) | 2026-10-22 evidence, module decisions, regression checks, and explicit hardware limits |
| System inputs, outputs, methods, and limits | [System technical overview](technical/system_overview_technical_report.md) | Start here for the complete monitoring pipeline |
| Data flow, modules, and algorithm relationships | [Architecture and algorithm map](technical/system_architecture_algorithm_map.md) | Connect implementation responsibilities to their inputs and outputs |
| ROIs, pulse separation, filtering, BPM, and HRV | [rPPG technical report v2](technical/rppg_technical_report_v2.md) | The [product README](../README.md#technical-design) records the actual `pos_pulse` formula and its naming limits; the [earlier report](technical/rppg_technical_report.md) preserves design history |
| EAR, PERCLOS, gaze, expressions, and fatigue fusion | [MediaPipe behavioral-fatigue report](technical/mediapipe_fatigue_technical_report.md) | Read alongside current code and validation evidence |

### Calibration, communication, and replay

| Topic | Reference | Reading context |
| :--- | :--- | :--- |
| Calibration models, quality gates, and reference measurements | [Heart-rate calibration analysis](technical/rppg_heart_rate_calibrator_technical_analysis.md) | Includes a retired watch workflow; use the operations guide for current BLE procedures |
| Measured belt services and characteristics | [Heart-rate belt GATT profile](technical/heart_rate_belt_bluetooth_gatt_profile.md) | Device-level reference for the measured belt |
| Bluetooth/BLE protocols and integration | [Bluetooth and BLE guide](technical/bluetooth_ble_protocol_global_guide.md) | Broader communication background |
| Offline replay, output reports, and validation limits | [UTA-RLDD replay-validation report](technical/utarldd_replay_validation_report.md) | Distinguish video-level labels from frame-level ground truth |

### Application, design, and review

| Topic | Reference | Reading context |
| :--- | :--- | :--- |
| UAV operator use cases | [Application positioning](technical/drone_operator_fatigue_application_report.md) | Intended monitoring context and application boundaries |
| Improvement proposals | [System optimization report](technical/drone_operator_system_optimization_report.md) | Recommendations require implementation and validation before being treated as delivered features |
| Poster and interface research | [Poster design source](technical/rppg_fatigue_monitoring_poster_design.md), [Pavise UI analysis](technical/pavise-ui-analysis.md) | Supporting design material; image/document exports remain local |
| Artifact analysis and implemented corrections | [2026-10-22 REA report](reviews/2026-10-22-rea-report.md) | Evidence identities, coverage, observations, inferences, fixes, and unverified areas |

## Documentation map

| Directory | Contents | How to use it |
| :--- | :--- | :--- |
| [`guides/`](guides/) | Current operations, diagnostics, and validation commands | Check the target platform, hardware, and local assets before execution |
| [`technical/`](technical/) | System and subsystem technical reports | Some sections preserve earlier designs; use the README and operations guide for current procedures |
| [`reviews/`](reviews/) | REA findings, evidence boundaries, and improvement records | Separate observations, inferences, and unverified claims |
| [`benchmarks/`](benchmarks/) | Saved test/performance JSON | Compare dates, platforms, modes, environments, and measurement limits |
| [`history/`](history/) | Dated calibration, experiment, and development records | Trace a specific version; do not generalize its results to every current configuration |
| [`plans/`](plans/) | Migration, platform separation, and future-work proposals | A plan is not proof of completed functionality |

## Read the evidence

Different checks establish different things:

| Evidence | What it can establish | What it does not establish by itself |
| :--- | :--- | :--- |
| Face-detection rate | Whether the face tracker obtained usable detections in the evaluated input | Fatigue-classification accuracy |
| Video completion rate | Whether a batch processed its inputs | Correct physiological estimates or decisions |
| Golden-output comparison | Whether selected outputs drift from a defined numerical baseline | Correctness against real-world labels |
| AUC and label-association measures | Relationships between scores and the evaluated labels/data split | Generalization to new users or UAV operating conditions |
| Camera hardware smoke | Pipeline lifecycle and frame origin on the tested setup | BLE acceptance, a complete UI/installer check, or fatigue accuracy |
| Static artifact analysis | Recorded properties and bounded code/resource evidence | Execution paths, runtime behavior, or complete coverage beyond the stated scope |

Historical measurements include the [2026-06-07 UTA-RLDD analysis](history/2026-06-07-utarldd-analysis.md) and [2026-07-03 fatigue-calibration study](history/2026-07-03-fatigue-accuracy-calibration.md). Their numbers apply to the documented data, configuration, and version.

After numerical changes, rerun the relevant evaluation. If the dataset or hardware is unavailable, state which checks were not run. The [operations guide](guides/operations.md#replay-and-validation) explains golden checks, label association, and replay interpretation.

## Local assets and generated reports

| Location | Local contents | Version-control boundary |
| :--- | :--- | :--- |
| `docs/images/` | Images, source diagrams, and artwork | Excluded from Git |
| `docs/exports/` | Generated PDFs, presentations, and document exports | Excluded from Git; Markdown remains the maintained source |
| `recordings/` | Videos, SQLite metrics, replay CSV/HTML, and manifests | Excluded from Git |
| Personal baseline and calibration paths | User-, device-, and environment-specific settings/results | Kept local; see the operations guide |

A report referencing a local asset does not mean a fresh checkout contains it. The report-generation commands in the [operations guide](guides/operations.md#supporting-tools-and-reports) rebuild PDFs from the required Markdown, experiment data, artwork, and available fonts; generating a document does not create new experimental evidence.

The optional [Canva flowchart app](../tools/canva-flowchart/README.md) lives in `tools/canva-flowchart/`. Select a local PNG/JPEG, inspect its preview, and then insert it into the Canva design. Preview is local; insertion uploads the image to Canva. Images do not need to be added to Git.

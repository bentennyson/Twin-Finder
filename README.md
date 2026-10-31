# Twin Finder desktop AI project 
Twin Finder identifies candidate duplicate publications, explains a learned matching score, learns proposed classifier updates from reviewed pairs, and exports only reviewer-approved consolidations. The desktop application selects local files directly; it does not upload bibliographic records to an external AI service.

This is the complete replacement source project for an 8 GB Windows computer. Keep the earlier project in a separate archive. Do not overlay isolated files from this version onto an older engine: the interface, model, storage format and research results must agree.

## Run from source

Use 64-bit Python 3.13 with Tcl/Tk (the standard python.org Windows installer includes it). In this project directory:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install torch==2.10.0 --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe desktop.py
```

The pinned, converted pretrained encoder and trained base classifier are supplied in `models/`. Normal use is offline. Model integrity is checked when the encoder loads. `research/prepare_encoder.py` reproduces the conversion from the declared public model revision; add `--download` only if that revision is not cached. Conversion requires the research dependencies.

Choose **Open dataset** and select a UTF-8 CSV or JSONL file. Standard columns are detected automatically; ambiguous mappings require confirmation. A working folder is created beside the source under `TwinFinderJobs`. Review begins as the first AI-scored pairs arrive, while import and discovery continue. Use **File → Recent datasets** or **Open saved work**, then **Resume processing**, to continue. See `USER_MANUAL.md` for the full workflow and limitations.

## What is AI and what learns

A frozen all-MiniLM-L6-v2 encoder produces 384-dimensional title embeddings. A trainable logistic classifier combines semantic title similarity, title edit similarity, author-token overlap, venue/year equality and availability indicators. The score is not an externally calibrated probability. The explanation shows the actual feature values and additive contributions to the classifier's logit; it does not explain individual neural tokens.

The base classifier is trained on the supplied benchmark's reconstructed training partition. Operator accept/reject decisions can train a new small classifier anchored to that base model. The encoder is not fine-tuned. Feedback records have fixed training or validation assignments; pairs spanning the two roles are excluded from fitting. At least 8 positives and 8 negatives are required for training, and 4 of each for validation. Those are operational minimums, not statistical guarantees. Threshold selection for a feedback proposal uses training labels. Its validation F1 must not fall, and recall may fall by at most 0.02; the operator must explicitly activate it. This guard is a heuristic, not significance testing. Repeated validation is development monitoring.

Review events retain the machine output at decision time. Label revisions invalidate old proposals. Model versions and activation/rollback actions remain in the job. Accepted links alone permit merging; an explicit rejection inside an accepted component blocks export.

## Progressive processing

`progressive.py` implements resumable 250-record imports, short SQLite WAL transactions, a roughly 50-pair ready buffer, and stable appended pair identifiers. It bounds each incoming record to 32 prior candidates from exact titles and up to three rare token blocks, with a 3,000,000-comparison budget and a 100,000-pair unscored reservoir. When a `source` column exists, unscored cross-source pairs receive scheduling priority. Source identity never decides the match. Remaining candidates are scored up to the review queue limit after the file is read. New records continue to import after a candidate limit is reached. Labels, model changes and processing state are serialized safely; partial imports cannot be exported as complete data.

The encoder pads to the longest title in each batch rather than always to 256 tokens; the truncation limit and learned model are retained. Identical normalized titles reuse cached embeddings in a progressive job. `results/progressive_performance.json` records the real-data timing; `results/progressive_coverage.json` records known-link retrieval separately from classifier accuracy. The first 50 pairs were available in 4.35 seconds in the measured run; full processing took 74.94 seconds. Neither is a guarantee for arbitrary files.

## Legacy jobs and large data behavior

CSV and JSONL/NDJSON are streamed into SQLite. JSON arrays, nested JSON and non-UTF-8 input are not accepted in large-file mode; convert them first. Each record must be at most 8 MiB and have at most 256 fields. Total dataset size has no fixed application upload cap. Disk space, filesystem limits, processing time, the current candidate budget and review volume remain finite constraints.

Import commits every 1,000 records, retaining the source byte offset. A stable source path, size, modification time and mapping are required to resume. A full input hash is saved on completion. AI embeddings are committed in batches of 8, with two CPU threads. Only records appearing in the bounded review queue are embedded; an entire million-record corpus is not embedded automatically. Candidate generation restarts safely after cancellation. Review/model state is atomically saved in the job; only one writer may change a job at once. Back up the whole job folder while idle. Do not delete its database or move/change an input while an import is incomplete.

The retained legacy terminal preparation and research reference prioritize identical normalized titles, then shared informative title tokens. Blocks larger than 100 are skipped; large exact-title groups use star links. The title edit prefilter is greater than 0.5. Defaults are 10,000 returned pairs and 3,000,000 candidate iterations. The UI reports skipped blocks, budget exhaustion and queue truncation. These settings constrain candidate coverage; an arbitrary large dataset is not searched exhaustively. Create another job to change a prepared queue's mapping or limits. Neural similarity scores lexical candidates and cannot recover a pair that blocking missed.

Records, token indexes, cached embeddings, temporary exports and final exports require additional disk space beyond the source file. Import/export stop with an error if free space falls below the reserve. SQLite sorts use temporary files, which can also use the operating system's temporary drive. Export memory depends on the bounded review graph and conflicts within accepted components; review history grows with user actions. No constant-memory claim is made for unlimited review histories or arbitrarily large merged groups.

## Terminal interface

```powershell
python cli.py start --input sample.csv --job C:\TwinFinderJobs\progressive_demo
```

Legacy/reference commands:

```powershell
python cli.py import --input sample.csv --job C:\TwinFinderJobs\demo
python cli.py prepare --job C:\TwinFinderJobs\demo
python cli.py inspect --job C:\TwinFinderJobs\demo --pair 1
python cli.py review --job C:\TwinFinderJobs\demo --pair 1 --decision accept
python cli.py counts --job C:\TwinFinderJobs\demo
python cli.py propose --job C:\TwinFinderJobs\demo
python cli.py activate --job C:\TwinFinderJobs\demo --proposal 1
python cli.py rollback --job C:\TwinFinderJobs\demo --version 0
python cli.py export --job C:\TwinFinderJobs\demo --output C:\TwinFinderJobs\cleaned.zip
```

The small sample is sufficient for scoring/review/export, but does not meet the training/validation label minima. Use `research/feedback_demo.py` for the explicitly simulated learning demonstration.

The desktop progressive path and terminal `start` command both call `progressive.py`; review, learning and export share `twin_workflow.py` and `storage.py`. The legacy `import`/`prepare` commands remain used for saved-job compatibility and reproducible reference experiments. The web version has been removed from the submitted project; no web deployment is required.

## Reproduce the evidence

```powershell
python -m pip install -r requirements-research.txt
python -m pytest tests -q -p no:cacheprovider
python research/evaluate.py
python research/feedback_demo.py --work C:\TwinFinderJobs\feedback_demo
python research/stress_test.py --work C:\TwinFinderJobs\scale_test
python research/generate_figures.py
python research/verify_evidence.py
```

Choose NEW work folders for the feedback and scale demonstrations. The scale test generates up to one million synthetic rows and consumes roughly a gigabyte including the source and working database; exports and other jobs need additional space. These scripts do not operate on your original project folder.

The benchmark's original pair partitions share records. The replacement evaluates a fixed, known-positive-component partition and excludes cross-partition pairs. It is a retrospective reanalysis of a previously inspected corpus, not an untouched external test. Both the neural-plus-metadata classifier and metadata-only ablation achieve the same F1 in the measured run. Simulated benchmark-label replay is not a librarian study or proof of improvement on unseen human-reviewed data. See the delivered report and `results/` manifests.

## Source and artifact purposes

| File or folder | Purpose |
|---|---|
| `progressive.py` | Incremental import/discovery, live queue, title cache and stable review identifiers |
| `desktop.py` | Native Tk desktop interface and packaged launch smoke check |
| `modern_ui.py` | Used interface components, typography and source-launch DPI setup |
| `windows.manifest` | DPI-awareness declaration embedded by the Windows builder |
| `cli.py` | Terminal interface using the same matching and feedback services as the desktop |
| `twin_workflow.py` | Shared prepare, inspect, review, propose, activate and rollback services |
| `storage.py` | Streaming import, SQLite records/indexes/features, locks, resumable checkpoints, disk export |
| `ai_model.py` | Frozen neural inference, features, deterministic classifier training and explanations |
| `twin_core.py` | Bibliographic evidence, audit/metric primitives and small reference candidate generator used in coverage tests |
| `models/` | Used encoder, tokenizer, learned classifier, checksums and model license |
| `data/dblp_acm/` | Five supplied benchmark inputs used by evaluation |
| `sample.csv` | Declared synthetic user-manual fixture |
| `research/` | Encoder conversion, measured evaluation, feedback simulation, scale test and figure generation |
| `tests/` | Failure, recovery, parity, feedback and export checks |
| `results/` | Predictions, split assignments, measured tables, provenance, figures and verification evidence |
| `build_windows.py`, `build_windows.ps1` | Packaging commands; Python builder avoids shell script-policy issues |

No author-identity resolver, institution normalizer, unused checkpoint, alternate matcher or old output collection is included as an implemented component.

## Reproduce progressive measurements

Download DBLP–Scholar from https://dbs.uni-leipzig.de/research/projects/benchmark-datasets-for-entity-resolution and use `research/prepare_bibliographic_dataset.py` on its ZIP to combine the two sources. Preserve its reference mapping separately. Then run:

```powershell
python research/benchmark_progressive.py --input <combined.csv> --job <new-job-folder> --output results/progressive_performance.json
python research/check_progressive_coverage.py --work <new-work-folder> --scholar-job <measured-job-folder> --scholar-mapping <perfectMapping.csv>
```

The Scholar source overlaps the DBLP source of the training benchmark; it is not an independent generalization test. Its measured known-link retrieval is 4,417/5,347 (82.61%). The old synthetic million-record measurements concern the retained legacy import/retrieval path, not the new progressive neural pipeline.

## Final verification and manual images

The final automated log is results/final_tests.txt. results/live_review_verification.json records 80 scripted saves during a real 66,879-record scan, safe pause/resume, preserved audit events and export. These engineering labels are not accuracy evidence. docs/screenshots contains actual application captures and their hashes; research/capture_manual.py reproduces them using isolated teaching/replay jobs. See DELIVERY_VERIFICATION.md for packaging and test scope.

Reproduce the real-input checks with a new job/work directory for every command:

```powershell
python research/benchmark_progressive.py --input "D:\Sample run\DBLP-Scholar_prepared\bibliographic_records.csv" --job C:\TwinFinderJobs\timing --output results/progressive_performance.json
python research/check_progressive_coverage.py --work C:\TwinFinderJobs\coverage --scholar-job C:\TwinFinderJobs\timing --scholar-mapping "D:\Sample run\DBLP-Scholar_perfectMapping.csv"
python research/verify_live_review.py --input "D:\Sample run\DBLP-Scholar_prepared\bibliographic_records.csv" --work C:\TwinFinderJobs\concurrency
```

Adjust input paths to the downloaded Leipzig files. research/prepare_bibliographic_dataset.py converts the original DBLP–Scholar archive without modifying it. data/dblp_scholar/README.md records the source and hashes; the external archive is not silently replaced by synthetic records.

## macOS test build

The macos-build branch adds Apple-silicon macOS 15+ packaging. See PACKAGING_MACOS.md and MACOS_BUILD_STATUS.md. The automated Mac run passed all 28 tests, then verified the app and the copy inside its DMG. The initial download is ad-hoc signed and has not been notarized by Apple.

Windows report evidence and screenshot provenance refer to the Windows snapshot d2449e69aff0843130383317e4d534604a103b19. Reproduce its full evidence check on that commit. Mac font/settings changes do not alter the AI or feedback services; the Windows report makes no Mac timing or usability claims.

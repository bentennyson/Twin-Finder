# Delivery verification

This revision addresses the 17 recorded committee comments through implementation, reproducible measurements, explicit limits and removal of unsupported claims. The response document maps each Word comment ID to report sections and source evidence. Committee acceptance is not assumed.

## Executed checks

- 28 automated tests passed in 19.97 seconds with two TorchScript deprecation warnings. The final suite covers shared CLI/desktop services, real neural inference, exact explanations, review navigation, source-change guards, cancellation/resume, feedback separation, activation/rollback, stale proposals, export contradictions and writer locking. See results/final_tests.txt.
- The real DBLP–Scholar operational run saved 80 scripted reviews while processing continued, paused at 13,750 imported rows, resumed to 66,879 rows, preserved all 80 audit events and stable pair identity, and exported a valid ZIP. The median save took 0.060 seconds and maximum 0.115 seconds. These scripted rejects are not human labels or accuracy evidence. See results/live_review_verification.json.
- The fresh progressive timing run reached its first scored pairs in 3.22 seconds, crossed 50 in 4.35 seconds and completed the selected 10,000-pair queue in 74.94 seconds. Peak sampled process RSS was 382.36 MiB. These are single-run observations, not guaranteed latencies.
- Classification evaluation, feedback replay, synthetic 10k/100k/1m scale measurements, candidate coverage and all four research figures were rerun. The scale monitor includes a Windows worker's descendants so it does not accidentally measure only the launcher. Shared pages can be counted twice in that process-tree sum.
- research/verify_evidence.py passes: numerical metrics reconstruct from predictions; data, source and encoder hashes match; retained pairs respect partition assignments; feedback changes match saved rows; all four figure files and nine actual-window images are present and verified.
- Nine manual screenshots were captured from the actual source application in isolated jobs. The teaching input is synthetic; the learning demonstration uses benchmark-label replay. The screenshot harness captures its own window, not other desktop applications.
- A new Windows one-folder executable was built with PyInstaller 6.21.0 from this source. It launched interactively. Help → Run diagnostics passed, reporting neural dimension 384, score 0.9829800665 and successful Tk UI construction. See results/packaged_interactive_diagnostics.json.

## Known verification limits

The packaged --self-test command launched through the agent's shell reported that Tcl init.tcl was unavailable. The same built application opened and passed diagnostics through the interactive desktop. The failed shell result is retained as results/packaged_final_diagnostics.json rather than overwritten with a false success. The cause of that launch-context difference is not conclusively established. A fresh dependency installation and a second-machine installation were not performed. The package is unsigned.

The user's earlier intermittent busy-job error was not reproduced. The final lock implementation nevertheless prevents scanner write reacquisition from overtaking a queued same-process reviewer; deterministic fairness and cross-process exclusion tests pass. This does not prove the historical error had only that cause.

The neural feature has no demonstrated F1 advantage over the metadata-only ablation on the retained retrospective partition. Replayed feedback changes seven classifications but leaves validation F1 unchanged. The million-record experiment excludes neural inference and the desktop UI. Arbitrary file sizes, exhaustive retrieval, independent generalization and improved human performance are not claimed.

## Source launch and packaging

Run desktop.py from the project environment to use the new source. An old executable does not update when source files change. Follow PACKAGING_WINDOWS.md to rebuild, or use the separately supplied new Windows folder. Keep all files in the executable folder, including _internal.

The full source archive excludes virtual environments, caches, build directories, verification working databases and obsolete result logs. SOURCE_INVENTORY.csv identifies the included files, hashes and purposes. Original reports and the previous delivery remain preserved separately from the clean submitted source.

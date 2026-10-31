# DBLP Scholar timing and retrieval inputs

These are the exact files used for the report's real-input timing, concurrent review and known-link retrieval experiments. They were copied without modifying the user's downloaded/prepared files. The prepared CSV contains 66,879 records and includes source provenance. The reference mapping contains 5,347 known cross-source positive links. It is not an exhaustive list of every possible duplicate within either source.

Source: [Database Group Leipzig entity-resolution benchmarks](https://dbs.uni-leipzig.de/research/projects/benchmark-datasets-for-entity-resolution), DBLP–Scholar. The supplied conversion helper, research/prepare_bibliographic_dataset.py, prepares the original benchmark ZIP. This helper reads this modest benchmark into memory; it is not the application's streaming importer for arbitrarily large datasets.

SHA-256 of bibliographic_records.csv: a2600158f31b5e680ea4a8606db54a49dfdb599306de3e43e407a58b6757202a

SHA-256 of DBLP-Scholar_perfectMapping.csv: 757ca3c5daa0ec77ade3300df6ee8ab9fe2a989b3d09da30be72ecf3ef8eba10

Run from the project directory using fresh working folders:

```powershell
python research/benchmark_progressive.py --input data/dblp_scholar/bibliographic_records.csv --job C:\TwinFinderJobs\timing --output results/progressive_performance.json
python research/check_progressive_coverage.py --work C:\TwinFinderJobs\coverage --scholar-job C:\TwinFinderJobs\timing --scholar-mapping data/dblp_scholar/DBLP-Scholar_perfectMapping.csv
python research/verify_live_review.py --input data/dblp_scholar/bibliographic_records.csv --work C:\TwinFinderJobs\concurrency
```

The DBLP portion overlaps the classification benchmark. These results are operational and retrieval evidence, not an independent generalization test. Original bibliographic records retain their source attribution; no claim of ownership or exclusive license is made by this project.

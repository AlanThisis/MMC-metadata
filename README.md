# PubMed / PMCID -> Accession Finder

This repository contains tools for resolving PubMed/PMC article identifiers to
study, project, submission, or dataset-level accession numbers from PMC full
text.

The repo includes:

- `index.html`: standalone browser batch tool.
- `scripts/resolve_pmcid_to_ena.py`: Python CSV resolver for `data/MMC2.csv`
  style datasets.

## What It Does

- Accepts one input per line in any of these formats:
  - PMID (numeric)
  - PMCID (for example `PMC10828421`)
  - PubMed URL (modern or legacy)
  - PMC URL (modern or legacy)
- Resolves each input to PMC context when available.
- For PMC articles, fetches full text XML and regex-scans for selected
  accession identifier families.
- Produces:
  - Batch summary counts
  - Per-item results
  - CSV export

## Browser Usage

1. Open `index.html` in a browser.
2. Paste inputs (one per line).
3. Optional: enable **Include metadata in results**.
4. Click **Run Batch**.
5. Review results in the output panel.
6. Click **Export CSV** (enabled only after a successful batch run).

## CSV Output

Default (metadata OFF) columns:

- `input_raw`
- `pubmed_url`
- `pmid`
- `pmcid`
- `is_pmc_article`
- `accessions`
- `accession_count`
- `error_message`

When metadata is ON during the run, export also includes:

- `title`
- `journal`
- `pub_year`
- `doi`
- `authors`

Notes:

- Export is one row per input article.
- Multiple accessions are deduplicated and stored as a semicolon-separated list in `accessions`.
- Export schema follows the metadata mode used when the batch was run.

## Python Resolver Usage

The Python resolver updates a CSV in place. By default it reads `data/MMC2.csv`,
processes rows with a non-empty `pmc_id`, and writes results to the `Accession`
column.

Clean misses are written as `ACCESSION_NOT_FOUND`. API/network failures are
written to `data/failed.csv` for retry instead of overwriting the main CSV row.

### Install

Using `uv` without a virtual environment:

```bash
uv run --with biopython --with pandas --with tenacity \
  python scripts/resolve_pmcid_to_ena.py --help
```

Using `pip`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/resolve_pmcid_to_ena.py --help
```

### Run On MMC2

```bash
uv run --with biopython --with pandas --with tenacity \
  python scripts/resolve_pmcid_to_ena.py \
  --input data/MMC2.csv \
  --failed data/failed.csv \
  --email your.email@example.edu
```

Useful flags:

- `--test`: run a small hardcoded PMCID set and print results only.
- `--retry`: reprocess rows in `data/failed.csv`.
- `--max-attempts 5`: max total retry attempts per failed row.
- `--rps 5`: request rate limit; keep at or below NCBI guidance for your setup.
- `--list-dbs`: list selectable database pattern groups.
- `--include-db ncbi,ena`: only search selected DB groups.
- `--exclude-db geo,arrayexpress`: search all groups except selected groups.
- `--api-key`: optional NCBI API key.

Examples:

```bash
# Test mode, no file writes.
uv run --with biopython --with pandas --with tenacity \
  python scripts/resolve_pmcid_to_ena.py --test

# Only search GSA and CNSA-style accessions.
uv run --with biopython --with pandas --with tenacity \
  python scripts/resolve_pmcid_to_ena.py --include-db gsa,cnsa

# Retry request/API failures from a previous run.
uv run --with biopython --with pandas --with tenacity \
  python scripts/resolve_pmcid_to_ena.py --retry --failed data/failed.csv
```

## APIs Used (NCBI Entrez E-utilities)

- `elink.fcgi` (`dbfrom=pubmed`, `db=pmc`, `linkname=pubmed_pmc`) for PMID -> PMC linking
- `esummary.fcgi` for PMC/PubMed metadata resolution
- `efetch.fcgi` for PMC full-text XML retrieval

## Accession Pattern Families

Supported database groups:

- NCBI SRA / BioProject: `PRJNA...`, `SRP...`
- ENA / EBI: `PRJEB...`, `ERP...`
- DDBJ DRA / BioProject: `PRJDB...`, `DRP...`, `DRA...`
- GSA / CNCB-NGDC: `PRJCA...`, `CRA...`
- CNSA / CNGBdb: `CNP...`
- NCBI GEO: `GSE...`
- ArrayExpress / BioStudies: `E-MTAB...`, `E-MEXP...`, `E-TABM...`,
  `E-GEOD...`

Reference notes and source URLs are documented in
`docs/accession_discovery_200_sample.md`.

## Operational Notes

- Fully client-side static HTML; no build step.
- Request throttling is applied in the client (~400ms minimum between Entrez requests) for safer no-key usage.
- CSV export sanitizes formula-leading cell values to reduce spreadsheet formula-injection risk.
- The Python resolver uses Entrez XML only. Rendered PMC article pages can expose
  generated sections that are absent from Entrez XML, but those pages are not
  used for reproducible batch resolution.

# PMID -> PMCID -> ENA Accession Finder

This repository contains a standalone browser tool (`index.html`) that batch-processes article identifiers and extracts ENA-style accession numbers from PMC full text.

## What It Does

- Accepts one input per line in any of these formats:
  - PMID (numeric)
  - PMCID (for example `PMC10828421`)
  - PubMed URL (modern or legacy)
  - PMC URL (modern or legacy)
- Resolves each input to PMC context when available.
- For PMC articles, fetches full text XML and regex-scans for ENA accession identifiers.
- Produces:
  - Batch summary counts
  - Per-item results
  - CSV export

## Usage

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

## APIs Used (NCBI Entrez E-utilities)

- `elink.fcgi` (`dbfrom=pubmed`, `db=pmc`, `linkname=pubmed_pmc`) for PMID -> PMC linking
- `esummary.fcgi` for PMC/PubMed metadata resolution
- `efetch.fcgi` for PMC full-text XML retrieval

## ENA Accession Regex Reference

Regex patterns are based on ENA accession formats:

- https://ena-docs.readthedocs.io/en/latest/submit/general-guide/accessions.html

## Operational Notes

- Fully client-side static HTML; no build step.
- Request throttling is applied in the client (~400ms minimum between Entrez requests) for safer no-key usage.
- CSV export sanitizes formula-leading cell values to reduce spreadsheet formula-injection risk.

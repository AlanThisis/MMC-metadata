# TODO

## Feature Roadmap (in order)

1. About panel in the HTML app
- Goal: Add a clear in-app explanation of workflow and expected outcomes.
- Implementation:
  - Add a two-panel UI (`Tool`, `About`) with simple toggle buttons.
  - Keep existing tool behavior unchanged.
  - In `About`, document:
    - PMID -> PMC check
    - PMCID resolution
    - Full-text fetch
    - ENA regex extraction
  - Add concrete examples:
    - non-PMC article
    - PMC article with no accession matches
    - PMC article with accession matches

2. Input parsing: PMID and PubMed URL
- Goal: Accept intuitive input formats.
- Implementation:
  - Add parser function:
    - If numeric, treat as PMID.
    - If URL includes `pubmed.ncbi.nlm.nih.gov/<pmid>`, extract `<pmid>`.
    - Reject anything else with clear validation feedback.

3. Multi-input batch mode (newline-separated)
- Goal: Process many articles in one run.
- Implementation:
  - Replace single-line input with textarea.
  - Parse non-empty lines independently.
  - Normalize each line to PMID via parser from step 2.
  - Process sequentially first (simpler rate-limit behavior), then consider controlled parallelism later.
  - Add explicit request throttling to stay safely under NCBI's no-key ceiling:
    - Target <3 requests/second per user
    - Start with ~400ms minimum delay between outbound E-utility requests
    - Keep this default even on GitHub Pages deployment
  - Show per-line progress and per-item status.

4. CSV export (metadata OFF baseline)
- Goal: Export minimal usable table.
- Implementation:
  - Add `Export CSV` button enabled after a run.
  - Export one row per input article.
  - OFF schema:
    - `input_raw`
    - `pubmed_url`
    - `pmid`
    - `pmcid`
    - `is_pmc_article`
    - `accessions`
    - `accession_count`
    - `error_message`
  - Multi-accession handling:
    - Store all accessions in a single `accessions` cell as a semicolon-separated list.
    - Populate `accession_count` with the number of unique accessions found.
    - Keep one-row-per-article as the default export format.
  - Optional future enhancement:
    - Add an alternate "long format" export with one row per `(article, accession)`.

5. Metadata ON/OFF toggle
- Goal: Let user choose compact vs enriched output.
- Implementation:
  - Add UI toggle: `Metadata: OFF | ON` (default OFF).
  - Keep tool execution identical; only output schema changes.

6. Metadata ON schema expansion
- Goal: Add bibliographic context for downstream triage/reporting.
- Implementation:
  - Pull metadata from Entrez summaries where available.
  - ON schema = OFF columns plus:
    - `title`
    - `journal`
    - `pub_year`
    - `doi`
    - `authors`
  - Keep one row per article for stable downstream use.

7. Validation on `data/MMC_final_data.csv`
- Goal: Demonstrate reliability against the existing labeled set.
- Implementation:
  - Build a small runner in the page (or a companion script) to process all PMIDs from the CSV.
  - Compare predicted accession presence/values to expected labels.
  - Report:
    - total records
    - successful fetches
    - PMC coverage
    - exact-match rate
    - mismatch list for manual review

## Output Schema (confirmed)

- Metadata OFF:
  - `input_raw, pubmed_url, pmid, pmcid, is_pmc_article, accessions, accession_count, error_message`

- Metadata ON:
  - `input_raw, pubmed_url, pmid, pmcid, is_pmc_article, accessions, accession_count, title, journal, pub_year, doi, authors, error_message`

## Notes

- Keep PMCID check strict with `elink.fcgi` + `linkname=pubmed_pmc`.
- Keep current accession extraction as regex-based scanning on full PMC text.
- Keep export UTF-8 CSV with proper escaping for commas/quotes/newlines.

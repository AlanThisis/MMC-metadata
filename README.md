# PMID -> PMCID -> ENA Accession Finder

This repository contains a standalone HTML tool that:

1. Accepts a PubMed ID (PMID)
2. Checks whether the article has a PMCID (via NCBI Entrez APIs)
3. If no PMCID exists, reports that it is not a PMCID article
4. If PMCID exists, fetches full text from PubMed Central and searches for ENA accessions with regular expressions

## File

- `pmid-ena-accession-finder.html`

## Usage

1. Open `pmid-ena-accession-finder.html` in a browser.
2. Enter a PMID.
3. Click **Check PMID**.
4. Review:
   - PMCID status
   - Found ENA accession numbers (deduplicated)

## APIs used

All requests are made to NCBI Entrez E-utilities:

- `elink.fcgi` with `linkname=pubmed_pmc` (PubMed -> its own PMC record)
- `esummary.fcgi` (resolve PMCID from PMC UID)
- `efetch.fcgi` (download PMC full text XML)

## ENA accession regex basis

Regex patterns are based on ENA accession formats from:

- https://ena-docs.readthedocs.io/en/latest/submit/general-guide/accessions.html

## Notes

- The tool is fully client-side and has no build step.
- NCBI may rate limit repeated requests. If needed, add `tool` and `email` parameters in the script.

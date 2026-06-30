# Accession Discovery From 200 ENA_NOT_FOUND Microbiome PMC Papers

This note records a discovery-only scan over a random sample from
`MMC2 _Rayyan_output - articles.csv.csv`. The goal was to identify non-ENA
accession families that appear in microbiome papers currently labeled
`ENA_NOT_FOUND`, not to write results back to the main dataset.

## Sampling Criteria

- Source CSV: `MMC2 _Rayyan_output - articles.csv.csv`
- Eligible rows: valid `PMC...` in `pmc_id` and `Accession Code == ENA_NOT_FOUND`
- Eligible pool size: 3,832 rows
- Sample size: 200 rows
- Random seed: 20260629
- Fetch source: NCBI Entrez `efetch`, `db=pmc`, `retmode=xml`
- Rate limit used: 4 requests/second
- Fetch errors: 0

The scan searched flanking text around accession/data availability language
such as `accession`, `BioProject`, `SRA`, `ENA`, `DDBJ`, `GSA`, `CNSA`,
`GEO`, `ArrayExpress`, `deposited`, `submitted`, `available`, and
`Sequence Read Archive`.

## Summary

Out of 200 sampled papers, 12 had accession-like hits in the scanned context
windows.

| Family | Unique accessions found | Examples |
| --- | ---: | --- |
| GSA / CNCB | 5 | `CRA015299`; `CRA015702`; `CRA019782`; `CRA020802`; `CRA028528` |
| CNSA / CNGB | 4 | `CNP0001259`; `CNP0004686`; `CNP0004687`; `CNP0005704` |
| DDBJ DRA | 5 | `DRA004160`; `DRA005774`; `DRA006684`; `DRA008156`; `DRA008239` |
| SRA experiment-level | 9 | `SRX020378`; `SRX020379`; `SRX020587`; `SRX020770`; `SRX020773`; `SRX021236`; `SRX021237`; `SRX089367`; `SRX1044553` |

## Papers With Hits

| PMCID | Hits |
| --- | --- |
| `PMC12361276` | `CRA020802` |
| `PMC5758520` | `DRA004160`; `DRA005774` |
| `PMC11264597` | `CRA015299` |
| `PMC12353712` | `CNP0005704` |
| `PMC4918959` | `SRX1044553` |
| `PMC11961944` | `CRA019782` |
| `PMC8116522` | `CNP0001259` |
| `PMC3368382` | `SRX020378`; `SRX020379`; `SRX020587`; `SRX020770`; `SRX020773`; `SRX021236`; `SRX021237`; `SRX089367` |
| `PMC12542775` | `DRA006684`; `DRA008156`; `CRA028528` |
| `PMC11151592` | `CNP0004686`; `CNP0004687` |
| `PMC12210941` | `CRA015702` |
| `PMC6582144` | `DRA008239` |

## Interpretation

The most useful missing production patterns from this sample are:

- `CRA[0-9]{6,}` for Genome Sequence Archive / CNCB records.
- `CNP[0-9]{7,}` for CNSA / CNGB project records.
- `DRA[0-9]{5,}` for DDBJ DRA submission/archive records.

The sample also confirms that secondary lower-level SRA accessions occur in
these papers, especially `SRX...` experiment accessions. These are real
accessions, but they are not project/study-level identifiers. If extracted,
they should be categorized separately from BioProject/SRA-study accessions.

Suggested production categories:

| Category | Candidate patterns | Notes |
| --- | --- | --- |
| NCBI SRA / BioProject | `PRJNA[0-9]+`, `SRP[0-9]{5,}` | `PRJNA` is NCBI BioProject; `SRP` is NCBI SRA Study. Keep `SRR/SRS/SRX/SRZ` out of the primary output because they are run/sample/experiment/analysis level. |
| ENA / EBI | `PRJEB[0-9]+`, `ERP[0-9]{5,}` | `PRJEB` is ENA BioProject; `ERP` is ENA Study. Keep `ERR/ERS/ERX/ERZ` out of the primary output for the same lower-level reason. |
| DDBJ DRA / BioProject | `PRJDB[0-9]+`, `DRP[0-9]{5,}`, `DRA[0-9]{5,}` | `PRJDB` is DDBJ BioProject, `DRP` is DDBJ Study, and `DRA` is DDBJ Submission. Include `DRA` because manual curation and sampled papers cite it directly; exclude `DRR/DRS/DRX/DRZ` from primary output. |
| GSA / CNCB-NGDC | `PRJCA[0-9]+`, `CRA[0-9]{6,}` | `PRJCA` is CNCB BioProject and `CRA` is the GSA accession. The official GSA page also documents `CRX` experiment and `CRR` run accessions, but neither appeared in the 200-paper sample and both are lower-level. |
| CNSA / CNGBdb | `CNP[0-9]{7,}` | CNSA project/accession family. The CNSA publication also documents lower-level `CNS`, `CNX`, `CNR`, `CNA`, `varc`, and `CVF` families, but `CNP` is the project-level family and matched sampled/manual records. |
| NCBI GEO | `GSE[0-9]+` | GEO Series accession. Local CSV inspection found rare microbiome examples. Exclude `GSM` sample and `GPL` platform from primary output. |
| ArrayExpress / BioStudies | `E-(MTAB|MEXP|TABM|GEOD)-[0-9]+` | Curated ArrayExpress study/experiment families. Include `E-MTAB` for current examples and older/imported `E-MEXP`, `E-TABM`, and `E-GEOD`; avoid broad `E-[A-Z]+-[0-9]+` overmatching. |

## Settled Primary Regex Set

These are the patterns selected for production-style extraction after reviewing
the 200-paper sample and the database documentation.

```text
NCBI_SRA_BIOPROJECT = \b(?:PRJNA[0-9]+|SRP[0-9]{5,})\b
ENA_EBI = \b(?:PRJEB[0-9]+|ERP[0-9]{5,})\b
DDBJ_PRIMARY = \b(?:PRJDB[0-9]+|DRP[0-9]{5,}|DRA[0-9]{5,})\b
GSA_CNCB_PRIMARY = \b(?:PRJCA[0-9]+|CRA[0-9]{6,})\b
CNSA_PRIMARY = \bCNP[0-9]{7,}\b
GEO_PRIMARY = \bGSE[0-9]+\b
ARRAYEXPRESS_PRIMARY = \bE-(?:MTAB|MEXP|TABM|GEOD)-[0-9]+\b
```

The guiding rule is to prefer project, study, submission, or dataset-level
accessions in the main output. Lower-level run, sample, experiment, and
analysis accessions are real but are intentionally excluded from primary
matching unless a later feature adds secondary reporting.

## PMC Text Source Caveat

Entrez `efetch` XML and the rendered PMC article report are not always
identical. For example, `PMC6997737` has `CNP0000408` in the PMC Data
Availability Statement on `?report=xml`, but that string is absent from the
Entrez XML payload. The resolver intentionally uses Entrez XML only, so these
rendered-report-only accessions are known misses rather than retryable failures.

## Official Documentation Notes

- ENA documents INSDC-style accessions for projects/studies, BioSamples,
  samples, experiments, runs, analyses, assemblies, and sequences. It also
  notes that first letters identify the original INSDC submitter for study,
  sample, experiment, run, and analysis accessions: `E` for ENA, `D` for DDBJ,
  and `S` for NCBI.
  Source: https://ena-docs.readthedocs.io/en/latest/submit/general-guide/accessions.html
- NLM/NCBI describes accession numbers as database record identifiers, usually
  an alphabetical prefix followed by digits, and explicitly mentions
  BioProject, BioSample, SRA, GEO DataSets, and dbSNP as NCBI databases using
  unversioned accession formats. It also states that `PRJNA`, `PRJEB`, and
  `PRJDB` distinguish BioProject records registered through NCBI, ENA, and
  DDBJ.
  Source: https://support.nlm.nih.gov/kbArticle/?pn=KA-03434
- DDBJ DRA documentation lists DRA metadata objects and says accession numbers
  are assigned after metadata and data files are complete. It explicitly names
  `DRX` for Experiment, `DRR` for Run, and `DRZ` for Analysis. DDBJ's citation
  FAQ recommends citing BioProject accessions for project-level references and
  notes that citing DRA submission accessions with prefix `DRA` is not
  recommended when a BioProject is available.
  Sources:
  https://www.ddbj.nig.ac.jp/dra/submission-e.html
  https://www.ddbj.nig.ac.jp/faq/en/cite-accession-e.html
- DDBJ's INSDC prefix table documents the broader Sequence Read Archive prefix
  family: `DRA/DRP/DRR/DRS/DRX/DRZ`, `ERA/ERP/ERR/ERS/ERX/ERZ`, and
  `SRA/SRP/SRR/SRS/SRX/SRZ`.
  Source: https://www.ddbj.nig.ac.jp/insdc/prefix-e.html
- CNSA / CNGB documentation gives the manuscript citation form
  `accession number CNPXXXXXXX`, supporting `CNP...` as a CNSA project
  accession family.
  Source: https://db.cngb.org/cnsa/
- The CNSA publication describes the CNSA object hierarchy: project `CNP`,
  sample `CNS`, experiment `CNX`, run `CNR`, assembly `CNA`, variation `varc`
  and `CVF`, and living sample `CNSEbb`. The primary output uses only `CNP`.
  Source: https://pmc.ncbi.nlm.nih.gov/articles/PMC7377928/
- GSA / CNCB's official data standards page documents several related
  accession systems: BioProject `PRJCA...`, BioSample `SAMC...`, GSA
  accession `CRA...`, Experiment `CRX...`, and Run `CRR...`.
  Source: https://ngdc.cncb.ac.cn/gsa/support/standardsGsa
- NCBI GEO documentation defines `GPLxxx` platform accessions, `GSMxxx` sample
  accessions, `GSExxx` series accessions, and `GDSxxx` curated DataSet
  accessions.
  Source: https://www.ncbi.nlm.nih.gov/geo/info/overview.html
- EMBL-EBI ArrayExpress is now presented as a BioStudies functional genomics
  data collection. The page notes that raw sequence reads from high-throughput
  sequencing studies are brokered to ENA.
  Source: https://www.ebi.ac.uk/biostudies/arrayexpress
- ArrayExpress help was reviewed while selecting a conservative pattern family
  that covers common `E-MTAB` records plus older/imported `E-MEXP`, `E-TABM`,
  and `E-GEOD` accessions without matching arbitrary `E-*` identifiers.
  Source: https://www.ebi.ac.uk/biostudies/arrayexpress/help

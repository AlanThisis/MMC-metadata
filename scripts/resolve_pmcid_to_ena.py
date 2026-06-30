#!/usr/bin/env python3
"""Resolve PMCIDs to dataset-level accessions and update MMC2.csv.

This script follows the same core logic as the repository's HTML tool:
- Fetch PMC full text from NCBI Entrez (`efetch`, db=pmc)
- Regex-scan full text for selected project/study/dataset-level accessions

Output states per processed PMCID row:
- Found: write semicolon+space-delimited accession list into `Accession`
- Clean miss: write `ENA_NOT_FOUND`
- API/network error: leave main CSV row untouched and write to failed.csv
"""

from __future__ import annotations

import argparse
import re
import socket
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd
from Bio import Entrez
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

DEFAULT_INPUT_CSV = Path("data/MMC2.csv")
DEFAULT_FAILED_CSV = Path("data/failed.csv")
DEFAULT_RPS_LIMIT = 5.0
DEFAULT_MAX_RETRY_ATTEMPTS = 5
DEFAULT_ENTREZ_TIMEOUT_SECONDS = 30.0

class EntrezFetchError(Exception):
    """Raised when efetch fails for reasons that should be treated as API/network errors."""


@dataclass(frozen=True)
class DatabasePatternGroup:
    """Named accession pattern family selectable from the CLI."""

    key: str
    label: str
    patterns: tuple[re.Pattern[str], ...]


@dataclass
class ResolutionResult:
    """Result for resolving a single PMCID."""

    status: str  # found | not_found | failed
    accession_value: Optional[str] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None


DATABASE_PATTERN_GROUPS: tuple[DatabasePatternGroup, ...] = (
    DatabasePatternGroup(
        key="ncbi",
        label="NCBI SRA / BioProject",
        patterns=(re.compile(r"PRJNA[0-9]+", re.IGNORECASE), re.compile(r"SRP[0-9]{5,}", re.IGNORECASE)),
    ),
    DatabasePatternGroup(
        key="ena",
        label="ENA / EBI",
        patterns=(re.compile(r"PRJEB[0-9]+", re.IGNORECASE), re.compile(r"ERP[0-9]{5,}", re.IGNORECASE)),
    ),
    DatabasePatternGroup(
        key="ddbj",
        label="DDBJ DRA / BioProject",
        patterns=(
            re.compile(r"PRJDB[0-9]+", re.IGNORECASE),
            re.compile(r"DRP[0-9]{5,}", re.IGNORECASE),
            re.compile(r"DRA[0-9]{5,}", re.IGNORECASE),
        ),
    ),
    DatabasePatternGroup(
        key="gsa",
        label="GSA / CNCB-NGDC",
        patterns=(re.compile(r"PRJCA[0-9]+", re.IGNORECASE), re.compile(r"CRA[0-9]{6,}", re.IGNORECASE)),
    ),
    DatabasePatternGroup(
        key="cnsa",
        label="CNSA / CNGBdb",
        patterns=(re.compile(r"CNP[0-9]{7,}", re.IGNORECASE),),
    ),
    DatabasePatternGroup(
        key="geo",
        label="NCBI GEO",
        patterns=(re.compile(r"GSE[0-9]+", re.IGNORECASE),),
    ),
    DatabasePatternGroup(
        key="arrayexpress",
        label="ArrayExpress / BioStudies",
        patterns=(re.compile(r"E-(?:MTAB|MEXP|TABM|GEOD)-[0-9]+", re.IGNORECASE),),
    ),
)
DATABASE_PATTERN_GROUPS_BY_KEY = {group.key: group for group in DATABASE_PATTERN_GROUPS}


class RateLimiter:
    """Simple global rate limiter for outbound requests."""

    def __init__(self, requests_per_second: float) -> None:
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be > 0")
        self.min_interval = 1.0 / requests_per_second
        self._last_ts = 0.0

    def wait(self) -> None:
        """Sleep if needed to stay below configured requests/sec."""
        now = time.monotonic()
        elapsed = now - self._last_ts
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_ts = time.monotonic()


def normalize_pmcid(value: object) -> str:
    """Normalize input PMCID to uppercase `PMC123...` format.

    Raises:
        ValueError: if value is empty or not a valid PMCID token.
    """
    raw = str(value or "").strip().upper()
    if not raw:
        raise ValueError("empty PMCID")
    if not re.fullmatch(r"PMC\d+", raw):
        raise ValueError(f"invalid PMCID format: {raw}")
    return raw


def extract_accessions(text: str, pattern_groups: Iterable[DatabasePatternGroup]) -> list[str]:
    """Extract and return unique sorted accession matches from free text."""
    found: set[str] = set()
    for group in pattern_groups:
        for pattern in group.patterns:
            for match in pattern.findall(text):
                found.add(match.upper())
    return sorted(found)


def fetch_pmc_fulltext_xml(pmcid: str, limiter: RateLimiter) -> str:
    """Fetch PMC full-text XML using Entrez efetch.

    Args:
        pmcid: `PMC...` identifier.
        limiter: shared request rate limiter.

    Returns:
        Raw XML text.

    Raises:
        EntrezFetchError: on network/API/read failures.
    """
    uid = pmcid.replace("PMC", "", 1)
    limiter.wait()
    previous_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(DEFAULT_ENTREZ_TIMEOUT_SECONDS)
    try:
        with Entrez.efetch(db="pmc", id=uid, retmode="xml") as handle:
            payload = handle.read()
    except Exception as exc:  # noqa: BLE001
        raise EntrezFetchError(str(exc)) from exc
    finally:
        socket.setdefaulttimeout(previous_timeout)

    if isinstance(payload, bytes):
        text = payload.decode("utf-8", errors="replace")
    else:
        text = str(payload)
    if not text.strip():
        raise EntrezFetchError("empty efetch response")
    # Entrez can return an XML envelope with <error ...> for unavailable IDs.
    # Treat this as API/data retrieval failure, not a clean accession miss.
    if re.search(r"<\s*error\b", text, re.IGNORECASE):
        snippet_match = re.search(r"<\s*error\b[^>]*>(.*?)<\s*/\s*error\s*>", text, re.IGNORECASE | re.DOTALL)
        message = snippet_match.group(1).strip() if snippet_match else "efetch returned error payload"
        raise EntrezFetchError(message)
    return text


def resolve_single_pmcid(pmcid: str, limiter: RateLimiter, pattern_groups: Iterable[DatabasePatternGroup]) -> ResolutionResult:
    """Resolve one PMCID to accession(s) using Entrez PMC XML."""
    groups = tuple(pattern_groups)
    try:
        xml_text = fetch_pmc_fulltext_xml(pmcid, limiter)
        accessions = extract_accessions(xml_text, groups)
        if accessions:
            return ResolutionResult(status="found", accession_value="; ".join(accessions))
        return ResolutionResult(status="not_found", accession_value="ENA_NOT_FOUND")
    except Exception as exc:  # noqa: BLE001
        return ResolutionResult(
            status="failed",
            error_type=type(exc).__name__,
            error_message=str(exc),
        )


def run_with_retry(
    pmcid: str,
    limiter: RateLimiter,
    max_attempts: int,
    pattern_groups: Iterable[DatabasePatternGroup],
) -> ResolutionResult:
    """Resolve PMCID with exponential backoff retry attempts."""
    groups = tuple(pattern_groups)

    def _attempt() -> ResolutionResult:
        result = resolve_single_pmcid(pmcid, limiter, groups)
        if result.status == "failed":
            raise EntrezFetchError(result.error_message or "unknown error")
        return result

    try:
        for attempt in Retrying(
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(multiplier=1, min=1, max=16),
            retry=retry_if_exception_type(EntrezFetchError),
            reraise=True,
        ):
            with attempt:
                return _attempt()
    except Exception as exc:  # noqa: BLE001
        return ResolutionResult(
            status="failed",
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
    return ResolutionResult(status="failed", error_type="RuntimeError", error_message="retry fell through")


def read_main_csv(path: Path) -> pd.DataFrame:
    """Read main MMC2 CSV."""
    if not path.exists():
        raise FileNotFoundError(f"Input CSV not found: {path}")
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def ensure_columns(df: pd.DataFrame, required: Iterable[str]) -> None:
    """Validate required columns in dataframe."""
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required column(s): {', '.join(missing)}")


def build_failure_row(source_row: pd.Series, row_index: int, pmcid: str, attempts: int, result: ResolutionResult) -> dict[str, str]:
    """Build failed.csv row preserving source row plus error metadata."""
    record = {k: str(v) for k, v in source_row.to_dict().items()}
    record.update(
        {
            "row_index": str(row_index),
            "pmc_id": pmcid,
            "error_type": str(result.error_type or ""),
            "error_message": str(result.error_message or ""),
            "attempts": str(attempts),
        }
    )
    return record


def write_failed_csv(path: Path, failure_rows: list[dict[str, str]], base_columns: list[str]) -> None:
    """Write/update failed.csv; remove file if empty failure set."""
    if not failure_rows:
        if path.exists():
            path.unlink()
        return

    cols = list(base_columns)
    for extra in ("row_index", "pmc_id", "error_type", "error_message", "attempts"):
        if extra not in cols:
            cols.append(extra)
    failed_df = pd.DataFrame(failure_rows)
    failed_df = failed_df.reindex(columns=cols, fill_value="")
    failed_df.to_csv(path, index=False)


def split_db_keys(values: Iterable[str]) -> list[str]:
    """Split repeated/comma-separated DB key CLI values into normalized keys."""
    keys: list[str] = []
    for value in values:
        for part in str(value).split(","):
            key = part.strip().lower()
            if key:
                keys.append(key)
    return keys


def format_pattern_group_keys(pattern_groups: Iterable[DatabasePatternGroup]) -> str:
    """Format selected DB group keys for stdout/help text."""
    return ", ".join(group.key for group in pattern_groups)


def resolve_pattern_groups(include_values: Iterable[str], exclude_values: Iterable[str]) -> tuple[DatabasePatternGroup, ...]:
    """Resolve include/exclude DB CLI values into pattern groups.

    By default all groups are selected. `include_values` narrows that baseline,
    then `exclude_values` removes groups from the selected set.
    """
    include_keys = split_db_keys(include_values)
    exclude_keys = split_db_keys(exclude_values)
    requested_keys = include_keys + exclude_keys
    invalid = sorted({key for key in requested_keys if key not in DATABASE_PATTERN_GROUPS_BY_KEY})
    if invalid:
        valid = ", ".join(DATABASE_PATTERN_GROUPS_BY_KEY)
        raise ValueError(f"Unknown DB group(s): {', '.join(invalid)}. Valid choices: {valid}")

    if include_keys:
        selected_keys = list(dict.fromkeys(include_keys))
    else:
        selected_keys = [group.key for group in DATABASE_PATTERN_GROUPS]

    excluded = set(exclude_keys)
    selected = tuple(DATABASE_PATTERN_GROUPS_BY_KEY[key] for key in selected_keys if key not in excluded)
    if not selected:
        raise ValueError("No DB groups selected after applying include/exclude filters.")
    return selected


def print_database_groups() -> None:
    """Print available DB pattern groups."""
    for group in DATABASE_PATTERN_GROUPS:
        regexes = ", ".join(pattern.pattern for pattern in group.patterns)
        print(f"{group.key}\t{group.label}\t{regexes}")


def run_normal_mode(
    input_csv: Path,
    failed_csv: Path,
    limiter: RateLimiter,
    pattern_groups: Iterable[DatabasePatternGroup],
) -> tuple[int, int, int]:
    """Process all rows with non-empty PMCID and update Accession in main CSV."""
    df = read_main_csv(input_csv)
    ensure_columns(df, ("pmc_id", "Accession"))
    groups = tuple(pattern_groups)

    found_count = 0
    not_found_count = 0
    failed_count = 0
    failure_rows: list[dict[str, str]] = []

    for idx, row in df.iterrows():
        raw_pmcid = str(row.get("pmc_id", "")).strip()
        if not raw_pmcid:
            continue

        try:
            pmcid = normalize_pmcid(raw_pmcid)
        except ValueError as exc:
            result = ResolutionResult(status="failed", error_type="ValueError", error_message=str(exc))
            failure_rows.append(build_failure_row(row, idx, raw_pmcid, 1, result))
            failed_count += 1
            continue

        result = resolve_single_pmcid(pmcid, limiter, groups)
        if result.status == "found":
            df.at[idx, "Accession"] = result.accession_value or ""
            found_count += 1
        elif result.status == "not_found":
            df.at[idx, "Accession"] = "ENA_NOT_FOUND"
            not_found_count += 1
        else:
            failure_rows.append(build_failure_row(row, idx, pmcid, 1, result))
            failed_count += 1

    df.to_csv(input_csv, index=False)
    write_failed_csv(failed_csv, failure_rows, list(df.columns))
    return found_count, not_found_count, failed_count


def run_retry_mode(
    input_csv: Path,
    failed_csv: Path,
    limiter: RateLimiter,
    max_attempts: int,
    pattern_groups: Iterable[DatabasePatternGroup],
) -> tuple[int, int, int]:
    """Retry only failed rows; keep unresolved rows in failed.csv."""
    if not failed_csv.exists():
        print("No failed.csv found. Nothing to retry.")
        return 0, 0, 0

    df = read_main_csv(input_csv)
    ensure_columns(df, ("pmc_id", "Accession"))

    failed_df = pd.read_csv(failed_csv, dtype=str, keep_default_na=False)
    ensure_columns(failed_df, ("row_index", "pmc_id", "attempts"))

    found_count = 0
    not_found_count = 0
    failed_count = 0
    remaining_failures: list[dict[str, str]] = []
    groups = tuple(pattern_groups)

    for _, frow in failed_df.iterrows():
        row_index_text = str(frow.get("row_index", "")).strip()
        pmcid_raw = str(frow.get("pmc_id", "")).strip()
        attempts_text = str(frow.get("attempts", "0") or "0").strip()
        try:
            attempts_so_far = int(attempts_text)
        except ValueError:
            remaining = dict(frow.to_dict())
            remaining["error_type"] = "ValueError"
            remaining["error_message"] = f"invalid attempts value: {attempts_text}"
            remaining["attempts"] = str(min(max_attempts, 1))
            remaining_failures.append({k: str(v) for k, v in remaining.items()})
            failed_count += 1
            continue

        try:
            row_index = int(row_index_text)
        except ValueError:
            remaining = dict(frow.to_dict())
            remaining["error_type"] = "ValueError"
            remaining["error_message"] = f"invalid row_index: {row_index_text}"
            remaining_failures.append({k: str(v) for k, v in remaining.items()})
            failed_count += 1
            continue

        if row_index < 0 or row_index >= len(df):
            remaining = dict(frow.to_dict())
            remaining["error_type"] = "IndexError"
            remaining["error_message"] = f"row_index out of range: {row_index}"
            remaining_failures.append({k: str(v) for k, v in remaining.items()})
            failed_count += 1
            continue

        try:
            pmcid = normalize_pmcid(pmcid_raw)
        except ValueError as exc:
            remaining = dict(frow.to_dict())
            remaining["error_type"] = "ValueError"
            remaining["error_message"] = str(exc)
            remaining["attempts"] = str(min(max_attempts, attempts_so_far + 1))
            remaining_failures.append({k: str(v) for k, v in remaining.items()})
            failed_count += 1
            continue
        try:
            current_row_pmcid = normalize_pmcid(df.at[row_index, "pmc_id"])
        except ValueError:
            remaining = dict(frow.to_dict())
            remaining["error_type"] = "ValueError"
            remaining["error_message"] = f"target row has invalid pmc_id at row_index {row_index}"
            remaining["attempts"] = str(min(max_attempts, attempts_so_far + 1))
            remaining_failures.append({k: str(v) for k, v in remaining.items()})
            failed_count += 1
            continue

        if current_row_pmcid != pmcid:
            remaining = dict(frow.to_dict())
            remaining["error_type"] = "ValueError"
            remaining["error_message"] = (
                f"row_index/pmc_id mismatch at row_index {row_index}: "
                f"failed.csv={pmcid}, MMC2.csv={current_row_pmcid}"
            )
            remaining["attempts"] = str(min(max_attempts, attempts_so_far + 1))
            remaining_failures.append({k: str(v) for k, v in remaining.items()})
            failed_count += 1
            continue

        remaining_budget = max_attempts - attempts_so_far
        if remaining_budget <= 0:
            remaining = dict(frow.to_dict())
            remaining["error_type"] = str(frow.get("error_type", "EntrezFetchError"))
            remaining["error_message"] = str(frow.get("error_message", "max attempts reached"))
            remaining["attempts"] = str(max_attempts)
            remaining_failures.append({k: str(v) for k, v in remaining.items()})
            failed_count += 1
            continue

        result = run_with_retry(pmcid, limiter, remaining_budget, groups)
        total_attempts = min(max_attempts, attempts_so_far + remaining_budget)

        if result.status == "found":
            df.at[row_index, "Accession"] = result.accession_value or ""
            found_count += 1
        elif result.status == "not_found":
            df.at[row_index, "Accession"] = "ENA_NOT_FOUND"
            not_found_count += 1
        else:
            remaining = dict(frow.to_dict())
            remaining["error_type"] = str(result.error_type or "EntrezFetchError")
            remaining["error_message"] = str(result.error_message or "retry failed")
            remaining["attempts"] = str(total_attempts)
            remaining_failures.append({k: str(v) for k, v in remaining.items()})
            failed_count += 1

    df.to_csv(input_csv, index=False)
    write_failed_csv(failed_csv, remaining_failures, list(df.columns))
    return found_count, not_found_count, failed_count


def run_test_mode(limiter: RateLimiter, pattern_groups: Iterable[DatabasePatternGroup]) -> tuple[int, int, int]:
    """Run a small hardcoded PMCID test set, stdout only."""
    test_pmcids = [
        "PMC4681099",       # known to contain ERP accessions
        "PMC10828421",      # valid article with a PRJCA accession
        "PMC999999999999",  # non-existent PMCID
        "PMCABC123",        # invalid format
    ]

    found_count = 0
    not_found_count = 0
    failed_count = 0
    groups = tuple(pattern_groups)

    print("Running --test mode (no file writes)")
    print(f"Selected DB groups: {format_pattern_group_keys(groups)}")
    for pmcid_raw in test_pmcids:
        try:
            pmcid = normalize_pmcid(pmcid_raw)
            result = resolve_single_pmcid(pmcid, limiter, groups)
        except Exception as exc:  # noqa: BLE001
            result = ResolutionResult(status="failed", error_type=type(exc).__name__, error_message=str(exc))

        if result.status == "found":
            found_count += 1
            print(f"{pmcid_raw}: FOUND -> {result.accession_value}")
        elif result.status == "not_found":
            not_found_count += 1
            print(f"{pmcid_raw}: ENA_NOT_FOUND")
        else:
            failed_count += 1
            print(f"{pmcid_raw}: FAILED ({result.error_type}) {result.error_message}")

    return found_count, not_found_count, failed_count


def build_arg_parser() -> argparse.ArgumentParser:
    """Create argument parser for CLI."""
    parser = argparse.ArgumentParser(
        description=(
            "Resolve PMCID rows in data/MMC2.csv to project/study/dataset accessions "
            "using NCBI Entrez full-text fetch + regex extraction."
        )
    )
    parser.add_argument(
        "--input",
        default=str(DEFAULT_INPUT_CSV),
        help=f"Path to main CSV (default: {DEFAULT_INPUT_CSV})",
    )
    parser.add_argument(
        "--failed",
        default=str(DEFAULT_FAILED_CSV),
        help=f"Path to failed rows CSV (default: {DEFAULT_FAILED_CSV})",
    )
    parser.add_argument(
        "--retry",
        action="store_true",
        help="Reprocess only rows in failed.csv with exponential backoff (max 5 attempts/row).",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Run hardcoded PMCID test cases and print stdout only (no file writes).",
    )
    parser.add_argument(
        "--include-db",
        action="append",
        default=[],
        metavar="KEY[,KEY...]",
        help=(
            "Only search these DB pattern groups. Can be repeated or comma-separated. "
            "Default: all groups. Use --list-dbs to see keys."
        ),
    )
    parser.add_argument(
        "--exclude-db",
        action="append",
        default=[],
        metavar="KEY[,KEY...]",
        help=(
            "Exclude these DB pattern groups from the selected set. Can be repeated "
            "or comma-separated. Applied after --include-db."
        ),
    )
    parser.add_argument(
        "--list-dbs",
        action="store_true",
        help="List available DB pattern group keys and regexes, then exit.",
    )
    parser.add_argument(
        "--email",
        default="",
        help="Optional contact email for NCBI Entrez (recommended by NCBI).",
    )
    parser.add_argument(
        "--api-key",
        default="",
        help="Optional NCBI API key for Entrez.",
    )
    parser.add_argument(
        "--rps",
        type=float,
        default=DEFAULT_RPS_LIMIT,
        help=f"Max requests per second (default: {DEFAULT_RPS_LIMIT}).",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=DEFAULT_MAX_RETRY_ATTEMPTS,
        help=f"Max total retry attempts per failed row (default: {DEFAULT_MAX_RETRY_ATTEMPTS}).",
    )
    return parser


def main() -> int:
    """CLI entrypoint."""
    parser = build_arg_parser()
    args = parser.parse_args()

    if args.list_dbs:
        print_database_groups()
        return 0

    try:
        pattern_groups = resolve_pattern_groups(args.include_db, args.exclude_db)
    except ValueError as exc:
        print(f"Fatal error: {exc}", file=sys.stderr)
        return 1

    input_csv = Path(args.input)
    failed_csv = Path(args.failed)

    # Entrez identification.
    Entrez.tool = "mmc-pmcid-ena-resolver"
    if args.email:
        Entrez.email = args.email
    if args.api_key:
        Entrez.api_key = args.api_key

    limiter = RateLimiter(args.rps)

    try:
        if args.test:
            found, not_found, failed = run_test_mode(limiter, pattern_groups)
        elif args.retry:
            found, not_found, failed = run_retry_mode(
                input_csv=input_csv,
                failed_csv=failed_csv,
                limiter=limiter,
                max_attempts=args.max_attempts,
                pattern_groups=pattern_groups,
            )
        else:
            print(f"Selected DB groups: {format_pattern_group_keys(pattern_groups)}")
            found, not_found, failed = run_normal_mode(
                input_csv=input_csv,
                failed_csv=failed_csv,
                limiter=limiter,
                pattern_groups=pattern_groups,
            )
    except Exception as exc:  # noqa: BLE001
        print(f"Fatal error: {exc}", file=sys.stderr)
        return 1

    print(f"Summary: {found} found, {not_found} not found, {failed} failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

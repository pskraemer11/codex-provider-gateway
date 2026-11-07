"""Build Codex catalogs from OpenRouter, AA, and OpenCode."""

from __future__ import annotations

import argparse
import copy
import hashlib
import html.parser
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from catalog_rules import (
    INDEX_NAMES,
    INPUT_PRICE_LIMIT,
    MIN_CALIBRATED_SCORE,
    ROUTER_MODEL_IDS,
    aa_model_base,
    finite_number,
    is_free_offer,
    is_free_variant,
    is_router_model,
    normalized_component,
    qualifies_model,
    score_candidate,
    score_population,
    unique_model_component,
)

# The `/free` endpoint/tier is AA API access metadata, not model token pricing.
AA_URL = "https://artificialanalysis.ai/api/v2/language/models/free"
AA_DOCUMENTATION_URL = "https://artificialanalysis.ai/data-api/docs#getLanguageModelsFree"
AA_SNAPSHOT_MAX_AGE_DAYS = 31
# Rolling fallback: the last successful live fetch, rewritten on every build.
LIVE_SNAPSHOT_NAME = "artificial-analysis-live-snapshot.json"
LIVE_SNAPSHOT_ENV = "ARTIFICIAL_ANALYSIS_LIVE_SNAPSHOT"
OR_MODELS_URL = "https://openrouter.ai/api/v1/models"
OR_BENCHMARKS_URL = "https://openrouter.ai/api/v1/benchmarks"
GO_DOC_URL = "https://opencode.ai/v2/docs/console/go"
ZEN_DOC_URL = "https://opencode.ai/v2/docs/console/models"
CODEX_TEMPLATE_TIMEOUT_SEC = 60
TASK_TYPES = {"intelligence": "intelligence_index", "coding": "coding_index", "agentic": "agentic_index"}
USD_PER_MILLION = Decimal("1000000")
SCORE_LIMIT = MIN_CALIBRATED_SCORE
PREFERRED_MODEL_IDS = {"openrouter": "deepseek/deepseek-v4.1-flash-1017"}
DEFAULT_REASONING_LEVELS = [
    {"effort": "low", "description": "Fast responses with lighter reasoning"},
    {"effort": "medium", "description": "Balances speed and reasoning depth for everyday tasks"},
    {"effort": "high", "description": "Greater reasoning depth for complex problems"},
    {"effort": "xhigh", "description": "Greater reasoning depth for complex problems"},
]
REMOVE_KEYS = (
    "service_tiers",
    "default_service_tier",
    "additional_speed_tiers",
    "comp_hash",
    "model_specialty",
    "tool_mode",
    "apply_patch_tool_type",
    "web_search_tool_type",
)

# Per-model values the provider catalog does not carry, keyed by bare model id
# so every provider prefix inherits them.
# gpt-6-luna: Codex 0.164.0 ships this model as a "responses lite" model.
# Without the flag, long reasoning turns against OpenCode Go end as
# `incomplete` with reason=max_output_tokens (measured 2026-10-27).
MODEL_OVERRIDES: dict[str, dict[str, Any]] = {
    "gpt-6-luna": {"use_responses_lite": True},
}


class CatalogError(RuntimeError):
    """A required source did not satisfy its data contract."""


def default_proxy_models_url() -> str:
    """Loopback proxy catalog URL, following the proxy's port environment."""
    explicit = os.environ.get("OPENCODE_GO_PROXY_MODELS_URL")
    if explicit:
        return explicit.rstrip("/")
    port = os.environ.get("OPENCODE_GO_PROXY_PORT", "8787")
    return f"http://127.0.0.1:{port}/v1/models"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _get_bytes(url: str, headers: dict[str, str] | None = None) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json,text/html", "User-Agent": "codex-picker-catalog/1.0", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            if response.status != 200:
                raise CatalogError(f"Quelle antwortete mit HTTP {response.status}: {url}")
            return response.read()
    except urllib.error.HTTPError as error:
        raise CatalogError(f"Quelle antwortete mit HTTP {error.code}: {url}") from None
    except urllib.error.URLError as error:
        raise CatalogError(f"Quelle nicht erreichbar ({error.reason}): {url}") from None


def _get_json(url: str, headers: dict[str, str] | None = None) -> tuple[dict[str, Any], str]:
    body = _get_bytes(url, headers)
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise CatalogError(f"Quelle lieferte kein gueltiges JSON: {url}") from error
    if not isinstance(data, dict):
        raise CatalogError(f"Quelle lieferte kein JSON-Objekt: {url}")
    return data, hashlib.sha256(body).hexdigest()


def _fetch_aa_models_once(api_key: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page = 1
    expected_pages: int | None = None
    expected_page_size: int | None = None
    expected_tier: str | None = None
    hashes: list[str] = []
    seen_ids: set[str] = set()
    version: Any = None
    while True:
        payload, digest = _get_json(f"{AA_URL}?page={page}", {"x-api-key": api_key})
        pagination, page_rows = payload.get("pagination"), payload.get("data")
        if not isinstance(pagination, dict) or not isinstance(page_rows, list):
            raise CatalogError("AA: Pagination oder data-Liste fehlt.")
        tier = payload.get("tier")
        page_size = pagination.get("page_size")
        total_pages = pagination.get("total_pages")
        response_version = payload.get("intelligence_index_version")
        if tier not in {"free", "pro", "commercial"}:
            raise CatalogError("AA: ungueltige oder fehlende tier-Metadaten.")
        if (
            type(pagination.get("page")) is not int
            or pagination["page"] != page
            or type(page_size) is not int
            or page_size < 1
            or type(total_pages) is not int
            or total_pages < 1
            or not isinstance(pagination.get("has_more"), bool)
        ):
            raise CatalogError("AA: widerspruechliche Seitennummern.")
        if finite_number(response_version) is None:
            raise CatalogError("AA: Intelligence-Index-Version fehlt oder ist ungueltig.")
        if expected_pages is None:
            expected_pages = total_pages
            expected_page_size = page_size
            expected_tier = tier
            version = response_version
        if (
            expected_pages != total_pages
            or expected_page_size != page_size
            or expected_tier != tier
            or version != response_version
            or page > expected_pages
        ):
            raise CatalogError("AA: Seitenzahl aenderte sich waehrend des Abrufs.")
        if pagination.get("has_more") is not (page < expected_pages):
            raise CatalogError("AA: has_more stimmt nicht mit total_pages ueberein.")
        for row_number, row in enumerate(page_rows, start=1):
            if (
                not isinstance(row, dict)
                or not isinstance(row.get("id"), str)
                or not isinstance(row.get("slug"), str)
                or not isinstance(row.get("evaluations"), dict)
            ):
                raise CatalogError(f"AA: Modell-schema unvollstaendig auf Seite {page}, Zeile {row_number}.")
            if row["id"] in seen_ids:
                raise CatalogError(f"AA: doppelte Modell-id auf Seite {page}, Zeile {row_number}.")
            seen_ids.add(row["id"])
            rows.append(row)
        hashes.append(digest)
        if page == expected_pages:
            break
        page += 1
    return rows, {
        "url": AA_URL,
        "retrieved_at": _now(),
        "page_count": expected_pages,
        "page_size": expected_page_size,
        "row_count": len(rows),
        "tier": expected_tier,
        "intelligence_index_version": version,
        "sha256_by_page": hashes,
    }


def fetch_aa_models(api_key: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    for attempt in range(2):
        try:
            return _fetch_aa_models_once(api_key)
        except CatalogError as error:
            if attempt == 0 and "doppelte Modell-id" in str(error):
                continue
            raise
    raise CatalogError("AA: Pagination blieb nach erneutem Abruf inkonsistent.")


def default_aa_snapshot_path() -> Path:
    configured = os.environ.get("ARTIFICIAL_ANALYSIS_FREE_SNAPSHOT")
    if configured:
        return Path(configured).expanduser()
    relative_path = Path("automatisierter Benchmark-Abgleich/data/artificial-analysis-free-snapshot-20261013.json")
    for parent in Path(__file__).resolve().parents:
        candidate = parent / relative_path
        if candidate.is_file():
            return candidate
    return Path.home() / "Python-Projekte" / relative_path


def default_live_snapshot_path() -> Path:
    """Rolling snapshot of the last successful AA fetch, kept next to this tool."""
    configured = os.environ.get(LIVE_SNAPSHOT_ENV)
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parent / "data" / LIVE_SNAPSHOT_NAME


def fetch_aa_snapshot(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read the validated AA Free API snapshot as a time-bounded score-population fallback."""
    if not path.is_file():
        return [], {"status": "missing", "file_name": path.name}
    try:
        raw = path.read_bytes()
    except OSError:
        return [], {"status": "unreadable", "file_name": path.name}
    digest = hashlib.sha256(raw).hexdigest()
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return [], {"status": "invalid", "file_name": path.name, "sha256": digest, "reason": "invalid JSON"}

    meta = payload.get("meta") if isinstance(payload, dict) else None
    rows = payload.get("data") if isinstance(payload, dict) else None
    if (
        not isinstance(meta, dict)
        or not isinstance(rows, list)
        or meta.get("source_url") != AA_URL
        # This `free` value describes the AA API tier, not whether a model is $0.
        or meta.get("tier") != "free"
        or meta.get("has_more_final") is not False
        or type(meta.get("pages")) is not int
        or meta["pages"] < 1
        or type(meta.get("page_size")) is not int
        or meta["page_size"] < 1
        or type(meta.get("records")) is not int
        or meta["records"] != len(rows)
        or finite_number(meta.get("intelligence_index_version")) is None
    ):
        return [], {
            "status": "invalid",
            "file_name": path.name,
            "sha256": digest,
            "reason": "schema or provenance mismatch",
        }

    retrieved_at = meta.get("retrieved_at_utc")
    try:
        retrieved = datetime.fromisoformat(str(retrieved_at))
    except ValueError:
        return [], {
            "status": "invalid",
            "file_name": path.name,
            "sha256": digest,
            "reason": "invalid retrieval timestamp",
        }
    if retrieved.tzinfo is None:
        return [], {
            "status": "invalid",
            "file_name": path.name,
            "sha256": digest,
            "reason": "retrieval timestamp has no timezone",
        }

    ids: set[str] = set()
    for row_number, row in enumerate(rows, start=1):
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("id"), str)
            or not isinstance(row.get("slug"), str)
            or not isinstance(row.get("evaluations"), dict)
        ):
            return [], {
                "status": "invalid",
                "file_name": path.name,
                "sha256": digest,
                "reason": f"incomplete model schema at row {row_number}",
            }
        if row["id"] in ids:
            return [], {"status": "invalid", "file_name": path.name, "sha256": digest, "reason": "duplicate model id"}
        ids.add(row["id"])

    age_seconds = (datetime.now(UTC) - retrieved.astimezone(UTC)).total_seconds()
    if age_seconds < -300:
        return [], {
            "status": "invalid",
            "file_name": path.name,
            "sha256": digest,
            "reason": "future retrieval timestamp",
        }
    age_days = max(0, int(age_seconds // 86400))
    provenance = {
        "status": "ok" if age_seconds <= AA_SNAPSHOT_MAX_AGE_DAYS * 86400 else "stale",
        "file_name": path.name,
        "source_url": meta["source_url"],
        "documentation_url": meta.get("documentation_url"),
        "retrieved_at": retrieved.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "age_days": age_days,
        "max_age_days": AA_SNAPSHOT_MAX_AGE_DAYS,
        "row_count": len(rows),
        "page_count": meta["pages"],
        "intelligence_index_version": meta["intelligence_index_version"],
        "sha256": digest,
    }
    return (rows if provenance["status"] == "ok" else []), provenance


def write_aa_snapshot(path: Path, rows: list[dict[str, Any]], source: dict[str, Any]) -> dict[str, Any]:
    """Persist a successful live AA fetch as the next rolling fallback.

    The file uses the same schema ``fetch_aa_snapshot`` validates, so the two
    readers stay interchangeable. Written atomically: a failed build never
    leaves a half-written snapshot behind.
    """
    payload = {
        "meta": {
            "documentation_url": AA_DOCUMENTATION_URL,
            "source_url": AA_URL,
            "tier": source.get("tier"),
            "has_more_final": False,
            "page_size": source.get("page_size"),
            "pages": source.get("page_count"),
            "records": len(rows),
            "intelligence_index_version": source.get("intelligence_index_version"),
            "retrieved_at_utc": source.get("retrieved_at"),
        },
        "data": rows,
    }
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    encoded = body.encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_bytes(encoded)
    os.replace(temporary, path)
    return {
        "path": str(path),
        "bytes": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


@dataclass(frozen=True)
class AaPopulation:
    """Live AA rows plus the fallback snapshot chosen for this run."""

    rows: list[dict[str, Any]]
    source: dict[str, Any]
    snapshot_rows: list[dict[str, Any]]
    snapshot_source: dict[str, Any]
    live_snapshot_source: dict[str, Any]
    dated_snapshot_source: dict[str, Any]


def load_aa_population(
    *,
    live_snapshot_path: Path,
    dated_snapshot_path: Path,
    api_key: str | None,
    persist_live_snapshot: bool = True,
) -> AaPopulation:
    """Fetch AA live, persist the rolling snapshot, and select the fallback.

    A failed or missing live fetch is not fatal: the rolling snapshot of the
    last successful fetch is used, then the dated snapshot. The build aborts
    later only when no usable Intelligence population remains.
    """
    rows: list[dict[str, Any]] = []
    if api_key:
        try:
            rows, source = fetch_aa_models(api_key)
        except CatalogError as error:
            rows, source = (
                [],
                {
                    "url": AA_URL,
                    "status": "unavailable",
                    "reason": str(error),
                    "retrieved_at": _now(),
                },
            )
        else:
            if persist_live_snapshot:
                try:
                    source["snapshot"] = {"status": "written", **write_aa_snapshot(live_snapshot_path, rows, source)}
                except OSError as error:
                    source["snapshot"] = {
                        "status": "write_failed",
                        "path": str(live_snapshot_path),
                        "reason": str(error),
                    }
            else:
                source["snapshot"] = {"status": "skipped"}
    else:
        source = {
            "url": AA_URL,
            "status": "unavailable",
            "reason": "ARTIFICIAL_ANALYSIS_API_KEY ist nicht gesetzt.",
            "retrieved_at": _now(),
        }

    live_snapshot_rows, live_snapshot_source = fetch_aa_snapshot(live_snapshot_path)
    dated_rows, dated_snapshot_source = fetch_aa_snapshot(dated_snapshot_path)
    if live_snapshot_rows:
        snapshot_rows, snapshot_source = live_snapshot_rows, live_snapshot_source
    else:
        snapshot_rows, snapshot_source = dated_rows, dated_snapshot_source
    return AaPopulation(
        rows=rows,
        source=source,
        snapshot_rows=snapshot_rows,
        snapshot_source=snapshot_source,
        live_snapshot_source=live_snapshot_source,
        dated_snapshot_source=dated_snapshot_source,
    )


def fetch_openrouter_models(api_key: str | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
    payload, digest = _get_json(OR_MODELS_URL, headers)
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise CatalogError("OpenRouter: data-Modellliste fehlt.")
    ids: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or row["id"] in ids:
            raise CatalogError("OpenRouter: fehlende oder doppelte Modell-id.")
        ids.add(row["id"])
    return rows, {"url": OR_MODELS_URL, "retrieved_at": _now(), "row_count": len(rows), "sha256": digest}


def fetch_openrouter_aa_indices(
    management_key: str | None, api_key: str | None
) -> tuple[dict[str, dict[str, float]], dict[str, Any]]:
    key = management_key or api_key
    key_env = "OPENROUTER_MANAGEMENT_KEY" if management_key else "OPENROUTER_API_KEY" if api_key else None
    if not key or not key_env:
        return {}, {"status": "unavailable", "reason": "kein OpenRouter-Key fuer Benchmark-GET verfuegbar"}
    metrics: dict[str, dict[str, float]] = {}
    provenance: dict[str, Any] = {
        "status": "ok",
        "url": OR_BENCHMARKS_URL,
        "retrieved_at": _now(),
        "credential_env": key_env,
        "tasks": {},
    }
    for task, field in TASK_TYPES.items():
        query = urllib.parse.urlencode({"source": "artificial-analysis", "task_type": task})
        payload, digest = _get_json(f"{OR_BENCHMARKS_URL}?{query}", {"Authorization": f"Bearer {key}"})
        meta, rows = payload.get("meta"), payload.get("data")
        if not isinstance(meta, dict) or not isinstance(rows, list):
            raise CatalogError(f"OpenRouter-Benchmark {task}: meta oder data fehlt.")
        if meta.get("source") != "artificial-analysis" or meta.get("task_type") != task:
            raise CatalogError(f"OpenRouter-Benchmark {task}: falsche source/task_type-Metadaten.")
        seen: set[str] = set()
        scored = 0
        for row in rows:
            model_id = row.get("model_permaslug") if isinstance(row, dict) else None
            if not isinstance(model_id, str) or model_id in seen or row.get("source") != "artificial-analysis":
                raise CatalogError(f"OpenRouter-Benchmark {task}: fehlende oder doppelte model_permaslug.")
            seen.add(model_id)
            value = finite_number(row.get(field))
            if value is not None:
                metrics.setdefault(model_id, {})[task] = value
                scored += 1
        count = meta.get("model_count")
        if type(count) is not int or count != len(rows):
            raise CatalogError(f"OpenRouter-Benchmark {task}: model_count stimmt nicht mit data ueberein.")
        provenance["tasks"][task] = {
            "as_of": meta.get("as_of"),
            "version": meta.get("version"),
            "row_count": len(rows),
            "scored_row_count": scored,
            "sha256": digest,
        }
    return metrics, provenance


class _TableParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in {"th", "td"} and self._row is not None:
            self._cell = []
        elif tag in {"del", "s", "strike"}:
            self._skip_depth += 1
        elif tag == "br" and self._cell is not None and self._skip_depth == 0:
            self._cell.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"del", "s", "strike"}:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in {"th", "td"} and self._cell is not None and self._row is not None:
            self._row.append("".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None and self._skip_depth == 0:
            self._cell.append(data)


@dataclass(frozen=True)
class PriceTier:
    model_name: str
    input_price: Decimal
    monthly_limit: str | None = None


def _normal_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _base_model_name(value: str) -> str:
    name = _normal_text(value)
    return re.sub(r"\s+\((?:[^)]*(?:tokens|off-peak|peak|% off)[^)]*)\)$", "", name, flags=re.IGNORECASE).strip()


def _display_key(value: str) -> str:
    return _normal_text(_base_model_name(value)).casefold()


def _slug_key(value: str) -> str:
    value = _base_model_name(value).casefold().replace(".", "-")
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", value)).strip("-")


def parse_money(value: str) -> Decimal | None:
    text = _normal_text(value).casefold()
    if "free" in text:
        return Decimal(0)
    if not text or text in {"-", "—", "n/a"}:
        return None
    match = re.search(r"(?:\$\s*)?([0-9]+(?:\.[0-9]+)?)", text)
    if not match:
        return None
    try:
        number = Decimal(match.group(1))
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _header_index(table: list[list[str]], keys: set[str]) -> tuple[int, dict[str, int]] | None:
    for row_index, row in enumerate(table):
        header = {re.sub(r"[^a-z]", "", value.casefold()): index for index, value in enumerate(row)}
        if keys <= header.keys():
            return row_index, header
    return None


def parse_console_price_tables(document_html: str) -> tuple[dict[str, str], list[PriceTier]]:
    parser = _TableParser()
    parser.feed(document_html)
    ids_by_name: dict[str, str] = {}
    tiers: list[PriceTier] = []
    for table in parser.tables:
        model_header = _header_index(table, {"model", "modelid"})
        if model_header:
            row_index, header = model_header
            for row in table[row_index + 1 :]:
                if max(header["model"], header["modelid"]) >= len(row):
                    continue
                name, model_id = _display_key(row[header["model"]]), _normal_text(row[header["modelid"]])
                if name and model_id:
                    if name in ids_by_name and ids_by_name[name] != model_id:
                        raise CatalogError(f"OpenCode Console: mehrdeutiger Modellname: {name}")
                    ids_by_name[name] = model_id
        price_header = _header_index(table, {"model", "input", "output", "cachedread", "cachedwrite"})
        if not price_header:
            continue
        row_index, header = price_header
        for row in table[row_index + 1 :]:
            if max(header["model"], header["input"]) >= len(row):
                continue
            price = parse_money(row[header["input"]])
            if price is not None:
                tiers.append(PriceTier(_base_model_name(row[header["model"]]), price))
    if not ids_by_name:
        raise CatalogError("OpenCode Console: Modellname↔Modell-ID-Tabelle nicht gefunden.")
    if not tiers:
        raise CatalogError("OpenCode Console: Preistabelle nicht gefunden.")
    return ids_by_name, tiers


def parse_go_price_table(document_html: str) -> list[PriceTier]:
    parser = _TableParser()
    parser.feed(document_html)
    for table in parser.tables:
        found = _header_index(table, {"model", "input", "output", "cachedread", "cachedwrite", "monthlylimit"})
        if not found:
            continue
        row_index, header = found
        tiers: list[PriceTier] = []
        for row in table[row_index + 1 :]:
            if max(header["model"], header["input"], header["monthlylimit"]) >= len(row):
                continue
            price = parse_money(row[header["input"]])
            if price is not None:
                limit = _normal_text(row[header["monthlylimit"]]) or None
                tiers.append(PriceTier(_base_model_name(row[header["model"]]), price, limit))
        if tiers:
            return tiers
    raise CatalogError("OpenCode Go: Preistabelle des Go-Tarifs nicht gefunden.")


def parse_go_plan_prices(document_html: str) -> dict[str, str]:
    parser = _TableParser()
    parser.feed(document_html)
    for table in parser.tables:
        found = _header_index(table, {"plan", "price", "includedusage"})
        if not found:
            continue
        row_index, header = found
        plans = {}
        for row in table[row_index + 1 :]:
            if max(header["plan"], header["price"]) < len(row):
                name = _normal_text(row[header["plan"]])
                price = _normal_text(row[header["price"]])
                if name and price:
                    plans[name] = price
        if plans:
            return plans
    raise CatalogError("OpenCode Go: monatliche Tarifpreise nicht gefunden.")


def _index_values(row: dict[str, Any]) -> dict[str, float]:
    evaluations = row.get("evaluations")
    if not isinstance(evaluations, dict):
        return {}
    output: dict[str, float] = {}
    for index, suffix in TASK_TYPES.items():
        value = finite_number(evaluations.get(f"artificial_analysis_{suffix}"))
        if value is not None:
            output[index] = value
    return output


def _best_index_values(rows: list[dict[str, Any]], index: str) -> dict[str, float]:
    """Highest value per base model across AA reasoning levels.

    AA lists one row per reasoning effort (``-low`` … ``-max`` plus
    ``-non-reasoning``). Collapsing each family to its strongest level keeps one
    value per model, both for the calibration population and for a target's
    score. The base slug is often but not always the strongest level.
    """
    best: dict[str, float] = {}
    for position, row in enumerate(rows):
        slug = row.get("slug")
        value = _index_values(row).get(index)
        if value is None:
            continue
        # A row without a slug cannot be grouped; keep it as its own model.
        base = aa_model_base(slug) if isinstance(slug, str) else f"__row_{position}"
        current = best.get(base)
        if current is None or value > current:
            best[base] = value
    return best


def _usable_calibration_population(values: list[Any]) -> tuple[float, ...] | None:
    population = score_population(values)
    if population is None or not any(population):
        return None
    return population


def calibration_populations(
    aa_rows: list[dict[str, Any]],
    snapshot_rows: list[dict[str, Any]],
    or_metrics: dict[str, dict[str, float]] | None = None,
) -> tuple[dict[str, tuple[float, ...]], dict[str, str]]:
    """Kalibriert den AA-Intelligence-Index vor der Preisfilterung.

    Die Skala verwendet pro Modell den höchsten Wert über alle AA-Reasoning-
    Stufen. Preisfilter und Score-Schwelle werden erst danach angewendet. Der
    optionale ``or_metrics``-Parameter bleibt für ältere Aufrufer akzeptiert,
    beeinflusst die Auswahl aber absichtlich nicht.
    """
    del or_metrics
    live_population = _usable_calibration_population(list(_best_index_values(aa_rows, "intelligence").values()))
    source = "artificial-analysis-data-api"
    if live_population is None:
        live_population = _usable_calibration_population(
            list(_best_index_values(snapshot_rows, "intelligence").values())
        )
        source = "artificial-analysis-local-snapshot"
    if live_population is None:
        return {}, {}

    return {"intelligence": live_population}, {"intelligence": source}


def usable_live_indices(primary_values: dict[str, float], population_sources: dict[str, str]) -> dict[str, float]:
    """Verwendet Live-AA-Einzelwerte nur, wenn auch dessen Population gültig war."""
    return {
        index: value
        for index, value in primary_values.items()
        if population_sources.get(index) == "artificial-analysis-data-api"
    }


def usable_snapshot_indices(snapshot_values: dict[str, float], population_sources: dict[str, str]) -> dict[str, float]:
    """Verhindert alte Snapshot-Werte, sobald Live-AA dieselbe Indexpopulation liefert."""
    return {
        index: value
        for index, value in snapshot_values.items()
        if population_sources.get(index) == "artificial-analysis-local-snapshot"
    }


def _proxy_state_dir(codex_dir: Path) -> Path:
    override = os.environ.get("OPENCODE_GO_PROXY_STATE_DIR")
    return Path(override).expanduser() if override else codex_dir / "opencode-go-proxy"


def fetch_proxy_catalog(
    codex_dir: Path, proxy_models_url: str | None = None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    proxy_models_url = proxy_models_url or default_proxy_models_url()
    live_hash: str | None = None
    live_ids: set[str] | None = None
    live_error: str | None = None
    try:
        payload, live_hash = _get_json(proxy_models_url)
        data = payload.get("data")
        if not isinstance(data, list):
            raise CatalogError("/v1/models lieferte keine data-Liste.")
        live_ids = {str(item["id"]) for item in data if isinstance(item, dict) and item.get("id")}
    except CatalogError as error:
        live_error = str(error)
    routed_ids = {value for value in live_ids or set() if value.startswith(("opencode-go/", "zen/"))}
    if live_ids is not None and not routed_ids:
        raise CatalogError("Lokaler Proxy: keine Go- oder Zen-Modelle unter /v1/models.")

    state_dir = _proxy_state_dir(codex_dir)
    caches = sorted(state_dir.glob("merged-models*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not caches:
        raise CatalogError(f"Lokaler Proxy: Codex-Metadatenkatalog fehlt in {state_dir}.")
    cache_path = caches[0]
    raw = cache_path.read_bytes()
    try:
        cached = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise CatalogError("Lokaler Proxy: Codex-Metadatenkatalog ist kein gueltiges JSON.") from error
    entries = cached.get("models") if isinstance(cached, dict) else None
    if not isinstance(entries, list):
        raise CatalogError("Lokaler Proxy: Codex-Metadatenkatalog hat kein models-Array.")
    ids = [slug for entry in entries if isinstance(entry, dict) and isinstance((slug := entry.get("slug")), str)]
    if len(ids) != len(set(ids)):
        raise CatalogError("Lokaler Proxy: doppelte Modell-slugs im Codex-Metadatenkatalog.")
    cached_routes = {value for value in ids if value.startswith(("opencode-go/", "zen/"))}
    if live_ids is not None and cached_routes != routed_ids:
        raise CatalogError("Lokaler Proxy: Live-Routen und Codex-Katalog weichen ab; Katalog aktualisieren.")
    return entries, {
        "url": proxy_models_url,
        "retrieved_at": _now(),
        "live_sha256": live_hash,
        "live_verified": live_ids is not None,
        "live_error": live_error,
        "state_catalog": str(cache_path),
        "state_catalog_sha256": hashlib.sha256(raw).hexdigest(),
        "live_provider_model_count": len(routed_ids) if live_ids is not None else None,
        "cached_provider_model_count": len(cached_routes),
        "state_catalog_fetched_at": cached.get("fetched_at"),
    }


def _price_per_million(model: dict[str, Any]) -> Decimal | None:
    pricing = model.get("pricing")
    if not isinstance(pricing, dict):
        return None
    try:
        amount = Decimal(str(pricing.get("prompt")))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not amount.is_finite() or amount < 0:
        return None
    return amount * USD_PER_MILLION


def _selection_reason(
    provider: str,
    identifier: str,
    input_price: Decimal,
    score: float | None,
    *,
    input_price_limit: Decimal = INPUT_PRICE_LIMIT,
    min_calibrated_score: float = MIN_CALIBRATED_SCORE,
    include_unverified_free: bool = False,
    include_router_models: bool = False,
) -> str | None:
    if is_router_model(identifier):
        return "router_model_exception" if include_router_models and provider == "openrouter" else None
    if is_free_variant(provider, identifier):
        return None
    if qualifies_model(
        input_price,
        score,
        input_price_limit=input_price_limit,
        min_calibrated_score=min_calibrated_score,
    ):
        return "price_and_calibrated_score"
    if (
        include_unverified_free
        and provider == "openrouter"
        and is_free_offer(provider, identifier)
        and score is None
        and input_price == 0
    ):
        return "unverified_free_exception"
    return None


def _candidate_sort_key(provider: str, candidate: dict[str, Any]) -> tuple[int, int, bool, bool, float, Decimal, str]:
    """Order a catalog; the proxy lists all Go routes before all Zen routes.

    Codex renders the model picker by the catalog ``priority`` field, which the
    builder assigns from this order. Within a route group the previous rule
    still applies: preferred model, scored before unverified, higher score,
    lower price, id. OpenRouter router slugs carry a variable price and rank
    after every free route.
    """
    identifier = str(candidate["id"])
    preferred = identifier == PREFERRED_MODEL_IDS.get(provider)
    score = finite_number(candidate.get("score"))
    route_group = 0
    if provider == "proxy" and not identifier.startswith("opencode-go/"):
        route_group = 1
    router_rank = 1 if provider == "openrouter" and is_router_model(identifier) else 0
    return (
        route_group,
        router_rank,
        not preferred,
        score is None,
        -(score if score is not None else 0.0),
        Decimal(str(candidate["price"])),
        identifier.casefold(),
    )


def _dedupe_reasoning_variants(
    items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep one catalog entry per base model and provider route.

    The picker lists a model once per provider; its reasoning intensity is the
    entry's ``supported_reasoning_levels``/``default_reasoning_level``
    sub-selection. If a provider advertises effort-suffixed variants as separate
    routes, the best-scored one wins (then the cheaper, then the shorter slug)
    and the rest are reported as dropped. ``opencode-go/`` and ``zen/`` stay
    distinct routes: they are different billing paths, not reasoning levels.
    """
    kept: dict[tuple[str, str], dict[str, Any]] = {}
    dropped: list[dict[str, Any]] = []
    for item in items:
        identifier = str(item["id"])
        vendor, _, model = identifier.rpartition("/")
        key = (vendor, aa_model_base(model))
        current = kept.get(key)
        if current is None:
            kept[key] = item
        elif _reasoning_variant_rank(item) > _reasoning_variant_rank(current):
            dropped.append(current)
            kept[key] = item
        else:
            dropped.append(item)
    return list(kept.values()), dropped


def _reasoning_variant_rank(item: dict[str, Any]) -> tuple[bool, float, Decimal, int]:
    score = finite_number(item.get("score"))
    return (
        score is not None,
        score if score is not None else 0.0,
        -Decimal(str(item["price"])),
        -len(str(item["id"])),
    )


def _price_ids(tiers: list[PriceTier], route_ids: list[str]) -> dict[str, str]:
    by_key: dict[str, list[str]] = {}
    for route_id in route_ids:
        by_key.setdefault(_slug_key(route_id), []).append(route_id)
    names = {_display_key(tier.model_name): tier.model_name for tier in tiers}
    result: dict[str, str] = {}
    for display_name in names.values():
        matches = by_key.get(_slug_key(display_name), [])
        if len(matches) == 1:
            result[matches[0]] = display_name
    return result


def _direct_provider_identifier(provider: str, route_id: str) -> str:
    """Keeps direct Go slugs in the Codex provider namespace; Zen uses bare IDs."""
    return f"opencode-go/{route_id}" if provider == "go" else route_id


def _aa_family_row(target_id: str, rows: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str]:
    """Row with the highest Intelligence value among the target's AA variants.

    Identity still starts with ``unique_model_component``; only the effort
    level is widened, so two genuinely different models are not merged. A
    target that names an effort suffix resolves to its base family.
    """
    slugs = [str(row["slug"]) for row in rows if isinstance(row.get("slug"), str)]
    match = unique_model_component(target_id, slugs)
    if match is not None:
        base = aa_model_base(match)
    else:
        base = aa_model_base(normalized_component(target_id))
        if not any(aa_model_base(slug) == base for slug in slugs):
            return None, "unverified"
    best_row: dict[str, Any] | None = None
    best_value: float | None = None
    for row in rows:
        slug = row.get("slug")
        if not isinstance(slug, str) or aa_model_base(slug) != base:
            continue
        value = _index_values(row).get("intelligence")
        if value is None:
            continue
        if best_value is None or value > best_value:
            best_row, best_value = row, value
    if best_row is None:
        return None, "unverified"
    chosen = str(best_row["slug"])
    if normalized_component(chosen) == normalized_component(target_id):
        return best_row, "exact slug"
    return best_row, f"reasoning-family maximum ({chosen})"


def _source_metrics(
    target_id: str,
    aa_rows: list[dict[str, Any]],
    snapshot_rows: list[dict[str, Any]],
    or_metrics: dict[str, dict[str, float]],
) -> tuple[dict[str, float], dict[str, float], dict[str, float], str]:
    aa_row, aa_join = _aa_family_row(target_id, aa_rows)
    primary = _index_values(aa_row) if aa_row is not None else {}
    snapshot_row, snapshot_join = _aa_family_row(target_id, snapshot_rows)
    snapshot_values = _index_values(snapshot_row) if snapshot_row is not None else {}
    if target_id in or_metrics:
        or_match = target_id
    else:
        or_match = unique_model_component(target_id, list(or_metrics))
    fallback = or_metrics.get(or_match, {}) if or_match else {}
    or_join = (
        "exact model_permaslug"
        if target_id == or_match
        else "unique exact model-id component"
        if or_match
        else "unverified"
    )
    join = f"AA={aa_join}; AA snapshot={snapshot_join}; OpenRouter={or_join}"
    return primary, snapshot_values, fallback, join


def _score_transport_sources(
    method: str,
    primary: dict[str, float],
    snapshot: dict[str, float],
    fallback: dict[str, float],
) -> tuple[str, str]:
    del fallback
    sources: list[str] = []
    if method.startswith("AA Intelligence Index"):
        if finite_number(primary.get("intelligence")) is not None:
            sources = ["artificial-analysis-data-api"]
        elif finite_number(snapshot.get("intelligence")) is not None:
            sources = ["artificial-analysis-local-snapshot"]

    labels = {
        "artificial-analysis-data-api": "AA Data API",
        "artificial-analysis-local-snapshot": "dated AA snapshot",
    }
    return "+".join(sources) or "unverified", " + ".join(labels[source] for source in sources) or "unverified"


def _clone_model(template: dict[str, Any], source: dict[str, Any] | None, slug: str) -> dict[str, Any]:
    entry = copy.deepcopy(source if source is not None else template)
    entry["slug"] = slug
    entry["visibility"] = "list"
    entry["supported_in_api"] = True
    entry["availability_nux"] = None
    entry["upgrade"] = None
    for key in REMOVE_KEYS:
        entry.pop(key, None)
    entry.update(MODEL_OVERRIDES.get(slug.split("/", 1)[-1], {}))
    if source is None and not slug.startswith("openai/"):
        entry["shell_type"] = "default"
    return entry


def _price_label(values: list[Decimal]) -> str:
    if any(value < 0 for value in values):
        return "variabler Preis"
    low, high = min(values), max(values)
    return f"${low}/M input" if low == high else f"${low}–${high}/M input"


def _format_intelligence_score(score: float | None) -> str:
    """Format a display-only score without changing its stored precision."""
    return f"{score:.1f}/100" if score is not None else "unverified"


def _make_entry(
    *,
    provider: str,
    identifier: str,
    source_model: dict[str, Any] | None,
    template: dict[str, Any],
    label: str,
    prices: list[Decimal],
    limits: list[str],
    score: float | None,
    method: str,
    transport: str,
    price_source: str,
    selection_reason: str,
    plan_fee: str | None = None,
    extra_note: str = "",
) -> dict[str, Any]:
    entry = _clone_model(template, source_model, identifier)
    price_text = _price_label(prices)
    billing_provider = provider.split(":", 1)[-1]
    limit_text = f"; Go-Tarif {plan_fee}" if billing_provider == "go" and plan_fee else ""
    if billing_provider == "go" and limits:
        limit_text += f"; Modell-Kontingent {limits[0]}/Monat"
    if billing_provider == "zen":
        limit_text += "; Pay-as-you-go"
    score_text = _format_intelligence_score(score)
    entry["display_name"] = f"{label} · {price_text} · Intelligence-Score {score_text}{limit_text}"
    benchmark_source = "AA" if score is not None else "unverified"
    entry["description"] = (
        f"{label} — {identifier}; {price_text}{limit_text}; AA-Intelligence-Score {score_text}; "
        f"Auswahl: {selection_reason}; "
        f"Basis: {method}; benchmark_source={benchmark_source}; "
        f"transport_source={transport}; price_source={price_source}"
    )
    if extra_note:
        entry["description"] += f"; {extra_note}"
    if provider == "openrouter" and identifier != "openai/gpt-6-luna":
        entry["supported_reasoning_levels"] = DEFAULT_REASONING_LEVELS
        entry["default_reasoning_level"] = "medium"
    return entry


def _template_models(payload: Any) -> list[dict[str, Any]]:
    models = payload.get("models") if isinstance(payload, dict) else payload
    if not isinstance(models, list) or not models:
        raise CatalogError("Codex-Native-Katalog enthaelt keine Modelle als Template.")
    templates = [model for model in models if isinstance(model, dict)]
    if not templates:
        raise CatalogError("Codex-Native-Katalog enthaelt keine Modellobjekte als Template.")
    return templates


def load_native_catalog_template(
    template_path: Path | None,
    *,
    codex_dir: Path,
    codex_bin: str = "codex",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load a full Codex model as template, falling back to `codex debug models`."""
    default_path = codex_dir / ".tmp" / "bundled-catalog.json"
    selected_path = template_path or default_path
    if selected_path.exists():
        try:
            raw = selected_path.read_bytes()
            payload = json.loads(raw)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
            raise CatalogError(f"Codex-Native-Katalog nicht lesbar: {selected_path}") from error
        templates = _template_models(payload)
        return templates, {
            "source": "file",
            "path": str(selected_path),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    if template_path is not None:
        raise CatalogError(f"Codex-Native-Katalog nicht lesbar: {selected_path}")

    # --bundled bypasses the configured model_catalog_json. A plain
    # `codex debug models` would return the proxy's own routes (or whatever
    # catalog Codex currently points at), which is not a native template.
    command = [codex_bin, "debug", "models", "--bundled"]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=CODEX_TEMPLATE_TIMEOUT_SEC,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CatalogError("Codex-Native-Katalog fehlt; --template angeben oder Codex CLI installieren") from error
    if result.returncode != 0:
        detail = " | ".join(line.strip() for line in (result.stderr or "").splitlines()[:3] if line.strip())
        raise CatalogError(
            f"{codex_bin} debug models --bundled exited {result.returncode}" + (f": {detail}" if detail else "")
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise CatalogError("codex debug models --bundled lieferte kein gueltiges JSON.") from error
    templates = _template_models(payload)
    return templates, {
        "source": "codex-debug-models-bundled",
        "command": command,
        "stdout_sha256": hashlib.sha256(result.stdout.encode("utf-8")).hexdigest(),
    }


def build_catalog_data(
    *,
    display_overrides: dict[str, str] | None,
    template_path: Path | None,
    codex_dir: Path,
    aa_snapshot_path: Path | None = None,
    live_snapshot_path: Path | None = None,
    persist_live_snapshot: bool = True,
    input_price_limit: Decimal = INPUT_PRICE_LIMIT,
    min_calibrated_score: float = MIN_CALIBRATED_SCORE,
    include_unverified_free: bool = False,
    include_router_models: bool = False,
    proxy_models_url: str | None = None,
    codex_bin: str = "codex",
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    population = load_aa_population(
        live_snapshot_path=live_snapshot_path or default_live_snapshot_path(),
        dated_snapshot_path=aa_snapshot_path or default_aa_snapshot_path(),
        api_key=os.environ.get("ARTIFICIAL_ANALYSIS_API_KEY"),
        persist_live_snapshot=persist_live_snapshot,
    )
    aa_rows, aa_source = population.rows, population.source
    aa_snapshot_rows, aa_snapshot_source = population.snapshot_rows, population.snapshot_source
    or_rows, or_source = fetch_openrouter_models(os.environ.get("OPENROUTER_API_KEY"))
    # OpenRouter benchmark transport is intentionally not part of picker
    # scoring. The picker uses only AA Intelligence, with the rolling live
    # snapshot (then the dated snapshot) as population fallback when live
    # Intelligence is unusable.
    or_metrics: dict[str, dict[str, float]] = {}
    or_benchmark_source = {
        "status": "disabled",
        "reason": "OpenRouter Coding/Agentic fallback is not used by the picker",
    }
    proxy_entries, proxy_source = fetch_proxy_catalog(codex_dir, proxy_models_url)

    go_html = _get_bytes(GO_DOC_URL)
    zen_html = _get_bytes(ZEN_DOC_URL)
    go_tiers = parse_go_price_table(go_html.decode("utf-8"))
    go_plans = parse_go_plan_prices(go_html.decode("utf-8"))
    if "Go" not in go_plans:
        raise CatalogError("OpenCode Go: Basistarif Go fehlt in der Tarifuebersicht.")
    zen_ids_by_name, zen_tiers = parse_console_price_tables(zen_html.decode("utf-8"))
    go_source = {
        "url": GO_DOC_URL,
        "retrieved_at": _now(),
        "sha256": hashlib.sha256(go_html).hexdigest(),
        "plan_prices": go_plans,
        "selected_plan_for_model_limits": "Go",
    }
    zen_source = {"url": ZEN_DOC_URL, "retrieved_at": _now(), "sha256": hashlib.sha256(zen_html).hexdigest()}

    templates, native_template_source = load_native_catalog_template(
        template_path, codex_dir=codex_dir, codex_bin=codex_bin
    )
    template = min(templates, key=lambda model: len(json.dumps(model, ensure_ascii=False)))

    diagnostics = {
        provider: {
            "under_price_limit": 0,
            "direct_aa_identity_match": 0,
            "score_available": 0,
            "selected": 0,
            "free_variants_excluded": 0,
            "highest_score": None,
            "highest_score_model": None,
        }
        for provider in ("openrouter", "go", "zen")
    }
    evaluated: list[dict[str, Any]] = []
    openrouter_ids = [str(model["id"]) for model in or_rows]
    benchmark_ids: list[str] = []
    benchmark_identity_diagnostics = {
        "openrouter_benchmark_model_ids_with_scores": len(benchmark_ids),
        "exact_openrouter_id_intersections": len(set(openrouter_ids) & set(benchmark_ids)),
        "unique_exact_component_matches": sum(
            unique_model_component(identifier, benchmark_ids) is not None for identifier in openrouter_ids
        ),
    }

    go_models = [entry for entry in proxy_entries if str(entry.get("slug", "")).startswith("opencode-go/")]
    zen_models = [entry for entry in proxy_entries if str(entry.get("slug", "")).startswith("zen/")]
    go_ids = [str(entry["slug"]).split("/", 1)[1] for entry in go_models]
    zen_ids = [str(entry["slug"]).split("/", 1)[1] for entry in zen_models]
    go_doc_names = _price_ids(go_tiers, go_ids)
    go_prices: dict[str, list[PriceTier]] = {}
    for tier in go_tiers:
        route_id = next(
            (
                model_id
                for model_id, name in go_doc_names.items()
                if _display_key(tier.model_name) == _display_key(name)
            ),
            None,
        )
        if route_id:
            go_prices.setdefault(route_id, []).append(tier)
    zen_name_by_id = {model_id: name for name, model_id in zen_ids_by_name.items()}
    zen_prices: dict[str, list[PriceTier]] = {}
    for tier in zen_tiers:
        model_id = zen_ids_by_name.get(_display_key(tier.model_name))
        if model_id:
            zen_prices.setdefault(model_id, []).append(tier)

    ranges, range_sources = calibration_populations(aa_rows, aa_snapshot_rows)
    if not ranges:
        raise CatalogError("AA: keine verwendbare Intelligence-Index-Population vorhanden.")

    proxy_by_slug = {str(entry["slug"]): entry for entry in proxy_entries if isinstance(entry.get("slug"), str)}
    candidates: list[dict[str, Any]] = []
    for model in or_rows:
        identifier = str(model["id"])
        router_model = is_router_model(identifier)
        if router_model and not include_router_models:
            continue
        if is_free_variant("openrouter", identifier):
            diagnostics["openrouter"]["free_variants_excluded"] += 1
            continue
        if router_model:
            price = Decimal("-1")
        else:
            price = _price_per_million(model)
            if price is None or price >= input_price_limit:
                continue
            diagnostics["openrouter"]["under_price_limit"] += 1
        primary, snapshot_values, fallback, join = _source_metrics(identifier, aa_rows, aa_snapshot_rows, or_metrics)
        primary = usable_live_indices(primary, range_sources)
        snapshot_values = usable_snapshot_indices(snapshot_values, range_sources)
        if primary:
            diagnostics["openrouter"]["direct_aa_identity_match"] += 1
        score, method = score_candidate(primary, fallback, ranges, snapshot_values)
        transport_source, transport_label = _score_transport_sources(method, primary, snapshot_values, fallback)
        if score is not None:
            diagnostics["openrouter"]["score_available"] += 1
            if diagnostics["openrouter"]["highest_score"] is None or score > diagnostics["openrouter"]["highest_score"]:
                diagnostics["openrouter"]["highest_score"] = round(score, 6)
                diagnostics["openrouter"]["highest_score_model"] = identifier
        selection_reason = _selection_reason(
            "openrouter",
            identifier,
            price,
            score,
            input_price_limit=input_price_limit,
            min_calibrated_score=min_calibrated_score,
            include_unverified_free=include_unverified_free,
            include_router_models=include_router_models,
        )
        selected = selection_reason is not None
        if not router_model:
            evaluated.append(
                {
                    "provider": "openrouter",
                    "id": identifier,
                    "input_price": str(price),
                    "score": score,
                    "score_method": method,
                    "selected": selected,
                    "selection_reason": selection_reason,
                    "identity_match": join,
                    "benchmark_source": "artificial-analysis" if score is not None else "unverified",
                    "transport_source": transport_source,
                    "aa_index_values": primary,
                    "aa_snapshot_index_values": snapshot_values,
                    "openrouter_aa_index_values": fallback,
                    "price_source": "openrouter-models-api",
                }
            )
        if not selected:
            continue
        diagnostics["openrouter"]["selected"] += 1
        label = (display_overrides or {}).get(identifier) or f"(O.R.) {model.get('name') or identifier}"
        entry = _make_entry(
            provider="openrouter",
            identifier=identifier,
            source_model=None,
            template=template,
            label=label,
            prices=[price],
            limits=[],
            score=score,
            method=method,
            transport=transport_label,
            price_source="OpenRouter /api/v1/models",
            selection_reason=selection_reason,
            extra_note=(
                "Router: Einstellungen accountweit in OpenRouter (Workspace -> Routing, "
                "Settings -> Tools -> Plugins); Codex sendet keine plugins[]"
                if router_model
                else ""
            ),
        )
        candidates.append(
            {
                "provider": "openrouter",
                "id": identifier,
                "label": label,
                "price": str(price),
                "score": round(score, 6) if score is not None else None,
                "score_method": method,
                "selection_reason": selection_reason,
                "identity_match": join,
                "benchmark_source": "artificial-analysis" if score is not None else "unverified",
                "aa_index_values": primary,
                "aa_snapshot_index_values": snapshot_values,
                "openrouter_aa_index_values": fallback,
                "transport_source": transport_source,
                "price_source": "openrouter-models-api",
                "entry": entry,
            }
        )

    for source_provider, route_ids, price_rows, names_by_id in (
        ("go", go_ids, go_prices, {route_id: name for route_id, name in go_doc_names.items()}),
        ("zen", zen_ids, zen_prices, zen_name_by_id),
    ):
        prefix = "opencode-go/" if source_provider == "go" else "zen/"
        for route_id in route_ids:
            if is_free_variant(source_provider, route_id):
                diagnostics[source_provider]["free_variants_excluded"] += 1
                continue
            prices = [tier.input_price for tier in price_rows.get(route_id, [])]
            if not prices or max(prices) >= input_price_limit:
                continue
            diagnostics[source_provider]["under_price_limit"] += 1
            full_id = f"{prefix}{route_id}"
            source_model = proxy_by_slug[full_id]
            primary, snapshot_values, fallback, join = _source_metrics(full_id, aa_rows, aa_snapshot_rows, or_metrics)
            primary = usable_live_indices(primary, range_sources)
            snapshot_values = usable_snapshot_indices(snapshot_values, range_sources)
            if primary:
                diagnostics[source_provider]["direct_aa_identity_match"] += 1
            score, method = score_candidate(primary, fallback, ranges, snapshot_values)
            transport_source, transport_label = _score_transport_sources(method, primary, snapshot_values, fallback)
            if score is not None:
                diagnostics[source_provider]["score_available"] += 1
                if (
                    diagnostics[source_provider]["highest_score"] is None
                    or score > diagnostics[source_provider]["highest_score"]
                ):
                    diagnostics[source_provider]["highest_score"] = round(score, 6)
                    diagnostics[source_provider]["highest_score_model"] = full_id
            selection_reason = _selection_reason(
                source_provider,
                route_id,
                min(prices),
                score,
                input_price_limit=input_price_limit,
                min_calibrated_score=min_calibrated_score,
                include_unverified_free=include_unverified_free,
            )
            selected = selection_reason is not None
            evaluated.append(
                {
                    "provider": source_provider,
                    "id": full_id,
                    "input_price_min": str(min(prices)),
                    "input_price_max": str(max(prices)),
                    "score": score,
                    "score_method": method,
                    "selected": selected,
                    "selection_reason": selection_reason,
                    "identity_match": join,
                    "benchmark_source": "artificial-analysis" if score is not None else "unverified",
                    "transport_source": transport_source,
                    "aa_index_values": primary,
                    "aa_snapshot_index_values": snapshot_values,
                    "openrouter_aa_index_values": fallback,
                    "price_source": "opencode-go-docs" if source_provider == "go" else "opencode-console-docs",
                }
            )
            if not selected:
                continue
            diagnostics[source_provider]["selected"] += 1
            limits = sorted({tier.monthly_limit for tier in price_rows.get(route_id, []) if tier.monthly_limit})
            model_name = names_by_id.get(route_id, route_id).title()
            label = f"Go · {model_name}" if source_provider == "go" else f"Zen · {model_name}"
            direct_id = _direct_provider_identifier(source_provider, route_id)
            for output_provider, output_id in ((source_provider, direct_id), ("proxy", full_id)):
                billing_provider = source_provider if output_provider == "proxy" else output_provider
                entry = _make_entry(
                    provider=f"{output_provider}:{billing_provider}",
                    identifier=output_id,
                    source_model=source_model,
                    template=template,
                    label=label,
                    prices=prices,
                    limits=limits,
                    score=score,
                    method=method,
                    transport=transport_label,
                    price_source="OpenCode Go documentation"
                    if source_provider == "go"
                    else "OpenCode Console documentation",
                    selection_reason=selection_reason,
                    plan_fee=go_plans["Go"] if source_provider == "go" else None,
                )
                candidates.append(
                    {
                        "provider": output_provider,
                        "id": output_id,
                        "label": label,
                        "price": str(min(prices)),
                        "price_max": str(max(prices)),
                        "monthly_limits": limits,
                        "score": round(score, 6) if score is not None else None,
                        "price_tiers": [
                            {
                                "model_name": tier.model_name,
                                "input_price": str(tier.input_price),
                                "monthly_limit": tier.monthly_limit,
                            }
                            for tier in price_rows.get(route_id, [])
                        ],
                        "score_method": method,
                        "selection_reason": selection_reason,
                        "identity_match": join,
                        "benchmark_source": "artificial-analysis" if score is not None else "unverified",
                        "aa_index_values": primary,
                        "aa_snapshot_index_values": snapshot_values,
                        "openrouter_aa_index_values": fallback,
                        "transport_source": transport_source,
                        "price_source": "opencode-go-docs" if source_provider == "go" else "opencode-console-docs",
                        "entry": entry,
                    }
                )

    names = {
        "openrouter": "picker-catalog.json",
        "go": "go-catalog.json",
        "zen": "zen-catalog.json",
        "proxy": "proxy-catalog.json",
    }
    by_provider: dict[str, list[dict[str, Any]]] = {provider: [] for provider in names}
    for candidate in candidates:
        by_provider[candidate["provider"]].append(candidate)
    deduplicated: dict[str, list[str]] = {}
    for provider, items in by_provider.items():
        kept, dropped = _dedupe_reasoning_variants(items)
        by_provider[provider] = kept
        if dropped:
            deduplicated[provider] = [str(item["id"]) for item in dropped]
    # The audit's model list mirrors the written catalogs, not the pre-dedupe set.
    candidates = [item for items in by_provider.values() for item in items]
    catalogs: dict[str, dict[str, Any]] = {}
    for provider, selected in by_provider.items():
        selected.sort(key=lambda item: _candidate_sort_key(provider, item))
        entries = []
        for priority, candidate in enumerate(selected):
            candidate["entry"]["priority"] = priority
            entries.append(candidate["entry"])
        catalogs[provider] = {"models": entries}

    audit = {
        "schema_version": 1,
        "generated_at": _now(),
        "criteria": {
            "input_price_usd_per_million_strictly_less_than": str(input_price_limit),
            "calibrated_score_strictly_greater_than": min_calibrated_score,
            "calibration_population": "all usable AA Intelligence values before provider price filtering",
            "preferred_default_model_if_selected": PREFERRED_MODEL_IDS,
            "free_variants": {
                "policy": "Free-Tier-Routen des OpenCode-Gateways werden nie aufgenommen: Harnesses erhalten 403 FreeTierError oder 429 FreeUsageLimitError. OpenRouter wird direkt angesprochen und ist nicht betroffen.",
                "rule": {
                    "go": "route endet auf '-free'",
                    "zen": "route endet auf '-free'",
                },
                "unverified_free_exception": {
                    "enabled": include_unverified_free,
                    "scope": "nur OpenRouter; Go und Zen bleiben gesperrt",
                    "selected": sorted(
                        str(item["id"])
                        for item in candidates
                        if item.get("selection_reason") == "unverified_free_exception"
                    ),
                },
                "excluded_counts": {
                    provider: diagnostics[provider]["free_variants_excluded"]
                    for provider in ("openrouter", "go", "zen")
                },
            },
            "router_models": {
                "enabled": include_router_models,
                "ids": sorted(ROUTER_MODEL_IDS),
                "selected": sorted(
                    str(item["id"]) for item in candidates if item.get("selection_reason") == "router_model_exception"
                ),
                "note": (
                    "Codex sendet keine plugins[]; cost_tier und min_coding_score werden accountweit "
                    "in OpenRouter gesetzt (Workspace > Routing, Settings > Tools > Plugins)."
                ),
            },
            "calibration": "AA Intelligence Index as a Min-Max scale over all usable values in the selected AA population before provider price filtering (minimum=0, maximum=100, clamping outside the observed range); populations with fewer than two values or all-zero values are unusable",
            "score_policy": (
                "Only calibrated AA Intelligence Index is selectable. Use the live AA population; "
                "when the live fetch fails or its Intelligence population is absent or all zero, "
                "use the rolling live snapshot, then the dated AA snapshot. "
                "Coding/Agentic composites and OpenRouter benchmark transport are not score fallbacks."
            ),
        },
        "sources": {
            "artificial_analysis": aa_source,
            "artificial_analysis_snapshot": aa_snapshot_source,
            "artificial_analysis_live_snapshot": population.live_snapshot_source,
            "artificial_analysis_dated_snapshot": population.dated_snapshot_source,
            "openrouter_models": or_source,
            "openrouter_benchmarks": or_benchmark_source,
            "opencode_proxy": proxy_source,
            "native_template": native_template_source,
            "opencode_go_prices": go_source,
            "opencode_console_prices": zen_source,
        },
        "calibration_populations": {
            key: {
                "model_count": len(values),
                "minimum": values[0],
                "maximum": values[-1],
                "source": range_sources[key],
            }
            for key, values in ranges.items()
        },
        "selection_diagnostics": diagnostics,
        "deduplicated_reasoning_variants": deduplicated,
        "openrouter_benchmark_identity_diagnostics": benchmark_identity_diagnostics,
        "evaluated_candidates": evaluated,
        "model_counts": {key: len(value) for key, value in by_provider.items()},
        "models": [{key: value for key, value in item.items() if key != "entry"} for item in candidates],
    }
    return catalogs, audit


def _write_json(target: Path, payload: dict[str, Any], backup_dir: Path, no_backup: bool) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not no_backup:
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = backup_dir / f"{target.name}.backup-{stamp}"
        if backup.exists():
            backup = backup_dir / f"{target.name}.backup-{stamp}-{time.time_ns()}"
        shutil.copy2(target, backup)
        print(f"Backup: {backup}")
    temporary = target.with_name(f"{target.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, target)


def _verify_codex_loader() -> int:
    try:
        result = subprocess.run(["codex", "debug", "models"], capture_output=True, text=True, timeout=300, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"Loader-Verify nicht ausgefuehrt: {type(error).__name__}")
        return 1
    if result.returncode:
        for line in (result.stderr or "").splitlines()[:3]:
            print(line)
        print(f"Loader-Verify FEHLGESCHLAGEN (exit {result.returncode})")
        return result.returncode
    print("Loader-Verify: ok (exit 0)")
    return 0


def _parse_input_price_limit(value: str) -> Decimal:
    try:
        price_limit = Decimal(value)
    except InvalidOperation:
        raise argparse.ArgumentTypeError("muss ein gueltiger Dezimalpreis in USD pro Million sein") from None
    if not price_limit.is_finite() or price_limit <= 0:
        raise argparse.ArgumentTypeError("muss groesser als 0 und endlich sein")
    return price_limit


def _parse_min_calibrated_score(value: str) -> float:
    score = finite_number(value)
    if score is None or not 0 <= score <= 100:
        raise argparse.ArgumentTypeError("muss eine endliche Zahl zwischen 0 und 100 sein")
    return score


def selection_criteria_text(
    input_price_limit: Decimal = INPUT_PRICE_LIMIT,
    min_calibrated_score: float = MIN_CALIBRATED_SCORE,
) -> str:
    return (
        f"Kriterien: Input < ${input_price_limit}/M Token und "
        f"kalibrierter AA-Intelligence-Score > {min_calibrated_score:g}/100"
    )


def main(*, default_provider: str = "all", display_overrides: dict[str, str] | None = None) -> int:
    codex_dir = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
    parser = argparse.ArgumentParser(description="Erzeugt Preis-/Benchmark-gefilterte Codex-Kataloge.")
    parser.add_argument("--provider", choices=("all", "openrouter", "go", "zen", "proxy"), default=default_provider)
    parser.add_argument(
        "--max-input-price",
        "--input-price-limit",
        dest="input_price_limit",
        type=_parse_input_price_limit,
        default=INPUT_PRICE_LIMIT,
        metavar="USD_PER_M",
        help=(
            "strikte Obergrenze pro 1 Mio. Input-Token; Dezimalzahl in USD ohne "
            f"Waehrungssymbol oder Einheit, z. B. 0.30 (Standard: {INPUT_PRICE_LIMIT})"
        ),
    )
    parser.add_argument(
        "--min-intelligence-score",
        "--min-calibrated-score",
        dest="min_calibrated_score",
        type=_parse_min_calibrated_score,
        default=MIN_CALIBRATED_SCORE,
        metavar="SCORE",
        help=(
            "exklusive Mindestschwelle fuer den normierten AA-Intelligence-Index; "
            "Zahl von 0 bis 100 auf der Min-Max-Skala, z. B. 45 "
            f"(Standard: {MIN_CALIBRATED_SCORE:g})"
        ),
    )
    parser.add_argument(
        "--aa-snapshot",
        type=Path,
        default=default_aa_snapshot_path(),
        help=(
            "lokaler AA-Snapshot als befristeter Fallback fuer fehlende "
            "Intelligence-Population; zusaetzlich wird jeder erfolgreiche Live-Abruf "
            "als rollierender Snapshot unter tools/codex-picker/data/ gespeichert"
        ),
    )
    parser.add_argument("--out-dir", type=Path, default=codex_dir, help="Zielordner (Standard: CODEX_HOME)")
    parser.add_argument("--out", type=Path, help="Exakter Ausgabepfad, nur fuer einen Provider")
    parser.add_argument(
        "--check", action="store_true", help="Quellen live pruefen und Auswahl anzeigen, nichts schreiben"
    )
    parser.add_argument(
        "--template",
        type=Path,
        help=(
            "Codex-Native-Katalog als Formvorlage; Standard: "
            "CODEX_HOME/.tmp/bundled-catalog.json, sonst "
            "`codex debug models --bundled` (umgeht model_catalog_json)"
        ),
    )
    parser.add_argument(
        "--proxy-url",
        default=default_proxy_models_url(),
        help="Modellkatalog des lokalen Proxys (Standard: OPENCODE_GO_PROXY_MODELS_URL oder Port aus OPENCODE_GO_PROXY_PORT)",
    )
    parser.add_argument(
        "--codex-bin",
        default=os.environ.get("OPENCODE_GO_PROXY_CODEX_BIN", "codex"),
        help="Codex-CLI fuer den Template-Fallback (Standard: OPENCODE_GO_PROXY_CODEX_BIN oder codex)",
    )
    parser.add_argument("--no-backup", action="store_true", help="Vorhandene Ausgaben nicht sichern")
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help=(
            "Loader-Pruefung `codex debug models` nach dem Schreiben "
            "ueberspringen; laeuft nur bei Ausgabe nach CODEX_HOME"
        ),
    )
    parser.add_argument(
        "--allow-cached-proxy",
        action="store_true",
        help=(
            "Pruefen/Schreiben mit dem zuletzt gespeicherten Proxy-Katalog "
            "erlauben, wenn der Proxy nicht erreichbar ist; die "
            "Live-/Cache-Konsistenzpruefung bleibt aktiv"
        ),
    )
    parser.add_argument(
        "--include-unverified-free",
        action="store_true",
        help=(
            "unverifizierte Free-Routen von OpenRouter aufnehmen (nur $0-Inputpreis, "
            "ohne Benchmark-Score, im Eintrag als unverified markiert); "
            "Go- und Zen-Free-Routen bleiben immer gesperrt"
        ),
    )
    parser.add_argument(
        "--include-router-models",
        action="store_true",
        help=(
            "OpenRouter-Router openrouter/auto und openrouter/pareto-code aufnehmen "
            "(variabler Preis, kein Benchmark); Router-Einstellungen wie cost_tier und "
            "min_coding_score werden accountweit in OpenRouter gesetzt, weil Codex "
            "keine plugins[] sendet"
        ),
    )
    args = parser.parse_args()
    if args.out and args.provider == "all":
        parser.error("--out ist nur mit genau einem --provider erlaubt.")

    try:
        catalogs, audit = build_catalog_data(
            display_overrides=display_overrides,
            template_path=args.template,
            codex_dir=codex_dir,
            aa_snapshot_path=args.aa_snapshot,
            persist_live_snapshot=not args.check,
            input_price_limit=args.input_price_limit,
            min_calibrated_score=args.min_calibrated_score,
            include_unverified_free=args.include_unverified_free,
            include_router_models=args.include_router_models,
            proxy_models_url=args.proxy_url,
            codex_bin=args.codex_bin,
        )
    except CatalogError as error:
        print(f"Katalogbau abgebrochen: {error}")
        return 1

    filenames = {
        "openrouter": "picker-catalog.json",
        "go": "go-catalog.json",
        "zen": "zen-catalog.json",
        "proxy": "proxy-catalog.json",
    }
    providers = list(filenames) if args.provider == "all" else [args.provider]
    print(selection_criteria_text(args.input_price_limit, args.min_calibrated_score))
    print("  Free-Tier-Routen des OpenCode-Gateways sind ausgeschlossen (in Codex nicht nutzbar)")
    for provider in providers:
        print(f"  {provider}: {len(catalogs[provider]['models'])} Modelle")
    diagnostic_provider = (
        "openrouter"
        if args.provider == "openrouter"
        else "go"
        if args.provider == "go"
        else "zen"
        if args.provider == "zen"
        else None
    )
    diagnostic_keys = (diagnostic_provider,) if diagnostic_provider else ("openrouter", "go", "zen")
    for provider in diagnostic_keys:
        counts = audit["selection_diagnostics"][provider]
        print(
            f"  {provider} Diagnose: {counts['under_price_limit']} guenstig, "
            f"{counts['direct_aa_identity_match']} AA-IDs exakt/kanonisch gematcht, "
            f"{counts['score_available']} Scores verfuegbar, hoechster Score {_format_intelligence_score(counts['highest_score'])}, "
            f"{counts['selected']} ausgewaehlt"
        )
    aa_source = audit["sources"]["artificial_analysis"]
    aa_text = (
        f"AA {aa_source['row_count']} Modelle / {aa_source['page_count']} Seiten"
        if aa_source.get("row_count") is not None
        else f"AA nicht abgerufen ({aa_source.get('reason') or aa_source.get('status')})"
    )
    print(
        f"Daten: {aa_text}; "
        f"OpenRouter {audit['sources']['openrouter_models']['row_count']} Modelle; "
        f"Proxy {audit['sources']['opencode_proxy']['cached_provider_model_count']} Go-/Zen-Routen"
    )
    snapshot = audit["sources"]["artificial_analysis_snapshot"]
    print(
        f"AA-Snapshot: {snapshot['status']}"
        + (
            f", {snapshot['file_name']}, {snapshot['row_count']} Modelle, {snapshot['age_days']} Tage alt"
            if "row_count" in snapshot and "age_days" in snapshot
            else ""
        )
    )
    if aa_source.get("row_count") is None:
        print("Warnung: AA-Abruf fehlgeschlagen; die Auswahl stuetzt sich auf den Snapshot.")
    elif aa_source.get("snapshot", {}).get("status") == "write_failed":
        print(f"Warnung: Live-Snapshot nicht geschrieben: {aa_source['snapshot']['reason']}")
    for index in INDEX_NAMES:
        population = audit["calibration_populations"].get(index)
        if population:
            print(
                f"  Kalibrierung {index}: {population['source']}, "
                f"{population['model_count']} Modelle ({population['minimum']}..{population['maximum']})"
            )
    if not audit["sources"]["opencode_proxy"].get("live_verified"):
        print("Warnung: lokaler Proxy nicht erreichbar; verwendet wird nur der letzte gespeicherte Katalog.")
    print("OpenRouter-AA-Benchmarktransport: deaktiviert (kein Score-Fallback)")
    free_counts = audit.get("criteria", {}).get("free_variants", {}).get("excluded_counts", {})
    if free_counts:
        print(
            "Free-Tier ausgeschlossen: " + ", ".join(f"{provider} {count}" for provider, count in free_counts.items())
        )
    router_selection = audit.get("criteria", {}).get("router_models", {})
    if router_selection.get("selected"):
        print(
            "Router-Modelle: "
            + ", ".join(router_selection["selected"])
            + " (Einstellungen accountweit, Codex sendet keine plugins[])"
        )
    if args.check:
        for provider in ("openrouter", "go", "zen"):
            top = sorted(
                (
                    item
                    for item in audit["evaluated_candidates"]
                    if item["provider"] == provider and item["score"] is not None
                ),
                key=lambda item: item["score"],
                reverse=True,
            )[:3]
            if top:
                print(
                    f"  {provider} Top verfuegbare Scores: "
                    + "; ".join(f"{item['id']}={_format_intelligence_score(item['score'])}" for item in top)
                )
        if not audit["sources"]["opencode_proxy"].get("live_verified") and not args.allow_cached_proxy:
            print("Abbruch: Live-Pruefung verlangt einen erreichbaren Proxy oder --allow-cached-proxy.")
            return 1
        return 0

    out_dir = args.out_dir.expanduser().resolve()
    if (
        out_dir == codex_dir.resolve()
        and not audit["sources"]["opencode_proxy"].get("live_verified")
        and not args.allow_cached_proxy
    ):
        print("Abbruch: vor globalem Schreiben Proxy starten oder explizit --allow-cached-proxy angeben.")
        return 1
    backups = out_dir / "backups"
    for provider in providers:
        target = args.out.expanduser().resolve() if args.out else out_dir / filenames[provider]
        _write_json(target, catalogs[provider], backups, args.no_backup)
        print(f"geschrieben: {target} ({len(catalogs[provider]['models'])} Modelle)")
    audit["models"] = [entry for entry in audit["models"] if entry["provider"] in providers]
    audit["model_counts"] = {key: len(catalogs[key]["models"]) for key in providers}
    _write_json(out_dir / "provider-catalog-audit.json", audit, backups, args.no_backup)

    if not args.no_verify and out_dir == codex_dir.resolve():
        return _verify_codex_loader()
    if not args.no_verify:
        print("Loader-Verify uebersprungen: Ausgabepfad ist nicht CODEX_HOME.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

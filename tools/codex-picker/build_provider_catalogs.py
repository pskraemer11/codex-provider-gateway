"""Build Codex catalogs from OpenRouter, Artificial Analysis, and OpenCode."""

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
    finite_number,
    qualifies_model,
    score_candidate,
    score_population,
    unique_model_component,
)

# The `/free` endpoint/tier is AA API access metadata, not model token pricing.
AA_URL = "https://artificialanalysis.ai/api/v2/language/models/free"
AA_SNAPSHOT_MAX_AGE_DAYS = 31
OR_MODELS_URL = "https://openrouter.ai/api/v1/models"
OR_BENCHMARKS_URL = "https://openrouter.ai/api/v1/benchmarks"
GO_DOC_URL = "https://opencode.ai/v2/docs/console/go"
ZEN_DOC_URL = "https://opencode.ai/v2/docs/console/models"
PROXY_MODELS_URL = "http://127.0.0.1:8787/v1/models"
TASK_TYPES = {"intelligence": "intelligence_index", "coding": "coding_index", "agentic": "agentic_index"}
USD_PER_MILLION = Decimal("1000000")
SCORE_LIMIT = MIN_CALIBRATED_SCORE
PINNED_FREE_MODELS = {
    "openrouter": frozenset({"cohere/north-mini-code:free", "openrouter/free"}),
    "zen": frozenset({"glm-5.3-flash-free", "deepseek-v4.1-flash-free", "mimo-v2.6-flash-free"}),
}
PINNED_FREE_LABELS = {
    "cohere/north-mini-code:free": "(O.R.) North Mini Code (free)",
    "openrouter/free": "(O.R.) Free Models Router",
    "glm-5.3-flash-free": "Zen · GLM-5.3-Flash Free",
    "deepseek-v4.1-flash-free": "Zen · DeepSeek V4.1 Flash Free",
    "mimo-v2.6-flash-free": "Zen · MiMo V2.6 Flash Free",
}
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


class CatalogError(RuntimeError):
    """A required source did not satisfy its data contract."""


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
            raise CatalogError("Artificial Analysis: Pagination oder data-Liste fehlt.")
        tier = payload.get("tier")
        page_size = pagination.get("page_size")
        total_pages = pagination.get("total_pages")
        response_version = payload.get("intelligence_index_version")
        if tier not in {"free", "pro", "commercial"}:
            raise CatalogError("Artificial Analysis: ungueltige oder fehlende tier-Metadaten.")
        if (
            type(pagination.get("page")) is not int
            or pagination["page"] != page
            or type(page_size) is not int
            or page_size < 1
            or type(total_pages) is not int
            or total_pages < 1
            or not isinstance(pagination.get("has_more"), bool)
        ):
            raise CatalogError("Artificial Analysis: widerspruechliche Seitennummern.")
        if finite_number(response_version) is None:
            raise CatalogError("Artificial Analysis: Intelligence-Index-Version fehlt oder ist ungueltig.")
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
            raise CatalogError("Artificial Analysis: Seitenzahl aenderte sich waehrend des Abrufs.")
        if pagination.get("has_more") is not (page < expected_pages):
            raise CatalogError("Artificial Analysis: has_more stimmt nicht mit total_pages ueberein.")
        for row_number, row in enumerate(page_rows, start=1):
            if (
                not isinstance(row, dict)
                or not isinstance(row.get("id"), str)
                or not isinstance(row.get("slug"), str)
                or not isinstance(row.get("evaluations"), dict)
            ):
                raise CatalogError(
                    f"Artificial Analysis: Modell-schema unvollstaendig auf Seite {page}, Zeile {row_number}."
                )
            if row["id"] in seen_ids:
                raise CatalogError(f"Artificial Analysis: doppelte Modell-id auf Seite {page}, Zeile {row_number}.")
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
    raise CatalogError("Artificial Analysis: Pagination blieb nach erneutem Abruf inkonsistent.")


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
        retrieved = datetime.fromisoformat(str(retrieved_at).replace("Z", "+00:00"))
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


def _usable_calibration_population(values: list[Any]) -> tuple[float, ...] | None:
    population = score_population(values)
    if population is None or not any(population):
        return None
    return population


def calibration_populations(
    aa_rows: list[dict[str, Any]],
    snapshot_rows: list[dict[str, Any]],
    or_metrics: dict[str, dict[str, float]] | None = None,
    eligible_ids: set[str] | None = None,
) -> tuple[dict[str, tuple[float, ...]], dict[str, str]]:
    """Kalibriert ausschließlich den AA-Intelligence-Index.

    Der optionale ``or_metrics``-Parameter bleibt für ältere Aufrufer
    akzeptiert, beeinflusst die Auswahl aber absichtlich nicht. Wenn
    ``eligible_ids`` gesetzt ist, wird die Skala aus den eindeutigen AA-
    Intelligence-Werten der preisbereinigten Kandidaten gebildet.
    """
    del or_metrics
    live_population = _usable_calibration_population([_index_values(row).get("intelligence") for row in aa_rows])
    source = "artificial-analysis-data-api"
    if live_population is None:
        live_population = _usable_calibration_population(
            [_index_values(row).get("intelligence") for row in snapshot_rows]
        )
        source = "artificial-analysis-local-snapshot"
    if live_population is None:
        return {}, {}

    if eligible_ids is None:
        return {"intelligence": live_population}, {"intelligence": source}

    rows = aa_rows if source == "artificial-analysis-data-api" else snapshot_rows
    slugs = [str(row["slug"]) for row in rows if isinstance(row.get("slug"), str)]
    by_slug = {str(row["slug"]): row for row in rows if isinstance(row.get("slug"), str)}
    eligible_values = [
        _index_values(by_slug[match]).get("intelligence")
        for target_id in sorted(eligible_ids)
        if (match := unique_model_component(target_id, slugs)) is not None
    ]
    candidate_population = _usable_calibration_population(eligible_values)
    if candidate_population is not None:
        return {"intelligence": candidate_population}, {"intelligence": source}
    return {}, {}


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


def fetch_proxy_catalog(codex_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    live_hash: str | None = None
    live_ids: set[str] | None = None
    live_error: str | None = None
    try:
        payload, live_hash = _get_json(PROXY_MODELS_URL)
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
        "url": PROXY_MODELS_URL,
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
) -> str | None:
    if qualifies_model(
        input_price,
        score,
        input_price_limit=input_price_limit,
        min_calibrated_score=min_calibrated_score,
    ):
        return "price_and_calibrated_score"
    if identifier in PINNED_FREE_MODELS.get(provider, ()) and input_price == 0:
        return "user_pinned_free_exception"
    return None


def _candidate_sort_key(provider: str, candidate: dict[str, Any]) -> tuple[bool, bool, float, Decimal, str]:
    identifier = str(candidate["id"])
    preferred = identifier == PREFERRED_MODEL_IDS.get(provider)
    score = finite_number(candidate.get("score"))
    return (
        not preferred,
        score is None,
        -(score if score is not None else 0.0),
        Decimal(str(candidate["price"])),
        identifier.casefold(),
    )


def _price_ids(tiers: list[PriceTier], route_ids: list[str]) -> dict[str, str]:
    by_key: dict[str, list[str]] = {}
    for route_id in route_ids:
        by_key.setdefault(_slug_key(route_id), []).append(route_id)
    names = {_display_key(tier.model_name): tier.model_name for tier in tiers}
    result: dict[str, str] = {}
    for _key, display_name in names.items():
        matches = by_key.get(_slug_key(display_name), [])
        if len(matches) == 1:
            result[matches[0]] = display_name
    return result


def _direct_provider_identifier(provider: str, route_id: str) -> str:
    """Keeps direct Go slugs in the Codex provider namespace; Zen uses bare IDs."""
    return f"opencode-go/{route_id}" if provider == "go" else route_id


def _source_metrics(
    target_id: str,
    aa_rows: list[dict[str, Any]],
    snapshot_rows: list[dict[str, Any]],
    or_metrics: dict[str, dict[str, float]],
) -> tuple[dict[str, float], dict[str, float], dict[str, float], str]:
    aa_slugs = [str(row["slug"]) for row in aa_rows if isinstance(row.get("slug"), str)]
    aa_match = unique_model_component(target_id, aa_slugs)
    aa_by_slug = {str(row["slug"]): row for row in aa_rows if isinstance(row.get("slug"), str)}
    primary = _index_values(aa_by_slug[aa_match]) if aa_match else {}
    snapshot_slugs = [str(row["slug"]) for row in snapshot_rows if isinstance(row.get("slug"), str)]
    snapshot_match = unique_model_component(target_id, snapshot_slugs)
    snapshot_by_slug = {str(row["slug"]): row for row in snapshot_rows if isinstance(row.get("slug"), str)}
    snapshot_values = _index_values(snapshot_by_slug[snapshot_match]) if snapshot_match else {}
    if target_id in or_metrics:
        or_match = target_id
    else:
        or_match = unique_model_component(target_id, list(or_metrics))
    fallback = or_metrics.get(or_match, {}) if or_match else {}
    aa_join = "exact slug" if target_id == aa_match else "unique exact model-id component" if aa_match else "unverified"
    or_join = (
        "exact model_permaslug"
        if target_id == or_match
        else "unique exact model-id component"
        if or_match
        else "unverified"
    )
    snapshot_join = (
        "unique exact model-id component"
        if snapshot_match and target_id != snapshot_match
        else "exact slug"
        if snapshot_match
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
        "artificial-analysis-data-api": "Artificial Analysis Data API",
        "artificial-analysis-local-snapshot": "dated Artificial Analysis snapshot",
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
    if source is None and not slug.startswith("openai/"):
        entry["shell_type"] = "default"
    return entry


def _price_label(values: list[Decimal]) -> str:
    low, high = min(values), max(values)
    return f"${low}/M input" if low == high else f"${low}–${high}/M input"


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
) -> dict[str, Any]:
    entry = _clone_model(template, source_model, identifier)
    price_text = _price_label(prices)
    billing_provider = provider.split(":", 1)[-1]
    limit_text = f"; Go-Tarif {plan_fee}" if billing_provider == "go" and plan_fee else ""
    if billing_provider == "go" and limits:
        limit_text += f"; Modell-Kontingent {limits[0]}/Monat"
    if billing_provider == "zen":
        limit_text += "; Pay-as-you-go"
    score_text = f"{score:.2f}/100" if score is not None else "unverified"
    exception_text = " · Free-Ausnahme" if selection_reason == "user_pinned_free_exception" else ""
    entry["display_name"] = f"{label} · {price_text} · Score {score_text}{exception_text}{limit_text}"
    benchmark_source = "artificial-analysis" if score is not None else "unverified"
    entry["description"] = (
        f"{label} — {identifier}; {price_text}{limit_text}; Benchmarkscore {score_text}; "
        f"Auswahlgrund {selection_reason}; "
        f"Basis: {method}; benchmark_source={benchmark_source}; "
        f"transport_source={transport}; price_source={price_source}"
    )
    if provider == "openrouter" and identifier != "openai/gpt-6-luna":
        entry["supported_reasoning_levels"] = DEFAULT_REASONING_LEVELS
        entry["default_reasoning_level"] = "medium"
    return entry


def build_catalog_data(
    *,
    display_overrides: dict[str, str] | None,
    template_path: Path,
    codex_dir: Path,
    aa_snapshot_path: Path | None = None,
    input_price_limit: Decimal = INPUT_PRICE_LIMIT,
    min_calibrated_score: float = MIN_CALIBRATED_SCORE,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    aa_key = os.environ.get("ARTIFICIAL_ANALYSIS_API_KEY")
    if not aa_key:
        raise CatalogError("ARTIFICIAL_ANALYSIS_API_KEY ist nicht gesetzt.")
    aa_rows, aa_source = fetch_aa_models(aa_key)
    aa_snapshot_rows, aa_snapshot_source = fetch_aa_snapshot(aa_snapshot_path or default_aa_snapshot_path())
    or_rows, or_source = fetch_openrouter_models(os.environ.get("OPENROUTER_API_KEY"))
    # OpenRouter benchmark transport is intentionally not part of picker
    # scoring. The picker uses only AA Intelligence, with the dated snapshot
    # as a population fallback when live Intelligence is unusable.
    or_metrics: dict[str, dict[str, float]] = {}
    or_benchmark_source = {
        "status": "disabled",
        "reason": "OpenRouter Coding/Agentic fallback is not used by the picker",
    }
    proxy_entries, proxy_source = fetch_proxy_catalog(codex_dir)

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

    try:
        native_catalog = json.loads(template_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CatalogError(f"Codex-Native-Katalog nicht lesbar: {template_path}") from error
    templates = native_catalog.get("models") if isinstance(native_catalog, dict) else None
    if not isinstance(templates, list) or not templates:
        raise CatalogError("Codex-Native-Katalog enthaelt keine Modelle als Template.")
    template = min(templates, key=lambda model: len(json.dumps(model, ensure_ascii=False)))

    diagnostics = {
        provider: {
            "under_price_limit": 0,
            "direct_aa_identity_match": 0,
            "score_available": 0,
            "selected": 0,
            "user_pinned_free_exceptions": 0,
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

    eligible_ids: set[str] = {
        identifier
        for model in or_rows
        if (identifier := str(model["id"]))
        and (price := _price_per_million(model)) is not None
        and price < input_price_limit
    }
    eligible_ids.update(
        f"opencode-go/{route_id}"
        for route_id in go_ids
        if go_prices.get(route_id) and max(tier.input_price for tier in go_prices[route_id]) < input_price_limit
    )
    eligible_ids.update(
        f"zen/{route_id}"
        for route_id in zen_ids
        if zen_prices.get(route_id) and max(tier.input_price for tier in zen_prices[route_id]) < input_price_limit
    )
    ranges, range_sources = calibration_populations(
        aa_rows, aa_snapshot_rows, eligible_ids=eligible_ids
    )
    if not ranges:
        raise CatalogError("Artificial Analysis: keine verwendbare Intelligence-Index-Population vorhanden.")

    proxy_by_slug = {str(entry["slug"]): entry for entry in proxy_entries if isinstance(entry.get("slug"), str)}
    candidates: list[dict[str, Any]] = []
    for model in or_rows:
        identifier = str(model["id"])
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
        )
        selected = selection_reason is not None
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
        if selection_reason == "user_pinned_free_exception":
            diagnostics["openrouter"]["user_pinned_free_exceptions"] += 1
        label = (
            (display_overrides or {}).get(identifier)
            or PINNED_FREE_LABELS.get(identifier)
            or f"(O.R.) {model.get('name') or identifier}"
        )
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
            )
            if selection_reason == "user_pinned_free_exception" and any(price != 0 for price in prices):
                selection_reason = None
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
            if selection_reason == "user_pinned_free_exception":
                diagnostics[source_provider]["user_pinned_free_exceptions"] += 1
            limits = sorted({tier.monthly_limit for tier in price_rows.get(route_id, []) if tier.monthly_limit})
            model_name = names_by_id.get(route_id, route_id).title()
            label = (
                f"Go · {model_name}"
                if source_provider == "go"
                else PINNED_FREE_LABELS.get(route_id, f"Zen · {model_name}")
            )
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
            "preferred_default_model_if_selected": PREFERRED_MODEL_IDS,
            "explicit_free_exceptions": {
                provider: sorted(model_ids) for provider, model_ids in PINNED_FREE_MODELS.items()
            },
            "free_exception_handling": (
                "Explicit user-pinned routes are included only at verified $0 input price; "
                "missing benchmark scores stay unverified and rank below scored models."
            ),
            "calibration": "AA Intelligence Index as a Min-Max scale over the price-eligible candidate population (minimum=0, maximum=100, clamping outside the observed range); populations with fewer than two values or all-zero values are unusable",
            "score_policy": (
                "Only calibrated AA Intelligence Index is selectable. Use the live AA population; "
                "use the dated AA snapshot only when the live Intelligence population is absent or all zero. "
                "Coding/Agentic composites and OpenRouter benchmark transport are not score fallbacks."
            ),
        },
        "sources": {
            "artificial_analysis": aa_source,
            "artificial_analysis_snapshot": aa_snapshot_source,
            "openrouter_models": or_source,
            "openrouter_benchmarks": or_benchmark_source,
            "opencode_proxy": proxy_source,
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
        help="strikte Obergrenze pro 1 Mio. Input-Token; Modellpreis muss darunter liegen (Standard: 0.25)",
    )
    parser.add_argument(
        "--min-intelligence-score",
        "--min-calibrated-score",
        dest="min_calibrated_score",
        type=_parse_min_calibrated_score,
        default=MIN_CALIBRATED_SCORE,
        metavar="SCORE",
        help="exklusive Mindestschwelle fuer den skalierten AA Intelligence Index, Bereich 0..100 (Standard: 70)",
    )
    parser.add_argument(
        "--aa-snapshot",
        type=Path,
        default=default_aa_snapshot_path(),
        help="lokaler AA-Snapshot als befristeter Fallback fuer fehlende Intelligence-Population",
    )
    parser.add_argument("--out-dir", type=Path, default=codex_dir, help="Zielordner (Standard: CODEX_HOME)")
    parser.add_argument("--out", type=Path, help="Exakter Ausgabepfad, nur fuer einen Provider")
    parser.add_argument("--check", action="store_true", help="Quellen pruefen und Auswahl anzeigen, nichts schreiben")
    parser.add_argument("--no-backup", action="store_true", help="Vorhandene Ausgaben nicht sichern")
    parser.add_argument("--no-verify", action="store_true", help="codex debug models nach dem Schreiben ueberspringen")
    parser.add_argument(
        "--allow-cached-proxy", action="store_true", help="schreibt trotz nicht live verifiziertem Proxy-Katalog"
    )
    args = parser.parse_args()
    if args.out and args.provider == "all":
        parser.error("--out ist nur mit genau einem --provider erlaubt.")

    try:
        catalogs, audit = build_catalog_data(
            display_overrides=display_overrides,
            template_path=codex_dir / ".tmp" / "bundled-catalog.json",
            codex_dir=codex_dir,
            aa_snapshot_path=args.aa_snapshot,
            input_price_limit=args.input_price_limit,
            min_calibrated_score=args.min_calibrated_score,
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
    print("  Ausnahmen: fuenf explizit angeheftete Free-Routen mit verifiziertem $0-Inputpreis")
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
            f"{counts['score_available']} Scores verfuegbar, hoechster Score {counts['highest_score']}, "
            f"{counts['selected']} ausgewaehlt"
        )
    print(
        f"Daten: AA {audit['sources']['artificial_analysis']['row_count']} Modelle / "
        f"{audit['sources']['artificial_analysis']['page_count']} Seiten; "
        f"OpenRouter {audit['sources']['openrouter_models']['row_count']} Modelle; "
        f"Proxy {audit['sources']['opencode_proxy']['cached_provider_model_count']} Go-/Zen-Routen"
    )
    snapshot = audit["sources"]["artificial_analysis_snapshot"]
    print(
        f"AA-Snapshot: {snapshot['status']}"
        + (
            f", {snapshot['row_count']} Modelle, {snapshot['age_days']} Tage alt"
            if "row_count" in snapshot and "age_days" in snapshot
            else ""
        )
    )
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
                    + "; ".join(f"{item['id']}={item['score']:.2f}" for item in top)
                )
        free_exceptions = [
            item for item in audit["models"] if item.get("selection_reason") == "user_pinned_free_exception"
        ]
        if free_exceptions:
            print("  Angeheftete Free-Ausnahmen:")
            for item in free_exceptions:
                print(f"    {item['provider']}: {item['id']} (Benchmark unverified)")
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

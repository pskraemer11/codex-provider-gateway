"""Reine Auswahlregeln fuer den preis- und benchmarkgefilterten Codex-Katalog."""

from __future__ import annotations

import math
import re
from decimal import Decimal, InvalidOperation
from typing import Any

INDEX_NAMES = ("intelligence", "coding", "agentic")
MIN_CALIBRATED_SCORE = 50.0
INPUT_PRICE_LIMIT = Decimal("0.25")


def finite_number(value: Any) -> float | None:
    """Liefert nur endliche Zahlen; fehlende oder fehlerhafte Werte bleiben None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def score_population(values: list[Any]) -> tuple[float, ...] | None:
    usable = [number for value in values if (number := finite_number(value)) is not None]
    if not usable:
        return None
    return tuple(sorted(usable))


def calibrate_score(value: Any, population: tuple[float, ...]) -> float | None:
    """Skaliert einen Index per Min-Max-Kalibrierung auf 0 bis 100."""
    number = finite_number(value)
    if number is None:
        return None
    if not population or any(not math.isfinite(item) for item in population):
        return None
    if len(population) < 2:
        return None
    low, high = population[0], population[-1]
    if high == low:
        return 50.0
    return min(100.0, max(0.0, (number - low) / (high - low) * 100.0))


def score_candidate(
    primary: dict[str, Any],
    fallback: dict[str, Any],
    ranges: dict[str, tuple[float, ...]],
    snapshot: dict[str, Any] | None = None,
) -> tuple[float | None, str]:
    """Bewertet ausschließlich den kalibrierten AA-Intelligence-Index.

    ``primary`` sind direkt von Artificial Analysis geholte Indexwerte.
    ``snapshot`` liefert Intelligence nur dann, wenn die Live-Population dafür
    nicht verwendet werden kann. OpenRouter-Transportwerte und Coding/Agentic-
    Werte sind absichtlich kein Score-Fallback.
    """
    del fallback  # retained in the call contract for audit/backward compatibility
    snapshot = snapshot or {}
    direct_intelligence = finite_number(primary.get("intelligence"))
    snapshot_intelligence = finite_number(snapshot.get("intelligence"))
    raw_intelligence = direct_intelligence if direct_intelligence is not None else snapshot_intelligence
    intelligence_bounds = ranges.get("intelligence")
    intelligence = (
        calibrate_score(raw_intelligence, intelligence_bounds)
        if raw_intelligence is not None and intelligence_bounds is not None
        else None
    )
    if intelligence is not None:
        method = "AA Intelligence Index"
        if direct_intelligence is None:
            method += " (dated AA snapshot fallback)"
        return intelligence, method

    return None, "unverified"


def qualifies_model(
    input_price: Any,
    score: Any,
    *,
    input_price_limit: Decimal = INPUT_PRICE_LIMIT,
    min_calibrated_score: float = MIN_CALIBRATED_SCORE,
) -> bool:
    """Qualify models strictly below the price limit and above the score threshold."""
    score_number = finite_number(score)
    minimum_score = finite_number(min_calibrated_score)
    if score_number is None or minimum_score is None:
        return False
    try:
        price = Decimal(str(input_price))
        price_limit = Decimal(str(input_price_limit))
    except (InvalidOperation, TypeError, ValueError):
        return False
    return price.is_finite() and price_limit.is_finite() and price < price_limit and score_number > minimum_score


def _component_key(identifier: str) -> str:
    """Kanonisiert nur Provider-Praefix und Trenner, nicht Modellversionsziffern."""
    component = identifier.rsplit("/", 1)[-1].casefold().strip()
    return re.sub(r"[._]+", "-", component)


def unique_model_component(target_id: str, source_ids: list[str]) -> str | None:
    """Matcht gleiche Modell-ID-Komponente nur dann, wenn genau ein Treffer existiert.

    Das ist kein Aehnlichkeits- oder Namensmatch: versionsfremde Suffixe bleiben
    verschieden; bei Varianten, die nur durch Punkt/Bindestrich mehrdeutig sind,
    wird absichtlich kein Treffer geliefert.
    """
    key = _component_key(target_id)
    matches = [source_id for source_id in source_ids if _component_key(source_id) == key]
    return matches[0] if len(matches) == 1 else None

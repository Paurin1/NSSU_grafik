"""Typed configuration loaded from YAML (Pydantic validates it)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class _Strict(BaseModel):
    """Base class rejecting unknown keys so that typos in YAML are caught."""

    model_config = ConfigDict(extra="forbid")


class SolverSettings(_Strict):
    time_limit_seconds: int = Field(120, gt=0)
    workers: int = Field(8, gt=0)
    random_seed: int = 1


class ObjectiveWeights(_Strict):
    """Initial weights; they are tunable parameters, not mathematically optimal values."""

    hours_balance: int = Field(10, ge=0)
    shift_count_balance: int = Field(5, ge=0)
    preferences: int = Field(8, ge=0)
    consecutive_5h: int = Field(3, ge=0)
    weekend_balance: int = Field(4, ge=0)
    long_shift_balance: int = Field(0, ge=0)
    short_shift_balance: int = Field(0, ge=0)


class ShiftClasses(_Strict):
    """Maps the generic "long"/"short" notions used by employee limits to shift types."""

    long_shift_type: str = "16"
    short_shift_type: str = "5"


class RestRules(_Strict):
    """Mandatory duty-free calendar days after a shift of the given type."""

    rest_days_after_shift_type: dict[str, int] = {"16": 1}

    @model_validator(mode="after")
    def _non_negative(self) -> RestRules:
        if any(days < 0 for days in self.rest_days_after_shift_type.values()):
            raise ValueError("liczba dni odpoczynku nie może być ujemna")
        return self

    def max_rest_days(self) -> int:
        return max(self.rest_days_after_shift_type.values(), default=0)


class BalancingRules(_Strict):
    """Switches for the balancing criteria."""

    balance_hours: bool = True
    balance_shift_count: bool = True
    balance_long_shifts: bool = True
    balance_short_shifts: bool = False
    use_history: bool = True


class WeekendRules(_Strict):
    """Weekend weighting; holidays are optional and configured explicitly."""

    saturday_weight: int = Field(1, ge=0)
    sunday_weight: int = Field(1, ge=0)
    holiday_weight: int = Field(1, ge=0)
    holidays: list[date] = []


class ConsecutiveShortRules(_Strict):
    """Back-to-back short shifts are allowed but penalised."""

    shift_type: str = "5"


class PreferenceRules(_Strict):
    mismatch_penalty: int = Field(1, ge=0)


class Settings(_Strict):
    year: int = Field(..., ge=1900, le=2200)
    month: int = Field(..., ge=1, le=12)
    csv_delimiter: str = Field(";", min_length=1, max_length=1)
    solver: SolverSettings = SolverSettings()
    weights: ObjectiveWeights = ObjectiveWeights()
    shift_classes: ShiftClasses = ShiftClasses()
    rest: RestRules = RestRules()
    balancing: BalancingRules = BalancingRules()
    weekends: WeekendRules = WeekendRules()
    consecutive_short: ConsecutiveShortRules = ConsecutiveShortRules()
    preferences: PreferenceRules = PreferenceRules()


class ConfigError(Exception):
    """Raised when the configuration file is missing or invalid."""


def load_settings(
    path: Path | str,
    year: int | None = None,
    month: int | None = None,
    time_limit: int | None = None,
) -> Settings:
    """Load YAML settings; explicit arguments override values from the file."""
    config_path = Path(path)
    if not config_path.is_file():
        raise ConfigError(f"Nie znaleziono pliku konfiguracji: {config_path}")
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Niepoprawny YAML w {config_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"Plik {config_path} musi zawierać mapę klucz-wartość.")

    if year is not None:
        raw["year"] = year
    if month is not None:
        raw["month"] = month
    if time_limit is not None:
        raw.setdefault("solver", {})["time_limit_seconds"] = time_limit
    try:
        return Settings(**raw)
    except ValidationError as exc:
        raise ConfigError(f"Niepoprawna konfiguracja: {exc}") from exc

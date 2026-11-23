# NSSU_grafik – Staff Duty Scheduler

Automatyczne układanie miesięcznych grafików dyżurowych (Google OR-Tools CP-SAT, działa lokalnie).

## Status

| Etap | Zakres | Stan |
|------|--------|------|
| 1 | Architektura, modele, CSV, loader, walidacja danych | gotowy |
| 2 | Model bazowy CP-SAT (obsada, kwalifikacje, niedostępność, 1 dyżur/dzień, odpoczynek) | gotowy |
| 3 | Funkcja celu (godziny, liczba dyżurów, preferencje, kolejne 5 h, weekendy, 16 h), limity, FIX/FORBID | gotowy |
| 4 | Historia: odpoczynek na granicy miesięcy, kolejne 5 h, FIX z następnego miesiąca, równoważenie między miesiącami | gotowy |
| 5–6 | Raporty, CLI, walidator grafiku | do zrobienia |

## Instalacja

    python -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    python -m pytest

## Dane wejściowe (`data/`, separator `;`, daty `RRRR-MM-DD`)

`employees.csv`, `shifts.csv`, `qualifications.csv` są wymagane; `availability.csv`,
`fixed_assignments.csv`, `previous_schedule.csv` – opcjonalne (brak dostępności = `NEUTRAL`).
Dane demonstracyjne (56 aktywnych pracowników, 5 pionów 16 h + 4 piony 5 h) generuje
`python tools/generate_sample_data.py`.

Wpisy `FIX` z następnego miesiąca są akceptowane: dyżur długi w ostatnich dniach miesiąca,
po którym wypada wymagany odpoczynek, jest wtedy zabroniony. `FORBID` z następnego miesiąca
jest pomijany z ostrzeżeniem; daty dalsze niż następny miesiąc to błąd.

## Konfiguracja

`config/settings.yaml` – miesiąc, solver, wagi funkcji celu, odpoczynek po dyżurze
(`rest.rest_days_after_shift_type`), klasy dyżurów (długi/krótki), weekendy i święta.
Nieznane klucze są odrzucane.

## Historia i granice miesięcy

`previous_schedule.csv` służy do: (1) odpoczynku po dyżurze 16 h na początku miesiąca,
(2) kary za kolejne dyżury 5 h przez granicę miesięcy, (3) równoważenia obciążenia:
cel godzinowy osoby, która w historii pracowała więcej niż średnia, jest obniżany (suma
korekt = 0), a bilans dyżurów 16 h i weekendów uwzględnia historię. Wyłączenie:
`balancing.use_history: false`. Korekta ma sens, gdy historia obejmuje pełny miesiąc;
krótka historia (np. 3 dni) tylko niewiele przesuwa cele.

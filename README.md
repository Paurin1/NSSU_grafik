# NSSU_grafik – Staff Duty Scheduler

Automatyczne układanie miesięcznych grafików dyżurowych (Google OR-Tools CP-SAT, działa lokalnie).

## Status

| Etap | Zakres | Stan |
|------|--------|------|
| 1 | Architektura, modele, CSV, loader, walidacja danych | gotowy |
| 2 | Model bazowy CP-SAT (obsada, kwalifikacje, niedostępność, 1 dyżur/dzień, odpoczynek) | gotowy |
| 3 | Funkcja celu (godziny, liczba dyżurów, preferencje, kolejne 5 h, weekendy, 16 h), limity, FIX/FORBID | gotowy |
| 4 | Historia: odpoczynek na granicy miesięcy, kolejne 5 h, FIX z następnego miesiąca, równoważenie między miesiącami | gotowy |
| 5 | Walidator grafiku, raporty, eksport CSV/XLSX/TXT, CLI | gotowy |
| 6 | Diagnostyka INFEASIBLE (assumptions), testy końcowe, dokumentacja, demo | gotowy |

## Wymagania

Python 3.11+ (testowane na 3.12). Program działa lokalnie, nie wysyła żadnych danych na zewnątrz.

## Instalacja

    git clone https://github.com/Paurin1/NSSU_grafik.git && cd NSSU_grafik
    python -m venv .venv
    source .venv/bin/activate        # Windows: .venv\Scripts\activate
    pip install -r requirements.txt
    python -m pytest                 # opcjonalnie: ok. 20 s, wszystkie testy powinny przejść

## Szybki start (dane demo)

    python tools/generate_sample_data.py
    python main.py --year 2026 --month 12 --time-limit 60 --overwrite

Wyniki trafią do `output/`. Dane demo: 56 aktywnych pracowników, 5 pionów 16 h i 4 piony 5 h.

## Instrukcja krok po kroku

1. **Przygotuj dane** w katalogu `data/` (opis plików poniżej).
2. **Ustaw konfigurację** w `config/settings.yaml` (rok, miesiąc, wagi, odpoczynek, święta).
3. **Uruchom** `python main.py --year RRRR --month M` (argumenty nadpisują wartości z YAML).
4. **Przeczytaj komunikaty**: program waliduje dane (błędy po polsku z numerem wiersza),
   uruchamia solver, waliduje wynik i zapisuje raporty.
5. **Sprawdź wyniki** w `output/`: `schedule.csv`, `schedule.xlsx`, `optimization_report.txt`.
6. Jeśli grafik jest zły lub niepełny – popraw dane/blokady, zwiększ `--time-limit` i uruchom ponownie.

## Argumenty wiersza poleceń

| Argument | Znaczenie | Domyślnie |
|----------|-----------|-----------|
| `--year`, `--month` | rok i miesiąc grafiku | z `settings.yaml` |
| `--config` | plik konfiguracji | `config/settings.yaml` |
| `--data-dir` | katalog z CSV | `data` |
| `--output-dir` | katalog wyników | `output` |
| `--time-limit` | limit czasu solvera w sekundach | `solver.time_limit_seconds` |
| `--overwrite` | zezwól na nadpisanie istniejących wyników | wyłączone |
| `--verbose` | szczegółowe logi | wyłączone |

Kody wyjścia: `0` OK, `2` błędne dane wejściowe, `3` brak rozwiązania, `4` błędy w grafiku
(niezatwierdzalny), `5` pliki wynikowe już istnieją (użyj `--overwrite`).

## Pliki wejściowe (`data/`)

Format: CSV, separator `;`, kodowanie UTF-8, daty `RRRR-MM-DD`. Wymagane: `employees.csv`,
`shifts.csv`, `qualifications.csv`. Opcjonalne: `availability.csv`, `fixed_assignments.csv`,
`previous_schedule.csv`. Kluczami są identyfikatory (`employee_id`, `post_id`), nie nazwiska.

**employees.csv** – `employee_id;name;active;target_hours;min_shifts;max_shifts;min_long_shifts;max_long_shifts;min_short_shifts;max_short_shifts`
- `active`: 1/0. `target_hours`: cel godzin (kryterium optymalizacji, nie ograniczenie);
  puste = równy udział.
- Limity `min_*`/`max_*` są ograniczeniami twardymi tylko, gdy je wypełnisz; puste = brak limitu.

        E001;Jan Kowalski;1;60;;;;;;
        E002;Anna Nowak;1;48;;12;2;;;

**shifts.csv** – `post_id;post_name;shift_type;duration_hours;active`. Każdy aktywny pion jest
obsadzany codziennie dokładnie jedną osobą. Nowe rodzaje dyżurów (np. 8, 12) dodajesz
wpisami tutaj (w razie potrzeby także w `rest` w YAML).

        P1;Pion 1;16;16;1
        P6;Pion 6;5;5;1

**qualifications.csv** – `employee_id;post_id;shift_type;qualified` (1/0). Brak wpisu =
brak kwalifikacji, czyli pracownik nie może być przydzielony do tego pionu.

        E001;P1;16;1

**availability.csv** – `employee_id;date;availability`; wartości: `UNAVAILABLE`, `PREFER_16`,
`PREFER_5`, `NEUTRAL`. Brak wpisu = `NEUTRAL` (nie `UNAVAILABLE`). Duplikat pracownik+dzień to błąd.

**fixed_assignments.csv** – `employee_id;date;post_id;action`; `FIX` = obowiązkowy przydział,
`FORBID` = zakaz. Blokady są twarde; sprzeczne blokady kończą się czytelnym błędem i nigdy
nie są po cichu ignorowane. `FIX` z następnego miesiąca jest akceptowany i blokuje dyżur 16 h
w ostatnim dniu bieżącego; `FORBID` z następnego miesiąca jest pomijany z ostrzeżeniem;
daty dalsze niż następny miesiąc to błąd.

**previous_schedule.csv** – `employee_id;date;post_id;shift_type` – dyżury z poprzednich
miesięcy. Służy do odpoczynku na granicy miesięcy, kary za kolejne 5 h i równoważenia
obciążenia. Jeśli brakuje historii potrzebnej do oceny odpoczynku, program ostrzega.

## Konfiguracja (`config/settings.yaml`)

| Sekcja | Znaczenie |
|--------|-----------|
| `year`, `month` | okres grafiku |
| `solver` | `time_limit_seconds`, `workers`, `random_seed` (determinizm ograniczony przy wielu wątkach) |
| `weights` | wagi kar: `hours_balance`, `shift_count_balance`, `preferences`, `consecutive_5h`, `weekend_balance`, `long_shift_balance`, `short_shift_balance` (0 = kryterium wyłączone) |
| `shift_classes` | które `shift_type` to dyżur „długi” i „krótki” (dla limitów `*_long_*`/`*_short_*`) |
| `rest.rest_days_after_shift_type` | liczba dni wolnych po dyżurze danego rodzaju (domyślnie `"16": 1`) |
| `balancing` | włączanie równoważenia godzin / liczby dyżurów / 16 h / 5 h oraz `use_history` |
| `weekends` | wagi sobót, niedziel i świąt oraz lista `holidays` |
| `consecutive_short.shift_type` | rodzaj dyżuru, którego dyżury dzień po dniu są karane |
| `preferences.mismatch_penalty` | kara za przydział niezgodny z preferencją |

Wagi są wartościami początkowymi, nie optymalnymi – dostrajaj je do swoich priorytetów.
Nieznane klucze w YAML są odrzucane z błędem.

## Historia i granice miesięcy

`previous_schedule.csv` służy do: (1) odpoczynku po dyżurze 16 h na początku miesiąca,
(2) kary za kolejne dyżury 5 h przez granicę miesięcy, (3) równoważenia obciążenia:
cel godzinowy osoby, która w historii pracowała więcej niż średnia, jest obniżany (suma
korekt = 0). Wyłączenie: `balancing.use_history: false`. Korekta ma sens, gdy historia
obejmuje pełny miesiąc.

## Wyniki

- **schedule.csv** – `date, weekday, post_id, post_name, shift_type, duration_hours, employee_id, employee_name`.
- **schedule.xlsx** – arkusze: Schedule (kalendarz), Employees (dyżury 16 h/5 h, godziny,
  odchylenie od celu, weekendy, preferencje), Statistics, Validation, Preferences.
- **optimization_report.txt** – status solvera, czas, wartość funkcji celu, rozkłady godzin,
  dyżurów i weekendów, preferencje, kolejne 5 h, ostrzeżenia i błędy.

Przed zapisem grafik przechodzi niezależny walidator (`src/schedule_validator.py`); błędy
twarde uniemożliwiają oznaczenie grafiku jako zatwierdzonego.

## Jak czytać status solvera

- **OPTIMAL** – rozwiązanie optymalne względem funkcji celu.
- **FEASIBLE** – grafik jest poprawny (przeszedł walidator), ale optymalność nie jest
  gwarantowana; zwiększ `--time-limit` lub `solver.workers`, aby poprawić wynik.
- **INFEASIBLE** – brak poprawnego grafiku; program wypisuje diagnostykę (niżej).

Jeśli suma `target_hours` znacznie odbiega od liczby godzin wymaganych do obsady wszystkich
pionów (liczba dni × suma godzin pionów), kara godzinowa będzie wysoka nawet dla najlepszego
grafiku. Dopasuj cele lub zostaw je puste.

## Diagnostyka braku rozwiązania

Przy INFEASIBLE `src/diagnostics.py` buduje model z literałami-asumpcjami (obsada dnia,
odpoczynek i limity pracownika) i wypisuje rdzeń sprzeczności z solvera. Rdzeń jest
wystarczający, ale niekoniecznie minimalny; sprzeczności wynikające tylko z kwalifikacji
lub blokad wychwytuje wcześniej walidacja danych.

## Rozwiązywanie problemów

| Objaw | Co zrobić |
|-------|-----------|
| Kod 2 i komunikat z numerem wiersza | popraw wskazany CSV/YAML |
| Ostrzeżenie o niewystarczającej liczbie kwalifikowanych/dostępnych osób | dodaj kwalifikacje lub zmniejsz niedostępności w danym dniu |
| Kod 3 (INFEASIBLE) | przeczytaj listę konfliktów; poluzuj blokady lub limity |
| Kod 4 | zobacz sekcję Validation – wskazuje naruszone reguły |
| Kod 5 | dodaj `--overwrite` lub zmień `--output-dir` |
| Słaby wynik (FEASIBLE) | wydłuż `--time-limit`, zwiększ `solver.workers` |

## Struktura projektu

    main.py              CLI
    config/settings.yaml konfiguracja
    data/                dane wejściowe CSV
    src/                 config, models, loader, validation, preprocessing, constraints,
                         objective, optimizer, diagnostics, schedule_validator, reports, exporter
    tests/               testy pytest
    tools/               generator danych demo
    output/              wyniki

## Ograniczenia

Funkcja celu to konfigurowalna suma ważona; optymalizacja leksykograficzna jest przygotowana
(`PRIORITY_ORDER` w `objective.py`), ale jeszcze nie zaimplementowana.

## Licencja

MIT.

# Portfolio Performance → Home Assistant (CSV / XML / .portfolio) — v0.3.3

Stellt Portfolio-Kennzahlen als **Sensoren** in Home Assistant bereit.

## Features
- **CSV**
  - *Bestands-CSV*: Auto-Delimiter (`,`, `;`, `\t`), DE/EN-Header, Dezimal-Komma/-Punkt
  - *Depotumsätze-CSV*: Aggregiert **Käufe/Verkäufe/Ein-/Auslieferungen** zu Beständen
- **XML** (PP → *Datei → Speichern unter…* → **XML**): Bestände aus `portfolio-transaction`, Kurs aus `<prices>`
- **.portfolio**: enthält `data.xml` → OK; enthält `data.portfolio` (PPPBV*) → Hinweis (binary, nicht parsebar)
- **Optional Live-Preise (Yahoo)**: füllt fehlende Kurse/Werte (Ticker erforderlich)

## Installation
1. Dateien nach `/config/custom_components/pp_portfolio/` kopieren **oder** via HACS (Custom Repository) installieren
2. Home Assistant **neu starten**
3. Integration hinzufügen und Pfad setzen, z. B.
   - XML: `/config/pp/Depot-Ing-Diba.xml`
   - CSV (Depotumsätze oder Bestand): `/config/pp/Ing-Diba.csv`
4. (Optional) **„Live-Preise aktivieren“** in den Optionen setzen

## Sensoren
- `sensor.pp_portfolio_total_value`, `total_cost`, `total_gain`, `total_gain_pct`
- pro Position: `<Name> Value`, `<Name> Gain %` (mit Attributen: Stück, Kurs, Einstand, Gewinn, Währung)
- `sensor.pp_portfolio_status` mit Quelle (`csv/xml/portfolio/tx_csv`) und Diagnose (Delimiter, Header, Hinweis)

## Hinweise zu Live-Preisen
- erfordern **Ticker-Symbole** wie bei Yahoo (`NVDA`, `AAPL`, `SAP.DE` …)
- Währungen können je Holding variieren; Gesamtwerte sind ohne FX-Konvertierung „best effort“

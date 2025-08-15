
# Portfolio Performance → Home Assistant (CSV / XML / .portfolio)

**Version 0.1.8** — README liegt im Komponentenordner.

- **CSV** (Berichte → Bestände → Exportieren): Auto-Detect `, ; \t`, DE/EN-Header, Dezimal-Komma/-Punkt.
- **XML** (Datei → *Speichern unter…* → **XML**): Aggregation aus `portfolio-transaction` (BUY/SELL/Delivery), Preis aus `<prices>`.
- **.portfolio**: Erkennt Container. Enthält `data.xml` → OK; enthält `data.portfolio` (PPPBV*) → Hinweis (binary, nicht parsebar).

**Sensoren**
- `sensor.pp_portfolio_total_value`, `total_cost`, `total_gain`, `total_gain_pct`
- je Position: `<Name> Value`, `<Name> Gain %` mit Attributen (Stückzahl, Kurs, Einstand, …)

**Installation**
1. Ordner `custom_components/pp_portfolio` nach `/config/custom_components/` kopieren.
2. Home Assistant neu starten.
3. Integration hinzufügen und Pfad zur CSV/XML/.portfolio angeben.

**Debug**
```yaml
logger:
  default: warning
  logs:
    custom_components.pp_portfolio: debug
```
Logs zeigen Quelle (csv/xml/portfolio), Delimiter und Anzahl Positionen.

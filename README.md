# Portfolio Performance → Home Assistant

**HACS-ready** custom integration for reading **Portfolio Performance** data (CSV / XML / .portfolio).

- CSV (Bestände-Export): auto delimiter detection (`,`, `;`, `\t`), DE/EN headers, decimal comma/point.
- XML (File → Save as… → XML): builds holdings from `portfolio-transaction` (BUY/SELL/Delivery), uses latest `<prices>` for quotes.
- .portfolio: detects container; parses if it contains `data.xml`. If binary (`data.portfolio` with `PPPBV*`), shows a status hint.

## Installation (via HACS custom repo)
1. In HACS: **Integrations → Custom repositories → Add**  
   - **Repository**: *your GitHub repo URL (this project)*  
   - **Category**: *Integration*
2. Install “**Portfolio Performance (CSV/XML/.portfolio)**”.
3. Restart Home Assistant.
4. Add the integration and set the path to your file (e.g. `/config/pp/Depot-Ing-Diba.xml` or `/config/pp/holdings.csv`).

## Development
- Bump the version in `custom_components/pp_portfolio/manifest.json` for each release.
- Tag releases with `vX.Y.Z` so HACS can pick them up.

MIT © 2025

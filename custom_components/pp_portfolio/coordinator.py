
from __future__ import annotations
import csv
import logging
import os, zipfile, io, re
from datetime import timedelta
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.core import HomeAssistant
from .const import DEFAULT_SCAN_INTERVAL

import xml.etree.ElementTree as ET

_LOGGER = logging.getLogger(__name__)

HEADER_ALIASES = {
    "name": ["name", "wertpapier", "wertpapiername", "security", "instrument"],
    "ticker": ["ticker", "ticker-symbol", "symbol", "isin"],
    "quantity": ["bestand", "stück", "menge", "anzahl", "quantity", "shares"],
    "price": ["kurs", "preis", "price"],
    "cost": ["einstandspreis", "einstand", "investiert", "kaufwert", "einstandswert", "cost", "cost basis", "purchase value"],
    "value": ["marktwert", "wert", "aktueller wert", "positionswert", "market value", "value"],
    "gain_abs": ["gewinn/verlust", "gewinn", "verlust", "p&l", "gain", "profit"],
    "gain_pct": ["gewinn/verlust %", "gewinn %", "verlust %", "p&l %", "gain %", "performance %"],
    "currency": ["währung", "currency"]
}

def _norm(s: str) -> str:
    return (s or "").strip().lower()

def _parse_num(s: str) -> float:
    if s is None:
        return 0.0
    s = s.strip()
    if s == "" or s == "-":
        return 0.0
    s = s.replace("€","").replace("%","").replace("\u00a0"," ").strip()
    if "," in s and "." in s:
        if s.rfind(",") < s.rfind("."):
            s = s.replace(",", "")
        else:
            s = s.replace(".", "").replace(",", ".")
    elif "," in s and "." not in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        _LOGGER.debug("Could not parse number: %s", s)
        return 0.0

def _header_map(headers):
    hdr_map = {}
    lower = [_norm(h) for h in headers]
    for key, aliases in HEADER_ALIASES.items():
        for i, h in enumerate(lower):
            if h in aliases:
                hdr_map[key] = i
                break
    return hdr_map

def _detect_delimiter(sample: str) -> str:
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
        return dialect.delimiter
    except Exception:
        pass
    if sample.count(";") >= sample.count(",") and sample.count(";") > 0:
        return ";"
    if sample.count(",") > 0:
        return ","
    if "\t" in sample:
        return "\t"
    return ";"

class PPDataCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, path: str):
        super().__init__(
            hass,
            logger=_LOGGER,
            name="PP Portfolio",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self._path = path
        self._status = {"ok": True, "message": "", "headers": [], "delimiter": "", "source": ""}

    @property
    def status(self):
        return self._status

    async def _async_update_data(self):
        try:
            if not os.path.exists(self._path):
                self._status.update(ok=False, message=f"Datei nicht gefunden: {self._path}")
                return {"holdings": [], "totals": {"value":0.0,"cost":0.0,"gain_abs":0.0,"gain_pct":0.0}}
            if self._path.endswith(".csv"):
                data = await self.hass.async_add_executor_job(self._read_csv, self._path)
                self._status["source"] = "csv"
            elif self._path.endswith(".portfolio"):
                data = await self.hass.async_add_executor_job(self._read_portfolio_container, self._path)
                self._status["source"] = "portfolio"
            elif self._path.endswith(".xml"):
                data = await self.hass.async_add_executor_job(self._read_pp_xml, self._path)
                self._status["source"] = "xml"
            else:
                data = await self.hass.async_add_executor_job(self._read_csv, self._path)
                self._status["source"] = "auto"
            _LOGGER.debug("Loaded %d holdings. Totals: value=%.2f cost=%.2f gain=%.2f pct=%.2f (source=%s)",
                          len(data.get("holdings", [])),
                          data.get("totals", {}).get("value", 0.0),
                          data.get("totals", {}).get("cost", 0.0),
                          data.get("totals", {}).get("gain_abs", 0.0),
                          data.get("totals", {}).get("gain_pct", 0.0),
                          self._status.get("source"))
            return data
        except Exception as e:
            raise UpdateFailed(str(e)) from e

    def _read_portfolio_container(self, path: str):
        with zipfile.ZipFile(path, "r") as z:
            names = z.namelist()
            xml_names = [n for n in names if n.lower().endswith(".xml")]
            if xml_names:
                xml_data = z.read(xml_names[0]).decode("utf-8", errors="ignore")
                f = io.StringIO(xml_data)
                return self._read_pp_xml(f)
            if "data.portfolio" in names:
                blob = z.read("data.portfolio")
                if blob[:5] == b"PPPBV":
                    self._status.update(ok=False, message="Binary .portfolio erkannt (PPPBV*). Bitte in PP: Datei → Speichern unter… → **XML** oder Berichte → Bestände → CSV exportieren.")
                    return {"holdings": [], "totals": {"value":0.0,"cost":0.0,"gain_abs":0.0,"gain_pct":0.0}}
                self._status.update(ok=False, message="Unbekanntes .portfolio-Innenformat.")
                return {"holdings": [], "totals": {"value":0.0,"cost":0.0,"gain_abs":0.0,"gain_pct":0.0}}
            self._status.update(ok=False, message="Leeres oder unbekanntes .portfolio-Archiv.")
            return {"holdings": [], "totals": {"value":0.0,"cost":0.0,"gain_abs":0.0,"gain_pct":0.0}}

    def _read_pp_xml(self, file_or_path):
        tree = ET.parse(file_or_path) if isinstance(file_or_path, str) else ET.parse(file_or_path)
        root = tree.getroot()

        securities = root.findall(".//securities/security")
        import re as _re
        def resolve_security_from_ref(ref: str):
            m = _re.search(r"securities/security\[(\d+)\]", ref or "")
            if not m:
                return None
            idx = int(m.group(1)) - 1
            return securities[idx] if 0 <= idx < len(securities) else None

        def parse_amount_cents(txt: str) -> float:
            try:
                return float(txt) / 100.0
            except Exception:
                return 0.0

        def parse_shares_scaled(txt: str) -> float:
            try:
                return float(txt) / 1_000_000_000.0
            except Exception:
                return 0.0

        def latest_price(secnode) -> float | None:
            prices = secnode.findall(".//prices/price")
            if not prices:
                return None
            try:
                iv = int(prices[-1].attrib.get("v", "0"))
            except Exception:
                return None
            for scale in (100_000_000, 10_000_000, 1_000_000, 100_000, 10_000, 1_000, 100, 10, 1):
                p = iv / scale
                if 0.01 <= p <= 1_000_000:
                    return p
            return iv

        signs = {"BUY": 1, "DELIVERY_INBOUND": 1, "SELL": -1, "DELIVERY_OUTBOUND": -1}
        tmp = {}
        for tx in root.findall(".//portfolio-transaction"):
            typ = (tx.findtext("./type") or "").strip().upper()
            if typ not in signs:
                continue
            sec_ref_el = tx.find("./security")
            if sec_ref_el is None or "reference" not in sec_ref_el.attrib:
                continue
            secnode = resolve_security_from_ref(sec_ref_el.attrib["reference"])
            if secnode is None:
                continue
            key = secnode.findtext("./uuid") or secnode.findtext("./name") or "unknown"
            name = secnode.findtext("./name") or "Unbekannt"
            ticker = secnode.findtext("./tickerSymbol") or secnode.findtext("./isin") or name
            currency = secnode.findtext("./currencyCode") or "EUR"
            shares = parse_shares_scaled(tx.findtext("./shares") or "0")
            amount = parse_amount_cents(tx.findtext("./amount") or "0")
            sign = signs[typ]

            entry = tmp.setdefault(key, {"name": name, "ticker": ticker, "currency": currency, "shares": 0.0, "cost": 0.0})
            entry["shares"] += sign * shares
            entry["cost"] += sign * amount

        holdings = []
        totals = {"value": 0.0, "cost": 0.0, "gain_abs": 0.0}

        for key, h in tmp.items():
            if h["shares"] <= 0.0:
                continue
            secnode = next((s for s in securities if (s.findtext("./uuid") or "") == key), None)
            price = latest_price(secnode) if secnode is not None else 0.0
            value = h["shares"] * price
            cost = h["cost"]
            gain = value - cost
            holdings.append({
                "name": h["name"],
                "ticker": h["ticker"],
                "quantity": h["shares"],
                "price": price,
                "value": value,
                "cost": cost,
                "gain_abs": gain,
                "gain_pct": (gain / cost * 100.0) if cost else 0.0,
                "currency": h["currency"],
            })
            totals["value"] += value
            totals["cost"] += cost
            totals["gain_abs"] += gain

        totals["gain_pct"] = (totals["gain_abs"] / totals["cost"] * 100.0) if totals["cost"] else 0.0
        if not holdings:
            self._status.update(ok=False, message="PP-XML erkannt, aber keine Bestands-Transaktionen gefunden.")
        else:
            self._status.update(ok=True, message=f"XML ok: {len(holdings)} Positionen.")

        return {"holdings": holdings, "totals": totals}

    def _read_csv(self, path: str):
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
        sample = "\n".join(raw.splitlines()[:5])
        delim = _detect_delimiter(sample)
        self._status["delimiter"] = delim

        holdings = []
        totals = {"value": 0.0, "cost": 0.0, "gain_abs": 0.0}

        f = io.StringIO(raw)
        reader = csv.reader(f, delimiter=delim)
        rows = list(reader)
        if not rows:
            self._status.update(ok=False, message="CSV leer", headers=[])
            return {"holdings": holdings, "totals": {**totals, "gain_pct": 0.0}}

        hdr = rows[0]
        self._status["headers"] = hdr
        mapping = _header_map(hdr)

        required_any = any(k in mapping for k in ("value","quantity","price","cost","gain_abs","gain_pct"))
        if not required_any:
            self._status.update(ok=False, message="CSV scheint eine Wertpapierliste zu sein. Bitte in PP 'Berichte → Bestände → Exportieren (CSV)' verwenden.")

        for r in rows[1:]:
            if not any(r):
                continue
            def get(key):
                idx = mapping.get(key)
                return r[idx] if idx is not None and idx < len(r) else ""
            name = get("name") or "Unbekannt"
            ticker = get("ticker") or ""
            qty = _parse_num(get("quantity"))
            price = _parse_num(get("price"))
            value = _parse_num(get("value"))
            cost = _parse_num(get("cost"))
            gain_abs = _parse_num(get("gain_abs"))
            gain_pct = _parse_num(get("gain_pct"))
            currency = (get("currency") or "").strip()

            if value == 0.0 and qty * price > 0:
                value = qty * price
            if gain_abs == 0.0 and value and cost:
                gain_abs = value - cost
            if cost == 0.0 and value and gain_abs:
                cost = value - gain_abs
            holding = {
                "name": name,
                "ticker": ticker or name,
                "quantity": qty,
                "price": price,
                "value": value,
                "cost": cost,
                "gain_abs": gain_abs,
                "gain_pct": gain_pct,
                "currency": currency or "EUR",
            }
            holdings.append(holding)
            totals["value"] += value
            totals["cost"] += cost
            totals["gain_abs"] += gain_abs
        totals["gain_pct"] = (totals["gain_abs"] / totals["cost"] * 100.0) if totals["cost"] else 0.0
        return {"holdings": holdings, "totals": totals}

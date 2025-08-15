from __future__ import annotations
import csv
import logging
import os, zipfile, io, re, json as _json
from datetime import timedelta
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from .const import DEFAULT_SCAN_INTERVAL

import xml.etree.ElementTree as ET

_LOGGER = logging.getLogger(__name__)

HEADER_ALIASES = {
    "name": ["name", "wertpapier", "wertpapiername", "security", "instrument"],
    "ticker": ["ticker", "ticker-symbol", "symbol", "isin"],
    "quantity": ["bestand", "stück", "stueck", "menge", "anzahl", "quantity", "shares"],
    "price": ["kurs", "preis", "price"],
    "cost": ["einstandspreis", "einstand", "investiert", "kaufwert", "einstandswert", "cost", "cost basis", "purchase value"],
    "value": ["marktwert", "wert", "aktueller wert", "positionswert", "market value", "value", "bewertung"],
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
    def __init__(self, hass: HomeAssistant, path: str, enable_live_prices: bool=False):
        super().__init__(
            hass,
            logger=_LOGGER,
            name="PP Portfolio",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self._path = path
        self._enable_live = enable_live_prices
        self._status = {"ok": True, "message": "", "headers": [], "delimiter": "", "source": ""}

    @property
    def status(self):
        return self._status

    async def _async_enrich_prices(self, holdings: list[dict], *, ticker_key="ticker") -> None:
        """Fill missing price/value via Yahoo Finance for items with a ticker symbol."""
        symbols = []
        index = {}
        for i, h in enumerate(holdings):
            t = (h.get(ticker_key) or "").strip()
            if not t:
                continue
            if not h.get("price"):
                sym = t.upper()
                symbols.append(sym)
                index.setdefault(sym, []).append(i)
        if not symbols:
            return
        # de-dup
        uniq = []
        for s in symbols:
            if s not in uniq:
                uniq.append(s)
        symbols = uniq
        session = async_get_clientsession(self.hass)
        base = "https://query1.finance.yahoo.com/v7/finance/quote?symbols="
        # chunks of 40
        for k in range(0, len(symbols), 40):
            chunk = symbols[k:k+40]
            url = base + ",".join(chunk)
            try:
                async with session.get(url, timeout=15) as resp:
                    if resp.status != 200:
                        _LOGGER.debug("Yahoo response %s for %s", resp.status, chunk)
                        continue
                    data = await resp.json()
            except Exception as e:
                _LOGGER.debug("Yahoo request failed: %s", e)
                continue
            results = (data or {}).get("quoteResponse", {}).get("result", [])
            for q in results:
                sym = str(q.get("symbol","")).upper()
                price = q.get("regularMarketPrice") or q.get("postMarketPrice") or q.get("preMarketPrice")
                curr = q.get("currency") or "EUR"
                if not sym or price is None:
                    continue
                for idx in index.get(sym, []):
                    h = holdings[idx]
                    h["price"] = float(price)
                    if not h.get("currency"):
                        h["currency"] = curr
                    qty = h.get("quantity") or h.get("shares") or 0.0
                    if qty and not h.get("value"):
                        h["value"] = float(price) * float(qty)

    async def _async_update_data(self):
        try:
            if not os.path.exists(self._path):
                self._status.update(ok=False, message=f"Datei nicht gefunden: {self._path}")
                return {"holdings": [], "totals": {"value":0.0,"cost":0.0,"gain_abs":0.0,"gain_pct":0.0}}
            if self._path.endswith(".csv"):
                with open(self._path, 'r', encoding='utf-8') as f:
                    first = f.readline()
                low = (first or '').lower()
                if 'typ' in low and ('stück' in low or 'stueck' in low):
                    data = await self.hass.async_add_executor_job(self._read_tx_csv, self._path)
                    self._status["source"] = "tx_csv"
                else:
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

            # Enrich prices if enabled
            if self._enable_live and data.get('holdings'):
                await self._async_enrich_prices(data['holdings'])
                totals = {"value":0.0,"cost":0.0,"gain_abs":0.0}
                for h in data['holdings']:
                    totals['value'] += float(h.get('value') or 0.0)
                    totals['cost'] += float(h.get('cost') or 0.0)
                totals["gain_abs"] = totals["value"] - totals["cost"]
                totals["gain_pct"] = (totals["gain_abs"]/totals["cost"]*100.0) if totals["cost"] else 0.0
                data["totals"] = totals

            _LOGGER.debug(
                "Loaded %d holdings. Totals: value=%.2f cost=%.2f gain=%.2f pct=%.2f (source=%s)",
                len(data.get("holdings", [])),
                data.get("totals", {}).get("value", 0.0),
                data.get("totals", {}).get("cost", 0.0),
                data.get("totals", {}).get("gain_abs", 0.0),
                data.get("totals", {}).get("gain_pct", 0.0),
                self._status.get("source"),
            )
            return data
        except Exception as e:
            raise UpdateFailed(str(e)) from e

    # ---------- Depotumsätze-CSV ----------
    def _read_tx_csv(self, path: str):
        import csv, io
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
        sample = "\n".join(raw.splitlines()[:5])
        delim = _detect_delimiter(sample)
        self._status["delimiter"] = delim
        reader = csv.reader(io.StringIO(raw), delimiter=delim)
        rows = list(reader)
        if not rows:
            self._status.update(ok=False, message="Depotumsätze-CSV leer", headers=[])
            return {"holdings": [], "totals": {"value":0.0,"cost":0.0,"gain_abs":0.0,"gain_pct":0.0}}

        hdr = rows[0]
        self._status["headers"] = hdr
        lower = [(_norm(h) if isinstance(h,str) else "") for h in hdr]
        def col(*aliases):
            for a in aliases:
                if a in lower:
                    return lower.index(a)
            return -1

        idx_typ = col("typ", "type")
        idx_stueck = col("stück", "stueck", "shares", "menge", "anzahl")
        idx_wert = col("wert", "amount", "betrag", "bruttobetrag")
        idx_ticker = col("ticker-symbol", "ticker", "symbol")
        idx_isin = col("isin")
        idx_name = col("wertpapiername", "wertpapier", "name")

        if idx_typ < 0 or idx_stueck < 0 or (idx_ticker < 0 and idx_isin < 0 and idx_name < 0):
            self._status.update(ok=False, message="Depotumsätze-CSV: benötigte Spalten nicht gefunden (Typ/Stück/Ticker/ISIN/Name).")
            return {"holdings": [], "totals": {"value":0.0,"cost":0.0,"gain_abs":0.0,"gain_pct":0.0}}

        holdings_map = {}
        for r in rows[1:]:
            if not any(r):
                continue
            typ = (r[idx_typ] if idx_typ>=0 and idx_typ < len(r) else "").strip().lower()
            stxt = r[idx_stueck] if idx_stueck>=0 and idx_stueck < len(r) else "0"
            wtxt = r[idx_wert] if idx_wert>=0 and idx_wert < len(r) else "0"
            qty = _parse_num(stxt)
            amt = _parse_num(wtxt)
            if typ in ("kauf","buy","einlieferung","delivery_inbound"):
                sign = 1
            elif typ in ("verkauf","sell","auslieferung","delivery_outbound"):
                sign = -1
            else:
                # ignore non-position transactions for quantity (dividends, fees, taxes, etc.)
                continue
            key = (r[idx_ticker] if idx_ticker>=0 and idx_ticker < len(r) and r[idx_ticker] else "") \
                  or (r[idx_isin] if idx_isin>=0 and idx_isin < len(r) and r[idx_isin] else "") \
                  or (r[idx_name] if idx_name>=0 and idx_name < len(r) else "Unbekannt")
            name = (r[idx_name] if idx_name>=0 and idx_name < len(r) and r[idx_name] else key) or "Unbekannt"
            ticker = (r[idx_ticker] if idx_ticker>=0 and idx_ticker < len(r) else "") or key

            h = holdings_map.setdefault(key, {"name": name, "ticker": ticker, "currency": "EUR", "shares": 0.0, "cost": 0.0})
            h["shares"] += sign * qty
            h["cost"] += sign * amt

        holdings = []
        totals = {"value": 0.0, "cost": 0.0, "gain_abs": 0.0}
        for key, h in holdings_map.items():
            if h["shares"] <= 0.0:
                continue
            price = 0.0
            value = 0.0
            cost = h["cost"]
            holdings.append({
                "name": h["name"],
                "ticker": h["ticker"] or h["name"],
                "quantity": h["shares"],
                "price": price,
                "value": value,
                "cost": cost,
                "gain_abs": 0.0,
                "gain_pct": 0.0,
                "currency": h["currency"],
            })
            totals["cost"] += cost

        totals["gain_pct"] = 0.0
        self._status.update(ok=True, message=f"Depotumsätze-CSV erkannt ({len(holdings)} Positionen). Werte ohne Marktpreise.", source="tx_csv")
        return {"holdings": holdings, "totals": totals}

    # ---------- .portfolio container ----------
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
                    self._status.update(ok=False, message="Binary .portfolio erkannt (PPPBV*). Bitte in PP: Datei → Speichern unter… → **XML** oder CSV exportieren.")
                    return {"holdings": [], "totals": {"value":0.0,"cost":0.0,"gain_abs":0.0,"gain_pct":0.0}}
                self._status.update(ok=False, message="Unbekanntes .portfolio-Innenformat.")
                return {"holdings": [], "totals": {"value":0.0,"cost":0.0,"gain_abs":0.0,"gain_pct":0.0}}
            self._status.update(ok=False, message="Leeres oder unbekanntes .portfolio-Archiv.")
            return {"holdings": [], "totals": {"value":0.0,"cost":0.0,"gain_abs":0.0,"gain_pct":0.0}}

    # ---------- PP XML ----------
    def _read_pp_xml(self, file_or_path):
        tree = ET.parse(file_or_path) if isinstance(file_or_path, str) else ET.parse(file_or_path)
        root = tree.getroot()

        securities = root.findall(".//securities/security")
        def resolve_security_from_ref(ref: str):
            m = re.search(r"securities/security\[(\d+)\]", ref or "")
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

    # ---------- Holdings-CSV ----------
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
            self._status.update(ok=False, message="CSV scheint keine Bestands-Ansicht zu sein (fehlende Spalten).")

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

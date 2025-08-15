
from __future__ import annotations
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import (
    DOMAIN, CONF_PATH, CONF_INCLUDE_DETAILS,
    ATTR_TICKER, ATTR_NAME, ATTR_QUANTITY, ATTR_PRICE, ATTR_COST, ATTR_VALUE, ATTR_GAIN_ABS, ATTR_GAIN_PCT,
    DEVICE_MANUFACTURER, DEVICE_MODEL, DEVICE_NAME, STATUS_ENTITY_ID
)
from .coordinator import PPDataCoordinator

DEVICE_INFO = {
    "identifiers": {(DOMAIN, "pp_portfolio_device")},
    "manufacturer": DEVICE_MANUFACTURER,
    "model": DEVICE_MODEL,
    "name": DEVICE_NAME,
}

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    path = entry.data[CONF_PATH]
    include_details = entry.data.get(CONF_INCLUDE_DETAILS, True)
    coordinator = PPDataCoordinator(hass, path)
    await coordinator.async_config_entry_first_refresh()

    entities = []
    entities.append(PPTotalValueSensor(coordinator, entry))
    entities.append(PPTotalCostSensor(coordinator, entry))
    entities.append(PPTotalGainAbsSensor(coordinator, entry))
    entities.append(PPTotalGainPctSensor(coordinator, entry))
    entities.append(PPStatusSensor(coordinator, entry))

    if include_details:
        for h in coordinator.data.get("holdings", []):
            entities.append(PPHoldingValueSensor(coordinator, entry, h))
            entities.append(PPHoldingGainSensor(coordinator, entry, h))

    async_add_entities(entities, True)

class _PPBase(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_device_info = DEVICE_INFO

    def __init__(self, coordinator: PPDataCoordinator, entry: ConfigEntry):
        super().__init__(coordinator)
        self._entry = entry

class PPStatusSensor(_PPBase):
    _attr_name = "Status"

    @property
    def unique_id(self) -> str:
        return f"{DOMAIN}_status"

    @property
    def native_value(self) -> StateType:
        st = self.coordinator.status
        return "ok" if st.get("ok", True) else "warn"

    @property
    def extra_state_attributes(self):
        st = self.coordinator.status
        return {
            "message": st.get("message",""),
            "headers": st.get("headers", []),
            "delimiter": st.get("delimiter", ""),
            "source": st.get("source", ""),
        }

class PPTotalValueSensor(_PPBase):
    _attr_name = "Total Value"
    _attr_native_unit_of_measurement = "EUR"

    @property
    def unique_id(self) -> str:
        return f"{DOMAIN}_total_value"

    @property
    def native_value(self) -> StateType:
        return round(self.coordinator.data["totals"].get("value", 0.0), 2)

class PPTotalCostSensor(_PPBase):
    _attr_name = "Total Cost"
    _attr_native_unit_of_measurement = "EUR"

    @property
    def unique_id(self) -> str:
        return f"{DOMAIN}_total_cost"

    @property
    def native_value(self) -> StateType:
        return round(self.coordinator.data["totals"].get("cost", 0.0), 2)

class PPTotalGainAbsSensor(_PPBase):
    _attr_name = "Total Gain"
    _attr_native_unit_of_measurement = "EUR"

    @property
    def unique_id(self) -> str:
        return f"{DOMAIN}_total_gain_abs"

    @property
    def native_value(self) -> StateType:
        return round(self.coordinator.data["totals"].get("gain_abs", 0.0), 2)

class PPTotalGainPctSensor(_PPBase):
    _attr_name = "Total Gain %"

    @property
    def unique_id(self) -> str:
        return f"{DOMAIN}_total_gain_pct"

    @property
    def native_value(self) -> StateType:
        return round(self.coordinator.data["totals"].get("gain_pct", 0.0), 2)

    @property
    def native_unit_of_measurement(self) -> str | None:
        return "%"

class PPHoldingValueSensor(_PPBase):
    def __init__(self, coordinator: PPDataCoordinator, entry: ConfigEntry, holding: dict):
        super().__init__(coordinator, entry)
        self._holding_key = holding["ticker"] or holding["name"]

    @property
    def _holding(self) -> dict:
        for h in self.coordinator.data.get("holdings", []):
            if (h["ticker"] or h["name"]) == self._holding_key:
                return h
        return {}

    @property
    def name(self):
        name = self._holding.get("name", "Holding")
        return f"{name} Value"

    @property
    def unique_id(self) -> str:
        return f"{DOMAIN}_holding_value_{self._holding_key}"

    @property
    def native_value(self) -> StateType:
        return round(self._holding.get("value", 0.0), 2)

    @property
    def native_unit_of_measurement(self) -> str | None:
        return self._holding.get("currency") or "EUR"

    @property
    def extra_state_attributes(self):
        h = self._holding
        return {
            ATTR_TICKER: h.get("ticker"),
            ATTR_NAME: h.get("name"),
            ATTR_QUANTITY: h.get("quantity"),
            ATTR_PRICE: h.get("price"),
            ATTR_COST: h.get("cost"),
            ATTR_VALUE: h.get("value"),
            ATTR_GAIN_ABS: h.get("gain_abs"),
            ATTR_GAIN_PCT: h.get("gain_pct"),
        }

class PPHoldingGainSensor(PPHoldingValueSensor):
    @property
    def name(self):
        return f"{self._holding.get('name','Holding')} Gain %"

    @property
    def unique_id(self) -> str:
        return f"{DOMAIN}_holding_gainpct_{self._holding_key}"

    @property
    def native_value(self) -> StateType:
        return round(self._holding.get("gain_pct", 0.0), 2)

    @property
    def native_unit_of_measurement(self) -> str | None:
        return "%"

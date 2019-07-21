from datetime import timedelta
import logging
import aiohttp

import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import (
    CONF_MONITORED_CONDITIONS, CONF_NAME, CONF_LATITUDE, CONF_LONGITUDE,
    CONF_API_KEY, CONF_SCAN_INTERVAL, TEMP_CELSIUS, DEVICE_CLASS_HUMIDITY,
    DEVICE_CLASS_TEMPERATURE, DEVICE_CLASS_PRESSURE, PRESSURE_HPA, HTTP_OK,
    CONTENT_TYPE_JSON, ATTR_ATTRIBUTION
)
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import Entity
from homeassistant.util import Throttle

_LOGGER = logging.getLogger(__name__)

__VERSION__ = '0.3.1'

URL = 'https://airapi.airly.eu/v2/measurements/point?lat={}&lng={}'

CONF_LANGUAGE = 'language'

DEFAULT_NAME = 'Airly'
DEFAULT_MONITORED_CONDITIONS = ['pm1', 'pm25', 'pm10']
DEFAULT_ATTRIBUTION = {"en": "Data provided by Airly",
                       "pl": "Dane dostarczone przez Airly"}
DEFAULT_SCAN_INTERVAL = timedelta(minutes=10)
DEFAULT_LANGUAGE = 'en'

LABEL_TEMPERATURE = 'Temperature'
LABEL_HUMIDITY = 'Humidity'
LABEL_PRESSURE = 'Pressure'
LABEL_PM1 = 'PM1'
LABEL_PM25 = 'PM2.5'
LABEL_PM10 = 'PM10'
LABEL_CAQI = 'CAQI'
LABEL_CAQI_DESCRIPTION = 'Description'
VOLUME_MICROGRAMS_PER_CUBIC_METER = 'µg/m³'
HUMI_PERCENT ='%'

ATTR_LIMIT = 'limit'
ATTR_PERCENT = 'percent'
ATTR_PM1 = 'pm1'
ATTR_PM25 = 'pm25'
ATTR_PM25_LIMIT = 'pm25_limit'
ATTR_PM25_PERCENT = 'pm25_percent'
ATTR_PM10 = 'pm10'
ATTR_PM10_LIMIT = 'pm10_limit'
ATTR_PM10_PERCENT = 'pm10_percent'
ATTR_TEMPERATURE = 'temperature'
ATTR_HUMIDITY = 'humidity'
ATTR_PRESSURE = 'pressure'
ATTR_CAQI = 'caqi'
ATTR_CAQI_LEVEL = 'level'
ATTR_CAQI_DESCRIPTION = 'description'
ATTR_CAQI_ADVICE = 'advice'

SENSOR_TYPES = {
    ATTR_PM1: [LABEL_PM1, VOLUME_MICROGRAMS_PER_CUBIC_METER, 'mdi:blur'],
    ATTR_PM25: [LABEL_PM25, VOLUME_MICROGRAMS_PER_CUBIC_METER, 'mdi:blur'],
    ATTR_PM10: [LABEL_PM10, VOLUME_MICROGRAMS_PER_CUBIC_METER, 'mdi:blur'],
    ATTR_PRESSURE: [LABEL_PRESSURE, PRESSURE_HPA, 'mdi:gauge'],
    ATTR_HUMIDITY: [LABEL_HUMIDITY, HUMI_PERCENT, 'mdi:water-percent'],
    ATTR_TEMPERATURE: [LABEL_TEMPERATURE, TEMP_CELSIUS, 'mdi:thermometer'],
    ATTR_CAQI: [LABEL_CAQI, None, None],
    ATTR_CAQI_DESCRIPTION: [LABEL_CAQI_DESCRIPTION, None,
                            'mdi:card-text-outline']
}

# Language supported codes
LANGUAGE_CODES = ['en', 'pl']

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_API_KEY, None): cv.string,
    vol.Inclusive(
        CONF_LATITUDE,
        'coordinates',
        'Latitude and longitude must exist together'
    ): cv.latitude,
    vol.Inclusive(
        CONF_LONGITUDE,
        'coordinates',
        'Latitude and longitude must exist together'
    ): cv.longitude,
    vol.Optional(CONF_LANGUAGE,
                 default=DEFAULT_LANGUAGE): vol.In(LANGUAGE_CODES),
    vol.Optional(CONF_MONITORED_CONDITIONS,
                 default=DEFAULT_MONITORED_CONDITIONS):
        vol.All(cv.ensure_list, [vol.In(SENSOR_TYPES)]),
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL):
        cv.time_period
})


async def async_setup_platform(
        hass, config, async_add_entities, discovery_info=None):
    """Configure the platform and add the sensors."""

    name = config.get(CONF_NAME)
    latitude = config.get(CONF_LATITUDE, hass.config.latitude)
    longitude = config.get(CONF_LONGITUDE, hass.config.longitude)
    language = config.get(CONF_LANGUAGE)
    _LOGGER.debug("Using latitude and longitude: %s, %s", latitude, longitude)

    data = AirlyData(config.get(CONF_API_KEY), latitude, longitude, language,
                     scan_interval=config[CONF_SCAN_INTERVAL])

    await data.async_update()

    sensors = []
    for variable in config[CONF_MONITORED_CONDITIONS]:
        sensors.append(AirlySensor(data, name, variable, language))
    async_add_entities(sensors, True)


class AirlySensor(Entity):
    """Define an Airly sensor."""

    def __init__(self, airly, name, type, language):
        """Initialize."""
        self._name = name
        self.type = type
        self._state = None
        self._attrs = {ATTR_ATTRIBUTION: DEFAULT_ATTRIBUTION[language]}
        self._device_class = None
        self._icon = None
        self._unit_of_measurement = None
        self.airly = airly

    @property
    def device_state_attributes(self):
        """Return the device state attributes."""
        if self.airly.data_available:
            if self.type == ATTR_CAQI_DESCRIPTION:
                self._attrs[ATTR_CAQI_ADVICE] = (self.airly.data
                        [ATTR_CAQI_ADVICE])
            if self.type == ATTR_CAQI:
                self._attrs[ATTR_CAQI_LEVEL] = self.airly.data[ATTR_CAQI_LEVEL]
            if self.type == ATTR_PM25:
                self._attrs[ATTR_LIMIT] = self.airly.data[ATTR_PM25_LIMIT]
                self._attrs[ATTR_PERCENT] = (round(self.airly.data
                        [ATTR_PM25_PERCENT]))
            if self.type == ATTR_PM10:
                self._attrs[ATTR_LIMIT] = self.airly.data[ATTR_PM10_LIMIT]
                self._attrs[ATTR_PERCENT] = (round(self.airly.data
                        [ATTR_PM10_PERCENT]))
        return self._attrs

    @property
    def name(self):
        """Return the name."""
        return '{} {}'.format(self._name, SENSOR_TYPES[self.type][0])

    @property
    def icon(self):
        """Return the icon."""
        if self.airly.data_available:
            if self.type == ATTR_CAQI:
                if self._state <= 25:
                    return 'mdi:emoticon-excited'
                elif self._state <= 50:
                    return 'mdi:emoticon-happy'
                elif self._state <= 75:
                    return 'mdi:emoticon-neutral'
                elif self._state <= 100:
                    return 'mdi:emoticon-sad'
                elif self._state > 100:
                    return 'mdi:emoticon-dead'
        return SENSOR_TYPES[self.type][2]

    @property
    def device_class(self):
        """Return the device_class."""
        if self.type == ATTR_TEMPERATURE:
            return DEVICE_CLASS_TEMPERATURE
        elif self.type == ATTR_HUMIDITY:
            return DEVICE_CLASS_HUMIDITY
        elif self.type == ATTR_PRESSURE:
            return DEVICE_CLASS_PRESSURE
        else:
            return self._device_class

    @property
    def unique_id(self):
        """Return a unique_id for this entity."""
        return '{}-{}-{}'.format(self.airly.latitude, self.airly.longitude,
                                 self.type)

    @property
    def state(self):
        """Return the state."""
        if self.airly.data_available:
            self._state = self.airly.data[self.type]
            if self.type in [ATTR_PM1, ATTR_PM25, ATTR_PM10, ATTR_PRESSURE,
                            ATTR_CAQI]:
                self._state = round(self._state)
            if self.type in [ATTR_TEMPERATURE, ATTR_HUMIDITY]:
                self._state = round(self._state, 1)
        return self._state

    @property
    def unit_of_measurement(self):
        """Return the unit the value is expressed in."""
        return SENSOR_TYPES[self.type][1]

    async def async_update(self):
        """Get the data from Airly."""
        await self.airly.async_update()


class AirlyData:
    """Define an object to hold sensor data."""

    def __init__(self, api_key, latitude, longitude, language, **kwargs):
        """Initialize."""
        self.latitude = latitude
        self.longitude = longitude
        self.language = language
        self.api_key = api_key
        self.data_available = False
        self.data = {}

        self.async_update = Throttle(
            kwargs[CONF_SCAN_INTERVAL])(self._async_update)

    async def _async_update(self):
        """Update Airly data."""
        headers = {'Accept': CONTENT_TYPE_JSON}
        headers.update({'apikey': self.api_key})
        headers.update({'Accept-Language': self.language})
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(URL.format(self.latitude,
                                                self.longitude)) as resp:
                    jsondata = await resp.json()
            _LOGGER.debug("New data retrieved: %s", resp.status)
            if resp.status == 400:
                _LOGGER.error("Can't retrieve data: bad request")
            elif resp.status == 401:
                _LOGGER.error("Can't retrieve data: unauthorized")
            elif resp.status == 429:
                _LOGGER.error("Can't retrieve data: too many requests")
            elif resp.status == 500:
                _LOGGER.error("Can't retrieve data: internal server error")
            elif resp.status == HTTP_OK:
                jsondata = jsondata['current']
                if jsondata['indexes'][0]['value']:
                    for i in range(len(jsondata['values'])):
                        self.data[jsondata['values'][i]['name'].lower()] = \
                                jsondata['values'][i]['value']
                    self.data[ATTR_PM25_LIMIT] = jsondata['standards'][0]['limit']
                    self.data[ATTR_PM25_PERCENT] = (jsondata['standards'][0]
                            ['percent'])
                    self.data[ATTR_PM10_LIMIT] = jsondata['standards'][1]['limit']
                    self.data[ATTR_PM10_PERCENT] = (jsondata['standards'][1]
                            ['percent'])
                    self.data[ATTR_CAQI] = jsondata['indexes'][0]['value']
                    self.data[ATTR_CAQI_LEVEL] = (jsondata['indexes'][0]
                            ['level'].lower().replace('_', ' '))
                    self.data[ATTR_CAQI_DESCRIPTION] = (jsondata['indexes'][0]
                            ['description'])
                    self.data[ATTR_CAQI_ADVICE] = jsondata['indexes'][0]['advice']
                    self.data_available = True
                else:
                    _LOGGER.error("Can't retrieve data: no Airly sensors in this " \
                            "area")
        except Exception as exception:
            _LOGGER.error(exception)

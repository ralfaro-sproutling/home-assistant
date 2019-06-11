"""Component to embed TP-Link smart home devices."""
import logging

import voluptuous as vol

from homeassistant.const import CONF_HOST
from homeassistant import config_entries
from homeassistant.helpers import config_entry_flow
import homeassistant.helpers.config_validation as cv


_LOGGER = logging.getLogger(__name__)

DOMAIN = 'tplink'

CONF_LIGHT = 'light'
CONF_SWITCH = 'switch'
CONF_DISCOVERY = 'discovery'
CONF_SWITCH_IS_STRIP = 'switch_is_strip'

ATTR_CONFIG = 'config'

DEFAULT_SWITCH_IS_STRIP = True

TPLINK_HOST_SCHEMA = vol.Schema({
    vol.Required(CONF_HOST): cv.string
})

TPLINK_SWITCH_HOST_SCHEMA = vol.Schema({
    vol.Required(CONF_HOST): cv.string,
    vol.Optional(CONF_SWITCH_IS_STRIP, default=DEFAULT_SWITCH_IS_STRIP): cv.boolean
})

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Optional('light', default=[]): vol.All(cv.ensure_list,
                                                   [TPLINK_HOST_SCHEMA]),
        vol.Optional('switch', default=[]): vol.All(cv.ensure_list,
                                                    [TPLINK_SWITCH_HOST_SCHEMA]),
        vol.Optional('discovery', default=True): cv.boolean,
    }),
}, extra=vol.ALLOW_EXTRA)


async def _async_has_devices(hass):
    """Return if there are devices that can be discovered."""
    from pyHS100 import Discover

    def discover():
        devs = Discover.discover()
        return devs
    return await hass.async_add_executor_job(discover)


async def async_setup(hass, config):
    """Set up the TP-Link component."""
    conf = config.get(DOMAIN)

    hass.data[DOMAIN] = {}
    hass.data[DOMAIN][ATTR_CONFIG] = conf

    if conf is not None:
        hass.async_create_task(hass.config_entries.flow.async_init(
            DOMAIN, context={'source': config_entries.SOURCE_IMPORT}))

    return True


async def async_setup_entry(hass, config_entry):
    """Set up TPLink from a config entry."""
    from pyHS100 import SmartBulb, SmartPlug, SmartStrip, SmartDeviceException

    devices = {}

    config_data = hass.data[DOMAIN].get(ATTR_CONFIG)

    # These will contain the initialized devices
    lights = hass.data[DOMAIN][CONF_LIGHT] = []
    switches = hass.data[DOMAIN][CONF_SWITCH] = []

    # If discovery is defined and not disabled, discover devices
    # If initialized from configure integrations, there's no config
    # so we default here to True
    if config_data is None or config_data[CONF_DISCOVERY]:
        devs = await _async_has_devices(hass)
        _LOGGER.info("Discovered %s TP-Link smart home device(s)", len(devs))
        devices.update(devs)

    def _device_for_type(host, type_):
        dev = None
        if type_ == CONF_LIGHT:
            dev = SmartBulb(host)
        elif type_ == CONF_SWITCH:
            dev = SmartPlug(host)
        elif type_ == CONF_SWITCH_IS_STRIP:
            _LOGGER.debug("***** SMART STRIP *****")
            dev = SmartStrip(host)

        return dev

    # When arriving from configure integrations, we have no config data.
    if config_data is not None:
        for type_ in [CONF_LIGHT, CONF_SWITCH]:
            for entry in config_data[type_]:
                try:
                    host = entry['host']
                    if entry.get(CONF_SWITCH_IS_STRIP, DEFAULT_SWITCH_IS_STRIP):
                        _LOGGER.debug("***** CONFIG SWITCH IS STRIP *****")
                        dev = _device_for_type(host, CONF_SWITCH_IS_STRIP)
                    else:
                        dev = _device_for_type(host, type_)
                    devices[host] = dev
                    _LOGGER.debug("Succesfully added %s %s: %s",
                                  type_, host, dev)
                except SmartDeviceException as ex:
                    _LOGGER.error("Unable to initialize %s %s: %s",
                                  type_, host, ex)

    # This is necessary to avoid I/O blocking on is_dimmable
    def _fill_device_lists():
        for dev in devices.values():
            _LOGGER.debug("***** instance is: {}".format(type(dev)))
            if isinstance(dev, SmartPlug) or isinstance(dev, SmartStrip):  # SmartStrip belongs in switch domain
                try:
                    if dev.is_dimmable:  # Dimmers act as lights
                        lights.append(dev)
                    else:
                        _LOGGER.debug("SWITCH {} ADDED TO SWITCHES".format(dev))
                        switches.append(dev)
                except SmartDeviceException as ex:
                    _LOGGER.error("Unable to connect to device %s: %s",
                                  dev.host, ex)

            elif isinstance(dev, SmartBulb):
                lights.append(dev)
            else:
                _LOGGER.error("Unknown smart device type: %s", type(dev))

    # Avoid blocking on is_dimmable
    await hass.async_add_executor_job(_fill_device_lists)

    forward_setup = hass.config_entries.async_forward_entry_setup
    if lights:
        _LOGGER.debug("Got %s lights: %s", len(lights), lights)
        hass.async_create_task(forward_setup(config_entry, 'light'))
    if switches:
        _LOGGER.debug("Got %s switches: %s", len(switches), switches)
        hass.async_create_task(forward_setup(config_entry, 'switch'))

    return True


async def async_unload_entry(hass, entry):
    """Unload a config entry."""
    forward_unload = hass.config_entries.async_forward_entry_unload
    remove_lights = remove_switches = False
    if hass.data[DOMAIN][CONF_LIGHT]:
        remove_lights = await forward_unload(entry, 'light')
    if hass.data[DOMAIN][CONF_SWITCH]:
        remove_switches = await forward_unload(entry, 'switch')

    if remove_lights or remove_switches:
        hass.data[DOMAIN].clear()
        return True

    # We were not able to unload the platforms, either because there
    # were none or one of the forward_unloads failed.
    return False


config_entry_flow.register_discovery_flow(DOMAIN,
                                          'TP-Link Smart Home',
                                          _async_has_devices,
                                          config_entries.CONN_CLASS_LOCAL_POLL)

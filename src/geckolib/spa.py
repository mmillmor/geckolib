""" GeckoSpa class """

import logging
import threading
import time

from .const import GeckoConstants
from .driver import (
    GeckoUdpSocket,
    GeckoHelloProtocolHandler,
    GeckoPacketProtocolHandler,
    GeckoPingProtocolHandler,
    GeckoVersionProtocolHandler,
    GeckoGetChannelProtocolHandler,
    GeckoConfigFileProtocolHandler,
    GeckoStatusBlockProtocolHandler,
    GeckoPartialStatusBlockProtocolHandler,
    GeckoPackCommandProtocolHandler,
    # Rest
    GeckoTemperatureDecorator,
    GeckoSpaPack,
    GeckoStructure,
)
from .driver import GeckoStructAccessor
from .automation import GeckoFacade

logger = logging.getLogger(__name__)


class GeckoSpaDescriptor:
    """ A descriptor class for spas that have been discovered on the network """

    def __init__(
        self,
        client_identifier: bytes,
        spa_identifier: bytes,
        spa_name: str,
        sender: tuple,
    ):
        self.client_identifier = client_identifier
        self.identifier = spa_identifier
        self.name = spa_name
        self.ipaddress, self.port = sender

    def get_facade(self):
        """Get an automation facade to interact with the spa described
        by this class"""
        return GeckoFacade(GeckoSpa(self).connect())

    @property
    def destination(self):
        return (self.ipaddress, self.port)


class GeckoSpa(GeckoUdpSocket, GeckoSpaPack):
    """
    GeckoSpa class manages an instance of a spa, and is the main point of contact for
    control and monitoring. Uses the declarations found in SpaPackStruct.xml to build
    an object that exposes the properties and capabilities of your spa. This class
    should only be used via a Facade which hides the implementation details"""

    def __init__(self, descriptor):
        super().__init__()
        GeckoSpaPack.__init__(self)

        self.descriptor = descriptor

        self.add_receive_handler(GeckoPacketProtocolHandler())
        self.add_receive_handler(
            GeckoPartialStatusBlockProtocolHandler(
                on_handled=self._on_partial_status_update
            )
        )
        self._ping_thread = threading.Thread(target=self._ping_thread_func, daemon=True)

        # Default values for properties
        self.channel = 0
        self.signal = 0

        self.intouch_version_en = ""
        self.intouch_version_co = ""

        self.gecko_pack_xml = None
        self.config_version = 0
        self.config_xml = None
        self.log_version = 0
        self.log_xml = None
        self.pack_type = None
        self.is_connected = False
        self.pack = None
        self.version = None
        self.config_number = None

        # Inspection of the SpaPackStruct.xml shows that there are (currently) no
        # configurations larger than this
        self.accessors = {}

        self.struct = GeckoStructure(self)

    def complete(self):
        """ Complete the use of this spa class """
        super().close()
        self._ping_thread.join()

    def _on_partial_status_update(self, handler, socket, sender):
        for change in handler.changes:
            self.struct.replace_status_block_segment(change[0], change[1])

    def _on_config_received(self, handler, socket, sender):
        # XML is case-sensitive, but the platform from the config isn't formed the same,
        # so we manually search the Plateform nodes to find the one we're interested in
        for plateform in self.xml.findall(GeckoConstants.SPA_PACK_PLATEFORM_XPATH):
            if (
                plateform.attrib[GeckoConstants.SPA_PACK_NAME_ATTRIB].lower()
                == handler.plateform_key.lower()
            ):
                self.gecko_pack_xml = plateform

        # We can't carry on without information on how the STATV data block is formed
        if self.gecko_pack_xml is None:
            raise Exception(
                GeckoConstants.EXCEPTION_MESSAGE_NO_SPA_PACK.format(
                    handler.plateform_key
                )
            )

        # Stash the config and log structure declarations
        self.config_version = handler.config_version
        self.config_xml = self.gecko_pack_xml.find(
            GeckoConstants.SPA_PACK_CONFIG_XPATH.format(self.config_version)
        )
        self.log_version = handler.log_version
        self.log_xml = self.gecko_pack_xml.find(
            GeckoConstants.SPA_PACK_LOG_XPATH.format(self.log_version)
        )
        self.pack_type = int(
            self.gecko_pack_xml.attrib[GeckoConstants.SPA_PACK_STRUCT_TYPE_ATTRIB]
        )
        logger.debug(
            "Got spa configuration Type %s - CFG %s/LOG %s, now ask for initial "
            "status block",
            self.pack_type,
            self.config_version,
            self.log_version,
        )

        self.struct.retry_request(
            GeckoStatusBlockProtocolHandler.full_request(
                socket.get_and_increment_sequence_counter(), parms=sender
            ),
            sender,
        )

    def _on_channel_received(self, handler, socket, sender):
        self.channel = handler.channel
        self.signal = handler.signal_strength
        logger.debug("Got channel %s/%s, now get config", self.channel, self.signal)
        socket.add_receive_handler(
            GeckoConfigFileProtocolHandler(on_handled=self._on_config_received)
        )
        socket.queue_send(
            GeckoConfigFileProtocolHandler.request(
                socket.get_and_increment_sequence_counter(), parms=sender
            ),
            sender,
        )

    def _on_version_received(self, handler, socket, sender):
        self.intouch_version_en = "{0} v{1}.{2}".format(
            handler.en_build, handler.en_major, handler.en_minor
        )
        self.intouch_version_co = "{0} v{1}.{2}".format(
            handler.co_build, handler.co_major, handler.co_minor
        )
        logger.debug(
            "Got software version %s/%s, now get channel",
            self.intouch_version_en,
            self.intouch_version_co,
        )
        socket.add_receive_handler(
            GeckoGetChannelProtocolHandler(on_handled=self._on_channel_received)
        )
        socket.queue_send(
            GeckoGetChannelProtocolHandler.request(
                socket.get_and_increment_sequence_counter(), parms=sender
            ),
            sender,
        )

    @property
    def sendparms(self):
        return (
            self.descriptor.destination[0],
            self.descriptor.destination[1],
            self.descriptor.identifier,
            self.descriptor.client_identifier,
        )

    def _on_ping_response(self, handler, socket, sender):
        self._last_ping = time.monotonic()

    def connect(self):
        """ Connect to the in.touch2 module """
        # Identify self to the intouch module
        self.queue_send(
            GeckoHelloProtocolHandler.client(self.descriptor.client_identifier),
            self.descriptor.destination,
        )
        self.open()
        self._ping_handler = GeckoPingProtocolHandler.request(
            parms=self.sendparms, on_handled=self._on_ping_response
        )
        self.add_receive_handler(self._ping_handler)
        self._ping_thread.start()
        # Get the intouch version
        logger.info("Starting spa connection handshake...")
        self.is_connected = False
        self.add_receive_handler(
            GeckoVersionProtocolHandler(on_handled=self._on_version_received)
        )
        self.queue_send(
            GeckoVersionProtocolHandler.request(
                self.get_and_increment_sequence_counter(),
                parms=self.sendparms,
            ),
            self.sendparms,
        )
        # Wait for connection sequence to complete
        # TODO: Add a timeout/retry mechanism here
        while not self.is_connected:
            if not self.isopen:
                return
            self.is_connected = self.struct.had_at_least_one_block
        self._build_accessors()
        self.pack = self.accessors[GeckoConstants.KEY_PACK_TYPE].value
        self.version = "{0} v{1}.{2}".format(
            self.accessors[GeckoConstants.KEY_PACK_CONFIG_ID].value,
            self.accessors[GeckoConstants.KEY_PACK_CONFIG_REV].value,
            self.accessors[GeckoConstants.KEY_PACK_CONFIG_REL].value,
        )
        self.config_number = self.accessors[GeckoConstants.KEY_CONFIG_NUMBER].value
        logger.info("Spa is connected")
        return self

    def _ping_thread_func(self):
        """ Ping thread function """
        logger.info("Ping thread started, %r", self.isopen)
        while self.isopen:
            self.queue_send(self._ping_handler, self.sendparms)
            self.refresh()
            self.wait(GeckoConstants.PING_FREQUENCY_IN_SECONDS)
            if (
                time.monotonic() - self._last_ping
                > GeckoConstants.PING_DEVICE_NOT_RESPONDING_TIMEOUT
            ):
                logger.warning(
                    "Spa is not responding to pings, need to reconnect...TODO"
                )
        logger.info("Ping thread finished")

    def _build_accessors(self):
        self.accessors = {
            element.tag: GeckoStructAccessor(self, element)
            for xml in [self.config_xml, self.log_xml]
            for element in xml.findall(
                GeckoConstants.SPA_PACK_STRUCT_POS_ELEMENTS_XPATH
            )
        }
        # Fix temperature accessors ...
        temp_keys = {
            element.tag
            for xml in [self.config_xml, self.log_xml]
            for element in xml.findall(
                GeckoConstants.SPA_PACK_STRUCT_WORD_TYPE_ELEMENTS_XPATH
            )
            if "temp" in element.tag.lower() or "setpoint" in element.tag.lower()
        }
        logger.debug("Temperature keys to decorate %s", temp_keys)
        for key in temp_keys:
            self.accessors[key] = GeckoTemperatureDecorator(self, self.accessors[key])

    def get_buttons(self):
        """ Get a list of buttons that can be pressed """
        return [button[0] for button in GeckoConstants.BUTTONS]

    def refresh(self):
        """ Refresh the live spa data block """
        if not self.is_connected:
            logger.debug("Can't refresh as we're not connected yet")
            return
        self.struct.retry_request(
            GeckoStatusBlockProtocolHandler.request(
                self.get_and_increment_sequence_counter(),
                int(self.log_xml.attrib[GeckoConstants.SPA_PACK_STRUCT_BEGIN_ATTRIB]),
                int(self.log_xml.attrib[GeckoConstants.SPA_PACK_STRUCT_END_ATTRIB]),
                parms=self.sendparms,
            ),
            self.sendparms,
        )

    def press(self, keypad):
        """ Simulate a button press """
        self.add_receive_handler(GeckoPackCommandProtocolHandler())
        self.queue_send(
            GeckoPackCommandProtocolHandler.keypress(
                self.get_and_increment_sequence_counter(),
                self.pack_type,
                keypad,
                parms=self.sendparms,
            ),
            self.sendparms,
        )

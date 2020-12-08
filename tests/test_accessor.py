""" Unit tests for the structure accessor class """

import struct
import unittest
import xml.etree.ElementTree as ET

from context import GeckoStructAccessor, GeckoStructure


class MockSpa:
    """ A Mock Spa class for use in unit tests """

    def __init__(self):

        self.pack_type = 6
        self.config_version = 9
        self.log_version = 9
        self.sendparms = (1, 2, 3, 4)

        self.struct = GeckoStructure(None)
        self.struct.set_status_block(
            # Bytes 0-16 are identity values
            b"\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10"
            # Bytes 17-18 are a temperature in farenheight 10ths from freezing
            b"\x02\xbe"
            # Bytes 19-20 are a sized bitpos enum
            b"\x11\x70"
            # Bytes 21-22 are an empty sized bitpos enum
            b"\x00\x00"
        )
        self.last_pos = 0
        self.last_len = 0
        self.last_data = None

    def send_request(self, message):
        """ Store data from the last message sent """
        self.last_len = struct.unpack(">B", message.parms[1:2].encode("latin1"))[0]
        self.last_pos = struct.unpack(">H", message.parms[5:7].encode("latin1"))[0]
        self.last_data = message.parms[7:]
        self.struct.replace_status_block_segment(
            self.last_pos, self.last_data.encode("latin1")
        )

    def add_receive_handler(self, handler):
        pass

    def queue_send(self, handler):
        content = handler._content[6:]
        self.last_len = struct.unpack(">B", content[1:2])[0]
        self.last_pos = struct.unpack(">H", content[5:7])[0]
        self.last_data = content[7:]
        self.struct.replace_status_block_segment(self.last_pos, self.last_data)

    def get_and_increment_sequence_counter(self):
        return 1


class TestStructAccessor(unittest.TestCase):
    """ Test the GeckoStructAccessor class """

    def setUp(self):
        self.spa = MockSpa()

    def test_read_byte(self):
        """ Can we read a byte from the structure """
        element = ET.fromstring('<PackBootRev Type="Byte" Pos="5" />')
        accessor = GeckoStructAccessor(self.spa, element)
        self.assertEqual(5, accessor.value)

    @unittest.expectedFailure
    def test_write_byte_fails(self):
        """ Can we write a byte to the structure without the RW tag? """
        element = ET.fromstring('<PackBootRev Type="Byte" Pos="5" />')
        accessor = GeckoStructAccessor(self.spa, element)
        accessor.value = 6

    def test_write_byte(self):
        """ Can we write a byte to the structure """
        element = ET.fromstring('<PackBootRev Type="Byte" Pos="5" RW="ALL" />')
        accessor = GeckoStructAccessor(self.spa, element)
        accessor.value = 6
        self.assertEqual(5, self.spa.last_pos)
        self.assertEqual(b"\x06", self.spa.last_data)

    def test_read_word(self):
        """ Can we read a word from the structure """
        element = ET.fromstring('<RealSetPointG Type="Word" Pos="17" />')
        accessor = GeckoStructAccessor(self.spa, element)
        self.assertEqual(702, accessor.value)

    def test_write_word(self):
        """ Can we write a word to the structure """
        element = ET.fromstring('<RealSetPointG Type="Word" Pos="17" RW="ALL"/>')
        accessor = GeckoStructAccessor(self.spa, element)
        accessor.value = 726
        self.assertEqual(17, self.spa.last_pos)
        self.assertEqual(b"\x02\xd6", self.spa.last_data)

    def test_read_enum(self):
        """ Can we read an enum from the structure """
        element = ET.fromstring(
            '<PackType Type="Enum" Pos="6" '
            'Items="Unknown|inXE|MasIBC|MIA|DJS4|inClear|inXM|K600'
            '|inTerface|inTouch|inYT|K800|inYJ" />'
        )
        accessor = GeckoStructAccessor(self.spa, element)
        self.assertEqual("inXM", accessor.value)

    def test_write_enum(self):
        """ Can we write an enum to the structure """
        element = ET.fromstring(
            '<PackType Type="Enum" Pos="6" '
            'Items="Unknown|inXE|MasIBC|MIA|DJS4|inClear|inXM|K600'
            '|inTerface|inTouch|inYT|K800|inYJ" RW="ALL"/>'
        )
        accessor = GeckoStructAccessor(self.spa, element)
        accessor.value = "inYJ"
        self.assertEqual(6, self.spa.last_pos)
        self.assertEqual(b"\x0c", self.spa.last_data)

    @unittest.expectedFailure
    def test_write_enum_not_member(self):
        """ Can we write an enum to the structure """
        element = ET.fromstring(
            '<PackType Type="Enum" Pos="6" '
            'Items="Unknown|inXE|MasIBC|MIA|DJS4|inClear|inXM|K600'
            '|inTerface|inTouch|inYT|K800|inYJ" RW="ALL"/>'
        )
        accessor = GeckoStructAccessor(self.spa, element)
        accessor.value = "Not A Member"

    def test_read_bool(self):
        """ Can we read a bool from the structure """
        element = ET.fromstring('<RelayStuck Type="Bool" Pos="2" BitPos="6" />')
        accessor = GeckoStructAccessor(self.spa, element)
        self.assertFalse(accessor.value)

    def test_write_bool(self):
        """ Can we write a bool to the structure """
        element = ET.fromstring(
            '<RelayStuck Type="Bool" Pos="2" BitPos="6" RW="ALL" />'
        )
        accessor = GeckoStructAccessor(self.spa, element)
        accessor.value = True
        self.assertEqual(2, self.spa.last_pos)
        self.assertEqual(b"B", self.spa.last_data)

    def test_read_bitpos_enum(self):
        """ Can we read a bitpos enum from the structure """
        element = ET.fromstring(
            '<UdP3 Type="Enum" Pos="3" BitPos="4" MaxItems="4"'
            ' Items="OFF|LO|HI" RW="ALL" />'
        )
        accessor = GeckoStructAccessor(self.spa, element)
        self.assertEqual("OFF", accessor.value)

    def test_write_bitpos_enum(self):
        """ Can we write an enum to the structure """
        element = ET.fromstring(
            '<UdP3 Type="Enum" Pos="3" BitPos="4" MaxItems="4"'
            ' Items="OFF|LO|HI" RW="ALL" />'
        )
        accessor = GeckoStructAccessor(self.spa, element)
        accessor.value = "HI"
        self.assertEqual(3, self.spa.last_pos)
        self.assertEqual(b"#", self.spa.last_data)
        accessor.value = "LO"
        self.assertEqual(b"\x13", self.spa.last_data)
        accessor.value = "OFF"
        self.assertEqual(b"\x03", self.spa.last_data)

    def test_read_sized_bitpos_enum(self):
        """ Can we read a sized bitpos enum from the structure """
        element = ET.fromstring(
            '<UdP2 Type="Enum" Pos="19" BitPos="12" Size="2" '
            'MaxItems="4" Items="OFF|LO|HI" RW="ALL" />'
        )
        accessor = GeckoStructAccessor(self.spa, element)
        self.assertEqual("LO", accessor.value)

    def test_write_sized_bitpos_enum(self):
        """ Can we write a sized bitpos enum to the structure """
        element = ET.fromstring(
            '<UdP2 Type="Enum" Pos="19" BitPos="12" Size="2" '
            'MaxItems="4" Items="OFF|LO|HI" RW="ALL" />'
        )
        accessor = GeckoStructAccessor(self.spa, element)
        accessor.value = "HI"
        self.assertEqual(19, self.spa.last_pos)
        self.assertEqual(
            chr(0b00100001) + chr(0b01110000), self.spa.last_data.decode("latin-1")
        )
        accessor.value = "LO"
        self.assertEqual(
            chr(0b00010001) + chr(0b01110000), self.spa.last_data.decode("latin-1")
        )
        accessor.value = "OFF"
        self.assertEqual(
            chr(0b00000001) + chr(0b01110000), self.spa.last_data.decode("latin-1")
        )

    def test_multiple_write_bitpos_enum(self):
        """ Can we write multiple bitpos enums to the structure """

        element_p1 = ET.fromstring(
            '<UdP1 Type="Enum" Pos="21" BitPos="14" Size="2" '
            'MaxItems="4" Items="OFF|LO|HI" RW="ALL" />'
        )
        element_p2 = ET.fromstring(
            '<UdP2 Type="Enum" Pos="21" BitPos="12" Size="2" '
            'MaxItems="4" Items="OFF|LO|HI" RW="ALL" />'
        )

        accessor_p1 = GeckoStructAccessor(self.spa, element_p1)
        accessor_p2 = GeckoStructAccessor(self.spa, element_p2)

        accessor_p2.value = "HI"
        self.assertEqual(21, self.spa.last_pos)
        self.assertEqual(b"\x20\x00", self.spa.last_data)
        self.assertEqual(7, self.spa.last_len)
        self.assertEqual(2, len(self.spa.last_data))

        accessor_p1.value = "HI"
        self.assertEqual(21, self.spa.last_pos)
        self.assertEqual(b"\xA0\x00", self.spa.last_data)
        self.assertEqual(7, self.spa.last_len)
        self.assertEqual(2, len(self.spa.last_data))


if __name__ == "__main__":
    unittest.main()

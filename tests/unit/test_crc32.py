import struct
import zlib


def test_crc32_calculation():
    """
    Test standard CRC32 checksum calculations for packet integrity verification.
    """
    # Create simple dummy byte buffer
    data = b"CSI_DATA_TEST_BUFFER_12345"

    # Calculate CRC32 using Python zlib
    calculated_crc = zlib.crc32(data) & 0xFFFFFFFF

    # Pack the data followed by the calculated CRC32 checksum (little-endian)
    packed_packet = data + struct.pack("<I", calculated_crc)

    # Unwrap and verify
    received_crc = struct.unpack_from("<I", packed_packet, offset=len(data))[0]
    recalculated_crc = zlib.crc32(packed_packet[:-4]) & 0xFFFFFFFF

    assert received_crc == calculated_crc
    assert recalculated_crc == received_crc

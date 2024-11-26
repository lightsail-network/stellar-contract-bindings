import base64
import dataclasses
from typing import List, Optional, Tuple, Type, Union

from stellar_sdk import xdr


@dataclasses.dataclass
class ContractMetaData:
    """The contract metadata parsed from the Stellar Contract WASM."""

    env_meta_bytes: Optional[bytes] = None
    env_meta: List[xdr.SCEnvMetaEntry] = dataclasses.field(default_factory=list)
    meta_bytes: Optional[bytes] = None
    meta: List[xdr.SCMetaEntry] = dataclasses.field(default_factory=list)
    spec_bytes: Optional[bytes] = None
    spec: List[xdr.SCSpecEntry] = dataclasses.field(default_factory=list)


def parse_contract_metadata(wasm: Union[bytes, str]) -> ContractMetaData:
    """Parse contract metadata from the Stellar Contract WASM.

    :param wasm: The Stellar Contract WASM as bytes or base64 encoded string.
    :return: The parsed contract metadata.
    """
    if isinstance(wasm, str):
        wasm = base64.b64decode(wasm)

    custom_sections = get_custom_sections(wasm)
    metadata = ContractMetaData()
    for name, content in custom_sections:
        if name == "contractenvmetav0":
            metadata.env_meta_bytes = content
            metadata.env_meta = parse_entries(content, xdr.SCEnvMetaEntry)
        if name == "contractspecv0":
            metadata.spec_bytes = content
            metadata.spec = parse_entries(content, xdr.SCSpecEntry)
        if name == "contractmetav0":
            metadata.meta_bytes = content
            metadata.meta = parse_entries(content, xdr.SCMetaEntry)
    return metadata


def leb128_decode(data: bytes, offset: int) -> Tuple[int, int]:
    """Decode a Little Endian Base 128 encoded integer.

    :param data: The data to decode.
    :param offset: The offset to start decoding.
    :return: The decoded integer and the number of bytes read.
    """
    result = 0
    shift = 0
    size = 0
    byte = 0x80
    while byte & 0x80:
        byte = data[offset + size]
        result |= (byte & 0x7F) << shift
        shift += 7
        size += 1
    return result, size


def get_custom_sections(wasm_data: bytes) -> List[Tuple[str, bytes]]:
    """Get the custom sections from the given WebAssembly data.

    :param wasm_data: The WebAssembly data.
    :return: The custom sections as a list of tuples containing the name and content.
    """

    assert wasm_data[:4] == b"\x00asm", "Invalid WebAssembly magic number"
    offset = 8  # Skip past the magic number and version
    custom_sections = []

    while offset < len(wasm_data):
        section_id, section_id_size = leb128_decode(wasm_data, offset)
        offset += section_id_size
        section_len, section_len_size = leb128_decode(wasm_data, offset)
        offset += section_len_size

        if section_id == 0:  # Custom Section
            name_len, size_name_size = leb128_decode(wasm_data, offset)
            offset += size_name_size
            name = wasm_data[offset : offset + name_len].decode("utf-8")
            offset += name_len
            content = wasm_data[
                offset : offset + section_len - size_name_size - name_len
            ]
            offset += section_len - size_name_size - name_len
            custom_sections.append((name, content))
        else:
            offset += section_len
    return custom_sections


def parse_entries(
    data: bytes, cls: Type[Union[xdr.SCEnvMetaEntry, xdr.SCMetaEntry, xdr.SCSpecEntry]]
) -> List[Union[xdr.SCEnvMetaEntry, xdr.SCMetaEntry, xdr.SCSpecEntry]]:
    """Parse a list of entries from the given data.

    :param data: The data to parse.
    :param cls: The class to use for parsing.
    :return: The parsed entries.
    """
    entries = []
    offset = 0
    while offset < len(data):
        entry = cls.from_xdr_bytes(data[offset:])
        offset += len(entry.to_xdr_bytes())
        entries.append(entry)
    return entries

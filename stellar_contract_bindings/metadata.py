import base64
import dataclasses
from typing import List, Optional, Tuple, Type, Union

import xdrlib3
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
            metadata.env_meta = parse_entries(content, xdr.SCEnvMetaEntry)  # type: ignore[assignment]
        if name == "contractspecv0":
            metadata.spec_bytes = content
            metadata.spec = parse_entries(content, xdr.SCSpecEntry)  # type: ignore[assignment]
        if name == "contractmetav0":
            metadata.meta_bytes = content
            metadata.meta = parse_entries(content, xdr.SCMetaEntry)  # type: ignore[assignment]
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


def get_token_sc_spec_entry() -> list[xdr.SCSpecEntry]:
    """Get the token contract spec entry."""

    # A little bit hacky, but it works
    # TODO: find a way to get the token contract spec entry in the repo
    # https://github.com/stellar/stellar-cli/blob/a11a924d310c1602e7b579377daa3e373010ac0e/cmd/soroban-cli/src/get_spec.rs#L77
    raw_xdr = "AAAAAAAAAYpSZXR1cm5zIHRoZSBhbGxvd2FuY2UgZm9yIGBzcGVuZGVyYCB0byB0cmFuc2ZlciBmcm9tIGBmcm9tYC4KClRoZSBhbW91bnQgcmV0dXJuZWQgaXMgdGhlIGFtb3VudCB0aGF0IHNwZW5kZXIgaXMgYWxsb3dlZCB0byB0cmFuc2ZlcgpvdXQgb2YgZnJvbSdzIGJhbGFuY2UuIFdoZW4gdGhlIHNwZW5kZXIgdHJhbnNmZXJzIGFtb3VudHMsIHRoZSBhbGxvd2FuY2UKd2lsbCBiZSByZWR1Y2VkIGJ5IHRoZSBhbW91bnQgdHJhbnNmZXJyZWQuCgojIEFyZ3VtZW50cwoKKiBgZnJvbWAgLSBUaGUgYWRkcmVzcyBob2xkaW5nIHRoZSBiYWxhbmNlIG9mIHRva2VucyB0byBiZSBkcmF3biBmcm9tLgoqIGBzcGVuZGVyYCAtIFRoZSBhZGRyZXNzIHNwZW5kaW5nIHRoZSB0b2tlbnMgaGVsZCBieSBgZnJvbWAuAAAAAAAJYWxsb3dhbmNlAAAAAAAAAgAAAAAAAAAEZnJvbQAAABMAAAAAAAAAB3NwZW5kZXIAAAAAEwAAAAEAAAALAAAAAAAAAIlSZXR1cm5zIHRydWUgaWYgYGlkYCBpcyBhdXRob3JpemVkIHRvIHVzZSBpdHMgYmFsYW5jZS4KCiMgQXJndW1lbnRzCgoqIGBpZGAgLSBUaGUgYWRkcmVzcyBmb3Igd2hpY2ggdG9rZW4gYXV0aG9yaXphdGlvbiBpcyBiZWluZyBjaGVja2VkLgAAAAAAAAphdXRob3JpemVkAAAAAAABAAAAAAAAAAJpZAAAAAAAEwAAAAEAAAABAAAAAAAAA59TZXQgdGhlIGFsbG93YW5jZSBieSBgYW1vdW50YCBmb3IgYHNwZW5kZXJgIHRvIHRyYW5zZmVyL2J1cm4gZnJvbQpgZnJvbWAuCgpUaGUgYW1vdW50IHNldCBpcyB0aGUgYW1vdW50IHRoYXQgc3BlbmRlciBpcyBhcHByb3ZlZCB0byB0cmFuc2ZlciBvdXQgb2YKZnJvbSdzIGJhbGFuY2UuIFRoZSBzcGVuZGVyIHdpbGwgYmUgYWxsb3dlZCB0byB0cmFuc2ZlciBhbW91bnRzLCBhbmQKd2hlbiBhbiBhbW91bnQgaXMgdHJhbnNmZXJyZWQgdGhlIGFsbG93YW5jZSB3aWxsIGJlIHJlZHVjZWQgYnkgdGhlCmFtb3VudCB0cmFuc2ZlcnJlZC4KCiMgQXJndW1lbnRzCgoqIGBmcm9tYCAtIFRoZSBhZGRyZXNzIGhvbGRpbmcgdGhlIGJhbGFuY2Ugb2YgdG9rZW5zIHRvIGJlIGRyYXduIGZyb20uCiogYHNwZW5kZXJgIC0gVGhlIGFkZHJlc3MgYmVpbmcgYXV0aG9yaXplZCB0byBzcGVuZCB0aGUgdG9rZW5zIGhlbGQgYnkKYGZyb21gLgoqIGBhbW91bnRgIC0gVGhlIHRva2VucyB0byBiZSBtYWRlIGF2YWlsYWJsZSB0byBgc3BlbmRlcmAuCiogYGV4cGlyYXRpb25fbGVkZ2VyYCAtIFRoZSBsZWRnZXIgbnVtYmVyIHdoZXJlIHRoaXMgYWxsb3dhbmNlIGV4cGlyZXMuIENhbm5vdApiZSBsZXNzIHRoYW4gdGhlIGN1cnJlbnQgbGVkZ2VyIG51bWJlciB1bmxlc3MgdGhlIGFtb3VudCBpcyBiZWluZyBzZXQgdG8gMC4KQW4gZXhwaXJlZCBlbnRyeSAod2hlcmUgZXhwaXJhdGlvbl9sZWRnZXIgPCB0aGUgY3VycmVudCBsZWRnZXIgbnVtYmVyKQpzaG91bGQgYmUgdHJlYXRlZCBhcyBhIDAgYW1vdW50IGFsbG93YW5jZS4KCiMgRXZlbnRzCgpFbWl0cyBhbiBldmVudCB3aXRoIHRvcGljcyBgWyJhcHByb3ZlIiwgZnJvbTogQWRkcmVzcywKc3BlbmRlcjogQWRkcmVzc10sIGRhdGEgPSBbYW1vdW50OiBpMTI4LCBleHBpcmF0aW9uX2xlZGdlcjogdTMyXWAAAAAAB2FwcHJvdmUAAAAABAAAAAAAAAAEZnJvbQAAABMAAAAAAAAAB3NwZW5kZXIAAAAAEwAAAAAAAAAGYW1vdW50AAAAAAALAAAAAAAAABFleHBpcmF0aW9uX2xlZGdlcgAAAAAAAAQAAAAAAAAAAAAAAJhSZXR1cm5zIHRoZSBiYWxhbmNlIG9mIGBpZGAuCgojIEFyZ3VtZW50cwoKKiBgaWRgIC0gVGhlIGFkZHJlc3MgZm9yIHdoaWNoIGEgYmFsYW5jZSBpcyBiZWluZyBxdWVyaWVkLiBJZiB0aGUKYWRkcmVzcyBoYXMgbm8gZXhpc3RpbmcgYmFsYW5jZSwgcmV0dXJucyAwLgAAAAdiYWxhbmNlAAAAAAEAAAAAAAAAAmlkAAAAAAATAAAAAQAAAAsAAAAAAAABYkJ1cm4gYGFtb3VudGAgZnJvbSBgZnJvbWAuCgpSZWR1Y2VzIGZyb20ncyBiYWxhbmNlIGJ5IHRoZSBhbW91bnQsIHdpdGhvdXQgdHJhbnNmZXJyaW5nIHRoZSBiYWxhbmNlCnRvIGFub3RoZXIgaG9sZGVyJ3MgYmFsYW5jZS4KCiMgQXJndW1lbnRzCgoqIGBmcm9tYCAtIFRoZSBhZGRyZXNzIGhvbGRpbmcgdGhlIGJhbGFuY2Ugb2YgdG9rZW5zIHdoaWNoIHdpbGwgYmUKYnVybmVkIGZyb20uCiogYGFtb3VudGAgLSBUaGUgYW1vdW50IG9mIHRva2VucyB0byBiZSBidXJuZWQuCgojIEV2ZW50cwoKRW1pdHMgYW4gZXZlbnQgd2l0aCB0b3BpY3MgYFsiYnVybiIsIGZyb206IEFkZHJlc3NdLCBkYXRhID0gYW1vdW50OgppMTI4YAAAAAAABGJ1cm4AAAACAAAAAAAAAARmcm9tAAAAEwAAAAAAAAAGYW1vdW50AAAAAAALAAAAAAAAAAAAAALaQnVybiBgYW1vdW50YCBmcm9tIGBmcm9tYCwgY29uc3VtaW5nIHRoZSBhbGxvd2FuY2Ugb2YgYHNwZW5kZXJgLgoKUmVkdWNlcyBmcm9tJ3MgYmFsYW5jZSBieSB0aGUgYW1vdW50LCB3aXRob3V0IHRyYW5zZmVycmluZyB0aGUgYmFsYW5jZQp0byBhbm90aGVyIGhvbGRlcidzIGJhbGFuY2UuCgpUaGUgc3BlbmRlciB3aWxsIGJlIGFsbG93ZWQgdG8gYnVybiB0aGUgYW1vdW50IGZyb20gZnJvbSdzIGJhbGFuY2UsIGlmCnRoZSBhbW91bnQgaXMgbGVzcyB0aGFuIG9yIGVxdWFsIHRvIHRoZSBhbGxvd2FuY2UgdGhhdCB0aGUgc3BlbmRlciBoYXMKb24gdGhlIGZyb20ncyBiYWxhbmNlLiBUaGUgc3BlbmRlcidzIGFsbG93YW5jZSBvbiBmcm9tJ3MgYmFsYW5jZSB3aWxsIGJlCnJlZHVjZWQgYnkgdGhlIGFtb3VudC4KCiMgQXJndW1lbnRzCgoqIGBzcGVuZGVyYCAtIFRoZSBhZGRyZXNzIGF1dGhvcml6aW5nIHRoZSBidXJuLCBhbmQgaGF2aW5nIGl0cyBhbGxvd2FuY2UKY29uc3VtZWQgZHVyaW5nIHRoZSBidXJuLgoqIGBmcm9tYCAtIFRoZSBhZGRyZXNzIGhvbGRpbmcgdGhlIGJhbGFuY2Ugb2YgdG9rZW5zIHdoaWNoIHdpbGwgYmUKYnVybmVkIGZyb20uCiogYGFtb3VudGAgLSBUaGUgYW1vdW50IG9mIHRva2VucyB0byBiZSBidXJuZWQuCgojIEV2ZW50cwoKRW1pdHMgYW4gZXZlbnQgd2l0aCB0b3BpY3MgYFsiYnVybiIsIGZyb206IEFkZHJlc3NdLCBkYXRhID0gYW1vdW50OgppMTI4YAAAAAAACWJ1cm5fZnJvbQAAAAAAAAMAAAAAAAAAB3NwZW5kZXIAAAAAEwAAAAAAAAAEZnJvbQAAABMAAAAAAAAABmFtb3VudAAAAAAACwAAAAAAAAAAAAABUUNsYXdiYWNrIGBhbW91bnRgIGZyb20gYGZyb21gIGFjY291bnQuIGBhbW91bnRgIGlzIGJ1cm5lZCBpbiB0aGUKY2xhd2JhY2sgcHJvY2Vzcy4KCiMgQXJndW1lbnRzCgoqIGBmcm9tYCAtIFRoZSBhZGRyZXNzIGhvbGRpbmcgdGhlIGJhbGFuY2UgZnJvbSB3aGljaCB0aGUgY2xhd2JhY2sgd2lsbAp0YWtlIHRva2Vucy4KKiBgYW1vdW50YCAtIFRoZSBhbW91bnQgb2YgdG9rZW5zIHRvIGJlIGNsYXdlZCBiYWNrLgoKIyBFdmVudHMKCkVtaXRzIGFuIGV2ZW50IHdpdGggdG9waWNzIGBbImNsYXdiYWNrIiwgYWRtaW46IEFkZHJlc3MsIHRvOiBBZGRyZXNzXSwKZGF0YSA9IGFtb3VudDogaTEyOGAAAAAAAAAIY2xhd2JhY2sAAAACAAAAAAAAAARmcm9tAAAAEwAAAAAAAAAGYW1vdW50AAAAAAALAAAAAAAAAAAAAACAUmV0dXJucyB0aGUgbnVtYmVyIG9mIGRlY2ltYWxzIHVzZWQgdG8gcmVwcmVzZW50IGFtb3VudHMgb2YgdGhpcyB0b2tlbi4KCiMgUGFuaWNzCgpJZiB0aGUgY29udHJhY3QgaGFzIG5vdCB5ZXQgYmVlbiBpbml0aWFsaXplZC4AAAAIZGVjaW1hbHMAAAAAAAAAAQAAAAQAAAAAAAAA801pbnRzIGBhbW91bnRgIHRvIGB0b2AuCgojIEFyZ3VtZW50cwoKKiBgdG9gIC0gVGhlIGFkZHJlc3Mgd2hpY2ggd2lsbCByZWNlaXZlIHRoZSBtaW50ZWQgdG9rZW5zLgoqIGBhbW91bnRgIC0gVGhlIGFtb3VudCBvZiB0b2tlbnMgdG8gYmUgbWludGVkLgoKIyBFdmVudHMKCkVtaXRzIGFuIGV2ZW50IHdpdGggdG9waWNzIGBbIm1pbnQiLCBhZG1pbjogQWRkcmVzcywgdG86IEFkZHJlc3NdLCBkYXRhCj0gYW1vdW50OiBpMTI4YAAAAAAEbWludAAAAAIAAAAAAAAAAnRvAAAAAAATAAAAAAAAAAZhbW91bnQAAAAAAAsAAAAAAAAAAAAAAFlSZXR1cm5zIHRoZSBuYW1lIGZvciB0aGlzIHRva2VuLgoKIyBQYW5pY3MKCklmIHRoZSBjb250cmFjdCBoYXMgbm90IHlldCBiZWVuIGluaXRpYWxpemVkLgAAAAAAAARuYW1lAAAAAAAAAAEAAAAQAAAAAAAAAQxTZXRzIHRoZSBhZG1pbmlzdHJhdG9yIHRvIHRoZSBzcGVjaWZpZWQgYWRkcmVzcyBgbmV3X2FkbWluYC4KCiMgQXJndW1lbnRzCgoqIGBuZXdfYWRtaW5gIC0gVGhlIGFkZHJlc3Mgd2hpY2ggd2lsbCBoZW5jZWZvcnRoIGJlIHRoZSBhZG1pbmlzdHJhdG9yCm9mIHRoaXMgdG9rZW4gY29udHJhY3QuCgojIEV2ZW50cwoKRW1pdHMgYW4gZXZlbnQgd2l0aCB0b3BpY3MgYFsic2V0X2FkbWluIiwgYWRtaW46IEFkZHJlc3NdLCBkYXRhID0KW25ld19hZG1pbjogQWRkcmVzc11gAAAACXNldF9hZG1pbgAAAAAAAAEAAAAAAAAACW5ld19hZG1pbgAAAAAAABMAAAAAAAAAAAAAAEZSZXR1cm5zIHRoZSBhZG1pbiBvZiB0aGUgY29udHJhY3QuCgojIFBhbmljcwoKSWYgdGhlIGFkbWluIGlzIG5vdCBzZXQuAAAAAAAFYWRtaW4AAAAAAAAAAAAAAQAAABMAAAAAAAABUFNldHMgd2hldGhlciB0aGUgYWNjb3VudCBpcyBhdXRob3JpemVkIHRvIHVzZSBpdHMgYmFsYW5jZS4gSWYKYGF1dGhvcml6ZWRgIGlzIHRydWUsIGBpZGAgc2hvdWxkIGJlIGFibGUgdG8gdXNlIGl0cyBiYWxhbmNlLgoKIyBBcmd1bWVudHMKCiogYGlkYCAtIFRoZSBhZGRyZXNzIGJlaW5nIChkZS0pYXV0aG9yaXplZC4KKiBgYXV0aG9yaXplYCAtIFdoZXRoZXIgb3Igbm90IGBpZGAgY2FuIHVzZSBpdHMgYmFsYW5jZS4KCiMgRXZlbnRzCgpFbWl0cyBhbiBldmVudCB3aXRoIHRvcGljcyBgWyJzZXRfYXV0aG9yaXplZCIsIGlkOiBBZGRyZXNzXSwgZGF0YSA9ClthdXRob3JpemU6IGJvb2xdYAAAAA5zZXRfYXV0aG9yaXplZAAAAAAAAgAAAAAAAAACaWQAAAAAABMAAAAAAAAACWF1dGhvcml6ZQAAAAAAAAEAAAAAAAAAAAAAAFtSZXR1cm5zIHRoZSBzeW1ib2wgZm9yIHRoaXMgdG9rZW4uCgojIFBhbmljcwoKSWYgdGhlIGNvbnRyYWN0IGhhcyBub3QgeWV0IGJlZW4gaW5pdGlhbGl6ZWQuAAAAAAZzeW1ib2wAAAAAAAAAAAABAAAAEAAAAAAAAAFiVHJhbnNmZXIgYGFtb3VudGAgZnJvbSBgZnJvbWAgdG8gYHRvYC4KCiMgQXJndW1lbnRzCgoqIGBmcm9tYCAtIFRoZSBhZGRyZXNzIGhvbGRpbmcgdGhlIGJhbGFuY2Ugb2YgdG9rZW5zIHdoaWNoIHdpbGwgYmUKd2l0aGRyYXduIGZyb20uCiogYHRvYCAtIFRoZSBhZGRyZXNzIHdoaWNoIHdpbGwgcmVjZWl2ZSB0aGUgdHJhbnNmZXJyZWQgdG9rZW5zLgoqIGBhbW91bnRgIC0gVGhlIGFtb3VudCBvZiB0b2tlbnMgdG8gYmUgdHJhbnNmZXJyZWQuCgojIEV2ZW50cwoKRW1pdHMgYW4gZXZlbnQgd2l0aCB0b3BpY3MgYFsidHJhbnNmZXIiLCBmcm9tOiBBZGRyZXNzLCB0bzogQWRkcmVzc10sCmRhdGEgPSBhbW91bnQ6IGkxMjhgAAAAAAAIdHJhbnNmZXIAAAADAAAAAAAAAARmcm9tAAAAEwAAAAAAAAACdG8AAAAAABMAAAAAAAAABmFtb3VudAAAAAAACwAAAAAAAAAAAAADMVRyYW5zZmVyIGBhbW91bnRgIGZyb20gYGZyb21gIHRvIGB0b2AsIGNvbnN1bWluZyB0aGUgYWxsb3dhbmNlIHRoYXQKYHNwZW5kZXJgIGhhcyBvbiBgZnJvbWAncyBiYWxhbmNlLiBBdXRob3JpemVkIGJ5IHNwZW5kZXIKKGBzcGVuZGVyLnJlcXVpcmVfYXV0aCgpYCkuCgpUaGUgc3BlbmRlciB3aWxsIGJlIGFsbG93ZWQgdG8gdHJhbnNmZXIgdGhlIGFtb3VudCBmcm9tIGZyb20ncyBiYWxhbmNlCmlmIHRoZSBhbW91bnQgaXMgbGVzcyB0aGFuIG9yIGVxdWFsIHRvIHRoZSBhbGxvd2FuY2UgdGhhdCB0aGUgc3BlbmRlcgpoYXMgb24gdGhlIGZyb20ncyBiYWxhbmNlLiBUaGUgc3BlbmRlcidzIGFsbG93YW5jZSBvbiBmcm9tJ3MgYmFsYW5jZQp3aWxsIGJlIHJlZHVjZWQgYnkgdGhlIGFtb3VudC4KCiMgQXJndW1lbnRzCgoqIGBzcGVuZGVyYCAtIFRoZSBhZGRyZXNzIGF1dGhvcml6aW5nIHRoZSB0cmFuc2ZlciwgYW5kIGhhdmluZyBpdHMKYWxsb3dhbmNlIGNvbnN1bWVkIGR1cmluZyB0aGUgdHJhbnNmZXIuCiogYGZyb21gIC0gVGhlIGFkZHJlc3MgaG9sZGluZyB0aGUgYmFsYW5jZSBvZiB0b2tlbnMgd2hpY2ggd2lsbCBiZQp3aXRoZHJhd24gZnJvbS4KKiBgdG9gIC0gVGhlIGFkZHJlc3Mgd2hpY2ggd2lsbCByZWNlaXZlIHRoZSB0cmFuc2ZlcnJlZCB0b2tlbnMuCiogYGFtb3VudGAgLSBUaGUgYW1vdW50IG9mIHRva2VucyB0byBiZSB0cmFuc2ZlcnJlZC4KCiMgRXZlbnRzCgpFbWl0cyBhbiBldmVudCB3aXRoIHRvcGljcyBgWyJ0cmFuc2ZlciIsIGZyb206IEFkZHJlc3MsIHRvOiBBZGRyZXNzXSwKZGF0YSA9IGFtb3VudDogaTEyOGAAAAAAAAANdHJhbnNmZXJfZnJvbQAAAAAAAAQAAAAAAAAAB3NwZW5kZXIAAAAAEwAAAAAAAAAEZnJvbQAAABMAAAAAAAAAAnRvAAAAAAATAAAAAAAAAAZhbW91bnQAAAAAAAsAAAAA"
    unpacker = xdrlib3.Unpacker(base64.b64decode(raw_xdr))
    specs = []
    while unpacker.get_position() < len(base64.b64decode(raw_xdr)):
        specs.append(xdr.SCSpecEntry.unpack(unpacker))
    return specs

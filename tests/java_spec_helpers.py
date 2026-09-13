"""Builders for the spec entries the Java generator tests feed it.

Every builder takes plain Python values and returns the XDR object the
generator reads, so a test can describe a contract in a few lines instead of
spelling out the constructors of the XDR types.
"""

from stellar_sdk import xdr

TOPIC = xdr.SCSpecEventParamLocationV0.SC_SPEC_EVENT_PARAM_LOCATION_TOPIC_LIST
DATA = xdr.SCSpecEventParamLocationV0.SC_SPEC_EVENT_PARAM_LOCATION_DATA
SINGLE = xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_SINGLE_VALUE
VEC_FORMAT = xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_VEC
MAP_FORMAT = xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_MAP


def scalar(t: xdr.SCSpecType) -> xdr.SCSpecTypeDef:
    return xdr.SCSpecTypeDef(t)


def u32() -> xdr.SCSpecTypeDef:
    return scalar(xdr.SCSpecType.SC_SPEC_TYPE_U32)


def i128() -> xdr.SCSpecTypeDef:
    return scalar(xdr.SCSpecType.SC_SPEC_TYPE_I128)


def address() -> xdr.SCSpecTypeDef:
    return scalar(xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS)


def error() -> xdr.SCSpecTypeDef:
    return scalar(xdr.SCSpecType.SC_SPEC_TYPE_ERROR)


def void() -> xdr.SCSpecTypeDef:
    return scalar(xdr.SCSpecType.SC_SPEC_TYPE_VOID)


def bytes_n(n: int) -> xdr.SCSpecTypeDef:
    return xdr.SCSpecTypeDef(
        xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N, bytes_n=xdr.SCSpecTypeBytesN(xdr.Uint32(n))
    )


def udt(name: bytes) -> xdr.SCSpecTypeDef:
    return xdr.SCSpecTypeDef(
        xdr.SCSpecType.SC_SPEC_TYPE_UDT, udt=xdr.SCSpecTypeUDT(name=name)
    )


def vec(inner: xdr.SCSpecTypeDef) -> xdr.SCSpecTypeDef:
    return xdr.SCSpecTypeDef(
        xdr.SCSpecType.SC_SPEC_TYPE_VEC, vec=xdr.SCSpecTypeVec(inner)
    )


def map_of(key: xdr.SCSpecTypeDef, value: xdr.SCSpecTypeDef) -> xdr.SCSpecTypeDef:
    return xdr.SCSpecTypeDef(
        xdr.SCSpecType.SC_SPEC_TYPE_MAP, map=xdr.SCSpecTypeMap(key, value)
    )


def tuple_of(*types: xdr.SCSpecTypeDef) -> xdr.SCSpecTypeDef:
    return xdr.SCSpecTypeDef(
        xdr.SCSpecType.SC_SPEC_TYPE_TUPLE, tuple=xdr.SCSpecTypeTuple(list(types))
    )


def option(inner: xdr.SCSpecTypeDef) -> xdr.SCSpecTypeDef:
    return xdr.SCSpecTypeDef(
        xdr.SCSpecType.SC_SPEC_TYPE_OPTION, option=xdr.SCSpecTypeOption(inner)
    )


def result(ok: xdr.SCSpecTypeDef, err: xdr.SCSpecTypeDef) -> xdr.SCSpecTypeDef:
    return xdr.SCSpecTypeDef(
        xdr.SCSpecType.SC_SPEC_TYPE_RESULT,
        result=xdr.SCSpecTypeResult(ok_type=ok, error_type=err),
    )


def struct(name: bytes, fields: list, doc: bytes = b"") -> xdr.SCSpecEntry:
    """``fields`` holds (name, type) or (name, type, doc) tuples."""
    return xdr.SCSpecEntry(
        xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0,
        udt_struct_v0=xdr.SCSpecUDTStructV0(
            doc=doc,
            lib=b"",
            name=name,
            fields=[
                xdr.SCSpecUDTStructFieldV0(
                    doc=f[2] if len(f) > 2 else b"", name=f[0], type=f[1]
                )
                for f in fields
            ],
        ),
    )


def enum(name: bytes, cases: list, doc: bytes = b"") -> xdr.SCSpecEntry:
    return xdr.SCSpecEntry(
        xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ENUM_V0,
        udt_enum_v0=xdr.SCSpecUDTEnumV0(
            doc=doc,
            lib=b"",
            name=name,
            cases=[
                xdr.SCSpecUDTEnumCaseV0(doc=b"", name=n, value=xdr.Uint32(v))
                for n, v in cases
            ],
        ),
    )


def error_enum(name: bytes, cases: list, doc: bytes = b"") -> xdr.SCSpecEntry:
    return xdr.SCSpecEntry(
        xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ERROR_ENUM_V0,
        udt_error_enum_v0=xdr.SCSpecUDTErrorEnumV0(
            doc=doc,
            lib=b"",
            name=name,
            cases=[
                xdr.SCSpecUDTErrorEnumCaseV0(doc=b"", name=n, value=xdr.Uint32(v))
                for n, v in cases
            ],
        ),
    )


def void_case(name: bytes, doc: bytes = b"") -> xdr.SCSpecUDTUnionCaseV0:
    return xdr.SCSpecUDTUnionCaseV0(
        xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0,
        void_case=xdr.SCSpecUDTUnionCaseVoidV0(doc=doc, name=name),
    )


def tuple_case(name: bytes, *types: xdr.SCSpecTypeDef) -> xdr.SCSpecUDTUnionCaseV0:
    return xdr.SCSpecUDTUnionCaseV0(
        xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_TUPLE_V0,
        tuple_case=xdr.SCSpecUDTUnionCaseTupleV0(doc=b"", name=name, type=list(types)),
    )


def union(name: bytes, cases: list, doc: bytes = b"") -> xdr.SCSpecEntry:
    return xdr.SCSpecEntry(
        xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_UNION_V0,
        udt_union_v0=xdr.SCSpecUDTUnionV0(doc=doc, lib=b"", name=name, cases=cases),
    )


def function(
    name: bytes, inputs: list, outputs: list, doc: bytes = b""
) -> xdr.SCSpecEntry:
    """``inputs`` holds (name, type) or (name, type, doc) tuples."""
    return xdr.SCSpecEntry(
        xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0,
        function_v0=xdr.SCSpecFunctionV0(
            doc=doc,
            name=xdr.SCSymbol(name),
            inputs=[
                xdr.SCSpecFunctionInputV0(
                    doc=p[2] if len(p) > 2 else b"", name=p[0], type=p[1]
                )
                for p in inputs
            ],
            outputs=outputs,
        ),
    )


def event(
    name: bytes,
    prefixes: list,
    params: list,
    data_format: xdr.SCSpecEventDataFormat = SINGLE,
    doc: bytes = b"",
) -> xdr.SCSpecEntry:
    """``params`` holds (name, type, location) tuples."""
    return xdr.SCSpecEntry(
        xdr.SCSpecEntryKind.SC_SPEC_ENTRY_EVENT_V0,
        event_v0=xdr.SCSpecEventV0(
            doc=doc,
            lib=b"",
            name=xdr.SCSymbol(name),
            prefix_topics=[xdr.SCSymbol(p) for p in prefixes],
            params=[
                xdr.SCSpecEventParamV0(doc=b"", name=n, type=t, location=loc)
                for n, t, loc in params
            ],
            data_format=data_format,
        ),
    )

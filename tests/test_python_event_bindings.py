import ast
import logging
from pathlib import Path

import black
import pytest
from click.testing import CliRunner
from stellar_sdk import Address, scval, xdr
from stellar_sdk.soroban_rpc import EventInfo

from stellar_contract_bindings.metadata import get_token_sc_spec_entry
from stellar_contract_bindings.python import (
    _GENERATED_MODULE_NAMES,
    command,
    event_class_name,
    generate_binding,
    generate_binding_with_diagnostics,
    render_event_helpers,
    render_imports,
    render_scval_helpers,
)

FROM_ADDRESS = "GBMBVAHBE6D4AJXJJVTBQTVU4G7SN4FEIJOL5YTOHZ4WCUMKQ52ANL2B"
TO_ADDRESS = "GAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAWHF"
CONTRACT_ID = "CBUZJXHZ6PBS2YR3SEJZ3CIGMQBYP6367D3KQAR2NB3U2I5AOWLC4DU2"


def _type(t: xdr.SCSpecType) -> xdr.SCSpecTypeDef:
    return xdr.SCSpecTypeDef(t)


def _vec_type(element_type: xdr.SCSpecTypeDef) -> xdr.SCSpecTypeDef:
    td = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_VEC)
    td.vec = xdr.SCSpecTypeVec(element_type)
    return td


def _udt_type(name: bytes) -> xdr.SCSpecTypeDef:
    return xdr.SCSpecTypeDef(
        xdr.SCSpecType.SC_SPEC_TYPE_UDT,
        udt=xdr.SCSpecTypeUDT(name=name),
    )


def _option_type(value_type: xdr.SCSpecTypeDef) -> xdr.SCSpecTypeDef:
    return xdr.SCSpecTypeDef(
        xdr.SCSpecType.SC_SPEC_TYPE_OPTION,
        option=xdr.SCSpecTypeOption(value_type=value_type),
    )


def _result_type(
    ok_type: xdr.SCSpecTypeDef, error_type: xdr.SCSpecTypeDef
) -> xdr.SCSpecTypeDef:
    return xdr.SCSpecTypeDef(
        xdr.SCSpecType.SC_SPEC_TYPE_RESULT,
        result=xdr.SCSpecTypeResult(ok_type=ok_type, error_type=error_type),
    )


def _contract_error(code: int) -> xdr.SCVal:
    return xdr.SCVal(
        xdr.SCValType.SCV_ERROR,
        error=xdr.SCError(
            xdr.SCErrorType.SCE_CONTRACT,
            contract_code=xdr.Uint32(code),
        ),
    )


def _struct(name: bytes, field_type: xdr.SCSpecTypeDef) -> xdr.SCSpecEntry:
    return xdr.SCSpecEntry(
        xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0,
        udt_struct_v0=xdr.SCSpecUDTStructV0(
            doc=b"",
            lib=b"",
            name=name,
            fields=[
                xdr.SCSpecUDTStructFieldV0(doc=b"", name=b"value", type=field_type)
            ],
        ),
    )


def _event_param(
    name: bytes,
    td: xdr.SCSpecTypeDef,
    location: xdr.SCSpecEventParamLocationV0,
) -> xdr.SCSpecEventParamV0:
    return xdr.SCSpecEventParamV0(doc=b"", name=name, type=td, location=location)


def _topic_param(name: bytes, td: xdr.SCSpecTypeDef) -> xdr.SCSpecEventParamV0:
    return _event_param(
        name,
        td,
        xdr.SCSpecEventParamLocationV0.SC_SPEC_EVENT_PARAM_LOCATION_TOPIC_LIST,
    )


def _data_param(name: bytes, td: xdr.SCSpecTypeDef) -> xdr.SCSpecEventParamV0:
    return _event_param(
        name, td, xdr.SCSpecEventParamLocationV0.SC_SPEC_EVENT_PARAM_LOCATION_DATA
    )


def _event(
    name: bytes,
    prefix_topics: list[bytes],
    params: list[xdr.SCSpecEventParamV0],
    data_format: xdr.SCSpecEventDataFormat,
) -> xdr.SCSpecEntry:
    entry = xdr.SCSpecEntry(xdr.SCSpecEntryKind.SC_SPEC_ENTRY_EVENT_V0)
    entry.event_v0 = xdr.SCSpecEventV0(
        doc=b"",
        lib=b"",
        name=xdr.SCSymbol(sc_symbol=name),
        prefix_topics=[xdr.SCSymbol(sc_symbol=t) for t in prefix_topics],
        params=params,
        data_format=data_format,
    )
    return entry


def _contract_event(topics: list[xdr.SCVal], data: xdr.SCVal) -> xdr.ContractEvent:
    return xdr.ContractEvent(
        ext=xdr.ExtensionPoint(0),
        contract_id=xdr.ContractID(
            xdr.Hash(Address(CONTRACT_ID).key),
        ),
        type=xdr.ContractEventType.CONTRACT,
        body=xdr.ContractEventBody(0, v0=xdr.ContractEventV0(topics=topics, data=data)),
    )


def _event_info(topics: list[str], value: str) -> EventInfo:
    """Build an RPC getEvents entry, whose topics/value are base64 XDR."""
    return EventInfo.model_validate(
        {
            "type": "contract",
            "ledger": 1,
            "ledgerClosedAt": "2026-07-21T00:00:00Z",
            "contractId": CONTRACT_ID,
            "id": "0000000001-0000000000",
            "topic": topics,
            "value": value,
            "inSuccessfulContractCall": True,
            "operationIndex": 0,
            "transactionIndex": 0,
            "txHash": "a" * 64,
        }
    )


def _top_level_bindings(tree: ast.Module) -> set[str]:
    """Names bound at module scope in generated source."""
    bindings = set()
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            bindings.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bindings.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.Assign):
            bindings.update(
                target.id for target in node.targets if isinstance(target, ast.Name)
            )
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            bindings.add(node.target.id)
    return bindings


def _load_bindings(specs: list[xdr.SCSpecEntry]) -> dict:
    code = generate_binding(specs, client_type="none")
    code = black.format_str(code, mode=black.Mode())
    namespace: dict = {}
    exec(compile(code, "bindings.py", "exec"), namespace)
    return namespace


class TestEventClassName:
    def test_snake_case(self):
        assert event_class_name("approve") == "ApproveEvent"
        assert event_class_name("set_admin") == "SetAdminEvent"

    def test_pascal_case(self):
        assert event_class_name("Transfer") == "TransferEvent"
        assert event_class_name("TransferWithMuxedString") == (
            "TransferWithMuxedStringEvent"
        )

    def test_existing_suffix_not_duplicated(self):
        assert event_class_name("TransferEvent") == "TransferEvent"
        assert event_class_name("transfer_event") == "TransferEvent"


class TestSingleValueFormat:
    def setup_method(self):
        specs = [
            _event(
                b"approve",
                [b"approve"],
                [
                    _topic_param(b"from", _type(xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS)),
                    _data_param(b"amount", _type(xdr.SCSpecType.SC_SPEC_TYPE_I128)),
                ],
                xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_SINGLE_VALUE,
            )
        ]
        self.ns = _load_bindings(specs)

    def test_parse(self):
        event = _contract_event(
            [scval.to_symbol("approve"), scval.to_address(FROM_ADDRESS)],
            scval.to_int128(10000),
        )
        parsed = self.ns["ApproveEvent"].parse(event)
        assert parsed.from_ == Address(FROM_ADDRESS)
        assert parsed.amount == 10000

    def test_matches_rejects_wrong_prefix(self):
        event = _contract_event(
            [scval.to_symbol("transfer"), scval.to_address(FROM_ADDRESS)],
            scval.to_int128(10000),
        )
        assert not self.ns["ApproveEvent"].matches(event)

    def test_matches_rejects_missing_topics(self):
        event = _contract_event([scval.to_symbol("approve")], scval.to_int128(10000))
        assert not self.ns["ApproveEvent"].matches(event)

    def test_extra_trailing_topics_ignored(self):
        # On-chain events may carry topics beyond the SEP-48 declaration,
        # e.g. SAC events append the SEP-11 asset string.
        event = _contract_event(
            [
                scval.to_symbol("approve"),
                scval.to_address(FROM_ADDRESS),
                scval.to_string("native"),
            ],
            scval.to_int128(10000),
        )
        parsed = self.ns["ApproveEvent"].parse(event)
        assert parsed.from_ == Address(FROM_ADDRESS)
        assert parsed.amount == 10000

    def test_parse_raises_on_mismatch(self):
        event = _contract_event([scval.to_symbol("other")], scval.to_void())
        with pytest.raises(ValueError, match="does not match ApproveEvent"):
            self.ns["ApproveEvent"].parse(event)

    def test_equality_and_hash(self):
        event = _contract_event(
            [scval.to_symbol("approve"), scval.to_address(FROM_ADDRESS)],
            scval.to_int128(10000),
        )
        a = self.ns["ApproveEvent"].parse(event)
        b = self.ns["ApproveEvent"].parse(event)
        assert a == b
        assert hash(a) == hash(b)

    def test_typed_topic_filter(self):
        wildcard = self.ns["ApproveEvent"].topic_filter()
        assert wildcard == [scval.to_symbol("approve").to_xdr(), "*", "**"]

        exact = self.ns["ApproveEvent"].topic_filter(from_=FROM_ADDRESS)
        assert exact == [
            scval.to_symbol("approve").to_xdr(),
            scval.to_address(FROM_ADDRESS).to_xdr(),
            "**",
        ]

    def test_parse_raw_scvals(self):
        parsed = self.ns["parse_event"](
            (
                [scval.to_symbol("approve"), scval.to_address(FROM_ADDRESS)],
                scval.to_int128(10000),
            )
        )
        assert isinstance(parsed, self.ns["ApproveEvent"])
        assert parsed.from_ == Address(FROM_ADDRESS)
        assert parsed.amount == 10000

    def test_parse_raw_base64_xdr(self):
        raw_event = (
            [
                scval.to_symbol("approve").to_xdr(),
                scval.to_address(FROM_ADDRESS).to_xdr(),
            ],
            scval.to_int128(10000).to_xdr(),
        )
        parsed = self.ns["ApproveEvent"].parse(raw_event)
        assert parsed.from_ == Address(FROM_ADDRESS)
        assert parsed.amount == 10000

    def test_parse_raw_binary_xdr(self):
        raw_event = (
            [
                scval.to_symbol("approve").to_xdr_bytes(),
                scval.to_address(FROM_ADDRESS).to_xdr_bytes(),
            ],
            scval.to_int128(10000).to_xdr_bytes(),
        )
        parsed = self.ns["ApproveEvent"].parse(raw_event)
        assert parsed.from_ == Address(FROM_ADDRESS)
        assert parsed.amount == 10000

    def test_malformed_raw_xdr_returns_none(self):
        assert self.ns["parse_event"]((["not base64 xdr"], "also invalid")) is None


class TestVecFormat:
    def setup_method(self):
        specs = [
            _event(
                b"swap",
                [b"swap"],
                [
                    _data_param(b"amount_in", _type(xdr.SCSpecType.SC_SPEC_TYPE_I128)),
                    _data_param(b"amount_out", _type(xdr.SCSpecType.SC_SPEC_TYPE_I128)),
                ],
                xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_VEC,
            )
        ]
        self.ns = _load_bindings(specs)

    def test_parse(self):
        event = _contract_event(
            [scval.to_symbol("swap")],
            scval.to_vec([scval.to_int128(5), scval.to_int128(7)]),
        )
        parsed = self.ns["SwapEvent"].parse(event)
        assert parsed.amount_in == 5
        assert parsed.amount_out == 7


class TestMapFormat:
    def setup_method(self):
        specs = [
            _event(
                b"transfer",
                [b"transfer"],
                [
                    _topic_param(b"from", _type(xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS)),
                    _topic_param(b"to", _type(xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS)),
                    _data_param(b"amount", _type(xdr.SCSpecType.SC_SPEC_TYPE_I128)),
                ],
                xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_MAP,
            )
        ]
        self.ns = _load_bindings(specs)

    def test_parse(self):
        event = _contract_event(
            [
                scval.to_symbol("transfer"),
                scval.to_address(FROM_ADDRESS),
                scval.to_address(TO_ADDRESS),
            ],
            scval.to_struct({"amount": scval.to_int128(42)}),
        )
        parsed = self.ns["TransferEvent"].parse(event)
        assert parsed.from_ == Address(FROM_ADDRESS)
        assert parsed.to == Address(TO_ADDRESS)
        assert parsed.amount == 42

    def test_missing_required_map_entry_is_rejected(self):
        # ``amount`` is declared without an option wrapper, so an event that
        # omits it does not satisfy the declaration and must not parse into a
        # TransferEvent with amount=None.
        event = _contract_event(
            [
                scval.to_symbol("transfer"),
                scval.to_address(FROM_ADDRESS),
                scval.to_address(TO_ADDRESS),
            ],
            scval.to_struct({}),
        )
        with pytest.raises(ValueError, match="missing required entries"):
            self.ns["TransferEvent"].parse(event)

    def test_extra_map_entry_is_ignored(self):
        event = _contract_event(
            [
                scval.to_symbol("transfer"),
                scval.to_address(FROM_ADDRESS),
                scval.to_address(TO_ADDRESS),
            ],
            scval.to_struct(
                {"amount": scval.to_int128(42), "future_field": scval.to_uint32(1)}
            ),
        )
        assert self.ns["TransferEvent"].parse(event).amount == 42

    def test_absent_optional_map_entry_is_none(self):
        specs = [
            _event(
                b"tagged",
                [b"tagged"],
                [
                    _data_param(b"amount", _type(xdr.SCSpecType.SC_SPEC_TYPE_I128)),
                    _data_param(
                        b"memo", _option_type(_type(xdr.SCSpecType.SC_SPEC_TYPE_U32))
                    ),
                ],
                xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_MAP,
            )
        ]
        ns = _load_bindings(specs)
        event = _contract_event(
            [scval.to_symbol("tagged")],
            scval.to_struct({"amount": scval.to_int128(42)}),
        )
        parsed = ns["TaggedEvent"].parse(event)
        assert parsed.amount == 42
        assert parsed.memo is None


class TestNoParams:
    def setup_method(self):
        specs = [
            _event(
                b"paused",
                [b"paused"],
                [],
                xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_SINGLE_VALUE,
            )
        ]
        self.ns = _load_bindings(specs)

    def test_parse(self):
        event = _contract_event([scval.to_symbol("paused")], scval.to_void())
        parsed = self.ns["PausedEvent"].parse(event)
        assert parsed == self.ns["PausedEvent"]()

    def test_non_void_data_is_rejected(self):
        event = _contract_event([scval.to_symbol("paused")], scval.to_uint32(1))
        with pytest.raises(ValueError):
            self.ns["PausedEvent"].parse(event)

    def test_topic_filter_contains_only_static_prefixes(self):
        assert self.ns["PausedEvent"].topic_filter() == [
            scval.to_symbol("paused").to_xdr(),
            "**",
        ]


class TestResultAndErrorTypes:
    def test_generic_error_event_param_round_trips(self):
        specs = [
            _event(
                b"failed",
                [b"failed"],
                [_data_param(b"error", _type(xdr.SCSpecType.SC_SPEC_TYPE_ERROR))],
                xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_SINGLE_VALUE,
            )
        ]
        ns = _load_bindings(specs)
        raw_error = _contract_error(7)
        parsed = ns["FailedEvent"].parse(
            _contract_event([scval.to_symbol("failed")], raw_error)
        )
        assert parsed.error == raw_error.error

    def test_result_with_generic_error_parses_both_arms(self):
        result_type = _result_type(
            _type(xdr.SCSpecType.SC_SPEC_TYPE_U32),
            _type(xdr.SCSpecType.SC_SPEC_TYPE_ERROR),
        )
        specs = [
            _event(
                b"outcome",
                [b"outcome"],
                [_data_param(b"result", result_type)],
                xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_SINGLE_VALUE,
            )
        ]
        ns = _load_bindings(specs)

        ok = ns["OutcomeEvent"].parse(
            _contract_event([scval.to_symbol("outcome")], scval.to_uint32(3))
        )
        assert ok.result == 3

        raw_error = _contract_error(9)
        failed = ns["OutcomeEvent"].parse(
            _contract_event([scval.to_symbol("outcome")], raw_error)
        )
        assert failed.result == raw_error.error

    def test_result_with_generic_error_builds_topic_filters(self):
        result_type = _result_type(
            _type(xdr.SCSpecType.SC_SPEC_TYPE_U32),
            _type(xdr.SCSpecType.SC_SPEC_TYPE_ERROR),
        )
        ns = _load_bindings(
            [
                _event(
                    b"outcome",
                    [b"outcome"],
                    [_topic_param(b"result", result_type)],
                    xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_SINGLE_VALUE,
                )
            ]
        )
        raw_error = _contract_error(9)
        assert (
            ns["OutcomeEvent"].topic_filter(result=3)[1] == scval.to_uint32(3).to_xdr()
        )
        assert (
            ns["OutcomeEvent"].topic_filter(result=raw_error.error)[1]
            == raw_error.to_xdr()
        )

    def test_result_with_error_enum_supports_topic_filters(self):
        error_entry = xdr.SCSpecEntry(
            xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ERROR_ENUM_V0,
            udt_error_enum_v0=xdr.SCSpecUDTErrorEnumV0(
                doc=b"",
                lib=b"",
                name=b"ContractError",
                cases=[
                    xdr.SCSpecUDTErrorEnumCaseV0(
                        doc=b"", name=b"Denied", value=xdr.Uint32(4)
                    )
                ],
            ),
        )
        result_type = _result_type(
            _type(xdr.SCSpecType.SC_SPEC_TYPE_U32),
            _udt_type(b"ContractError"),
        )
        specs = [
            error_entry,
            _event(
                b"outcome",
                [b"outcome"],
                [_topic_param(b"result", result_type)],
                xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_SINGLE_VALUE,
            ),
        ]
        ns = _load_bindings(specs)
        expected_error = _contract_error(4)
        assert ns["OutcomeEvent"].topic_filter(result=ns["ContractError"].Denied) == [
            scval.to_symbol("outcome").to_xdr(),
            expected_error.to_xdr(),
            "**",
        ]

        parsed = ns["OutcomeEvent"].parse(
            _contract_event(
                [scval.to_symbol("outcome"), expected_error], scval.to_void()
            )
        )
        assert parsed.result is ns["ContractError"].Denied


class TestFunctionResultOutputs:
    """A function's ``Result<T, E>`` return arrives as T; ``Err`` traps the
    invocation instead of being handed back as an SCV_ERROR value."""

    def _client(self, output: xdr.SCSpecTypeDef) -> str:
        fn = xdr.SCSpecEntry(
            xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0,
            function_v0=xdr.SCSpecFunctionV0(
                doc=b"",
                name=xdr.SCSymbol(sc_symbol=b"probe"),
                inputs=[],
                outputs=[output],
            ),
        )
        return generate_binding([fn], client_type="sync")

    def test_top_level_result_exposes_only_ok_type(self):
        code = self._client(
            _result_type(
                _type(xdr.SCSpecType.SC_SPEC_TYPE_U32),
                _type(xdr.SCSpecType.SC_SPEC_TYPE_ERROR),
            )
        )
        assert "AssembledTransaction[int]" in code
        assert "parse_result_xdr_fn=lambda v: scval.from_uint32(v)" in code
        invoke_line = next(line for line in code.splitlines() if "self.invoke(" in line)
        assert "SCV_ERROR" not in invoke_line

    def test_nested_result_keeps_both_arms(self):
        code = self._client(
            _vec_type(
                _result_type(
                    _type(xdr.SCSpecType.SC_SPEC_TYPE_U32),
                    _type(xdr.SCSpecType.SC_SPEC_TYPE_ERROR),
                )
            )
        )
        assert "AssembledTransaction[List[Union[int, xdr.SCError]]]" in code
        assert "SCV_ERROR" in code


class TestParseEventDispatcher:
    def setup_method(self):
        specs = [
            _event(
                b"approve",
                [b"approve"],
                [
                    _topic_param(b"from", _type(xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS)),
                    _data_param(b"amount", _type(xdr.SCSpecType.SC_SPEC_TYPE_I128)),
                ],
                xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_SINGLE_VALUE,
            ),
            # Same topic shape as the next event; disambiguated by data type.
            _event(
                b"deposit_i128",
                [b"deposit"],
                [_data_param(b"amount", _type(xdr.SCSpecType.SC_SPEC_TYPE_I128))],
                xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_SINGLE_VALUE,
            ),
            _event(
                b"deposit_str",
                [b"deposit"],
                [_data_param(b"memo", _type(xdr.SCSpecType.SC_SPEC_TYPE_STRING))],
                xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_SINGLE_VALUE,
            ),
        ]
        self.ns = _load_bindings(specs)

    def test_dispatch(self):
        event = _contract_event(
            [scval.to_symbol("approve"), scval.to_address(FROM_ADDRESS)],
            scval.to_int128(10000),
        )
        parsed = self.ns["parse_event"](event)
        assert isinstance(parsed, self.ns["ApproveEvent"])

    def test_dispatch_disambiguates_by_data(self):
        i128_event = _contract_event(
            [scval.to_symbol("deposit")], scval.to_int128(10000)
        )
        str_event = _contract_event(
            [scval.to_symbol("deposit")], scval.to_string("hello")
        )
        assert isinstance(
            self.ns["parse_event"](i128_event), self.ns["DepositI128Event"]
        )
        assert isinstance(self.ns["parse_event"](str_event), self.ns["DepositStrEvent"])

    def test_dispatch_unknown_event_returns_none(self, caplog):
        event = _contract_event([scval.to_symbol("unknown")], scval.to_void())
        with caplog.at_level(logging.WARNING):
            assert self.ns["parse_event"](event) is None
        # A genuinely undeclared event is not an error condition.
        assert not caplog.records

    def test_dispatch_success_after_intermediate_failure_is_silent(self, caplog):
        # deposit_i128 fails on string data before deposit_str succeeds;
        # that intermediate failure is normal disambiguation, not a problem.
        event = _contract_event([scval.to_symbol("deposit")], scval.to_string("hello"))
        with caplog.at_level(logging.WARNING):
            parsed = self.ns["parse_event"](event)
        assert isinstance(parsed, self.ns["DepositStrEvent"])
        assert not caplog.records

    def test_dispatch_matched_but_unparseable_logs_warning(self, caplog):
        # Topics match ApproveEvent, but the data is a bool instead of the
        # declared i128 — e.g. the contract's event format drifted.
        event = _contract_event(
            [scval.to_symbol("approve"), scval.to_address(FROM_ADDRESS)],
            scval.to_bool(True),
        )
        with caplog.at_level(logging.WARNING):
            assert self.ns["parse_event"](event) is None
        assert len(caplog.records) == 1
        assert "ApproveEvent" in caplog.records[0].message
        assert "drifted" in caplog.records[0].message

    def test_dispatch_matched_but_unparseable_raises_when_requested(self):
        event = _contract_event(
            [scval.to_symbol("approve"), scval.to_address(FROM_ADDRESS)],
            scval.to_bool(True),
        )
        with pytest.raises(self.ns["UnparsedEventError"]) as exc_info:
            self.ns["parse_event"](event, raise_on_unparsed=True)
        failures = exc_info.value.failures
        assert len(failures) == 1
        assert failures[0][0] is self.ns["ApproveEvent"]
        assert isinstance(failures[0][1], ValueError)
        assert exc_info.value.__cause__ is failures[0][1]

    def test_event_info_values_are_decoded_once(self):
        # parse_event normalizes up front so candidates share one decode;
        # otherwise every candidate re-decodes the base64 topics before
        # rejecting them.
        decoded = []
        coerce = self.ns["_coerce_event_scval"]

        def counting_coerce(value):
            if not isinstance(value, xdr.SCVal):
                decoded.append(value)
            return coerce(value)

        self.ns["_coerce_event_scval"] = counting_coerce
        try:
            info = _event_info(
                [
                    scval.to_symbol("approve").to_xdr(),
                    scval.to_address(FROM_ADDRESS).to_xdr(),
                ],
                scval.to_int128(10000).to_xdr(),
            )
            assert isinstance(self.ns["parse_event"](info), self.ns["ApproveEvent"])
        finally:
            self.ns["_coerce_event_scval"] = coerce
        assert len(decoded) == 3  # 2 topics + 1 data value, each decoded once

    def test_dispatch_event_info(self):
        event_info = _event_info(
            [
                scval.to_symbol("approve").to_xdr(),
                scval.to_address(FROM_ADDRESS).to_xdr(),
            ],
            scval.to_int128(10000).to_xdr(),
        )
        parsed = self.ns["parse_event"](event_info)
        assert isinstance(parsed, self.ns["ApproveEvent"])
        assert parsed.amount == 10000

    def test_malformed_event_info_does_not_escape_decoder_errors(self):
        assert self.ns["parse_event"](_event_info(["AAAA"], "AAAA")) is None

    def test_dispatch_continues_after_assertion_error(self):
        event = _contract_event([scval.to_symbol("deposit")], scval.to_string("ok"))

        def fail_with_assertion(cls, event):
            raise AssertionError("invalid UDT union payload")

        self.ns["DepositI128Event"].parse = classmethod(fail_with_assertion)
        parsed = self.ns["parse_event"](event)
        assert isinstance(parsed, self.ns["DepositStrEvent"])


class TestStringPrefixTopics:
    """SEP-48: parsers should tolerate static topics being SCV_SYMBOL or SCV_STRING."""

    def setup_method(self):
        specs = [
            _event(
                b"approve",
                [b"approve"],
                [
                    _topic_param(b"from", _type(xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS)),
                    _data_param(b"amount", _type(xdr.SCSpecType.SC_SPEC_TYPE_I128)),
                ],
                xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_SINGLE_VALUE,
            )
        ]
        self.ns = _load_bindings(specs)

    def test_string_prefix_topic_matches(self):
        event = _contract_event(
            [scval.to_string("approve"), scval.to_address(FROM_ADDRESS)],
            scval.to_int128(10000),
        )
        parsed = self.ns["ApproveEvent"].parse(event)
        assert parsed.amount == 10000

    def test_non_symbol_non_string_prefix_rejected(self):
        event = _contract_event(
            [scval.to_uint32(1), scval.to_address(FROM_ADDRESS)],
            scval.to_int128(10000),
        )
        assert not self.ns["ApproveEvent"].matches(event)


class TestSpecificityOrdering:
    """A shorter declaration sharing a prefix must not swallow events of a
    longer declaration via the extra-trailing-topics tolerance."""

    def setup_method(self):
        specs = [
            # Declared shorter event first in spec order on purpose.
            _event(
                b"foo_short",
                [b"foo"],
                [
                    _topic_param(b"addr", _type(xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS)),
                    _data_param(b"amount", _type(xdr.SCSpecType.SC_SPEC_TYPE_I128)),
                ],
                xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_SINGLE_VALUE,
            ),
            _event(
                b"foo_long",
                [b"foo"],
                [
                    _topic_param(b"addr", _type(xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS)),
                    _topic_param(b"index", _type(xdr.SCSpecType.SC_SPEC_TYPE_U32)),
                    _data_param(b"amount", _type(xdr.SCSpecType.SC_SPEC_TYPE_I128)),
                ],
                xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_SINGLE_VALUE,
            ),
        ]
        self.ns = _load_bindings(specs)

    def test_longer_event_wins_over_shorter_declaration(self):
        event = _contract_event(
            [
                scval.to_symbol("foo"),
                scval.to_address(FROM_ADDRESS),
                scval.to_uint32(7),
            ],
            scval.to_int128(10000),
        )
        parsed = self.ns["parse_event"](event)
        assert isinstance(parsed, self.ns["FooLongEvent"])
        assert parsed.index == 7

    def test_shorter_event_still_parses(self):
        event = _contract_event(
            [scval.to_symbol("foo"), scval.to_address(FROM_ADDRESS)],
            scval.to_int128(10000),
        )
        parsed = self.ns["parse_event"](event)
        assert isinstance(parsed, self.ns["FooShortEvent"])


class TestClassNameCollisions:
    def test_event_named_event_does_not_overwrite_union_alias(self):
        specs = [
            _event(
                b"event",
                [b"event"],
                [_data_param(b"value", _type(xdr.SCSpecType.SC_SPEC_TYPE_U32))],
                xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_SINGLE_VALUE,
            )
        ]
        ns = _load_bindings(specs)
        event = _contract_event([scval.to_symbol("event")], scval.to_uint32(7))
        parsed = ns["parse_event"](event)
        assert isinstance(ns["Event_"], type)
        assert isinstance(parsed, ns["Event_"])
        assert parsed.value == 7

    def test_udt_named_event_is_not_overwritten_by_union_alias(self):
        struct_entry = xdr.SCSpecEntry(xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0)
        struct_entry.udt_struct_v0 = xdr.SCSpecUDTStructV0(
            doc=b"",
            lib=b"",
            name=b"Event",
            fields=[
                xdr.SCSpecUDTStructFieldV0(
                    doc=b"",
                    name=b"value",
                    type=_type(xdr.SCSpecType.SC_SPEC_TYPE_U32),
                )
            ],
        )
        specs = [
            struct_entry,
            _event(
                b"foo",
                [b"foo"],
                [_data_param(b"value", _type(xdr.SCSpecType.SC_SPEC_TYPE_U32))],
                xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_SINGLE_VALUE,
            ),
        ]
        ns = _load_bindings(specs)
        assert hasattr(ns["Event"], "from_scval")
        assert ns["Event_"] == ns["FooEvent"]

    def test_event_names_normalizing_identically(self):
        specs = [
            _event(
                b"foo",
                [b"foo"],
                [_data_param(b"a", _type(xdr.SCSpecType.SC_SPEC_TYPE_U32))],
                xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_SINGLE_VALUE,
            ),
            _event(
                b"foo_event",
                [b"bar"],
                [_data_param(b"a", _type(xdr.SCSpecType.SC_SPEC_TYPE_U32))],
                xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_SINGLE_VALUE,
            ),
        ]
        ns = _load_bindings(specs)
        assert isinstance(ns["FooEvent"], type)
        assert isinstance(ns["FooEvent_"], type)
        event = _contract_event([scval.to_symbol("bar")], scval.to_uint32(2))
        parsed = ns["parse_event"](event)
        assert isinstance(parsed, ns["FooEvent_"])

        _, diagnostics = generate_binding_with_diagnostics(specs, client_type="none")
        assert diagnostics == [
            "Event binding note: 'foo_event' -> FooEvent_ "
            "(renamed to avoid a generated-name collision)"
        ]

    def test_event_name_colliding_with_udt(self):
        struct_entry = xdr.SCSpecEntry(xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0)
        struct_entry.udt_struct_v0 = xdr.SCSpecUDTStructV0(
            doc=b"",
            lib=b"",
            name=b"FooEvent",
            fields=[
                xdr.SCSpecUDTStructFieldV0(
                    doc=b"",
                    name=b"a",
                    type=_type(xdr.SCSpecType.SC_SPEC_TYPE_U32),
                )
            ],
        )
        udt_type = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_UDT)
        udt_type.udt = xdr.SCSpecTypeUDT(name=b"FooEvent")
        specs = [
            struct_entry,
            _event(
                b"foo",
                [b"foo"],
                [_data_param(b"payload", udt_type)],
                xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_SINGLE_VALUE,
            ),
        ]
        ns = _load_bindings(specs)
        # The UDT keeps its name; the event is renamed out of its way.
        assert hasattr(ns["FooEvent"], "from_scval")
        event = _contract_event(
            [scval.to_symbol("foo")],
            scval.to_struct({"a": scval.to_uint32(5)}),
        )
        parsed = ns["parse_event"](event)
        assert isinstance(parsed, ns["FooEvent_"])
        assert parsed.payload.a == 5


class TestQualifiedUdtNames:
    def test_unambiguous_qualified_udt_uses_its_bare_name(self):
        specs = [
            _struct(b"test_udt::Payload", _type(xdr.SCSpecType.SC_SPEC_TYPE_U32)),
            _event(
                b"changed",
                [b"changed"],
                [_data_param(b"payload", _udt_type(b"test_udt::Payload"))],
                xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_SINGLE_VALUE,
            ),
        ]
        ns = _load_bindings(specs)
        assert "test_udt_Payload" not in ns

        event = _contract_event(
            [scval.to_symbol("changed")],
            scval.to_struct({"value": scval.to_uint32(7)}),
        )
        parsed = ns["parse_event"](event)
        assert isinstance(parsed.payload, ns["Payload"])
        assert parsed.payload.value == 7

    def test_nested_qualified_udt_round_trips(self):
        specs = [
            _struct(b"test_udt::Payload", _type(xdr.SCSpecType.SC_SPEC_TYPE_U32)),
            _struct(b"test_udt::Envelope", _udt_type(b"test_udt::Payload")),
        ]
        ns = _load_bindings(specs)
        envelope = ns["Envelope"](ns["Payload"](11))
        decoded = ns["Envelope"].from_scval(envelope.to_scval())
        assert isinstance(decoded.value, ns["Payload"])
        assert decoded.value.value == 11

    def test_ambiguous_bare_udt_names_use_qualified_declarations(self):
        specs = [
            _struct(b"first::Shared", _type(xdr.SCSpecType.SC_SPEC_TYPE_U32)),
            _struct(b"second::Shared", _type(xdr.SCSpecType.SC_SPEC_TYPE_U32)),
            _event(
                b"changed",
                [b"changed"],
                [_data_param(b"payload", _udt_type(b"second::Shared"))],
                xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_SINGLE_VALUE,
            ),
        ]
        ns = _load_bindings(specs)
        assert "Shared" not in ns

        event = _contract_event(
            [scval.to_symbol("changed")],
            scval.to_struct({"value": scval.to_uint32(8)}),
        )
        parsed = ns["parse_event"](event)
        assert isinstance(parsed.payload, ns["second_Shared"])
        assert parsed.payload.value == 8

    def test_udt_name_wins_over_later_event_class_name(self):
        # The UDT is declared first, so it keeps the bare name and the event
        # class, which would otherwise be generated with the same name, is the
        # one that gets renamed.
        specs = [
            _struct(
                b"test_udt::TransferEvent",
                _type(xdr.SCSpecType.SC_SPEC_TYPE_U32),
            ),
            _event(
                b"transfer",
                [b"transfer"],
                [_data_param(b"amount", _type(xdr.SCSpecType.SC_SPEC_TYPE_U32))],
                xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_SINGLE_VALUE,
            ),
        ]
        ns = _load_bindings(specs)
        assert hasattr(ns["TransferEvent"], "from_scval")
        assert hasattr(ns["TransferEvent_"], "EVENT_NAME")

    @pytest.mark.parametrize(
        "reserved_name",
        [b"EventInfo", b"_EVENTS", b"UnparsedEventError", b"parse_event"],
    )
    def test_udt_does_not_overwrite_generated_runtime(self, reserved_name):
        specs = [
            _struct(reserved_name, _type(xdr.SCSpecType.SC_SPEC_TYPE_U32)),
            _event(
                b"changed",
                [b"changed"],
                [_data_param(b"payload", _udt_type(reserved_name))],
                xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_SINGLE_VALUE,
            ),
        ]
        ns = _load_bindings(specs)
        event = _contract_event(
            [scval.to_symbol("changed")],
            scval.to_struct({"value": scval.to_uint32(9)}),
        )
        # parse_event still dispatching proves the generated runtime survived;
        # the contract's own type lives under a renamed symbol.
        parsed = ns["parse_event"](event)
        assert parsed.payload.value == 9
        assert isinstance(parsed.payload, ns[reserved_name.decode() + "2"])


class TestReservedModuleNames:
    def test_reserved_set_matches_what_the_generator_emits(self):
        # _GENERATED_MODULE_NAMES is hand-maintained and is what stops a UDT or
        # event from shadowing a generated symbol. Render every optional part
        # of the runtime and check the set still covers exactly the names bound
        # at module scope, so adding a helper cannot silently drift out of it.
        source = black.format_str(
            "\n".join(
                [
                    render_imports("both", has_events=True),
                    render_scval_helpers(),
                    render_event_helpers(),
                ]
            ),
            mode=black.Mode(),
        )
        emitted = _top_level_bindings(ast.parse(source))
        emitted.discard("annotations")  # __future__ import, not a real binding
        # Emitted elsewhere, from templates that need a spec to render.
        emitted |= {"Client", "ClientAsync", "_EVENTS", "parse_event"}
        assert emitted == set(_GENERATED_MODULE_NAMES)

    def test_generated_module_binds_each_name_once(self):
        # A UDT or event whose name collides with a generated symbol must be
        # renamed, not emitted a second time and silently shadowed.
        specs = [
            _struct(b"Payload", _type(xdr.SCSpecType.SC_SPEC_TYPE_U32)),
            _struct(b"other::Payload", _type(xdr.SCSpecType.SC_SPEC_TYPE_U32)),
            _struct(b"parse_event", _type(xdr.SCSpecType.SC_SPEC_TYPE_U32)),
            _event(
                b"payload",
                [b"payload"],
                [_data_param(b"payload", _udt_type(b"Payload"))],
                xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_SINGLE_VALUE,
            ),
        ]
        source = black.format_str(
            generate_binding(specs, client_type="both"), mode=black.Mode()
        )
        tree = ast.parse(source)
        names = [
            node.name
            for node in tree.body
            if isinstance(node, (ast.ClassDef, ast.FunctionDef))
        ] + [
            target.id
            for node in tree.body
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
        ]
        assert len(names) == len(set(names)), "generated module binds a name twice"


class TestGeneratedIdentifierSafety:
    def test_invalid_event_and_param_names_are_sanitized_and_unique(self):
        specs = [
            _event(
                b"1odd-event",
                [b"odd"],
                [
                    _topic_param(b"bad-name", _type(xdr.SCSpecType.SC_SPEC_TYPE_U32)),
                    _data_param(b"from", _type(xdr.SCSpecType.SC_SPEC_TYPE_U32)),
                ],
                xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_VEC,
            ),
            _event(
                b"duplicates",
                [b"duplicates"],
                [
                    _data_param(b"from", _type(xdr.SCSpecType.SC_SPEC_TYPE_U32)),
                    _data_param(b"from_", _type(xdr.SCSpecType.SC_SPEC_TYPE_U32)),
                    _data_param(b"self", _type(xdr.SCSpecType.SC_SPEC_TYPE_U32)),
                    _data_param(b"cls", _type(xdr.SCSpecType.SC_SPEC_TYPE_U32)),
                ],
                xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_VEC,
            ),
        ]
        ns = _load_bindings(specs)
        odd_event = _contract_event(
            [scval.to_symbol("odd"), scval.to_uint32(1)],
            scval.to_vec([scval.to_uint32(2)]),
        )
        parsed = ns["_1oddEvent"].parse(odd_event)
        assert parsed.bad_name == 1
        assert parsed.from_ == 2

        duplicate_event = _contract_event(
            [scval.to_symbol("duplicates")],
            scval.to_vec([scval.to_uint32(i) for i in range(4)]),
        )
        parsed = ns["DuplicatesEvent"].parse(duplicate_event)
        assert parsed.from_ == 0
        assert parsed.from__ == 1
        assert parsed.self_ == 2
        assert parsed.cls_ == 3

    def test_dunder_params_are_safe_attributes(self):
        specs = [
            _event(
                b"dunders",
                [b"dunders"],
                [
                    _data_param(name, _type(xdr.SCSpecType.SC_SPEC_TYPE_U32))
                    for name in (b"__class__", b"__dict__", b"__weakref__")
                ],
                xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_VEC,
            )
        ]
        ns = _load_bindings(specs)
        parsed = ns["DundersEvent"].parse(
            _contract_event(
                [scval.to_symbol("dunders")],
                scval.to_vec([scval.to_uint32(i) for i in range(3)]),
            )
        )
        assert parsed.__class___ == 0
        assert parsed.__dict___ == 1
        assert parsed.__weakref___ == 2

    def test_nfkc_equivalent_names_are_disambiguated(self):
        kelvin_sign = "K".encode()
        specs = [
            _event(
                b"unicode",
                [b"unicode"],
                [
                    _data_param(b"K", _type(xdr.SCSpecType.SC_SPEC_TYPE_U32)),
                    _data_param(kelvin_sign, _type(xdr.SCSpecType.SC_SPEC_TYPE_U32)),
                ],
                xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_VEC,
            )
        ]
        ns = _load_bindings(specs)
        parsed = ns["UnicodeEvent"].parse(
            _contract_event(
                [scval.to_symbol("unicode")],
                scval.to_vec([scval.to_uint32(1), scval.to_uint32(2)]),
            )
        )
        assert parsed.K == 1
        assert parsed.K_ == 2

    def test_event_spec_strings_cannot_inject_generated_code(self):
        entry = _event(
            b"safe",
            [b"safe"],
            [],
            xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_SINGLE_VALUE,
        )
        malicious_doc = b"x'''\n    INJECTED = True\n    #"
        entry.event_v0.doc = malicious_doc
        ns = _load_bindings([entry])
        assert ns["SafeEvent"].__doc__ == malicious_doc.decode()
        assert not hasattr(ns["SafeEvent"], "INJECTED")
        assert "INJECTED" not in ns

    def test_invalid_single_value_declaration_is_rejected(self):
        specs = [
            _event(
                b"invalid",
                [b"invalid"],
                [
                    _data_param(b"a", _type(xdr.SCSpecType.SC_SPEC_TYPE_U32)),
                    _data_param(b"b", _type(xdr.SCSpecType.SC_SPEC_TYPE_U32)),
                ],
                xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_SINGLE_VALUE,
            )
        ]
        with pytest.raises(ValueError, match="at most one data parameter"):
            generate_binding(specs, client_type="none")


class TestDuplicateEventDeclarations:
    def setup_method(self):
        self.specs = [
            _event(
                b"changed",
                [b"first"],
                [_topic_param(b"account", _type(xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS))],
                xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_SINGLE_VALUE,
            ),
            _event(
                b"changed",
                [b"second"],
                [_topic_param(b"index", _type(xdr.SCSpecType.SC_SPEC_TYPE_U32))],
                xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_SINGLE_VALUE,
            ),
        ]
        # Both declarations have no data params, so SEP-48 requires SCV_VOID.
        self.ns = _load_bindings(self.specs)

    def test_each_declaration_gets_distinct_parser_and_filter(self):
        first = _contract_event(
            [scval.to_symbol("first"), scval.to_address(FROM_ADDRESS)],
            scval.to_void(),
        )
        second = _contract_event(
            [scval.to_symbol("second"), scval.to_uint32(3)], scval.to_void()
        )
        assert isinstance(self.ns["parse_event"](first), self.ns["ChangedEvent"])
        assert isinstance(self.ns["parse_event"](second), self.ns["ChangedEvent_"])
        assert self.ns["ChangedEvent"].topic_filter(account=FROM_ADDRESS) == [
            scval.to_symbol("first").to_xdr(),
            scval.to_address(FROM_ADDRESS).to_xdr(),
            "**",
        ]
        assert self.ns["ChangedEvent_"].topic_filter(index=3) == [
            scval.to_symbol("second").to_xdr(),
            scval.to_uint32(3).to_xdr(),
            "**",
        ]

    def test_generation_reports_occurrence_specific_diagnostics(self):
        source, diagnostics = generate_binding_with_diagnostics(
            self.specs, client_type="none"
        )
        assert "class ChangedEvent:" in source
        assert "class ChangedEvent_:" in source
        assert diagnostics == [
            "Event binding note: 'changed' -> ChangedEvent "
            "(declaration 1 of 2 with this event name)",
            "Event binding note: 'changed' -> ChangedEvent_ "
            "(declaration 2 of 2 with this event name; "
            "renamed to avoid a generated-name collision)",
        ]


class TestEventDocumentation:
    def test_parameter_docs_are_preserved_on_generated_class(self):
        entry = _event(
            b"documented",
            [b"documented"],
            [_topic_param(b"from", _type(xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS))],
            xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_SINGLE_VALUE,
        )
        entry.event_v0.doc = b"Emitted when something changes."
        entry.event_v0.params[0].doc = b"The source account."
        ns = _load_bindings([entry])
        assert "Emitted when something changes." in ns["DocumentedEvent"].__doc__
        assert (
            "from_ (wire name 'from'): The source account."
            in ns["DocumentedEvent"].__doc__
        )


class TestPythonCommand:
    def test_format_failure_aborts_without_writing_binding(self, monkeypatch):
        specs = [
            _event(
                b"paused",
                [b"paused"],
                [],
                xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_SINGLE_VALUE,
            )
        ]
        monkeypatch.setattr(
            "stellar_contract_bindings.python.get_specs_by_contract_id",
            lambda contract_id, rpc_url: specs,
        )

        def fail_format(source, mode):
            raise black.InvalidInput("generated source is invalid")

        monkeypatch.setattr(
            "stellar_contract_bindings.python.black.format_str", fail_format
        )
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(
                command,
                ["--contract-id", CONTRACT_ID, "--output", "generated"],
            )
            assert result.exit_code != 0
            assert "formatting failed" in result.output
            assert not (Path("generated") / "bindings.py").exists()

    def test_duplicate_event_diagnostics_are_printed(self, monkeypatch):
        specs = [
            _event(
                b"changed",
                [b"first"],
                [],
                xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_SINGLE_VALUE,
            ),
            _event(
                b"changed",
                [b"second"],
                [],
                xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_SINGLE_VALUE,
            ),
        ]
        monkeypatch.setattr(
            "stellar_contract_bindings.python.get_specs_by_contract_id",
            lambda contract_id, rpc_url: specs,
        )
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(command, ["--contract-id", CONTRACT_ID])
            assert result.exit_code == 0, result.output
            assert "'changed' -> ChangedEvent (declaration 1 of 2" in result.output
            assert "'changed' -> ChangedEvent_ (declaration 2 of 2" in result.output


class TestHashability:
    def setup_method(self):
        specs = [
            _event(
                b"batch",
                [b"batch"],
                [
                    _data_param(
                        b"values",
                        _vec_type(_type(xdr.SCSpecType.SC_SPEC_TYPE_U32)),
                    )
                ],
                xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_SINGLE_VALUE,
            ),
            _event(
                b"single",
                [b"single"],
                [_data_param(b"amount", _type(xdr.SCSpecType.SC_SPEC_TYPE_I128))],
                xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_SINGLE_VALUE,
            ),
        ]
        self.ns = _load_bindings(specs)

    def test_event_with_vec_param_is_unhashable(self):
        # Like the generated struct and union classes, events always define
        # __hash__; hashing one that holds a list fails the same way it would
        # for a struct with a Vec field.
        event = _contract_event(
            [scval.to_symbol("batch")],
            scval.to_vec([scval.to_uint32(1)]),
        )
        parsed = self.ns["BatchEvent"].parse(event)
        with pytest.raises(TypeError):
            hash(parsed)
        # Equality still works.
        assert parsed == self.ns["BatchEvent"].parse(event)

    def test_event_with_hashable_params_is_hashable(self):
        event = _contract_event([scval.to_symbol("single")], scval.to_int128(1))
        parsed = self.ns["SingleEvent"].parse(event)
        assert hash(parsed) == hash(self.ns["SingleEvent"].parse(event))


class TestStellarAssetContractSpec:
    """End-to-end over the embedded Stellar Asset Contract spec, which declares
    events using all shapes emitted by real contracts."""

    def setup_method(self):
        self.ns = _load_bindings(get_token_sc_spec_entry())

    def test_transfer_with_muxed_variants_disambiguate(self):
        base_topics = [
            scval.to_symbol("transfer"),
            scval.to_address(FROM_ADDRESS),
            scval.to_address(TO_ADDRESS),
        ]
        map_event = _contract_event(
            base_topics,
            scval.to_struct(
                {
                    "to_muxed_id": scval.to_uint64(123),
                    "amount": scval.to_int128(42),
                }
            ),
        )
        parsed = self.ns["parse_event"](map_event)
        assert isinstance(parsed, self.ns["TransferEvent"])
        assert parsed.to_muxed_id == 123
        assert parsed.amount == 42

        map_without_muxed_id = _contract_event(
            base_topics,
            scval.to_struct({"amount": scval.to_int128(42)}),
        )
        parsed = self.ns["parse_event"](map_without_muxed_id)
        assert isinstance(parsed, self.ns["TransferEvent"])
        assert parsed.to_muxed_id is None
        assert parsed.amount == 42

        legacy_event = _contract_event(base_topics, scval.to_int128(42))
        parsed = self.ns["parse_event"](legacy_event)
        assert isinstance(parsed, self.ns["TransferWithAmountOnlyEvent"])
        assert parsed.amount == 42

    def test_burn(self):
        event = _contract_event(
            [scval.to_symbol("burn"), scval.to_address(FROM_ADDRESS)],
            scval.to_int128(7),
        )
        parsed = self.ns["parse_event"](event)
        assert isinstance(parsed, self.ns["BurnEvent"])
        assert parsed.from_ == Address(FROM_ADDRESS)
        assert parsed.amount == 7

    def test_mainnet_shaped_transfer(self):
        # Real mainnet XLM SAC transfer events carry a trailing SEP-11 asset
        # string topic that the stellar-asset-spec declarations omit, and use
        # the legacy bare-i128 data format.
        event = _contract_event(
            [
                scval.to_symbol("transfer"),
                scval.to_address(FROM_ADDRESS),
                scval.to_address(TO_ADDRESS),
                scval.to_string("native"),
            ],
            scval.to_int128(601428),
        )
        parsed = self.ns["parse_event"](event)
        assert isinstance(parsed, self.ns["TransferWithAmountOnlyEvent"])
        assert parsed.from_ == Address(FROM_ADDRESS)
        assert parsed.to == Address(TO_ADDRESS)
        assert parsed.amount == 601428

    def test_topic_filter_reaches_events_with_extra_topics(self):
        # The declaration has 3 topics but mainnet SAC transfers carry a 4th
        # (the SEP-11 asset string). Without the trailing "**" the RPC matches
        # on the exact topic count and would never return them.
        topics = self.ns["TransferEvent"].topic_filter(to=TO_ADDRESS)
        assert topics[-1] == "**"
        assert topics[:-1] == [
            scval.to_symbol("transfer").to_xdr(),
            "*",
            scval.to_address(TO_ADDRESS).to_xdr(),
        ]
        # "**" is excluded from the RPC's four-segment limit.
        assert len(topics) - 1 <= 4

import unittest

from stellar_sdk import xdr

from stellar_contract_bindings.metadata import get_token_sc_spec_entry


class TestGetTokenScSpecEntry(unittest.TestCase):
    def setUp(self):
        self.entries = get_token_sc_spec_entry()

    def _functions(self):
        return {
            entry.function_v0.name.sc_symbol.decode(): entry.function_v0
            for entry in self.entries
            if entry.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0
        }

    def test_contains_expected_functions(self):
        expected = {
            "allowance",
            "authorized",
            "approve",
            "balance",
            "burn",
            "burn_from",
            "clawback",
            "decimals",
            "mint",
            "name",
            "set_admin",
            "admin",
            "set_authorized",
            "symbol",
            "transfer",
            "transfer_from",
            "trust",
        }
        self.assertEqual(expected, set(self._functions().keys()))

    def test_transfer_accepts_muxed_destination(self):
        transfer = self._functions()["transfer"]
        params = [
            (param.name.decode(), param.type.type)
            for param in transfer.inputs
        ]
        self.assertEqual(
            [
                ("from", xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS),
                ("to", xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS),
                ("amount", xdr.SCSpecType.SC_SPEC_TYPE_I128),
            ],
            params,
        )

    def test_contains_event_entries(self):
        event_names = {
            entry.event_v0.name.sc_symbol.decode()
            for entry in self.entries
            if entry.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_EVENT_V0
        }
        self.assertTrue(
            {"Transfer", "Mint", "Burn", "Clawback", "Approve"}.issubset(event_names)
        )

    def test_contains_only_function_and_event_entries(self):
        kinds = {entry.kind for entry in self.entries}
        self.assertEqual(
            {
                xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0,
                xdr.SCSpecEntryKind.SC_SPEC_ENTRY_EVENT_V0,
            },
            kinds,
        )


if __name__ == "__main__":
    unittest.main()

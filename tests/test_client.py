import pytest
from stellar_sdk import Network
from stellar_sdk.contract.exceptions import SimulationFailedError

from .client import *

CONTRACT_ID = "CCCEM6UHXEVHVXDN4E4G3IIN5LTUJ2NVVSRR3WCQHKP6GROQFGRN3HIE"
RPC_URL = "https://soroban-testnet.stellar.org"
NETWORK_PASSPHRASE = Network.TESTNET_NETWORK_PASSPHRASE


class TestClient:
    @classmethod
    def setup_class(cls):
        cls.client = Client(CONTRACT_ID, RPC_URL, NETWORK_PASSPHRASE)

    @classmethod
    def teardown_class(cls):
        cls.client.server.close()

    def test_hello(self):
        result = self.client.hello("overcat")
        assert result.result() == "overcat"

    def test_void(self):
        result = self.client.void()
        assert result.result() is None

    def test_val(self):
        result = self.client.val(0, scval.to_void())
        assert result.result() == scval.to_bool(True)

        result = self.client.val(1, scval.to_void())
        assert result.result() == scval.to_uint32(123)

        result = self.client.val(2, scval.to_void())
        assert result.result() == scval.to_int32(-123)

        result = self.client.val(3, scval.to_void())
        assert result.result() == scval.to_void()

        result = self.client.val(255, scval.to_bytes(b"test"))
        assert result.result() == scval.to_bytes(b"test")

    def test_u32_fail_on_even(self):
        result = self.client.u32_fail_on_even(1)
        assert result.result() == 1

        with pytest.raises(SimulationFailedError):
            self.client.u32_fail_on_even(2)

    def test_u32(self):
        result = self.client.u32(34543534)
        assert result.result() == 34543534

    def test_i32(self):
        result = self.client.i32(-34543534)
        assert result.result() == -34543534

    def test_u64(self):
        result = self.client.u64(34543534)
        assert result.result() == 34543534

    def test_i64(self):
        result = self.client.i64(-34543534)
        assert result.result() == -34543534

    def test_strukt_hel(self):
        strukt = Test(123, True, "world")
        result = self.client.strukt_hel(strukt)
        assert result.result() == ["Hello", "world"]

    def test_strukt(self):
        strukt = Test(123, True, "world")
        result = self.client.strukt(strukt)
        assert result.result() == strukt

    def test_simple(self):
        simple = SimpleEnum(SimpleEnumKind.Second)
        result = self.client.simple(simple)
        assert result.result() == simple

    def test_complex_struct(self):
        complex_struct = ComplexEnum(
            ComplexEnumKind.Struct, struct=Test(123, True, "world")
        )
        result = self.client.complex(complex_struct)
        assert result.result() == complex_struct

    def test_complex_tuple(self):
        complex_tuple = ComplexEnum(
            ComplexEnumKind.Tuple,
            tuple=TupleStruct(
                (Test(123, True, "world"), SimpleEnum(SimpleEnumKind.Third))
            ),
        )
        result = self.client.complex(complex_tuple)
        assert result.result() == complex_tuple

    def test_complex_enum(self):
        complex_enum = ComplexEnum(
            ComplexEnumKind.Enum, enum=SimpleEnum(SimpleEnumKind.Second)
        )
        result = self.client.complex(complex_enum)
        assert result.result() == complex_enum

    def test_complex_asset(self):
        complex_asset = ComplexEnum(
            ComplexEnumKind.Asset,
            asset=(
                Address("GBXCJUTSISFIAS2UENBBO4NXVBJDL7MQHHWM2MSM6S7N4BNNUAO2CWKF"),
                100123,
            ),
        )
        result = self.client.complex(complex_asset)
        assert result.result() == complex_asset

    def test_complex_void(self):
        complex_void = ComplexEnum(ComplexEnumKind.Void)
        result = self.client.complex(complex_void)
        assert result.result() == complex_void

    def test_address(self):
        address = Address("GBXCJUTSISFIAS2UENBBO4NXVBJDL7MQHHWM2MSM6S7N4BNNUAO2CWKF")
        result = self.client.address(address)
        assert result.result() == address

    def test_bytes(self):
        result = self.client.bytes(b"123")
        assert result.result() == b"123"

    def test_bytes_n(self):
        result = self.client.bytes_n(b"123456789")
        assert result.result() == b"123456789"

    def test_card(self):
        card = RoyalCard.King
        result = self.client.card(card)
        assert result.result() == card

    def test_boolean(self):
        result = self.client.boolean(True)
        assert result.result() is True

    def test_not(self):
        result = self.client.not_(True)
        assert result.result() is False

    def test_i128(self):
        result = self.client.i128(-170141183460469231731687303715884105728)
        assert result.result() == -170141183460469231731687303715884105728

    def test_u128(self):
        result = self.client.u128(340282366920938463463374607431768211455)
        assert result.result() == 340282366920938463463374607431768211455

    def test_multi_args(self):
        result = self.client.multi_args(123, True)
        assert result.result() == 123

    def test_map(self):
        result = self.client.map({13: True, 62: False, 993: True})
        assert result.result() == {13: True, 62: False, 993: True}

    def test_vec(self):
        result = self.client.vec([13, 62, 993])
        assert result.result() == [13, 62, 993]

    def test_tuple(self):
        result = self.client.tuple(("hello", 100))
        assert result.result() == ("hello", 100)

    def test_empty_tuple(self):
        result = self.client.empty_tuple()
        assert result.result() is None

    def test_option(self):
        result = self.client.option(None)
        assert result.result() is None

        result = self.client.option(100)
        assert result.result() == 100

    def test_u256(self):
        result = self.client.u256(
            115792089237316195423570985008687907853269984665640564039457584007913129639935
        )
        assert (
            result.result()
            == 115792089237316195423570985008687907853269984665640564039457584007913129639935
        )

    def test_i256(self):
        result = self.client.i256(
            -57896044618658097711785492504343953926634992332820282019728792003956564819968
        )
        assert (
            result.result()
            == -57896044618658097711785492504343953926634992332820282019728792003956564819968
        )

    def test_string(self):
        result = self.client.string(b"hello")
        assert result.result() == b"hello"

    def test_tuple_strukt(self):
        t = TupleStruct((Test(1, False, "hello"), SimpleEnum(SimpleEnumKind.First)))
        result = self.client.tuple_strukt(t)
        assert result.result() == t

    def test_tuple_strukt_nested(self):
        t = (Test(1, False, "hello"), SimpleEnum(SimpleEnumKind.First))
        result = self.client.tuple_strukt_nested(t)
        assert result.result() == t

    def test_timepoint(self):
        result = self.client.timepoint(123456789)
        assert result.result() == 123456789

    def test_duration(self):
        result = self.client.duration(123456789)
        assert result.result() == 123456789

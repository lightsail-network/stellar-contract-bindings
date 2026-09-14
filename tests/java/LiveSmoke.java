import com.example.Client;
import org.stellar.sdk.Address;
import org.stellar.sdk.Network;
import org.stellar.sdk.contract.exception.SimulationFailedException;
import org.stellar.sdk.scval.Scv;

import java.math.BigInteger;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Calls the reference contract on testnet through the generated client.
 *
 * <p>The contract ID is the first argument: the test deploys the contract
 * before running this. Every call is a read-only simulation from the null
 * account, so nothing is signed or submitted. These are the same checks as
 * tests/test_client.py, which makes them through the Python bindings.
 */
public class LiveSmoke {
    static int failures = 0;

    static void check(String label, boolean ok) {
        System.out.println((ok ? "PASS " : "FAIL ") + label);
        if (!ok) failures++;
    }

    static final String RPC_URL = "https://soroban-testnet.stellar.org";
    static final String A = "GA7QYNF7SOWQ3GLR2BGMZEHXAVIRZA4KVWLTJJFC7MGXUA74P7UJVSGZ";

    public static void main(String[] args) throws Exception {
        if (args.length != 1) {
            throw new IllegalArgumentException("usage: LiveSmoke <contract id>");
        }
        try (Client client = new Client(args[0], RPC_URL, Network.TESTNET)) {
            check("hello", client.hello("overcat").result().equals("overcat"));
            check("void", client.void_().result() == null);
            check("u32", client.u32(34543534).result() == 34543534L);
            check("i32", client.i32(-34543534).result() == -34543534);
            check("u64", client.u64(BigInteger.valueOf(3454353400L)).result().equals(BigInteger.valueOf(3454353400L)));
            check("i128", client.i128(BigInteger.valueOf(-3454353400L)).result().equals(BigInteger.valueOf(-3454353400L)));
            check("val passthrough", client.val(0, Scv.toVoid()).result().getB());
            check("not", !client.not(true).result());

            check("u32_fail_on_even ok", client.u32FailOnEven(1).result() == 1L);
            Client.Error error = null;
            try {
                client.u32FailOnEven(2);
            } catch (SimulationFailedException e) {
                error = Client.Error.fromSimulationError(e).orElse(null);
            }
            check("u32_fail_on_even reports its contract error", error == Client.Error.NumberMustBeOdd);

            Client.SimpleStruct simple = new Client.SimpleStruct(1, true, "hello");
            check("struct", client.strukt(simple).result().equals(simple));
            check("strukt_hel", client.struktHel(simple).result().equals(Arrays.asList("Hello", "hello")));
            Client.SimpleEnum second = new Client.SimpleEnum.Second();
            check("void-case union", client.simple(second).result().equals(second));
            check("card", client.card(Client.RoyalCard.King).result() == Client.RoyalCard.King);

            Client.ComplexEnum asset = new Client.ComplexEnum.Asset(new Address(A), BigInteger.valueOf(100));
            check("complex Asset", client.complex(asset).result().equals(asset));
            Client.ComplexEnum voidCase = new Client.ComplexEnum.Void();
            check("complex Void", client.complex(voidCase).result().equals(voidCase));
            Client.ComplexEnum tuple = new Client.ComplexEnum.Tuple(new Client.TupleStruct(simple, new Client.SimpleEnum.Third()));
            check("complex Tuple", client.complex(tuple).result().equals(tuple));

            check("address", client.address(new Address(A)).result().equals(new Address(A)));
            byte[] data = "data".getBytes(StandardCharsets.UTF_8);
            check("bytes", Arrays.equals(client.bytes(data).result(), data));
            byte[] nine = new byte[9];
            check("bytes_n", Arrays.equals(client.bytesN(nine).result(), nine));
            // An SCV_STRING is bytes: text and bytes that are not UTF-8 both round-trip.
            byte[] text = "text \u4e2d\u6587".getBytes(StandardCharsets.UTF_8);
            check("string", Arrays.equals(client.string(text).result(), text));
            byte[] raw = {(byte) 0xff, (byte) 0xfe, 0, 1};
            check("string that is not UTF-8", Arrays.equals(client.string(raw).result(), raw));

            check("option none", client.option(null).result() == null);
            check("option some", client.option(5L).result() == 5L);
            check("vec", client.vec(Arrays.asList(1L, 2L, 3L)).result().equals(Arrays.asList(1L, 2L, 3L)));
            Map<Long, Boolean> map = new LinkedHashMap<>();
            map.put(2L, false);
            map.put(1L, true);
            check("map", client.map(map).result().equals(map));
            Client.Tuple2<String, Long> pair = Client.Tuple2.of("a", 1L);
            check("tuple", client.tuple(pair).result().equals(pair));
            check("empty tuple", client.emptyTuple().result() == null);
            check("timepoint", client.timepoint(BigInteger.valueOf(1234)).result().equals(BigInteger.valueOf(1234)));
        }

        if (failures > 0) throw new AssertionError(failures + " checks failed");
        System.out.println("all checks passed");
    }
}

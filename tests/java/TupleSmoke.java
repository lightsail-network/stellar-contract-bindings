import com.example.Client;
import org.stellar.sdk.scval.Scv;
import org.stellar.sdk.xdr.SCVal;
import java.util.Arrays;
import java.util.LinkedHashMap;

/** Exercises the generated tuple classes, which replaced javatuples. */
public class TupleSmoke {
    static int failures = 0;

    static void check(String label, boolean ok) {
        System.out.println((ok ? "PASS " : "FAIL ") + label);
        if (!ok) failures++;
    }

    public static void main(String[] args) {
        // A tuple encodes as a vec, in declaration order.
        Client.Holder holder = new Client.Holder(new Client.Tuple2<>(1L, 2L));
        Client.Holder back = Client.Holder.fromSCVal(holder.toSCVal());

        check("round trip preserves value0", back.getPair().getValue0().equals(1L));
        check("round trip preserves value1", back.getPair().getValue1().equals(2L));
        check("value semantics", holder.equals(back));
        check("hash matches", holder.hashCode() == back.hashCode());
        check("toString is readable", back.getPair().toString().contains("value0=1"));

        // Twelve elements: two more than javatuples offered.
        Client.Wide wide = new Client.Wide(new Client.Tuple12<>(
            0L, 1L, 2L, 3L, 4L, 5L, 6L, 7L, 8L, 9L, 10L, 11L));
        Client.Wide wideBack = Client.Wide.fromSCVal(wide.toSCVal());
        check("12-element first", wideBack.getWide().getValue0().equals(0L));
        check("12-element last", wideBack.getWide().getValue11().equals(11L));

        // A tuple's wire form is a plain vec, so a hand-built one decodes too.
        // The struct around it is a map, keyed by field name.
        LinkedHashMap<SCVal, SCVal> fields = new LinkedHashMap<>();
        fields.put(Scv.toSymbol("pair"),
            Scv.toVec(Arrays.asList(Scv.toUint32(7L), Scv.toUint32(8L))));
        Client.Holder manual = Client.Holder.fromSCVal(Scv.toMap(fields));
        check("decodes a hand-built vec", manual.getPair().getValue1().equals(8L));

        if (failures > 0) throw new AssertionError(failures + " checks failed");
        System.out.println("all checks passed");
    }
}

#!/usr/bin/env python3
"""
Pass/fail gate for a UgandaConnect load-test run.

Reads the statistics.json that JMeter writes into the HTML report folder
(jmeter ... -e -o results/report) and checks every operation against sla.json:
error rate, p95 and p99 response time. Prints a table with throughput,
average, p95, p99 and error % for each operation, and exits 1 if any SLA is
breached so a CI pipeline fails the build.

    python3 scripts/check_sla.py results/report/statistics.json [sla.json] [--md summary.md]
"""
import json
import os
import re
import sys


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    md_out = sys.argv[sys.argv.index("--md") + 1] if "--md" in sys.argv else None
    if md_out in args:
        args.remove(md_out)
    if not args:
        sys.exit(__doc__)
    stats_path = args[0]
    sla_path = args[1] if len(args) > 1 else os.path.join(os.path.dirname(__file__), "..", "sla.json")
    stats = json.load(open(stats_path))
    sla = json.load(open(sla_path))

    # Transaction Controllers are named "01 Login", "SOLAR 03 ..." etc.; raw HTTP samplers start with the method.
    is_txn = re.compile(r"^(?:\d\d |[A-Z]+ \d\d )")
    rows, breaches = [], []
    for name, s in sorted(stats.items()):
        if name == "Total" or (sla.get("only_transactions") and not is_txn.match(name)):
            continue
        rule = next((r for r in sla["rules"] if re.search(r["match"], name)), sla["default"])
        p95, p99, err = s["pct2ResTime"], s["pct3ResTime"], s["errorPct"]
        bad = []
        if p95 > rule["p95_ms"]:
            bad.append(f"p95 {p95:.0f} > {rule['p95_ms']} ms")
        if p99 > rule["p99_ms"]:
            bad.append(f"p99 {p99:.0f} > {rule['p99_ms']} ms")
        if err > rule["max_error_pct"]:
            bad.append(f"errors {err:.2f}% > {rule['max_error_pct']}%")
        rows.append((name, s["sampleCount"], s["throughput"], s["meanResTime"], p95, p99, err, "FAIL" if bad else "PASS"))
        breaches += [f"{name}: {b}" for b in bad]

    tot = stats.get("Total")
    if tot:
        o = sla["overall"]
        if tot["errorPct"] > o["max_error_pct"]:
            breaches.append(f"Overall error rate {tot['errorPct']:.2f}% > {o['max_error_pct']}%")
        if tot["throughput"] < o["min_throughput_rps"]:
            breaches.append(f"Overall throughput {tot['throughput']:.1f} req/s < {o['min_throughput_rps']}")

    head = ("Operation", "Samples", "Req/s", "Avg ms", "p95 ms", "p99 ms", "Error %", "SLA")
    fmt = "{:<48} {:>9} {:>9} {:>8} {:>8} {:>8} {:>8} {:>5}"
    print(fmt.format(*head))
    for r in rows:
        print(fmt.format(r[0][:48], r[1], f"{r[2]:.2f}", f"{r[3]:.0f}", f"{r[4]:.0f}", f"{r[5]:.0f}", f"{r[6]:.2f}", r[7]))
    if tot:
        print(fmt.format("TOTAL (all requests)", tot["sampleCount"], f"{tot['throughput']:.2f}", f"{tot['meanResTime']:.0f}",
                         f"{tot['pct2ResTime']:.0f}", f"{tot['pct3ResTime']:.0f}", f"{tot['errorPct']:.2f}", ""))

    if md_out:
        with open(md_out, "w") as f:
            f.write("| " + " | ".join(head) + " |\n|" + "---|" * len(head) + "\n")
            for r in rows:
                f.write(f"| {r[0]} | {r[1]} | {r[2]:.2f} | {r[3]:.0f} | {r[4]:.0f} | {r[5]:.0f} | {r[6]:.2f} | {r[7]} |\n")
            f.write("\n" + ("**SLA breaches:**\n" + "\n".join(f"- {b}" for b in breaches) if breaches else "**All SLAs met.**") + "\n")

    if breaches:
        print("\nSLA BREACHES:")
        for b in breaches:
            print("  -", b)
        sys.exit(1)
    print("\nAll SLAs met.")


if __name__ == "__main__":
    main()

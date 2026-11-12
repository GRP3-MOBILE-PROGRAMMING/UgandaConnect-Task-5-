#!/usr/bin/env python3
"""
Generates parameterised test data for the UgandaConnect JMeter plan.

Every virtual user gets its own credentials and every request draws different
search values, so the backend cannot answer from a warm cache and the database
sees a realistic spread of keys.

Rule of thumb: generate at least as many users per persona as that persona's
thread count, so no two concurrent threads share a login.

    python3 generate_data.py                 # 2,000 users per persona (dev/staging)
    python3 generate_data.py --users 150000  # full-scale run (500k concurrent split by mix)

The same users must exist in the target environment. Seed them with the
backend's test-data loader, using the same phone numbers and password.
"""
import argparse
import csv
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
PASSWORD = "Test@2026!"

DISTRICTS = [
    ("Kampala", 0.3476, 32.5825), ("Wakiso", 0.4044, 32.4594), ("Mukono", 0.3533, 32.7553),
    ("Jinja", 0.4479, 33.2026), ("Mbarara", -0.6072, 30.6545), ("Gulu", 2.7724, 32.2881),
    ("Lira", 2.2499, 32.8999), ("Mbale", 1.0827, 34.1750), ("Arua", 3.0303, 30.9073),
    ("Masaka", -0.3338, 31.7341), ("Fort Portal", 0.6710, 30.2750), ("Hoima", 1.4331, 31.3524),
    ("Kabale", -1.2486, 29.9899), ("Soroti", 1.7146, 33.6111), ("Tororo", 0.6928, 34.1809),
    ("Moroto", 2.5345, 34.6666), ("Kasese", 0.1833, 30.0833), ("Busia", 0.4544, 34.0758),
    ("Iganga", 0.6092, 33.4686), ("Masindi", 1.6744, 31.7150),
]
KCCA_DIVISIONS = [
    ("Central", 0.3136, 32.5811), ("Kawempe", 0.3741, 32.5579), ("Makindye", 0.2817, 32.5949),
    ("Nakawa", 0.3326, 32.6144), ("Rubaga", 0.3036, 32.5520),
]
SPECIALTIES = ["GENERAL", "MATERNITY", "PAEDIATRICS", "DENTAL", "OPTICAL", "ANTENATAL",
               "IMMUNISATION", "HIV_CARE", "SURGERY", "MENTAL_HEALTH"]
EXAM_LEVELS = [("PLE", 0.40), ("UCE", 0.35), ("UACE", 0.25)]
MSISDN_PREFIX = {"MTN": ["077", "078", "076"], "AIRTEL": ["070", "075", "074"]}


def phone(rng, network=None):
    network = network or rng.choice(list(MSISDN_PREFIX))
    return "256" + rng.choice(MSISDN_PREFIX[network])[1:] + f"{rng.randint(0, 9_999_999):07d}"


def nin(rng):
    # Ugandan NIN format: CM/CF + 12 alphanumerics (14 chars total)
    letters = "ABCDEFGHJKLMNPQRSTUVWXYZ"
    return rng.choice(["CM", "CF"]) + f"{rng.randint(0, 99_999_999):08d}" + "".join(rng.choice(letters) for _ in range(4))


def write(name, header, rows):
    path = os.path.join(HERE, name)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"  {name:<28} {len(rows):>8} rows")


def users(rng, n, persona):
    rows, seen = [], set()
    while len(rows) < n:
        p = phone(rng)
        if p in seen:
            continue
        seen.add(p)
        d = rng.choice(DISTRICTS)[0] if persona != "kcca" else "Kampala"
        rows.append([p, PASSWORD, nin(rng), d, persona])
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=2000, help="users per persona")
    ap.add_argument("--seed", type=int, default=20261111)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    print("Generating UgandaConnect load-test data:")

    for persona in ["solar", "health", "uneb", "bills", "kcca"]:
        write(f"users_{persona}.csv", ["phone", "password", "nin", "district", "persona"], users(rng, a.users, persona))

    # Solar (REA) household profile used in the application form
    write("solar_households.csv", ["village", "householdSize", "monthlyIncome", "roofType"],
          [[f"Village-{rng.randint(1, 9999)}", rng.randint(1, 14), rng.randrange(50_000, 1_500_000, 5_000),
            rng.choice(["IRON_SHEETS", "TILES", "THATCH", "CONCRETE"])] for _ in range(max(a.users, 5000))])

    # Health search mix: district x specialty
    write("health_searches.csv", ["searchDistrict", "specialty", "visitReason"],
          [[rng.choice(DISTRICTS)[0], rng.choice(SPECIALTIES),
            rng.choice(["Routine check-up", "Follow-up visit", "Fever and headache", "Antenatal visit",
                        "Child immunisation", "Tooth pain", "Eye test", "Prescription refill"])]
           for _ in range(5000)])

    # UNEB candidates: index numbers are centre/candidate, e.g. U0123/045
    cands = []
    for _ in range(max(a.users * 5, 20000)):
        level = rng.choices([l for l, _ in EXAM_LEVELS], [w for _, w in EXAM_LEVELS])[0]
        cands.append([f"U{rng.randint(1, 9999):04d}/{rng.randint(1, 999):03d}", rng.randint(2019, 2025), level])
    write("uneb_candidates.csv", ["indexNumber", "examYear", "examLevel"], cands)

    # Utility accounts: UMEME (yaka meter numbers / account numbers) and NWSC
    accts = []
    for _ in range(max(a.users * 5, 20000)):
        prov = rng.choices(["UMEME", "NWSC"], [0.6, 0.4])[0]
        acct = f"{rng.randint(10**10, 10**11 - 1)}" if prov == "UMEME" else f"{rng.randint(10**7, 10**8 - 1)}"
        net = rng.choice(["MTN", "AIRTEL"])
        accts.append([prov, acct, phone(rng, net), net, rng.randrange(5_000, 300_000, 1_000)])
    write("utility_accounts.csv", ["provider", "accountNumber", "msisdn", "channel", "amount"], accts)

    # KCCA issue reports: location jittered within a division
    issues = []
    for _ in range(5000):
        div, lat, lng = rng.choice(KCCA_DIVISIONS)
        issues.append([div, round(lat + rng.uniform(-0.02, 0.02), 6), round(lng + rng.uniform(-0.02, 0.02), 6),
                       rng.choice(["Pothole on main road", "Blocked drainage channel", "Broken street light",
                                   "Uncollected garbage", "Illegal dumping", "Damaged walkway",
                                   "Flooding after rain", "Fallen tree blocking road"])])
    write("kcca_reports.csv", ["division", "lat", "lng", "issueTitle"], issues)


if __name__ == "__main__":
    main()

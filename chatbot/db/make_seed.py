"""Generate db/seed.sql: the synthetic demo dataset. See PROVENANCE.md.

Every row is made up. Names come from the word lists below. Planted accounts sit
behind each approved question, so the expected answers in
config/approved_questions.yml are known in advance. Filler accounts are kept
below the planted thresholds so they never change those answers.

    python db/make_seed.py            # rewrites db/seed.sql
"""
import random
from datetime import date, datetime, timedelta
from pathlib import Path

OUT = Path(__file__).with_name("seed.sql")

# account_no, name, class, street_no, street, city, utility, current, overdue, late, interest
PLANTED = [
    ("100101", "Harbor View Bakery", "COM", "12", "Harbour Road", "Port Alder", "E", "210.00", "640.00", "25.00", "4.10"),
    ("100102", "Elena Marsh", "RES", "42", "Maple Street", "Port Alder", "W", "88.20", "275.50", "10.00", "0.00"),
    ("100103", "Pinecrest Dental", "COM", "300", "Pine Avenue", "Port Alder", "E", "150.00", "180.25", "0.00", "0.00"),
    ("100104", "Tomas Reyes", "RES", "7", "Birch Lane", "Cedar Falls", "W", "64.75", "120.00", "5.00", "0.00"),
    ("100105", "Northgate Laundromat", "COM", "88", "North Gate Road", "Cedar Falls", "E", "402.10", "95.00", "0.00", "0.00"),
    ("100106", "Kiran Patel", "RES", "19", "Willow Court", "Cedar Falls", "E", "71.30", "260.00", "12.50", "1.20"),
    ("100107", "Riverside Auto Body", "COM", "5", "River Road", "Port Alder", "E", "330.00", "510.00", "30.00", "6.40"),
]

FIRST = ["Avery", "Blake", "Casey", "Devon", "Emery", "Finley", "Harper", "Jordan", "Kendall", "Logan",
         "Morgan", "Parker", "Quinn", "Reese", "Rowan", "Sawyer", "Skyler", "Taylor", "Toby", "Wren"]
LAST = ["Abbott", "Brook", "Calder", "Dunmore", "Ellery", "Fairlie", "Garrow", "Hollis", "Ingram", "Jessop"]
STREETS = ["Oak Street", "Cedar Drive", "Hillcrest Road", "Lakeview Avenue", "Spruce Lane", "Elm Crescent"]


def q(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, (datetime, date)):
        return f"'{value.isoformat(sep=' ') if isinstance(value, datetime) else value.isoformat()}'"
    return "'" + str(value).replace("'", "''") + "'"


def insert(table: str, columns: list[str], rows: list[tuple]) -> str:
    values = ",\n".join("  (" + ", ".join(q(v) for v in row) + ")" for row in rows)
    return f"INSERT INTO {table} ({', '.join(columns)}) VALUES\n{values};\n"


def build() -> str:
    rng = random.Random(20261208)  # fixed seed: the file is reproducible
    accounts, pay = [], []
    pay_cols = ["account_no", "occupant_code", "utility_type", "start_date", "end_date", "due_date",
                "last_bill_amount", "current_balance", "overdue_balance", "latecharge_balance", "interest_balance"]
    open_period = (date(2026, 9, 1), None, date(2026, 10, 15))

    for no, name, cls, street_no, street, city, util, cur, over, late, intr in PLANTED:
        accounts.append((no, "01", name, "D" + no, street_no, None, street, city, "NS", "B0A 1C0   ", cls))
        pay.append((no, "01", util, *open_period, cur, cur, over, late, intr))

    for i in range(40):
        no = str(100201 + i)
        name = f"{FIRST[i % len(FIRST)]} {LAST[(i * 7) % len(LAST)]}"
        cls = "COM" if i % 8 == 3 else "RES"
        street_no = str(rng.randint(1, 250))
        zip_code = "00000     " if i % 10 == 0 else "B0A 2D0   "
        accounts.append((no, "01", name, "D" + no, street_no, None, STREETS[i % len(STREETS)], "Cedar Falls", "NS", zip_code, cls))
        cur = f"{rng.randint(2000, 18000) / 100:.2f}"   # 20.00 to 180.00
        over = f"{rng.randint(0, 6000) / 100:.2f}"      # at most 60.00: below every planted threshold
        pay.append((no, "01", "W", *open_period, cur, cur, over, "0.00", "0.00"))

    # Closed billing periods (end_date set) must be ignored by the Account Balance cube.
    closed = (date(2026, 8, 1), date(2026, 8, 31), date(2026, 9, 15))
    for no in ("100105", "100201", "100202"):
        pay.append((no, "01", "E", *closed, "150.00", "150.00", "999.00", "0.00", "0.00"))

    batches = [("B0914JLEE", "B-2026-0914-01", "jlee"), ("B0914MOKA", "B-2026-0914-02", "mokafor"),
               ("B0915JLEE", "B-2026-0915-01", "jlee"), ("B0912SRAO", "B-2026-0912-01", "srao")]
    cash = [
        ("B0914JLEE", "E1001", datetime(2026, 9, 14, 9, 5), "125.00"),
        ("B0914JLEE", "E1002", datetime(2026, 9, 14, 10, 40), "200.00"),
        ("B0914JLEE", "E1003", datetime(2026, 9, 14, 15, 15), "100.00"),
        ("B0914MOKA", "E1004", datetime(2026, 9, 14, 11, 20), "180.50"),
        ("B0914MOKA", "E1005", datetime(2026, 9, 14, 16, 45), "130.00"),
        ("B0915JLEE", "E1006", datetime(2026, 9, 15, 9, 30), "75.00"),
        ("B0915JLEE", "E1007", datetime(2026, 9, 15, 13, 10), "60.00"),
        ("B0912SRAO", "E1008", datetime(2026, 9, 12, 10, 0), "90.00"),
        ("B0912SRAO", "E1009", datetime(2026, 9, 12, 14, 25), "45.25"),
    ]

    ar = [("PAY", "Payment - Counter"), ("PAYM", "Payment - Mail"), ("ADJ", "Adjustment")]
    gl = [("J1001", "PB", "CR"), ("J1002", "PB", "CR"), ("J1003", "GL", "CR"), ("J1004", "PB", "CR")]
    jan8, jan9 = date(2026, 1, 8), date(2026, 1, 9)
    hist = [
        (1, "100101", "01", jan8, jan8, "CR", "J1001", "250.00", "PAY"),
        (2, "100102", "01", jan8, jan8, "CR", "J1001", "120.00", "PAYM"),
        (3, "100104", "01", jan8, jan8, "CR", "J1002", "64.75", "PAY"),
        (4, "100103", "01", jan8, jan8, "BL", "J1002", "150.00", "ADJ"),   # not a cash receipt journal
        (5, "100106", "01", jan8, jan8, "CR", "J1003", "71.30", "PAY"),    # GL application, not PB
        (6, "100107", "01", jan9, jan9, "CR", "J1004", "330.00", "PAY"),   # a different day
    ]

    call_types = [("MOVEIN", "IN", "Move in request", "Move In"), ("RECON", "RC", "Reconnect service", "Reconnect"),
                  ("BILLQ", "BQ", "Billing question", "Bill Query")]
    statuses = [("C", "Completed"), ("S", "Scheduled"), ("O", "Open")]
    codes = {t[0]: t[1] for t in call_types}
    plan = [  # (created, type, agent, account)
        (datetime(2025, 1, 14, 9, 0), "MOVEIN", "agarcia", "100102"),
        (datetime(2025, 2, 3, 10, 30), "MOVEIN", "bchen", "100104"),
        (datetime(2025, 2, 20, 14, 0), "BILLQ", "agarcia", "100101"),
        (datetime(2025, 3, 11, 11, 15), "RECON", "agarcia", "100106"),
        (datetime(2025, 4, 7, 15, 45), "BILLQ", "bchen", "100103"),
        (datetime(2025, 5, 19, 9, 20), "MOVEIN", "agarcia", "100201"),
        (datetime(2025, 6, 2, 13, 5), "RECON", "bchen", "100107"),
        (datetime(2025, 6, 23, 10, 10), "BILLQ", "agarcia", "100105"),
        (datetime(2025, 8, 15, 16, 30), "MOVEIN", "bchen", "100202"),
        (datetime(2025, 9, 9, 8, 50), "RECON", "agarcia", "100104"),
        (datetime(2025, 10, 28, 12, 0), "BILLQ", "agarcia", "100102"),
        (datetime(2025, 11, 17, 14, 40), "MOVEIN", "bchen", "100203"),
        (datetime(2024, 12, 30, 9, 0), "MOVEIN", "agarcia", "100204"),   # outside 2025
        (datetime(2026, 1, 5, 9, 30), "BILLQ", "agarcia", "100101"),     # outside 2025
        (datetime(2026, 2, 10, 11, 0), "RECON", "bchen", "100106"),      # outside 2025
    ]
    calls = []
    for n, (created, ctype, agent, acct) in enumerate(plan, start=1):
        is_order = ctype in ("MOVEIN", "RECON")
        calls.append((f"C{5000 + n}", created, ctype, codes[ctype], f"SO{7000 + n}" if is_order else None,
                      "SO" if is_order else None, agent, acct, "01",
                      created + timedelta(days=2) if is_order else None, created + timedelta(days=3), "C"))

    parts = [
        "-- Synthetic demo dataset generated by db/make_seed.py. No row is live customer data.\n",
        insert("pu_account", ["account_no", "occupant_code", "name", "debtor_no", "serv_street_no", "serv_street_mod",
                              "serv_street", "serv_city", "serv_province", "serv_postal_zip", "cust_class"], accounts),
        insert("pu_account_pay", pay_cols, pay),
        insert("icphdrh", ["login", "batchid", "userid"], batches),
        insert("icpcashm", ["login", "entry_no", "trans_date", "tendered_amt"], cash),
        insert("pu_ar_descript", ["ar_code", "ar_descript"], ar),
        insert("glsvdata", ["jrnl_no", "applcode", "journalcode"], gl),
        insert("pu_balance_hist", ["sequence_", "account_no", "occupant_code", "run_date", "trans_date", "jour_code",
                                   "jour_no", "trans_amt", "desc_code"], hist),
        insert("csrctypr", ["calltype", "callcode", "description", "shortdesc"], call_types),
        insert("csrstatc", ["callstatus", "shortdesc"], statuses),
        insert("csrcalld", ["call_number", "createdon", "calltype", "callcode", "order_no", "ordercode", "createdby",
                            "account_no", "occupant_code", "scheduledon", "completedon", "callstatus"], calls),
    ]
    return "\n".join(parts)


if __name__ == "__main__":
    OUT.write_text(build(), encoding="utf-8")
    print(f"wrote {OUT}")

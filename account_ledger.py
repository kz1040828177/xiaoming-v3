"""Xiaoming V4 broker-neutral account ledger. No broker login or live orders."""
from dataclasses import dataclass, asdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
import csv
import json

D = lambda x: Decimal(str(x))
ALLOWED = {"BUY", "SELL"}
FIELDS = {"trade_id", "trade_date", "code", "side", "quantity", "price", "fee"}

@dataclass
class Trade:
    trade_id: str
    trade_date: str
    code: str
    side: str
    quantity: int
    price: str
    fee: str = "0"

def load_trades(path):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if not FIELDS.issubset(set(reader.fieldnames or [])):
            raise ValueError("CSV requires: " + ", ".join(sorted(FIELDS)))
        rows = [Trade(**{k: row[k] for k in FIELDS}) for row in reader]
    ids = set()
    for t in rows:
        if not t.trade_id or t.trade_id in ids:
            raise ValueError("Duplicate or missing trade_id")
        ids.add(t.trade_id)
        datetime.strptime(t.trade_date, "%Y-%m-%d")
        if t.side not in ALLOWED or not (t.code.isdigit() and len(t.code) == 6):
            raise ValueError("Invalid side or stock code")
        if int(t.quantity) <= 0 or D(t.price) <= 0 or D(t.fee) < 0:
            raise ValueError("Invalid trade values")
    return sorted(rows, key=lambda x: (x.trade_date, x.trade_id))

def reconcile(trades, opening_cash="0"):
    cash = D(opening_cash)
    if cash < 0:
        raise ValueError("Opening cash must be nonnegative")
    holdings = {}
    history = []
    for t in trades:
        qty = int(t.quantity)
        value = D(t.price) * qty
        fee = D(t.fee)
        before = holdings.get(t.code, 0)
        if t.side == "BUY":
            if cash < value + fee:
                raise ValueError("Insufficient cash at trade " + t.trade_id)
            cash -= value + fee
            holdings[t.code] = before + qty
        else:
            if before < qty:
                raise ValueError("Insufficient holdings at trade " + t.trade_id)
            cash += value - fee
            holdings[t.code] = before - qty
        history.append({"trade_id": t.trade_id, "cash_after": str(cash),
                        "quantity_after": holdings[t.code]})
    return {"account_source": "USER_IMPORTED_CSV", "broker": "国信证券金太阳",
            "execution_mode": "MANUAL_IMPORT_ONLY", "cash": str(cash),
            "holdings": {k: v for k, v in holdings.items() if v},
            "trades_count": len(trades), "audit": history,
            "warning": "Only imported trades; no broker balance or settlement verification."}

def export_report(csv_path, opening_cash, output_path):
    report = reconcile(load_trades(csv_path), opening_cash)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--trades", required=True)
    p.add_argument("--opening-cash", required=True)
    p.add_argument("--output", default="output/account.json")
    args = p.parse_args()
    print(json.dumps(export_report(args.trades, args.opening_cash, args.output),
                     ensure_ascii=False, indent=2))

import requests
import json
import os
import certifi

# Multi-asset Phase 1: commodity (MCX) and currency (NSE_CD) symbol masters are fetched ADDITIVELY
# after NSE_FO. They only fill keys NSE_FO did not set (setdefault), so NIFTY/BANKNIFTY/etc. lot
# sizes stay byte-for-byte identical, and a failed extra fetch never blocks the NSE output.
# NOTE (unverified): the extra masters are assumed to share Fyers' NSE_FO column layout
# (lot=parts[3], sym=parts[9], base=parts[13]); confirm before trading those asset classes.
EXTRA_MASTERS = {
    "MCX_COM": "https://public.fyers.in/sym_details/MCX_COM.csv",
    "NSE_CD": "https://public.fyers.in/sym_details/NSE_CD.csv",
}


def _fetch_csv(url):
    resp = requests.get(url, verify=certifi.where(), timeout=10)
    if resp.status_code != 200:
        print(f"Failed to fetch {url}. Status: {resp.status_code}")
        return None
    return resp.text


def _parse_extra(text, lot_sizes):
    """Additive parse for MCX/CDS masters — only fills keys NSE_FO did not already set."""
    added = 0
    for line in text.splitlines():
        parts = line.split(',')
        if len(parts) > 13:
            try:
                lot = int(parts[3])
                sym = parts[9]
                base_name = parts[13]
                if base_name and not base_name.startswith("NSE:") and base_name not in lot_sizes:
                    lot_sizes[base_name] = lot
                    added += 1
                lot_sizes.setdefault(sym, lot)
            except ValueError:
                pass
    return added


def fetch_and_save_lot_sizes():
    print("Downloading NSE_FO.csv from Fyers...")
    # D2: TLS certificate verification is ON. Point at certifi's CA bundle explicitly so a
    # broken/absent system trust store does not silently disable verification (the previous
    # verify=False exposed this fetch to MITM tampering).
    resp_text = _fetch_csv("https://public.fyers.in/sym_details/NSE_FO.csv")

    if resp_text is None:
        return

    lot_sizes = {}
    lines = resp_text.splitlines()
    for line in lines:
        parts = line.split(',')
        if len(parts) > 13:
            try:
                lot = int(parts[3])
                sym = parts[9] # e.g. NSE:NIFTY...
                base_name = parts[13] # e.g. NIFTY
                
                # Fyers prefix handling
                if not base_name.startswith("NSE:"):
                    lot_sizes[base_name] = lot
                
                lot_sizes[sym] = lot # If they ever look up exact strike
                
                # Also try to map the base to index format if it's an index
                if base_name == "NIFTY":
                    lot_sizes["NSE:NIFTY50-INDEX"] = lot
                elif base_name == "BANKNIFTY":
                    lot_sizes["NSE:BANKNIFTY-INDEX"] = lot
                elif base_name == "FINNIFTY":
                    lot_sizes["NSE:FINNIFTY-INDEX"] = lot
                elif base_name == "MIDCPNIFTY":
                    lot_sizes["NSE:MIDCPNIFTY-INDEX"] = lot
                elif base_name == "SENSEX":
                    lot_sizes["BSE:SENSEX-INDEX"] = lot
                elif base_name == "BANKEX":
                    lot_sizes["BSE:BANKEX-INDEX"] = lot
            except ValueError:
                pass

    nse_count = len(lot_sizes)

    # --- ADDITIVE: commodity + currency masters (multi-asset Phase 1) ---
    for name, url in EXTRA_MASTERS.items():
        try:
            print(f"Downloading {name}.csv from Fyers (additive)...")
            text = _fetch_csv(url)
            if text:
                added = _parse_extra(text, lot_sizes)
                print(f"  + {added} {name} base symbols")
        except Exception as e:
            print(f"  ⚠️ {name} fetch skipped ({e}) — NSE output unaffected")

    out_path = os.path.join(os.path.dirname(__file__), "data", "lot_sizes.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    with open(out_path, "w") as f:
        json.dump(lot_sizes, f, indent=2)
    print(f"Saved {len(lot_sizes)} lot sizes ({nse_count} NSE_FO + {len(lot_sizes) - nse_count} MCX/CDS) to {out_path}")

if __name__ == "__main__":
    fetch_and_save_lot_sizes()

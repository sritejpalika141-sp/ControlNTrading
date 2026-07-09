import requests
import json
import os
import certifi

def fetch_and_save_lot_sizes():
    print("Downloading NSE_FO.csv from Fyers...")
    # D2: TLS certificate verification is ON. Point at certifi's CA bundle explicitly so a
    # broken/absent system trust store does not silently disable verification (the previous
    # verify=False exposed this fetch to MITM tampering).
    resp = requests.get("https://public.fyers.in/sym_details/NSE_FO.csv", verify=certifi.where(), timeout=10)
    
    if resp.status_code != 200:
        print(f"Failed to fetch. Status: {resp.status_code}")
        return

    lot_sizes = {}
    lines = resp.text.splitlines()
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

    out_path = os.path.join(os.path.dirname(__file__), "data", "lot_sizes.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    
    with open(out_path, "w") as f:
        json.dump(lot_sizes, f, indent=2)
    print(f"Saved {len(lot_sizes)} lot sizes to {out_path}")

if __name__ == "__main__":
    fetch_and_save_lot_sizes()

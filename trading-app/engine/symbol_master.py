import os
import aiohttp
import asyncio
import csv
from collections import defaultdict
from io import StringIO
import time
import logging

logger = logging.getLogger(__name__)

# Fyers public URLs for symbol masters
SYMBOL_FILES = {
    "NSE_CM": "https://public.fyers.in/sym_details/NSE_CM.csv",
    "NSE_FO": "https://public.fyers.in/sym_details/NSE_FO.csv",
    "MCX": "https://public.fyers.in/sym_details/MCX_COM.csv",
    "BSE_CM": "https://public.fyers.in/sym_details/BSE_CM.csv",
    "CDS": "https://public.fyers.in/sym_details/NSE_CD.csv"
}

class SymbolMaster:
    def __init__(self):
        self._symbols = []  # List of dicts: {"symbol": "NSE:RELIANCE-EQ", "desc": "RELIANCE INDUSTRIES"}
        self._last_update = 0
        self._lock = asyncio.Lock()
        
    async def initialize(self):
        """Download and parse all symbol files."""
        if time.time() - self._last_update < 86400 * 3: # Cache for 3 days
            if self._symbols:
                return
                
        logger.info("Downloading Fyers Symbol Masters for Search Autocomplete...")
        new_symbols = []
        
        # Add basic indices immediately so they are always available
        new_symbols.append({"symbol": "NSE:NIFTY50-INDEX", "desc": "NIFTY 50 INDEX"})
        new_symbols.append({"symbol": "NSE:NIFTYBANK-INDEX", "desc": "NIFTY BANK INDEX"})
        new_symbols.append({"symbol": "NSE:INDIAVIX-INDEX", "desc": "INDIA VIX"})
        new_symbols.append({"symbol": "NSE:FINNIFTY-INDEX", "desc": "NIFTY FIN SERVICE"})
        
        async with aiohttp.ClientSession() as session:
            for exchange, url in SYMBOL_FILES.items():
                try:
                    async with session.get(url) as response:
                        if response.status == 200:
                            text = await response.text()
                            reader = csv.reader(StringIO(text))
                            for row in reader:
                                if len(row) > 9:
                                    symbol = row[9]
                                    desc = row[1]
                                    new_symbols.append({"symbol": symbol, "desc": desc})
                except Exception as e:
                    logger.error(f"Failed to download {exchange} symbols: {e}")
                    
        async with self._lock:
            self._symbols = new_symbols
            self._last_update = time.time()
        logger.info(f"Loaded {len(self._symbols)} symbols into memory.")

    def search(self, query: str, limit: int = 20):
        """Fuzzy search for symbols matching the query."""
        if not query:
            return []
            
        query = query.upper().strip()
        results = []
        
        # 1. Exact prefix match on symbol (highest priority)
        for s in self._symbols:
            clean_sym = s["symbol"].upper().replace("NSE:", "").replace("MCX:", "").replace("BSE:", "")
            if clean_sym.startswith(query):
                results.append(s)
                if len(results) >= limit:
                    return results
                    
        # 2. Prefix match on description
        for s in self._symbols:
            if s["desc"].upper().startswith(query) and s not in results:
                results.append(s)
                if len(results) >= limit:
                    return results
                    
        # 3. Substring match
        for s in self._symbols:
            if query in s["symbol"].upper() or query in s["desc"].upper():
                if s not in results:
                    results.append(s)
                    if len(results) >= limit:
                        return results
                        
        return results

# Singleton instance
symbol_master = SymbolMaster()

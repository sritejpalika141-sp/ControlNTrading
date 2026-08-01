"""
Native C++ Core Bridge for Sritej Trading Platform v6.0.0.
Binds compiled SIMD C++ shared library (libcpp_core) into Python using ctypes
for microsecond-level indicator calculations and lock-free ring-buffer operations.
"""
import ctypes
import os
import platform
from pathlib import Path
from typing import List, Dict, Tuple, Optional

# Define C structures matching c_api.h
class CCandle(ctypes.Structure):
    _fields_ = [
        ("open", ctypes.c_double),
        ("high", ctypes.c_double),
        ("low", ctypes.c_double),
        ("close", ctypes.c_double),
        ("volume", ctypes.c_double),
        ("timestamp", ctypes.c_longlong),
    ]

class COrderBlock(ctypes.Structure):
    _fields_ = [
        ("top", ctypes.c_double),
        ("bottom", ctypes.c_double),
        ("is_bullish", ctypes.c_int),
        ("candle_index", ctypes.c_size_t),
    ]

class CFairValueGap(ctypes.Structure):
    _fields_ = [
        ("top", ctypes.c_double),
        ("bottom", ctypes.c_double),
        ("is_bullish", ctypes.c_int),
        ("candle_index", ctypes.c_size_t),
    ]

class CORBRange(ctypes.Structure):
    _fields_ = [
        ("high", ctypes.c_double),
        ("low", ctypes.c_double),
        ("is_valid", ctypes.c_int),
    ]

class CMarketTick(ctypes.Structure):
    _fields_ = [
        ("symbol", ctypes.c_char * 32),
        ("ltp", ctypes.c_double),
        ("high", ctypes.c_double),
        ("low", ctypes.c_double),
        ("open", ctypes.c_double),
        ("close", ctypes.c_double),
        ("volume", ctypes.c_double),
        ("change", ctypes.c_double),
        ("change_pct", ctypes.c_double),
        ("timestamp", ctypes.c_longlong),
    ]

class NativeCore:
    _lib = None
    _loaded = False

    @classmethod
    def _init_library(cls):
        if cls._loaded:
            return

        base_dir = Path(__file__).resolve().parent.parent
        lib_name = "libcpp_core.dylib" if platform.system() == "Darwin" else "libcpp_core.so"
        
        candidates = [
            base_dir / "cpp_core" / "build" / lib_name,
            base_dir / "cpp_core" / lib_name,
            base_dir.parent / "cpp_core" / "build" / lib_name,
            base_dir.parent / "cpp_core" / lib_name,
            Path("/home/sritejpalika/cpp_core/build") / lib_name,
            Path("/home/sritejpalika/trading-app/cpp_core/build") / lib_name,
        ]

        lib_path = None
        for cand in candidates:
            if cand.exists():
                lib_path = cand
                break

        if lib_path and lib_path.exists():
            try:
                cls._lib = ctypes.CDLL(str(lib_path))
                cls._setup_function_signatures()
                cls._loaded = True
                print(f"⚡ Native C++ HFT Core loaded successfully: {lib_path}", flush=True)
            except Exception as e:
                print(f"⚠️ Failed to load Native C++ HFT Core: {e}", flush=True)
        else:
            print(f"⚠️ Native C++ library not found at {lib_path}. Python fallback active.", flush=True)

    @classmethod
    def _setup_function_signatures(cls):
        if not cls._lib: return

        cls._lib.get_hft_core_version.restype = ctypes.c_char_p

        cls._lib.calculate_ema_c.argtypes = [
            ctypes.POINTER(ctypes.c_double), ctypes.c_size_t, ctypes.c_int, ctypes.POINTER(ctypes.c_double)
        ]
        cls._lib.calculate_ema_c.restype = ctypes.c_int

        cls._lib.calculate_atr_c.argtypes = [
            ctypes.POINTER(CCandle), ctypes.c_size_t, ctypes.c_int, ctypes.POINTER(ctypes.c_double)
        ]
        cls._lib.calculate_atr_c.restype = ctypes.c_int

        cls._lib.detect_fvg_c.argtypes = [
            ctypes.POINTER(CCandle), ctypes.c_size_t, ctypes.c_double, ctypes.POINTER(CFairValueGap), ctypes.c_size_t
        ]
        cls._lib.detect_fvg_c.restype = ctypes.c_size_t

        cls._lib.detect_order_blocks_c.argtypes = [
            ctypes.POINTER(CCandle), ctypes.c_size_t, ctypes.POINTER(COrderBlock), ctypes.c_size_t
        ]
        cls._lib.detect_order_blocks_c.restype = ctypes.c_size_t

        cls._lib.calculate_orb_c.argtypes = [
            ctypes.POINTER(CCandle), ctypes.c_size_t, ctypes.c_int
        ]
        cls._lib.calculate_orb_c.restype = CORBRange

    @classmethod
    def is_available(cls) -> bool:
        cls._init_library()
        return cls._loaded

    @classmethod
    def get_version(cls) -> str:
        cls._init_library()
        if cls._lib:
            return cls._lib.get_hft_core_version().decode("utf-8")
        return "Python Fallback Engine"

    @classmethod
    def calculate_ema(cls, prices: List[float], period: int) -> List[float]:
        cls._init_library()
        count = len(prices)
        if not cls._loaded or count == 0:
            return []

        c_prices = (ctypes.c_double * count)(*prices)
        c_out = (ctypes.c_double * count)()

        res = cls._lib.calculate_ema_c(c_prices, count, period, c_out)
        if res:
            return list(c_out)
        return []

    @classmethod
    def calculate_atr(cls, candles_dict: List[dict], period: int = 14) -> List[float]:
        cls._init_library()
        count = len(candles_dict)
        if not cls._loaded or count == 0:
            return []

        c_candles = (CCandle * count)()
        for i, c in enumerate(candles_dict):
            c_candles[i] = CCandle(
                open=float(c.get("open", 0)),
                high=float(c.get("high", 0)),
                low=float(c.get("low", 0)),
                close=float(c.get("close", 0)),
                volume=float(c.get("volume", 0)),
                timestamp=int(c.get("timestamp", c.get("time", 0)))
            )

        c_out = (ctypes.c_double * count)()
        res = cls._lib.calculate_atr_c(c_candles, count, period, c_out)
        if res:
            return list(c_out)
        return []

    @classmethod
    def detect_fvg(cls, candles_dict: List[dict], min_gap_pct: float = 0.0005) -> List[dict]:
        cls._init_library()
        count = len(candles_dict)
        if not cls._loaded or count < 3:
            return []

        c_candles = (CCandle * count)()
        for i, c in enumerate(candles_dict):
            c_candles[i] = CCandle(
                open=float(c.get("open", 0)),
                high=float(c.get("high", 0)),
                low=float(c.get("low", 0)),
                close=float(c.get("close", 0)),
                volume=float(c.get("volume", 0)),
                timestamp=int(c.get("timestamp", c.get("time", 0)))
            )

        max_out = 100
        c_out = (CFairValueGap * max_out)()
        found = cls._lib.detect_fvg_c(c_candles, count, min_gap_pct, c_out, max_out)

        results = []
        for i in range(found):
            results.append({
                "top": c_out[i].top,
                "bottom": c_out[i].bottom,
                "is_bullish": bool(c_out[i].is_bullish),
                "candle_index": c_out[i].candle_index
            })
        return results

    @classmethod
    def calculate_orb(cls, candles_dict: List[dict], orb_candles_count: int = 1) -> Tuple[float, float, bool]:
        cls._init_library()
        count = len(candles_dict)
        if not cls._loaded or count < orb_candles_count:
            return 0.0, 0.0, False

        c_candles = (CCandle * count)()
        for i, c in enumerate(candles_dict):
            c_candles[i] = CCandle(
                open=float(c.get("open", 0)),
                high=float(c.get("high", 0)),
                low=float(c.get("low", 0)),
                close=float(c.get("close", 0)),
                volume=float(c.get("volume", 0)),
                timestamp=int(c.get("timestamp", c.get("time", 0)))
            )

        orb = cls._lib.calculate_orb_c(c_candles, count, orb_candles_count)
        return orb.high, orb.low, bool(orb.is_valid)

# Initialize on module import
NativeCore._init_library()

"""Black-Scholes option greeks (owner directive 31-07-26).

Fyers' option chain gives price + OI but NOT implied volatility or greeks, so we compute them here:
implied volatility (inverted from the market price), delta, and theta. Used by the strike selector
to prefer strikes that actually move (delta), aren't over-priced by rich IV, and don't bleed too fast
to time decay (theta).

Pure-stdlib (math only), deterministic, no external deps. All functions are defensive: on any bad
input they return None rather than raising, so the trade path never breaks on a greeks failure.
"""
import math

RISK_FREE_RATE = 0.065          # ~India 1Y G-Sec; good enough for short-DTE greeks
_MIN_T = 0.5 / 365.0            # floor time-to-expiry at ~half a day to avoid div-by-zero at expiry


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _bs_price(spot, strike, t, r, iv, is_call):
    """Black-Scholes fair price of a European option."""
    if iv <= 0 or t <= 0 or spot <= 0 or strike <= 0:
        return None
    sqrt_t = math.sqrt(t)
    d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * t) / (iv * sqrt_t)
    d2 = d1 - iv * sqrt_t
    if is_call:
        return spot * _norm_cdf(d1) - strike * math.exp(-r * t) * _norm_cdf(d2)
    return strike * math.exp(-r * t) * _norm_cdf(-d2) - spot * _norm_cdf(-d1)


def implied_vol(price, spot, strike, t_years, is_call, r=RISK_FREE_RATE):
    """Invert the Black-Scholes price for implied volatility via bisection (price is monotonic in
    IV, so bisection is robust). Returns IV as a decimal (e.g. 0.18 = 18%), or None if unsolvable."""
    try:
        price = float(price); spot = float(spot); strike = float(strike)
        t = max(float(t_years), _MIN_T)
        if price <= 0 or spot <= 0 or strike <= 0:
            return None
        # Price must exceed intrinsic value for a solvable IV.
        intrinsic = max(0.0, (spot - strike) if is_call else (strike - spot))
        if price < intrinsic - 1e-6:
            return None
        lo, hi = 1e-4, 5.0
        p_lo = _bs_price(spot, strike, t, r, lo, is_call)
        p_hi = _bs_price(spot, strike, t, r, hi, is_call)
        if p_lo is None or p_hi is None:
            return None
        if not (p_lo <= price <= p_hi):
            # Price outside solvable band (deep ITM/at-vol-cap) — clamp sensibly.
            return None
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            pm = _bs_price(spot, strike, t, r, mid, is_call)
            if pm is None:
                return None
            if abs(pm - price) < 1e-4:
                return round(mid, 4)
            if pm < price:
                lo = mid
            else:
                hi = mid
        return round(0.5 * (lo + hi), 4)
    except Exception:
        return None


def compute_greeks(price, spot, strike, t_years, is_call, r=RISK_FREE_RATE):
    """Return {'iv', 'delta', 'theta_per_day'} for one option, or {} if it can't be computed.
    delta is signed (calls +, puts -); theta_per_day is the (negative) daily time decay."""
    try:
        iv = implied_vol(price, spot, strike, t_years, is_call, r)
        if iv is None or iv <= 0:
            return {}
        spot = float(spot); strike = float(strike)
        t = max(float(t_years), _MIN_T)
        sqrt_t = math.sqrt(t)
        d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * t) / (iv * sqrt_t)
        d2 = d1 - iv * sqrt_t
        if is_call:
            delta = _norm_cdf(d1)
            theta = (-(spot * _norm_pdf(d1) * iv) / (2 * sqrt_t)
                     - r * strike * math.exp(-r * t) * _norm_cdf(d2)) / 365.0
        else:
            delta = _norm_cdf(d1) - 1.0
            theta = (-(spot * _norm_pdf(d1) * iv) / (2 * sqrt_t)
                     + r * strike * math.exp(-r * t) * _norm_cdf(-d2)) / 365.0
        return {"iv": round(iv, 4), "delta": round(delta, 4), "theta_per_day": round(theta, 4)}
    except Exception:
        return {}

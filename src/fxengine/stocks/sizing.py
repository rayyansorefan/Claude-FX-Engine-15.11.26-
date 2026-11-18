"""Position sizing for the £2,500 paper account: ONE place, shared by the nightly account and the live 5-minute job so they can never disagree. Pure functions, no dependencies."""
START = 2500.0
RISK = 20.0                 # £ at risk per trade (1R), sized from the setup's own invalid-below level
MAX_POS = 0.25              # no position over 25% of the account
NO_STOP_PCT = 0.10          # a setup with no level is treated as 10% below entry
MIN_POSITION = 25.0         # below this it is not a meaningful position


def stop_for(invalidation, entry: float) -> tuple[float, bool]:
    """(stop price in the stock's own units, True if it is the default 10% because the setup has no level)."""
    if invalidation and 0 < invalidation < entry:
        return float(invalidation), False
    return entry * (1 - NO_STOP_PCT), True


def shares(ep_gbp: float, stop_gbp: float, equity: float, cash: float) -> tuple[float, str | None]:
    """(shares, reason-if-skipped). Risk £20, cap 25% of the account, never more than the cash available."""
    dist = ep_gbp - stop_gbp
    if dist <= 0:
        return 0.0, "invalid-below level is above the entry price"
    sh = min(RISK / dist, MAX_POS * equity / ep_gbp, cash / ep_gbp)
    if sh * ep_gbp < MIN_POSITION:
        return 0.0, "not enough free cash for a meaningful position"
    return sh, None

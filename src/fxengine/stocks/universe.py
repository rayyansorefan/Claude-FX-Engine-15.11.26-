"""Stock universe v1 (docs/STOCKS_PLAN.md). Stooq symbols: '<ticker>.us' for US, '<ticker>.uk' for London. Mostly available on Revolut:
the owner must confirm availability before any trade. Known bias: today's survivors only (flatters long-only results)."""
US_STOCKS = ("aapl msft nvda amzn googl meta tsla jpm v unh xom jnj wmt pg ma hd cvx mrk abbv ko pep cost avgo adbe crm nflx amd intc csco orcl qcom txn "
             "nke mcd dis ba cat gs ms bac wfc c t vz pfe lly tmo abt dhr ibm ge hon lmt ups sbux pypl low amgn").split()
US_ETFS = "spy qqq iwm dia xlk xlf xle xlv xly xlp xli xlu gld tlt".split()
UK_STOCKS = ("azn shel hsba ulvr bp gsk rio bats dge lseg rel ng vod barc lloy nwg glen aal tsco rr iag stan pru lgen expn fltr abf sse rkt").split()
UK_ETFS = "isf vusa cspx".split()

SYMBOLS = ([f"{t}.us" for t in US_STOCKS + US_ETFS] + [f"{t}.uk" for t in UK_STOCKS + UK_ETFS])
_ETF = {f"{t}.us" for t in US_ETFS} | {f"{t}.uk" for t in UK_ETFS}


def kind(sym: str) -> str:
    """Cost class: us | us_etf | uk | uk_etf."""
    return ("us" if sym.endswith(".us") else "uk") + ("_etf" if sym in _ETF else "")


def market(sym: str) -> str:
    return "US" if sym.endswith(".us") else "UK"

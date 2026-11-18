"""Stock universe v1 (docs/STOCKS_PLAN.md). Stooq symbols: '<ticker>.us' for US, '<ticker>.uk' for London. Mostly available on Revolut:
the owner must confirm availability before any trade. Known bias: today's survivors only (flatters long-only results)."""
US_STOCKS = ("aapl msft nvda amzn googl meta tsla jpm v unh xom jnj wmt pg ma hd cvx mrk abbv ko pep cost avgo adbe crm nflx amd intc csco orcl qcom txn "
             "nke mcd dis ba cat gs ms bac wfc c t vz pfe lly tmo abt dhr ibm ge hon lmt ups sbux pypl low amgn").split()
US_ETFS = "spy qqq iwm dia xlk xlf xle xlv xly xlp xli xlu gld tlt".split()
UK_STOCKS = ("azn shel hsba ulvr bp gsk rio bats dge lseg rel ng vod barc lloy nwg glen aal tsco rr iag stan pru lgen expn fltr abf sse rkt").split()
UK_ETFS = "isf vusa cspx".split()

# International large caps (Yahoo tickers without the exchange suffix). Revolut availability differs by country and changes: the owner confirms what he can trade;
# anything Yahoo does not carry simply shows up as a gap in the data report. Symbols are '<ticker>.<country code>'.
INTL = {
    "de": ("DE", "Germany", "EUR", "sap sie alv dte bas bmw mbg vow3 ads ifx muv2 dbk rwe eoan"),
    "fr": ("PA", "France", "EUR", "mc or tte san ai bnp cs su rms ker air dg sgo"),
    "nl": ("AS", "Netherlands", "EUR", "asml inga phia heia ad"),
    "it": ("MI", "Italy", "EUR", "eni isp ucg enel race"),
    "es": ("MC", "Spain", "EUR", "san bbva ibe itx tef"),
    "be": ("BR", "Belgium", "EUR", "abi kbc ucb"),
    "pt": ("LS", "Portugal", "EUR", "edp gal jmt"),
    "at": ("VI", "Austria", "EUR", "omv ebs voe"),
    "fi": ("HE", "Finland", "EUR", "nokia neste fortum sampo"),
    "ch": ("SW", "Switzerland", "CHF", "nesn rog novn ubsg zurn abbn cfr lonn"),
    "se": ("ST", "Sweden", "SEK", "volv-b eric-b atco-a hm-b seb-a sand"),
    "dk": ("CO", "Denmark", "DKK", "novo-b maersk-b dsv vws carl-b"),
    "no": ("OL", "Norway", "NOK", "eqnr dnb tel mowi"),
    "ca": ("TO", "Canada", "CAD", "ry td shop enb cnq bns cp cnr su bmo"),
    "au": ("AX", "Australia", "AUD", "bhp cba csl wbc nab wes mqg anz fmg rio"),
    "nz": ("NZ", "New Zealand", "NZD", "fph aia mel"),
    "jp": ("T", "Japan", "JPY", "7203 6758 9984 8306 6861 7974 9432 8035 9983 4063"),
    "hk": ("HK", "Hong Kong", "HKD", "0700 9988 0005 1299 0941 0388 2318 1810"),
    "sg": ("SI", "Singapore", "SGD", "d05 o39 u11 z74"),
    "kr": ("KS", "South Korea", "KRW", "005930 000660 035420 051910"),
    "tw": ("TW", "Taiwan", "TWD", "2330 2317 2454"),
    "in": ("NS", "India", "INR", "reliance tcs hdfcbank infy icicibank bhartiartl itc"),
    "br": ("SA", "Brazil", "BRL", "petr4 vale3 itub4 bbdc4 abev3"),
    "mx": ("MX", "Mexico", "MXN", "walmex gfnorteo"),
    "za": ("JO", "South Africa", "ZAR", "npn sol agl sbk fsr"),
    "il": ("TA", "Israel", "ILS", "teva nice lumi"),
}
MINOR_UNIT = {"uk": ("GBP", 100.0), "za": ("ZAR", 100.0), "il": ("ILS", 100.0)}        # quoted in pence / cents / agorot
USD_QUOTED = {"cspx.uk"}                                                                 # London-listed but quoted in US dollars
COUNTRY = {"us": "United States", "uk": "United Kingdom", **{k: v[1] for k, v in INTL.items()}}

INTL_SYMBOLS = [f"{t}.{m}" for m, (_, _, _, ts) in INTL.items() for t in ts.split()]
SYMBOLS = ([f"{t}.us" for t in US_STOCKS + US_ETFS] + [f"{t}.uk" for t in UK_STOCKS + UK_ETFS] + INTL_SYMBOLS)
_ETF = {f"{t}.us" for t in US_ETFS} | {f"{t}.uk" for t in UK_ETFS}


def country_code(sym: str) -> str:
    return sym.rsplit(".", 1)[-1]


def currency(sym: str) -> tuple[str, float]:
    """(ISO currency, divisor to the major unit): 'vod.uk' -> ('GBP', 100) because London quotes pence."""
    c = country_code(sym)
    if sym in USD_QUOTED or c == "us":
        return "USD", 1.0
    if c in MINOR_UNIT:
        return MINOR_UNIT[c]
    return (INTL[c][2], 1.0) if c in INTL else ("USD", 1.0)


def yahoo_symbol(sym: str) -> str:
    """'aapl.us' -> 'AAPL'; 'vod.uk' -> 'VOD.L'; 'sap.de' -> 'SAP.DE'; 'volv-b.se' -> 'VOLV-B.ST'."""
    t, c = sym.rsplit(".", 1)
    if c == "us":
        return t.upper().replace(".", "-")
    if c == "uk":
        return t.upper() + ".L"
    return f"{t.upper()}.{INTL[c][0]}" if c in INTL else t.upper()


def kind(sym: str) -> str:
    """Cost class: us | us_etf | uk | uk_etf | intl."""
    c = country_code(sym)
    if c in ("us", "uk"):
        return c + ("_etf" if sym in _ETF else "")
    return "intl"


def market(sym: str) -> str:
    return country_code(sym).upper()

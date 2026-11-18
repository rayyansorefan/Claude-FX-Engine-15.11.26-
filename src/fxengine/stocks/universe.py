"""Stock universe v1 (docs/STOCKS_PLAN.md). Stooq symbols: '<ticker>.us' for US, '<ticker>.uk' for London. Mostly available on Revolut:
the owner must confirm availability before any trade. Known bias: today's survivors only (flatters long-only results)."""
US_STOCKS = ("aapl msft nvda amzn googl meta tsla jpm v unh xom jnj wmt pg ma hd cvx mrk abbv ko pep cost avgo adbe crm nflx amd intc csco orcl qcom txn "
             "nke mcd dis ba cat gs ms bac wfc c t vz pfe lly tmo abt dhr ibm ge hon lmt ups sbux pypl low amgn").split()
US_STOCKS += ("acn adi adp aep aig amat amt anet aon apd axp bdx bk bkng blk bmy bsx ci cl cmcsa cme cmg cnc cof cop csx cvs d de dhi dow duk ecl emr eog etn ew fcx fdx fis gd gild gm hca hum "
              "ice intu isrg itw jci klac kmb lrcx mar mco mdlz mmc mmm mnst mo mpc nee nem nsc nxpi o orly oxy payx pgr pld pnc psa psx regn rost rtx schw shw slb so spg spgi syk tfc tgt tjx tmus trv "
              "usb vlo vrtx wm wmb zts adsk amp a ba cat cb csco dis ge gs hd ibm jnj jpm ko lly lmt low ma mcd mrk ms msft nke orcl pep pfe pg qcom sbux t tmo txn unh ups v vz wfc wmt xom").split()
US_STOCKS = list(dict.fromkeys(US_STOCKS))                 # de-duplicated, order kept
US_ETFS = "spy qqq iwm dia xlk xlf xle xlv xly xlp xli xlu gld tlt".split()
UK_STOCKS = ("azn shel hsba ulvr bp gsk rio bats dge lseg rel ng vod barc lloy nwg glen aal tsco rr iag stan pru lgen expn fltr abf sse rkt").split()
UK_ETFS = "isf vusa cspx".split()

# US-listed ADRs / cross-listings: companies from other countries that trade on US exchanges (so on Revolut, which offers US, EEA and UK listings). ticker -> company's home country code.
ADRS = {"tsm": "tw", "tm": "jp", "sony": "jp", "mfg": "jp", "hmc": "jp", "baba": "cn", "pdd": "cn", "jd": "cn", "bidu": "cn", "nio": "cn", "li": "cn", "infy": "in", "hdb": "in", "ibn": "in", "wit": "in",
        "vale": "br", "pbr": "br", "itub": "br", "bbd": "br", "nu": "br", "abev": "br", "meli": "ar", "shop": "ca", "ry": "ca", "td": "ca", "enb": "ca", "cnq": "ca", "bmo": "ca", "bns": "ca", "cp": "ca", "cni": "ca",
        "bhp": "au", "rio": "au", "se": "sg", "grab": "sg", "nvo": "dk", "sap": "de", "asml": "nl", "ing": "nl", "nvs": "ch", "ubs": "ch", "azn": "uk", "gsk": "uk", "bp": "uk", "shel": "uk", "hsbc": "uk",
        "ul": "uk", "deo": "uk", "bti": "uk", "lyg": "uk", "bcs": "uk", "vod": "uk", "sny": "fr", "ttE": "fr", "stm": "fr", "eqnr": "no", "nok": "fi", "eric": "se", "spot": "se", "wix": "il", "teva": "il",
        "chkp": "il", "cyber": "il", "kb": "kr", "skm": "kr", "pkx": "kr", "lpl": "kr", "tcom": "cn", "yum": "cn", "gold": "ca", "wpm": "ca", "fnv": "ca", "sqm": "cl", "ec": "co", "bap": "pe", "fmx": "mx",
        "ambev": "br", "amx": "mx", "cx": "mx", "tv": "mx", "gfi": "za", "ang": "za", "ntes": "cn", "yumc": "cn", "hdb2": "in"}
ADRS = {k.lower(): v for k, v in ADRS.items() if k not in ("hdb2", "ambev", "yum", "ttE", "li", "nio")}
ADRS.update({"tte": "fr"})
US_STOCKS = list(dict.fromkeys(list(US_STOCKS) + [t for t in ADRS if t not in US_STOCKS]))        # (the list above this line is rebuilt below with ADRs included)

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
COUNTRY = {"us": "United States", "uk": "United Kingdom", "cn": "China", "ar": "Argentina", "cl": "Chile", "co": "Colombia", "pe": "Peru", **{k: v[1] for k, v in INTL.items()}}


def home_country(sym: str) -> str:
    """The company's home country: for a US-listed ADR it differs from the listing (e.g. 'tsm.us' -> 'tw'); otherwise the listing country."""
    t, c = sym.rsplit(".", 1)
    return ADRS.get(t, c) if c == "us" else c

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


ALLOWED_FILE = "ops/stocks_countries.txt"


def allowed_countries(path: str = ALLOWED_FILE) -> set[str] | None:
    """Country codes the owner can actually trade on Revolut (one per line, e.g. us, uk, de; '#' comments allowed). None = no file = every market is shown.
    The research always uses every market (more evidence); only the setups shown, tracked for the paper account and tagged are limited to these."""
    from pathlib import Path
    f = Path(path)
    if not f.exists():
        return None
    codes = {ln.split("#")[0].strip().lower() for ln in f.read_text().splitlines()}
    codes = {c for c in codes if c}
    return codes or None


def resolve_country(name: str) -> str | None:
    """'Germany' / 'germany' / 'de' -> 'de' (None if unknown)."""
    n = name.strip().lower()
    if n in COUNTRY:
        return n
    for code, full in COUNTRY.items():
        if full.lower() == n:
            return code
    return {"usa": "us", "united states of america": "us", "america": "us", "britain": "uk", "england": "uk", "great britain": "uk", "korea": "kr", "holland": "nl", "uae": None}.get(n)

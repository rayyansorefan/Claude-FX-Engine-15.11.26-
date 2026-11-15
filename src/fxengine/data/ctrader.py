"""READ-ONLY cTrader Open API history fetcher (demo host). Sends ONLY: app auth, account list,
account auth, symbols list, get-trendbars. No order messages are imported or sent anywhere.
NOTE: written from library docs, NOT yet verified against the live server (needs keys).
cTrader trendbars are BID prices only; spread must be modelled separately."""
from __future__ import annotations
import logging
import pandas as pd
from twisted.internet import defer, reactor
from ctrader_open_api import Client, Protobuf, TcpProtocol, EndPoints
from ctrader_open_api.messages import OpenApiMessages_pb2 as M
from ctrader_open_api.messages import OpenApiModelMessages_pb2 as MM
from .decode import decode_trendbars
from . import store

log = logging.getLogger("ctrader")
PERIOD = {"M1": MM.M1, "M5": MM.M5, "M15": MM.M15, "M30": MM.M30, "H1": MM.H1, "H4": MM.H4, "D1": MM.D1}
# max span per request (conservative; the server caps bars per call)
CHUNK = {"M1": pd.Timedelta(days=5), "M5": pd.Timedelta(days=20), "M15": pd.Timedelta(days=60),
         "H1": pd.Timedelta(days=200)}
PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD", "EURGBP", "EURJPY", "GBPJPY"]


class Session:
    def __init__(self, env: dict):
        self.env = env
        self.client = Client(EndPoints.PROTOBUF_DEMO_HOST, EndPoints.PROTOBUF_PORT, TcpProtocol)
        self.account_id = None

    def _send(self, msg, timeout=30):
        return self.client.send(msg, responseTimeoutInSeconds=timeout)

    @defer.inlineCallbacks
    def _call(self, msg, timeout=30):
        res = yield self._send(msg, timeout)
        out = Protobuf.extract(res)
        if isinstance(out, M.ProtoOAErrorRes):
            raise RuntimeError(f"cTrader error {out.errorCode}: {out.description}")
        return out

    @defer.inlineCallbacks
    def connect(self):
        e = self.env
        self.client.startService()
        yield self.client.whenConnected()
        yield self._call(M.ProtoOAApplicationAuthReq(clientId=e["CTRADER_CLIENT_ID"], clientSecret=e["CTRADER_CLIENT_SECRET"]))
        accts = yield self._call(M.ProtoOAGetAccountListByAccessTokenReq(accessToken=e["CTRADER_ACCESS_TOKEN"]))
        want = e.get("CTRADER_LOGIN")
        pick = [a for a in accts.ctidTraderAccount if not a.isLive and (not want or str(a.traderLogin) == want)]
        if not pick:
            raise RuntimeError("no matching DEMO account on this token")
        self.account_id = pick[0].ctidTraderAccountId
        yield self._call(M.ProtoOAAccountAuthReq(ctidTraderAccountId=self.account_id, accessToken=e["CTRADER_ACCESS_TOKEN"]))
        syms = yield self._call(M.ProtoOASymbolsListReq(ctidTraderAccountId=self.account_id))
        self.symbols = {s.symbolName.replace("/", ""): s.symbolId for s in syms.symbol}

    @defer.inlineCallbacks
    def bars(self, symbol, tf, start, end):
        out = []
        step = CHUNK[tf]
        t = start
        while t < end:
            t2 = min(t + step, end)
            req = M.ProtoOAGetTrendbarsReq(ctidTraderAccountId=self.account_id, symbolId=self.symbols[symbol],
                                           period=PERIOD[tf], fromTimestamp=int(t.timestamp() * 1000),
                                           toTimestamp=int(t2.timestamp() * 1000))
            res = yield self._call(req, timeout=60)
            out.append(decode_trendbars(res.trendbar))
            t = t2
            yield _sleep(0.3)  # stay under the ~5 req/s historical limit
        return pd.concat(out) if out else decode_trendbars([])


def _sleep(s):
    d = defer.Deferred()
    reactor.callLater(s, d.callback, None)
    return d


@defer.inlineCallbacks
def fetch_all(env, pairs, tfs, years, root=store.ROOT):
    s = Session(env)
    yield s.connect()
    end = pd.Timestamp.now(tz="UTC").floor("min")
    for sym in pairs:
        for tf in tfs:
            last = store.last_open(sym, tf, root)
            start = (last if last is not None else end - pd.Timedelta(days=365 * years))
            df = yield s.bars(sym, tf, start, end)
            # drop the still-forming last bar: keep only closed candles
            from .timeframes import closed_only
            df = closed_only(df, tf, end)
            store.merge_save(sym, tf, df, root)
            log.info("%s %s +%d rows", sym, tf, len(df))

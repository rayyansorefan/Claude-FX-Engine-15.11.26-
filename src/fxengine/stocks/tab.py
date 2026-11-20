"""The Stocks tab for the FX Engine dashboard, written as two ready-made fragments the FX dashboard can include:
  docs/results/stocks_tab.html  - one <div class='tab' id='stocks'> section (its inner sections use their OWN class names, so the FX page's tab script is not confused)
  docs/results/stocks_tab.css   - extra styles, ALL scoped under #stocks (it reuses the FX page's own card / kpi / pill / chip / table styles, so it looks identical)
If these files are absent the FX dashboard simply shows no Stocks tab. Nothing in the FX engine depends on the stocks engine running."""
from __future__ import annotations
import json
from pathlib import Path
from . import dashboard as DB

CSS = """
#stocks .stnav{display:flex;gap:4px;overflow-x:auto;border-bottom:1px solid var(--line);margin:8px 0 12px}
#stocks .stnav button{background:none;border:0;color:var(--ink2);padding:7px 12px;font:600 11px inherit;font-family:inherit;letter-spacing:.06em;text-transform:uppercase;cursor:pointer;border-bottom:2px solid transparent;white-space:nowrap}
#stocks .stnav button.on{color:var(--ink);border-bottom-color:var(--s1)}
#stocks .stsec{display:none}#stocks .stsec.on{display:block}
#stocks .badge{display:inline-block;border-radius:4px;padding:1px 8px;font-size:10px;font-weight:700;letter-spacing:.06em;color:#fff;white-space:nowrap}
#stocks .badge.v{background:#0a6e0a}#stocks .badge.w{background:#8a5f00}#stocks .badge.x{background:#9c2b2b}#stocks .badge.n{background:var(--line);color:var(--ink2)}#stocks .badge.u{background:color-mix(in srgb,var(--s1) 35%,var(--card));color:var(--ink)}
#stocks .verdict.ok{border-color:var(--good);background:color-mix(in srgb,var(--good) 12%,var(--card))}#stocks .verdict.empty{border-color:var(--line);background:var(--card)}
#stocks .paperbanner{border:1px solid var(--s1);background:color-mix(in srgb,var(--s1) 10%,var(--card));border-radius:10px;padding:8px 14px;margin:0 0 12px;font-size:13px;color:var(--ink2)}
#stocks .scroll{overflow-x:auto}#stocks .scroll svg{min-width:640px}#stocks svg{width:100%;height:auto;display:block}
#stocks .gridl{stroke:var(--line);stroke-width:1}#stocks .zero{stroke:var(--mute);stroke-width:1.2;stroke-dasharray:4 3}#stocks .tick{fill:var(--mute);font-size:11px}
#stocks .rl{fill:var(--ink);font-size:13px;font-weight:600}#stocks .rs{fill:var(--mute);font-size:11px}#stocks .val{fill:var(--ink);font-size:12px;font-weight:600}
#stocks .ci{stroke-width:3;stroke-linecap:round}#stocks .ci.no{stroke:var(--s2)}#stocks .ci.ok{stroke:var(--good)}
#stocks .dot.no{fill:var(--s2);stroke:var(--card);stroke-width:2}#stocks .dot.ok{fill:var(--good);stroke:var(--card);stroke-width:2}#stocks .chal{fill:var(--s1)}
#stocks .legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px}
#stocks .rulecard h4{margin:0;font-size:15px}#stocks .rulecard .d{color:var(--mute);font-size:12px;margin:2px 0 10px}#stocks .rulecard .tag{float:right}
#stocks .nums{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px}#stocks .nums div{background:color-mix(in srgb,var(--bg) 55%,var(--card));border-radius:8px;padding:8px 10px}
#stocks .nums small{display:block;color:var(--mute);font-size:11px;text-transform:uppercase;letter-spacing:.07em}#stocks .nums b{font:600 16px ui-monospace,Menlo,monospace}
#stocks .chk{display:flex;gap:10px;flex-wrap:wrap;font-size:11.5px;margin:6px 0}#stocks .chk span{color:var(--mute)}#stocks .chk b.ok{color:#3fd13f}#stocks .chk b.no{color:#e0605a}
#stocks .paperbanner{margin-bottom:12px}#stocks .sel{display:flex;gap:6px;flex-wrap:wrap}#stocks .sel button{background:var(--card);border:1px solid var(--line);color:var(--ink2);border-radius:6px;padding:4px 10px;font:600 11px inherit;font-family:inherit;cursor:pointer}#stocks .sel button.on{border-color:var(--s1);color:var(--ink)}
#stocks .tag.f{background:#9c2b2b;color:#fff}#stocks .tag.p{background:#0a6e0a;color:#fff}#stocks .tag{display:inline-block;border-radius:4px;padding:1px 8px;font-size:10px;font-weight:700;letter-spacing:.06em}#stocks .empty{border:1px dashed var(--line);border-radius:10px;padding:18px;color:var(--ink2)}
#stocks ul.lim{margin:6px 0 0;padding-left:18px;color:var(--ink2);font-size:13.5px}#stocks ul.lim li{margin:4px 0}
"""
JS = ("<script>(function(){var r=document.getElementById('stocks');if(!r)return;var bs=r.querySelectorAll('.stnav button'),ss=r.querySelectorAll('.stsec');"
      "function go(k){bs.forEach(function(b){b.classList.toggle('on',b.dataset.s===k)});ss.forEach(function(s){s.classList.toggle('on',s.dataset.s===k)})}"
      "bs.forEach(function(b){b.onclick=function(){go(b.dataset.s)}});go('setups')})();</script>")


def _fresh(sp: dict | None) -> str:
    """How fresh the live data is, in plain words (the owner asked for data age to be always visible): minutes since the 5-minute job last updated, red if it is overdue on a weekday."""
    from datetime import datetime, timezone
    lv = (sp or {}).get("live") or {}
    try:
        t = datetime.strptime(lv["asof"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    except (KeyError, ValueError, TypeError):
        return "<span class='chip'>live prices: not running yet</span>"
    now = datetime.now(timezone.utc)
    m = max(0, int((now - t).total_seconds() // 60))
    market = now.weekday() < 5 and 6 <= now.hour < 22
    late = market and m > 20
    return f"<span class='chip' style='{'color:#e5534b;border-color:#e5534b' if late else ''}'>live prices updated {m} min ago{' · OVERDUE' if late else ''}</span>"


def fragment(res: dict | None, sp: dict | None = None, mk: dict | None = None, jr: dict | None = None, fl: dict | None = None) -> str:
    x = DB.parts(res, sp, mk, jr, fl)
    names = DB.SECTIONS
    nav = "".join(f"<button data-s='{k}'>{v}</button>" for k, v in names)
    secs = "".join(f"<div class='stsec' data-s='{k}'>{x[k]}</div>" for k, _ in names)
    return (f"<div class='tab' id='stocks'><div class='top' style='padding:0 0 4px'><span class='pill {x['state']}'>{x['label']}</span><span class='chip'>stocks · last close used {DB.E(x['asof'])}</span>{_fresh(sp)}"
            f"<span class='chip'>research only · never places an order</span></div><div class='stnav'>{nav}</div>{secs}{JS}</div>")


def load_journal() -> dict:
    from . import journal as J
    rows = J.load()
    return dict(J.pair(rows), raw=len(rows))


def write(res_path=Path("docs/results/stocks.json"), setups_path=None, out_dir=None) -> Path:
    rp = Path(res_path)
    out_dir = Path(out_dir) if out_dir else rp.parent
    sp_path = Path(setups_path) if setups_path else rp.with_name("stocks_setups.json")
    res = json.loads(rp.read_text()) if rp.exists() else None
    sp = json.loads(sp_path.read_text()) if sp_path.exists() else None
    mp = rp.with_name("stocks_market.json")
    mk = json.loads(mp.read_text()) if mp.exists() else None
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "stocks_tab.css").write_text(CSS)
    fp = rp.with_name("stocks_filters.json")
    (out_dir / "stocks_tab.html").write_text(fragment(res, sp, mk, load_journal(), json.loads(fp.read_text()) if fp.exists() else None))
    return out_dir / "stocks_tab.html"


if __name__ == "__main__":
    print("wrote", write())

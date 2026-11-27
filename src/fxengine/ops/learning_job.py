"""Standalone learning job runner: can be queued in ops/jobs.txt to run the learning pipeline outside the live loop.
Runs: shadow-replay, reinforce, scorecard, postmortem, and monitor. Saves all reports to docs/results/.
Used when you need to re-run learning on the VM without waiting for 21:20 UTC."""
import sys
from pathlib import Path
import pandas as pd

REPO = Path(__file__).resolve().parents[2]


def main():
    sys.path.insert(0, str(REPO / "src"))
    from fxengine.data import store
    from fxengine.live import db as DB

    # Open the live ledger
    conn = DB.connect(REPO / "data" / "engine.db")
    root = store.ROOT
    now = pd.Timestamp.utcnow()

    try:
        # 1. Shadow-replay finished trades
        from fxengine.learn import review as LR
        print("[1/5] Running shadow-replay on finished trades...")
        LR.daily(conn, root, now)

        # 2. Reinforce (update strategy weights)
        from fxengine.learn import reinforce as RF
        print("[2/5] Running reinforcement (nightly weights)...")
        for m in RF.nightly(conn, now):
            print(f"  {m}")

        # 3. Scorecard (strategy status)
        from fxengine.learn import scorecard as SCORE
        print("[3/5] Computing scorecard...")
        sc = SCORE.scorecard(conn)
        for strat, info in sorted(sc.items()):
            print(f"  {strat}: {info['n']} trades [{info['status']}] {info['mean']:+.2f}R")

        # 4. Post-mortem (loss analysis and separators)
        from fxengine.learn import postmortem as PM
        print("[4/5] Running post-mortem analysis...")
        res = PM.analyse(conn)
        PM.write_report(conn)
        print(f"  {res['n']} finished trades analyzed")
        for grp, hit in PM.labeled_hits(res):
            print(f"    {grp}: {hit['status']} {hit['name']}")

        # 5. Monitor (progress toward thresholds)
        from fxengine.learn import monitor as MON
        print("[5/5] Learning pipeline progress:")
        for line in MON.summary_text(conn).split("\n"):
            print(f"  {line}")

        # 6. Learning report (decisions)
        print("\n[DECISIONS] Friday weekly review (if today is Friday):")
        if now.day_of_week == 4:
            for m in LR.decide(conn, now):
                print(f"  {m}")

        LR.write_report(conn, now)
        print("\n✅ Learning job completed. Reports saved to docs/results/")
        conn.commit()
        return 0

    except Exception as e:
        print(f"\n❌ Learning job failed: {type(e).__name__}: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())

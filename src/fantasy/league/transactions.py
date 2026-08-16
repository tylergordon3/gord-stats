"""
League transaction data (waivers, free agents, trades) from Sleeper.

get_transactions(league_id) pulls every week's transaction log and flattens it
into one row per completed transaction:

    week          leg the move processed in (0 = preseason)
    type          waiver | free_agent | trade
    adds/drops    {sleeper_player_id: roster_id}
    waiver_bid    FAAB spent (waiver claims only)
    faab_moves    [{sender, receiver, amount}] (trades only)
    draft_picks   traded picks, as returned by Sleeper (trades only)
"""
import pandas as pd
from sleeper_wrapper import League
from tqdm import tqdm

# Transactions run past the fantasy regular season (playoff pickups, deadline
# trades), so pull the full NFL slate rather than clamping to week 14.
MAX_WEEK = 18

KEEP = ["transaction_id", "type", "status", "leg", "created", "creator",
        "roster_ids", "adds", "drops", "waiver_bid", "faab_moves", "draft_picks"]


def get_transactions(league_id: str) -> pd.DataFrame:
    """All completed transactions for a league, one row each, weeks 0..18."""
    league = League(league_id)
    rows = []
    for week in tqdm(range(0, MAX_WEEK + 1), desc="Loading transactions"):
        for t in league.get_transactions(week) or []:
            if t.get("status") != "complete":
                continue
            settings = t.get("settings") or {}
            rows.append({
                "transaction_id": t["transaction_id"],
                "type": t["type"],
                "status": t["status"],
                "leg": t.get("leg", week),
                "created": t.get("created"),
                "creator": t.get("creator"),
                "roster_ids": t.get("roster_ids") or [],
                "adds": t.get("adds") or {},
                "drops": t.get("drops") or {},
                "waiver_bid": settings.get("waiver_bid"),
                "faab_moves": t.get("waiver_budget") or [],
                "draft_picks": t.get("draft_picks") or [],
            })
    df = pd.DataFrame(rows, columns=KEEP)
    # A transaction only lives under one leg, but dedupe defensively.
    df = df.drop_duplicates(subset="transaction_id")
    return df.sort_values(["leg", "created"]).reset_index(drop=True)

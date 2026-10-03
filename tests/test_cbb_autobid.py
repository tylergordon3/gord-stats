"""The women's bracket gives a conference without a named champion its BEST
team as the auto-bid. Ovr is a rank (1 is best): idxmax picked the worst."""
import inspect

from cbb import predictions


def test_the_womens_fallback_auto_bid_is_the_best_ranked_team():
    src = inspect.getsource(predictions.predict_womens)
    assert '"Ovr"].idxmin()' in src and '"Ovr"].idxmax()' not in src
    # Ovr is assigned as a rank, best first, in the same function.
    assert 'df["Ovr"] = range(1, len(df) + 1)' in src
    assert 'sort_values("Rank", ascending=False)' in src

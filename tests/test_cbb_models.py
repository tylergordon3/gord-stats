"""The bracketology models are scikit-learn pickles, and a pickle loads only
under the scikit-learn that wrote it. The 2026 models were written by 1.2.2
and would not load at all under 1.9 - found by an audit five weeks before
tipoff, when the first in-season run would otherwise have been the test.

Loading and scoring them here makes a dependency bump that breaks them fail CI
instead. scikit-learn is pinned in pyproject.toml for the same reason; moving
the pin means retraining with src/cbb/models/train_*.py.
"""
import re
import warnings
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest
from sklearn.exceptions import InconsistentVersionWarning

from cbb import paths

# joblib's own unpickler sets ndarray.shape, which NumPy 2.5 deprecates: one
# warning per tree node, thousands a model, and nothing to do with these pickles.
pytestmark = pytest.mark.filterwarnings("ignore:Setting the shape on a NumPy array:DeprecationWarning")

PREDICTIONS = Path(__file__).parent.parent / "src" / "cbb" / "predictions.py"
LOADED = sorted(set(re.findall(r'"([\w-]+\.pkl)"', PREDICTIONS.read_text())))


def test_predictions_load_three_models():
    assert len(LOADED) == 3, LOADED


@pytest.mark.parametrize("name", LOADED)
def test_model_loads_under_the_installed_scikit_learn_and_scores(name):
    path = paths.ML_2026_DIR / name
    assert path.exists(), f"predictions.py loads {name}, which is not in {paths.ML_2026_DIR}"
    with warnings.catch_warnings():
        # A pickle from another version sometimes loads with only this warning
        # and then predicts wrongly, so it counts as a failure too.
        warnings.simplefilter("error", InconsistentVersionWarning)
        package = joblib.load(path)

    base = package["base_models"]
    stacked = []
    for key in ("logistic", "rf" if "rf" in base else "svc", "ada", "gb", "hgb"):
        model, features = base[key]["model"], base[key]["features"]
        row = pd.DataFrame(np.zeros((1, len(features))), columns=features)
        stacked.append(model.predict_proba(row)[:, 1])
    p = package["meta_model"].predict_proba(np.column_stack(stacked))[:, 1]
    assert 0.0 <= p[0] <= 1.0

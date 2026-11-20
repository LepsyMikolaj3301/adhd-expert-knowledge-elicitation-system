"""eval_agreement.py: Krippendorff's alpha against a worked example, and the bootstrap's shape.

scripts/rag is on pytest's pythonpath (pyproject.toml).
"""

import eval_agreement as ea
import numpy as np

# Krippendorff (2011), nominal data: four coders, twelve units, `None` = not coded. Alpha = 0.743.
KRIPPENDORFF = [
    [1, 2, 3, 3, 2, 1, 4, 1, 2, None, None, None],
    [1, 2, 3, 3, 2, 2, 4, 1, 2, 5, None, 3],
    [None, 3, 3, 3, 2, 3, 4, 2, 2, 5, 1, None],
    [1, 2, 3, 3, 2, 4, 4, 1, 2, 5, 1, None],
]


def counts_of(table, categories=5):
    units = []
    for unit in range(len(table[0])):
        values = [row[unit] for row in table if row[unit] is not None]
        units.append([values.count(c) for c in range(1, categories + 1)])
    return units


def test_alpha_matches_krippendorffs_worked_example():
    alpha = ea.alpha_from(ea.coincidences(counts_of(KRIPPENDORFF)))
    assert alpha == np.float64(alpha) and round(alpha, 3) == 0.743


def test_perfect_agreement_is_one_and_chance_is_about_zero():
    assert ea.alpha_from(ea.coincidences([[3, 0], [0, 3], [3, 0], [0, 3]])) == 1.0
    rng = np.random.default_rng(1)
    units = [list(np.bincount(rng.integers(0, 2, 6), minlength=2)) for _ in range(2000)]
    assert abs(ea.alpha_from(ea.coincidences(units))) < 0.05


def test_alpha_is_undefined_when_nobody_ever_differs_in_the_category_used():
    assert ea.alpha_from(ea.coincidences([[3, 0], [4, 0]])) is None
    assert ea.alpha_from(ea.coincidences([])) is None


def test_a_unit_read_by_one_coder_is_left_out():
    with_single = ea.coincidences([[2, 1], [0, 3], [1, 0]])
    without = ea.coincidences([[2, 1], [0, 3]])
    assert np.array_equal(with_single, without)


def test_the_interval_brackets_the_estimate_and_is_repeatable():
    per_vignette = {
        v: ea.coincidences([[3, 1], [1, 3], [4, 0], [0, 4]][: 2 + v % 3]) for v in range(12)
    }
    point, (low, high) = ea.bootstrap_alpha(per_vignette, np.random.default_rng(0), 500)
    assert low <= point <= high
    again = ea.bootstrap_alpha(per_vignette, np.random.default_rng(0), 500)
    assert again == (point, [low, high])

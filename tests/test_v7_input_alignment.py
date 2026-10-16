"""The HP source export must reproduce the historical data used by v7."""
import csv
from pathlib import Path
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[1] / 'Vensim'


def read_series(path):
    with path.open(encoding='latin-1', newline='') as stream:
        rows = list(csv.reader(stream))
    series = {row[0].strip().strip('"').lower(): np.array(row[1:], dtype=float)
              for row in rows[1:] if row}
    return rows[0], series


class V7InputAlignmentTests(unittest.TestCase):
    def test_hp_source_and_translation_use_the_same_history(self):
        header, source = read_series(ROOT / 'HPinput.csv')
        translated_header, translated = read_series(ROOT / 'HPinput_pysd_v7.csv')
        self.assertEqual(header, translated_header)
        self.assertEqual(source.keys(), translated.keys())
        for label in source:
            with self.subTest(series=label):
                self.assertTrue(np.isfinite(source[label]).all())
                np.testing.assert_array_equal(source[label], translated[label])


if __name__ == '__main__':
    unittest.main()

"""检查业务录入资料能否对账；不计算业务结果。"""

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SourceContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = json.loads((ROOT / "data" / "supplies.json").read_text(encoding="utf-8"))
        cls.schema = json.loads((ROOT / "data" / "fields.json").read_text(encoding="utf-8"))

    def rows(self, table):
        return self.source["tables"][table]

    def references(self, table, field, reference_table, reference_field):
        values = {row[reference_field] for row in self.rows(reference_table)}
        for row in self.rows(table):
            if row[field] is not None:
                self.assertIn(row[field], values, (table, row))

    def test_fields(self):
        self.assertTrue(self.source["synthetic"])
        self.assertEqual(set(self.schema), set(self.source["tables"]))
        for table, fields in self.schema.items():
            self.assertTrue(self.rows(table))
            for row in self.rows(table):
                self.assertEqual(set(fields), set(row), table)
                for field, accepted in fields.items():
                    self.assertIn(type(row[field]).__name__, accepted, (table, field))

    def test_source_relationships(self):
        self.references('readings', 'meter', 'meter_map', 'meter')
        self.references('readings', 'date', 'activity', 'date')
        self.references('activity', 'date', 'weather', 'date')
        self.references('signoffs', 'contract', 'protocol', 'contract')
        self.assertEqual({row['split'] for row in self.rows('weather')}, {'拟合', '留出', '分步投用', '改造后'})

    def test_measurement_calendar(self):
        self.references('calendar', 'date', 'weather', 'date')
        self.references('calendar', 'purpose', 'protocol', 'purpose')
        calendar = {(row['date'], row['purpose']): row for row in self.rows('calendar')}
        self.assertEqual(len(calendar), len(self.rows('weather')) * len(self.rows('protocol')))
        for row in self.rows('activity'):
            for purpose, field in [('活动室', 'activity_hours'), ('托育点', 'nursery_hours')]:
                entry = calendar[(row['date'], purpose)]
                self.assertEqual(entry['observed_hours'], row[field])
                if entry['state'] == '临时停用':
                    self.assertGreater(entry['scheduled_hours'], 0)
        reading_keys = {(row['date'], row['meter']) for row in self.rows('readings')}
        self.assertEqual(len(reading_keys), len(self.rows('readings')))
        self.assertTrue(all((row['date'], 'M0') in reading_keys for row in self.rows('weather')))
        effective = sorted(row['effective'] for row in self.rows('protocol'))
        for entry in self.rows('weather'):
            if entry['split'] == '分步投用':
                self.assertLessEqual(effective[0], entry['date'])
                self.assertLess(entry['date'], effective[1])
            if entry['split'] in ('拟合', '留出'):
                self.assertLess(entry['date'], effective[0])

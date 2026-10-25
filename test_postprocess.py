"""Boundary and corruption tests. No additional packages required."""
import copy
import unittest
from datetime import date
from postprocess import Processor, expected_mrz, valid_dates, visual, check_digit


def fixture():
    fields = dict(Last_name_ru='ИВАНОВ', First_name_ru='ИВАН', Middle_name_ru='ИВАНОВИЧ',
                  Sex_ru='МУЖ.', Birth_date='01.01.1999', Birth_place_ru='Г. МОСКВА',
                  Issue_date='01.02.2020', Issue_organisation_code='010-001',
                  Licence_number='01 20 123456', Issue_organization_ru='МВД ПО РЕСП. АДЫГЕЯ')
    viz = {k: {'box': [0, i*40, 500, 30], 'conf': .999,
               'lines': [{'text': v, 'box': [0, i*40, 500, 30], 'char_conf': [.999]*len(v)}]}
           for i, (k, v) in enumerate(fields.items())}
    return {'doc_id': 'synthetic', 'source': 'mobile', 'viz': viz,
            'mrz': {'lines': [{'text': s, 'char_conf': [.999]*44} for s in expected_mrz(fields)]}}, fields


class TestPostprocess(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.processor = Processor()

    def test_clean_document(self):
        d, f = fixture()
        answer, reason = self.processor.process(d)
        self.assertEqual(reason, 'accepted')
        self.assertEqual(answer['fields'], f)

    def test_check_digit_known_icao_example(self):
        self.assertEqual(check_digit('L898902C3'), '6')
        self.assertEqual(check_digit('740812'), '2')

    def test_mrz_number_layout(self):
        _, f = fixture()
        first, second = expected_mrz(f)
        self.assertEqual(first, 'PNRUSIVANOV<<IVAN<IVANOVI3<<<<<<<<<<<<<<<<<<')
        self.assertEqual(second[:9], '012123456')
        self.assertEqual(second[28], '0')
        self.assertEqual(len(second), 44)

    def test_corrupted_mrz_rejected(self):
        d, _ = fixture()
        line = d['mrz']['lines'][1]['text']
        d['mrz']['lines'][1]['text'] = line[:-1] + str((int(line[-1])+1)%10)
        self.assertEqual(self.processor.process(d)[1], 'mrz_mismatch')

    def test_visual_mrz_disagreement(self):
        d, _ = fixture()
        d['viz']['Last_name_ru']['lines'][0]['text'] = 'ИВАНОФ'
        self.assertEqual(self.processor.process(d)[1], 'mrz_mismatch')

    def test_missing_field_rejected(self):
        d, _ = fixture()
        d['viz']['Birth_place_ru'] = None
        self.assertEqual(self.processor.process(d)[0]['decision'], 'reject')

    def test_missing_patronymic_not_assumed_absent(self):
        d, _ = fixture()
        d['viz']['Middle_name_ru'] = None
        self.assertEqual(self.processor.process(d)[1], 'mrz_mismatch')

    def test_mobile_v2_rejected_despite_perfect_confidence(self):
        d, _ = fixture()
        d['source'] = 'mobile_v2'
        self.assertEqual(self.processor.process(d)[1], 'uncalibrated_source')

    def test_low_confidence_unprotected_text(self):
        d, _ = fixture()
        d['viz']['Birth_place_ru']['lines'][0]['char_conf'][0] = .94
        self.assertEqual(self.processor.process(d)[1], 'low_visual_confidence')

    def test_low_confidence_numeric_field_despite_matching_mrz(self):
        d, _ = fixture()
        d['viz']['Licence_number']['lines'][0]['char_conf'][0] = .9899
        self.assertEqual(self.processor.process(d)[1], 'low_visual_confidence')

    def test_low_confidence_mrz_despite_matching_text(self):
        d, _ = fixture()
        d['mrz']['lines'][0]['char_conf'][0] = .9899
        self.assertEqual(self.processor.process(d)[1], 'low_mrz_confidence')

    def test_missing_mrz_confidence(self):
        d, _ = fixture()
        d['mrz']['lines'][0].pop('char_conf')
        self.assertEqual(self.processor.process(d)[1], 'invalid_mrz_confidence')

    def test_invalid_mrz_confidence_nan_or_short_array(self):
        for value in [float('nan'), float('inf'), -1, 1.1, '0.999']:
            d, _ = fixture()
            d['mrz']['lines'][0]['char_conf'][0] = value
            self.assertEqual(self.processor.process(d)[1], 'invalid_mrz_confidence')
        d, _ = fixture()
        d['mrz']['lines'][0]['char_conf'].pop()
        self.assertEqual(self.processor.process(d)[1], 'invalid_mrz_confidence')

    def test_confidence_boundary_is_inclusive(self):
        d, _ = fixture()
        for f in d['viz'].values():
            for line in f['lines']:
                line['char_conf'] = [.99] * len(line['text'])
        for line in d['mrz']['lines']:
            line['char_conf'] = [.99] * 44
        self.assertEqual(self.processor.process(d)[1], 'accepted')

    def test_line_order_and_missing_lines(self):
        f = {'box': [0, 0, 300, 90], 'lines': [
            {'text': 'В', 'box': [0, 60, 300, 30], 'char_conf': [.99]},
            {'text': 'А', 'box': [0, 0, 300, 30], 'char_conf': [.99]},
            {'text': 'Б', 'box': [0, 30, 300, 30], 'char_conf': [.99]}]}
        self.assertEqual(visual(f), ('А Б В', .99, True))
        for i in range(3):
            broken = copy.deepcopy(f)
            broken['lines'].pop(i)
            self.assertFalse(visual(broken)[2])

    def test_invalid_calendar_and_future_issue(self):
        _, f = fixture()
        f['Birth_date'] = '31.02.1999'
        self.assertFalse(valid_dates(f))
        f['Birth_date'], f['Issue_date'] = '01.01.1999', '02.10.2026'
        self.assertFalse(valid_dates(f))

    def test_20_year_grace_boundary(self):
        f = {'Birth_date': '01.01.2000', 'Issue_date': '01.02.2014'}
        self.assertTrue(valid_dates(f, date(2020, 3, 31)))
        self.assertFalse(valid_dates(f, date(2020, 4, 1)))

    def test_45_year_expiry_and_replacement(self):
        f = {'Birth_date': '01.01.1980', 'Issue_date': '01.02.2000'}
        self.assertFalse(valid_dates(f))
        f['Issue_date'] = '01.01.2025'
        self.assertTrue(valid_dates(f))

    def test_under_14_issue(self):
        f = {'Birth_date': '01.01.2010', 'Issue_date': '31.12.2023'}
        self.assertFalse(valid_dates(f))


if __name__ == '__main__':
    unittest.main()

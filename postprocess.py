"""Conservative, offline Russian passport OCR postprocessing (Python 3.9+)."""
import argparse
import calendar
import csv
import json
import re
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AS_OF = date(2026, 10, 1)
MIN_CONFIDENCE = .99
FIELDS = ('Last_name_ru', 'First_name_ru', 'Middle_name_ru', 'Sex_ru',
          'Birth_date', 'Birth_place_ru', 'Issue_date', 'Issue_organisation_code',
          'Licence_number', 'Issue_organization_ru')
TRANSLIT = dict(zip('АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ',
                    'ABVGDE2JZIQKLMNOPRSTUFHC34WXY9678'))


def norm(s):
    return ' '.join(str(s or '').split()).upper()


def read_jsonl(path):
    with open(path, encoding='utf-8') as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def parse_date(s):
    if not re.fullmatch(r'\d{2}\.\d{2}\.\d{4}', s):
        raise ValueError('date format')
    day, month, year = map(int, s.split('.'))
    return date(year, month, day)


def anniversary(birth, years):
    year = birth.year + years
    return date(year, birth.month,
                min(birth.day, calendar.monthrange(year, birth.month)[1]))


def valid_dates(fields, as_of=AS_OF):
    """Only calendar/age validity; loss, replacement and registry status are unknown."""
    try:
        birth, issued = parse_date(fields['Birth_date']), parse_date(fields['Issue_date'])
    except (ValueError, KeyError, TypeError):
        return False
    if not date(1900, 1, 1) <= birth <= issued <= as_of:
        return False
    if issued < max(date(1997, 10, 1), anniversary(birth, 14)):
        return False
    for age in (20, 45):
        birthday = anniversary(birth, age)
        if issued < birthday and as_of > birthday + timedelta(days=90):
            return False
    return True


def check_digit(text):
    values = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    return str(sum((0 if c == '<' else values.index(c)) * (7, 3, 1)[i % 3]
                   for i, c in enumerate(text)) % 10)


def encode_name(s):
    return ''.join('<' if c in ' -' else TRANSLIT[c] for c in s)


def expected_mrz(fields):
    name = 'PNRUS' + encode_name(fields['Last_name_ru']) + '<<'
    name += encode_name(fields['First_name_ru']) + '<' + encode_name(fields['Middle_name_ru'])
    first = name[:44].ljust(44, '<')
    number = fields['Licence_number'].replace(' ', '')
    serial = number[:3] + number[4:]
    birth = parse_date(fields['Birth_date']).strftime('%y%m%d')
    issued = parse_date(fields['Issue_date']).strftime('%y%m%d')
    extra = number[3] + issued + fields['Issue_organisation_code'].replace('-', '') + '<'
    second = serial + check_digit(serial) + 'RUS' + birth + check_digit(birth)
    second += {'МУЖ.': 'M', 'ЖЕН.': 'F'}[fields['Sex_ru']] + '<<<<<<<'
    second += extra + check_digit(extra)
    second += check_digit(second[:10] + second[13:20] + second[21:43])
    return first, second


def visual(field):
    """Recover reading order, reject missing lines from geometry and malformed scores."""
    if not isinstance(field, dict) or not field.get('lines'):
        return '', 0.0, False
    lines = sorted(field['lines'], key=lambda l: (l['box'][1], l['box'][0]))
    box = field['box']
    heights = sorted(l['box'][3] for l in lines)
    height = heights[len(heights) // 2]
    complete = height > 0 and box[3] > 0
    complete &= lines[0]['box'][1] - box[1] < .6 * height
    complete &= box[1] + box[3] - (lines[-1]['box'][1] + lines[-1]['box'][3]) < .6 * height
    complete &= all(b['box'][1] - (a['box'][1] + a['box'][3]) < .6 * height
                    for a, b in zip(lines, lines[1:]))
    scores = []
    for line in lines:
        cc = line.get('char_conf', [])
        complete &= len(cc) == len(line['text'])
        scores.extend(cc)
    complete &= all(isinstance(c, (int, float)) and 0 <= c <= 1 for c in scores)
    return norm(' '.join(l['text'] for l in lines)), min(scores, default=0), complete


class Processor:
    def __init__(self):
        self.units = defaultdict(set)
        with (ROOT / 'reference' / 'subdivisions.csv').open(encoding='utf-8') as stream:
            for row in csv.DictReader(stream):
                self.units[row['code']].add(norm(row['name']))

    def process(self, document):
        answer = {'doc_id': document['doc_id'], 'decision': 'reject'}
        if document.get('source') != 'mobile':
            return answer, 'uncalibrated_source'
        fields, confidence = {}, {}
        for key in FIELDS:
            value, score, complete = visual(document.get('viz', {}).get(key))
            if key == 'Middle_name_ru' and document.get('viz', {}).get(key) is None:
                value, score, complete = '', 1.0, True  # Must also agree with MRZ.
            if not complete:
                return answer, 'missing_or_incomplete:' + key
            fields[key], confidence[key] = value, score
        # Matching MRZ is not independent confirmation: correlated errors exist.
        # Even checksum-protected numeric fields must pass the confidence gate.
        if min(confidence.values()) < MIN_CONFIDENCE:
            return answer, 'low_visual_confidence'
        if not re.fullmatch(r'\d{2} \d{2} \d{6}', fields['Licence_number']):
            return answer, 'number_format'
        if fields['Issue_organisation_code'] not in self.units:
            return answer, 'unknown_unit'
        if not valid_dates(fields):
            return answer, 'invalid_dates'
        try:
            expected = expected_mrz(fields)
        except (ValueError, KeyError, IndexError):
            return answer, 'field_format'
        mrz = document.get('mrz') or {}
        lines = mrz.get('lines', [])
        if len(lines) != 2 or tuple(l['text'] for l in lines) != expected:
            return answer, 'mrz_mismatch'
        for line in lines:
            scores = line.get('char_conf')
            if not isinstance(scores, list) or len(scores) != 44:
                return answer, 'invalid_mrz_confidence'
            if not all(isinstance(c, (int, float)) and 0 <= c <= 1 for c in scores):
                return answer, 'invalid_mrz_confidence'
            if min(scores) < MIN_CONFIDENCE:
                return answer, 'low_mrz_confidence'
        answer.update(decision='accept', fields=fields)
        return answer, 'accepted'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input')
    parser.add_argument('output')
    parser.add_argument('--diagnostics', help='Optional rejection reasons JSONL')
    args = parser.parse_args()
    if Path(args.input).resolve() == Path(args.output).resolve():
        parser.error('input and output must differ')
    if args.diagnostics and Path(args.diagnostics).resolve() in {
            Path(args.input).resolve(), Path(args.output).resolve()}:
        parser.error('diagnostics must not overwrite input or output')
    processor = Processor()
    seen = set()
    diagnostics = open(args.diagnostics, 'w', encoding='utf-8') if args.diagnostics else None
    try:
        with open(args.output, 'w', encoding='utf-8') as out:
            for document in read_jsonl(args.input):
                if document['doc_id'] in seen:
                    raise ValueError('duplicate doc_id: ' + document['doc_id'])
                seen.add(document['doc_id'])
                answer, reason = processor.process(document)
                out.write(json.dumps(answer, ensure_ascii=False) + '\n')
                if diagnostics:
                    diagnostics.write(json.dumps({'doc_id': document['doc_id'], 'reason': reason}) + '\n')
    finally:
        if diagnostics:
            diagnostics.close()


if __name__ == '__main__':
    main()

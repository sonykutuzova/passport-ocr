"""Reproduce strict-policy checks. The original holdout has already been reused."""
import hashlib
import json
import time
from collections import Counter
from postprocess import ROOT, FIELDS, Processor, norm, read_jsonl, valid_dates


def main():
    started = time.perf_counter()
    split = json.loads((ROOT/'split.json').read_text())
    holdout = set(split['holdout'])
    labels = {d['doc_id']: d['fields'] for d in read_jsonl(ROOT/'data/train_labels.jsonl')}
    result = {'policy': 'strict_mobile_all_char_confidence_0.99',
              'validation_status': 'retrospective; original holdout reused during revision',
              'postprocess_sha256': hashlib.sha256((ROOT/'postprocess.py').read_bytes()).hexdigest()}
    processor = Processor()
    for subset in ['development', 'reused_holdout', 'test']:
        counts = {'documents': 0, 'accepted': 0, 'wrong': 0, 'invalid_accepted': 0}
        by_source, errors, reasons = {}, [], Counter()
        path = ROOT / ('data/test_predictions.jsonl' if subset == 'test'
                       else 'data/train_predictions.jsonl')
        for d in read_jsonl(path):
            if subset != 'test' and ((d['doc_id'] in holdout) != (subset == 'reused_holdout')):
                continue
            counts['documents'] += 1
            answer, reason = processor.process(d)
            reasons[reason] += 1
            source = by_source.setdefault(d['source'], {'documents': 0, 'accepted': 0, 'wrong': 0})
            source['documents'] += 1
            if answer['decision'] == 'accept':
                counts['accepted'] += 1
                source['accepted'] += 1
                if subset != 'test':
                    wrong = [k for k in FIELDS
                             if norm(answer['fields'][k]) != norm(labels[d['doc_id']][k])]
                    if wrong:
                        counts['wrong'] += 1
                        source['wrong'] += 1
                        errors.append({'doc_id': d['doc_id'], 'fields': wrong})
                    counts['invalid_accepted'] += not valid_dates(labels[d['doc_id']])
        if subset == 'test':
            counts['wrong'] = counts['invalid_accepted'] = None
            for s in by_source.values():
                s['wrong'] = None
        result[subset] = {**counts, 'by_source': by_source, 'errors': errors, 'reasons': dict(reasons)}
        print(subset, counts)
    result['forecast'] = {
        'accepted': result['test']['accepted'],
        'wrong_point_estimate': 0,
        'method': 'Empirical error rate 0 / 45 on reused labeled data; not an independent risk estimate.',
        'zero_error_guarantee': False,
        'test_labels_available': False,
    }
    result['elapsed_seconds'] = time.perf_counter() - started
    (ROOT/'metrics.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    # Zero observed false accepts is an executable regression requirement.
    for subset in ('development', 'reused_holdout'):
        assert result[subset]['wrong'] == 0, 'False accepts on ' + subset
        assert result[subset]['invalid_accepted'] == 0, 'Invalid documents on ' + subset


if __name__ == '__main__':
    main()

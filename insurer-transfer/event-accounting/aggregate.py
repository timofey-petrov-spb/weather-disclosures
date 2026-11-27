"""Compute table-slice and full-filing counts from source-reviewed row assignments."""
from collections import Counter
from pathlib import Path
from statistics import mean
import hashlib
import json


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fraction(n, d):
    return n / d if d else None


def tally(reference, assignments):
    by_id = {r['id']: r for r in reference}
    table = [r for r in assignments if r['scope']=='table']
    extracted = [r for r in table if not r['review']]
    supported = [r for r in extracted if r.get('ref') is not None]
    anchored = {r['ref'] for r in supported}
    signed = {r['ref'] for r in supported if r['signed']}
    full = {r['ref'] for r in supported if r['full']}
    assert anchored<=by_id.keys() and full<=signed<=anchored
    neg = {r['id'] for r in reference if r['signed_low_usd']<0 or r['signed_high_usd']<0}
    number_only={r['relaxed_amount_event_reference'] for r in extracted if r.get('relaxed_amount_event_reference')} | anchored
    assert all(r.get('ref') is not None or not (r.get('full') or r.get('signed')) for r in extracted)
    correct_measure_wrong_owner={r['relaxed_amount_event_reference'] for r in extracted if r['disposition']=='wrong_owner' and r.get('relaxed_amount_event_reference')}
    return dict(reference=len(reference), automatic=len(extracted),relaxed_number_and_event=len(number_only),
                correct_measure_wrong_owner=len(correct_measure_wrong_owner),
                true_negative_rate=None,
                relaxed_number_and_event_recall=fraction(len(number_only),len(reference)),relaxed_number_and_event_precision=fraction(len(number_only),len(extracted)),
                distinct_amount=len(anchored),distinct_signed=len(signed),distinct_full=len(full),
                amount_recall=fraction(len(anchored),len(reference)),signed_recall=fraction(len(signed),len(reference)),
                full_recall=fraction(len(full),len(reference)),full_precision=fraction(len(full),len(extracted)),
                distinct_amount_precision=fraction(len(anchored),len(extracted)),supported_row_precision=fraction(len(supported),len(extracted)),
                negative_reference=len(neg),signed_negatives=len(neg & signed),negative_signed_recall=fraction(len(neg & signed),len(neg)),
                unsupported=len(extracted)-len(supported),duplicates=len(supported)-len(anchored),review_only=len(table)-len(extracted),
                missing_amount=sorted(by_id.keys()-anchored),missing_full=sorted(by_id.keys()-full),
                table_dispositions=dict(Counter(r['disposition'] for r in table)),
                outside_table_automatic=sum(r['scope']=='outside' and not r['review'] for r in assignments),
                outside_table_review=sum(r['scope']=='outside' and r['review'] for r in assignments),
                outside_table_by_disposition=dict(Counter(r['disposition'] for r in assignments if r['scope']=='outside')))


def aggregate(verified, adjudicated):
    results={}
    ref=verified['claims']
    for version,docs in adjudicated['predictions'].items():
        whole=[]
        per_doc={}
        for d,v in docs.items():
            rows=v['rows']
            assert [r['index'] for r in rows]==list(range(len(rows)))
            for r in rows:
                assert r['scope'] in ('table','outside') and r['reason']
            per_doc[d]=tally([c for c in ref if c['doc_id']==d],rows)
            whole.extend(rows)
        pooled=tally(ref,whole)
        rates=[v['amount_recall'] for v in per_doc.values() if v['reference']]
        precisions=[v['distinct_amount_precision'] for v in per_doc.values() if v['automatic']]
        frames={key:tally([c for c in ref if c['doc_id'] in verified[key]],
                          [r for d in verified[key] for r in docs[d]['rows']])
                for key in ('original_roster','reserve_supplement')}
        results[version]=dict(by_filing=per_doc,by_sampling_frame=frames,pooled=pooled,macro_amount_recall=mean(rates) if rates else None,
                              macro_filing_count=len(rates),macro_precision=mean(precisions) if precisions else None,
                              macro_precision_filing_count=len(precisions))
    return results


if __name__=='__main__':
    folder=Path(__file__).resolve().parent
    refs=folder/'independent-reference.json'
    decisions=folder/'judgments.json'
    out=dict(scoring_protocol_sha256=digest(folder/'scoring-protocol.json'),
             source_review_sha256=digest(refs),judgments_sha256=digest(decisions),
             versions=aggregate(read(refs),read(decisions)))
    (folder/'score.json').write_bytes((json.dumps(out,ensure_ascii=False,indent=2)+'\n').encode())

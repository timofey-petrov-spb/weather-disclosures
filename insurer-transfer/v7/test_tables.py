"""Synthetic table contracts and known-source regression tests (development only)."""
from collections import Counter
import json
from pathlib import Path
import unittest
from extract import table_records
from source_reader import VisibleText

ROOT = Path(__file__).resolve().parents[1]


def run(body, target='Yara'):
    body = ('<html><body><p>For the quarterly period ended September 30, 2024.</p>'+
            body+'</body></html>').encode()
    parser = VisibleText()
    parser.feed(body.decode())
    parser.close()
    parser.flush()
    rows = [dict(doc_id='TEST',passage_id='TEST-P%05d'%i,text=text,kind=kind,event=target,issuer='Example',
                 source_url='https://example.org',source_kind='10-Q') for i,(kind,_,text) in enumerate(parser.rows,1)]
    return table_records(rows,body)


class TableTests(unittest.TestCase):

    def test_columns_swapped_and_unit_scaled(self):
        for reverse in (True,False):
            name=['Hurricane Yara','Hurricane Nova','Total storms']
            amount=['($11.2)','$38','$49.2']
            if reverse: name.reverse(); amount.reverse()
            table='<table><tr><th>(USD in millions)</th>'+''.join('<th>'+x+'</th>' for x in name)+'</tr>'
            table+='<tr><td>Net losses incurred</td>'+''.join('<td>'+x+'</td>' for x in amount)+'</tr></table>'
            for event,sign in [('Yara',-11_200_000),('Nova',38_000_000)]:
                rs=run(table,event)
                self.assertEqual([r['signed_usd'] for r in rs],[sign])
                point=rs[0]['table_observations'][0]
                self.assertEqual(point['amount_cell']['column'],point['event_cell']['column'])
                self.assertIn(event,point['event_cell']['text'])
                self.assertEqual(rs[0]['basis'],'net of reinsurance')

    def test_rows_with_stacked_headers_periods_and_same_amount(self):
        body='''<table><tr><th rowspan="2">(USD in millions, pre-tax and net of reinsurance)</th>
            <th colspan="3">Losses incurred</th><th rowspan="2">Estimated ultimate losses</th></tr>
            <tr><th>September 30, 2023</th><th>June 30, 2024</th><th>September 30, 2024</th></tr>
            <tr><td>Hurricane Nova</td><td>99</td><td>98</td><td>97</td><td>96</td></tr>
            <tr><td>Hurricane Yara</td><td>5</td><td>6</td><td>17</td><td>17</td></tr>
            <tr><td>Total</td><td>104</td><td>104</td><td>114</td><td>113</td></tr></table>'''
        rs=run(body)
        self.assertEqual([(r['status'],r['signed_usd']) for r in rs],[('incurred',17_000_000),('ultimate estimate',17_000_000)])
        self.assertTrue(all(r['basis']=='net of reinsurance' and r['tax_basis']=='pretax' for r in rs))
        self.assertEqual([r['table_observations'][0]['amount_cell']['column'] for r in rs],[4,5])
        self.assertEqual(rs[0]['table_observations'][0]['metric_cell']['colspan'],3)

    def test_repetitions_and_lookalike_year_amount(self):
        table='''<table><tr><th>(USD in thousands)</th><th>Hurricane Yara</th></tr>
            <tr><td>Claims expenses</td><td>2024</td></tr>
            <tr><td>Combined loss ratio</td><td>54</td></tr></table>'''
        rs=run(table+table)
        self.assertEqual([(r['signed_usd'],len(r['table_observations'])) for r in rs],[(2_024_000,2)])
        self.assertEqual([o['amount_cell']['table'] for o in rs[0]['table_observations']],[1,2])

    def test_fragmented_sign_event_colspan_and_segment(self):
        body='''<table><tr><th>(USD in thousands)</th><th colspan="3">Hurricane Yara</th><th>Other events</th></tr>
            <tr><td>Impact on Marine segment underwriting result</td><td>(</td><td>43</td><td>)</td><td>90</td></tr>
            <tr><td>Net claims incurred</td><td>−</td><td>2</td><td></td><td>19</td></tr></table>'''
        rs=run(body)
        self.assertEqual([r['signed_usd'] for r in rs],[-43000,-2000])
        self.assertEqual(rs[0]['segment'],'Marine segment')
        self.assertEqual(len(rs[0]['table_observations'][0]['sign_cells']),2)

    def test_storm_as_caption_and_ambiguous_currency(self):
        base='''<table><caption>Hurricane Yara</caption><tr><th>({units})</th><th>September 30, 2024</th></tr>
        <tr><td>Assumed premiums earned</td><td>{amount}</td></tr></table>'''
        self.assertEqual([r['signed_usd'] for r in run(base.format(units='USD in thousands',amount='42'))],[42000])
        self.assertEqual(run(base.format(units='in thousands of Canadian dollars',amount='$42')),[])
        self.assertEqual(run(base.format(units='in thousands',amount='42')),[])

    def test_wrong_entity_percent_joint_label_and_prose(self):
        table='''<table><tr><th>(USD in millions)</th><th>{header}</th></tr>
        <tr><td>Industry-wide losses</td><td>3</td></tr><tr><td>Gross loss ratio</td><td>3</td></tr>
        <tr><td>Net losses incurred</td><td>3%</td></tr><tr><td>Losses paid</td><td>4</td></tr></table>'''
        for header in ['Hurricanes Yara and Nova','Hurricane Yara & Nova','Aggregate losses including Hurricane Yara','Hurricane Nova']:
            self.assertEqual(run('<p>Hurricane Yara was mentioned.</p>'+table.format(header=header)),[])
        self.assertEqual([r['measure'] for r in run(table.format(header='Hurricane Yara'))],['Losses paid'])

    @unittest.skipUnless((ROOT/'panel_audit/panel_reference.json').is_file() and
                         (ROOT/'insurer-panel/travelers/source_reference.json').is_file() and
                         (ROOT/'v7/dev/renaissance.json').is_file(),'local development reference files required')
    def test_real_table_results_compare_source_references(self):
        dev=ROOT/'v7/dev'
        travelers=json.loads((ROOT/'insurer-panel/travelers/source_reference.json').read_text(encoding='utf8'))['claims']
        out=json.loads((dev/'travelers.json').read_text(encoding='utf8'))
        def key(r):
            return (r['doc_id'],r['low_usd'],'ultimate' if 'ultimate' in r['status'] else 'incurred')
        self.assertEqual(Counter(map(key,out)),Counter(map(key,travelers)))
        for r in out:
            self.assertEqual((r['tax_basis'],r['basis'],r['signed_usd']),('pretax','net of reinsurance',r['low_usd']))
            self.assertGreater(len(r['table_observations']),0)
        refs=json.loads((ROOT/'panel_audit/panel_reference.json').read_text(encoding='utf8'))['claims']
        refs=[r for r in refs if r['doc_id'] in {'RQ','RK'}]
        out=json.loads((dev/'renaissance.json').read_text(encoding='utf8'))
        self.assertEqual(Counter((r['doc_id'],r['measure'],r['signed_usd']) for r in out),
                         Counter((r['doc_id'],r['measure'],r['signed_economic_effect_usd']) for r in refs))
        for r in out:
            ref=next(s for s in refs if s['measure']==r['measure'] and s['doc_id']==r['doc_id'])
            self.assertTrue(set(ref['passage_ids']) & set(r['evidence_passage_ids']))
            self.assertTrue(set(ref['unit_header_ids']) & set(r['evidence_passage_ids']))
            self.assertTrue(set(ref['event_column_header_ids']) & set(r['evidence_passage_ids']))
            self.assertEqual(r['unit_scale'],1000)
            if r['segment']: self.assertIn(r['segment'],ref['affected_entity'])
            if r['doc_id']=='RQ': self.assertEqual(len(r['observed_windows']),2)

    @unittest.skipUnless((ROOT/'v6/dev/hci.json').is_file() and (ROOT/'v7/dev/hci.json').is_file(),
                         'local development outputs required')
    def test_earlier_development_outputs(self):
        for name in ['chubb','elliott','allstate','hci','michael','irma']:
            v6=(ROOT/'v6/dev'/(name+'.json')).read_bytes()
            self.assertEqual(v6,(ROOT/'v7/dev'/(name+'.json')).read_bytes(),name)


if __name__=='__main__':
    unittest.main()

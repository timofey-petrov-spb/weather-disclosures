"""Regression probes for attribution in mixed storm disclosures."""
import unittest

from extract import allocated_rows, refine


def item(text,event,idx=1):
    return dict(doc_id='F',passage_id=f'F-P{idx:05d}',text=text,kind='paragraph',source_kind='10-K',
                event=event,issuer='Coastal Mutual',source_url='https://example.org/filing',accession='TEST')


def facts(text,event):
    return allocated_rows(item(text,event),(None,'FY2024','F-P00001'),'Coastal Mutual',None)


class AllocationTests(unittest.TestCase):
    def test_source_order_and_units(self):
        for sentence in (
            'Pre-tax catastrophe losses included Hurricane Lumen losses of $1.25 billion, Winter Storm Vega losses of $170 million, and other weather events.',
            'Pre-tax catastrophe losses included Winter Storm Vega losses of $170 million and Hurricane Lumen losses of $1.25 billion.'
        ):
            for event,expected in [('Lumen',1250000000),('Vega',170000000)]:
                rs=facts(sentence,event)
                self.assertEqual([(r['low_usd'],r['high_usd'],r['tax_basis']) for r in rs],[(expected,expected,'pretax')])
                self.assertEqual(rs[0]['basis'],None)
                self.assertEqual(rs[0]['allocation_evidence'],sentence[slice(*rs[0]['allocation_span'])])
                self.assertEqual(rs[0]['event_quarter'],None)

    def test_joint_and_industry_controls(self):
        cases=[
            'Hurricane Lumen and Winter Storm Vega losses of $400 million were reported.',
            'The estimated losses of $400 million from Hurricane Lumen and Winter Storm Vega were reported.',
            'Industry-wide catastrophe losses included Hurricane Lumen losses of $1 billion and Winter Storm Vega losses of $400 million.',
            'The policy limit for Hurricane Lumen losses of $700 million became effective this January.',
            'The group estimated hurricane Lumen losses of up to CAD$40 million.',
            'Hurricane Lumen losses of $20 million to $30 million were possible.',
            'Hurricane Lumen and Winter Storm Vega accounted for $45 million together.',
        ]
        for sentence in cases:
            for event in ('Lumen','Vega'):
                self.assertEqual(facts(sentence,event),[],(sentence,event))

    def test_tax_and_status_are_local(self):
        text='Hurricane Lumen estimated gross losses of approximately $50 million pre-tax, and Winter Storm Vega net losses of $11 million after tax.'
        first=facts(text,'Lumen')[0];second=facts(text,'Vega')[0]
        self.assertEqual((first['status'],first['basis'],first['tax_basis'],first['approximate_amount']),('estimate','gross','pretax',True))
        self.assertEqual((second['status'],second['basis'],second['tax_basis']),('reported','net','after_tax'))

    def test_event_after_money_and_unsupported_allocations(self):
        sentence='Catastrophe losses included $100 million attributable to Hurricane Lumen and $25 million attributable to Winter Storm Vega.'
        self.assertEqual([r['low_usd'] for r in facts(sentence,'Lumen')],[100000000])
        self.assertEqual([r['low_usd'] for r in facts(sentence,'Vega')],[25000000])
        self.assertFalse(facts('Premiums included $100 million from Hurricane Lumen and $25 million from Winter Storm Vega.','Vega'))
        self.assertFalse(facts(sentence,'Missing'))

    def test_explicitly_ordered_event_list(self):
        t='Losses from Hurricanes Lumen and Vega were $62 million and $7 million, respectively.'
        for event,num in (('Lumen',62000000),('Vega',7000000)):
            self.assertEqual([r['low_usd'] for r in facts(t,event)],[num])
            self.assertFalse(facts(t.replace(', respectively',''),event))
            self.assertFalse(facts(t.replace('Losses','Gross and net losses'),event))

    def test_dedup_preserves_conflicting_bases(self):
        rows=[item('For the fiscal year ended December 31, 2024','Lumen',1),
              item('Pre-tax catastrophe losses included Hurricane Lumen losses of $20 million and Winter Storm Vega losses of $12 million.','Lumen',2),
              item('Pre-tax catastrophe losses included Hurricane Lumen losses of $20 million and Winter Storm Vega losses of $12 million.','Lumen',3),
              item('After-tax catastrophe losses included Hurricane Lumen losses of $20 million and Winter Storm Vega losses of $12 million.','Lumen',4)]
        rs=refine(rows,[])
        self.assertEqual(len(rs),2)
        self.assertEqual(rs[0]['evidence_passage_ids'],['F-P00002','F-P00003'])
        self.assertEqual({r['tax_basis'] for r in rs},{'pretax','after_tax'})


if __name__=='__main__':
    unittest.main()


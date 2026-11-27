"""Synthetic transfer and counterexample checks for filing-level event binding."""
import unittest
from extract import refine, single_clause, tax_pair, named_bundle, only_event

def row(i,text,kind='paragraph'):
    return dict(doc_id='T',passage_id=f'T-P{i:05d}',text=text,kind=kind,event='Zeta',issuer='Fictional Holdings',source_url='https://example.test/t',source_kind='10-Q')
def make(c=1,wrong=22,joint=False):
    info=('Hurricane Zeta and Winter Storm Iota' if joint else 'Hurricane Zeta')
    return [row(1,'For the quarterly period ended September 30, 2025'),row(2,'Coastal Segment Results'),
           row(3,info+' estimated gross losses, excluding Public Flood Fund expenses, totaled $90 million, pre-tax, which will be reduced by $40 million in anticipated reinsurance recoveries for a net estimated loss of $50 million.'),
           row(4,'Catastrophe losses by the type of event'),row(5,'Three months ended September 30,'),
           row(6,'($ in millions) | Number of events | 2025 | Number of events | 2024','table_row'),
           row(7,f'Hurricanes/Tropical storms (1) | {c} | $ | 62 | 3 | $ | {wrong}','table_row'),
           row(8,'(1)2025 includes $12 million of claims expenses related to the Public Flood Fund.')]
class Regression(unittest.TestCase):
    def test_bridge_numeric_and_source_evidence(self):
        r=refine(make(),[])
        self.assertEqual([(x['low_usd'],x['basis']) for x in r],[(90000000,'gross'),(40000000,'ceded'),(50000000,'net'),(62000000,'net_including_expenses'),(12000000,'program_expense_component')])
        self.assertTrue(all(x['issuer']=='Coastal segment' for x in r))
        self.assertEqual(len(r[-1]['supporting_passage_ids']),6)
    def test_multi_event_controls(self):
        self.assertFalse(refine(make(joint=True),[]))
        self.assertEqual(len(refine(make(2),[])),3)
        x=make();x[-1]['text']='(1)2024 includes $12 million of expenses related to the Public Flood Fund.'
        self.assertEqual(len(refine(x,[])),3)
        x=make();x[-1]['text']='(1)2025 includes $10 million of expenses related to the Public Flood Fund.'
        self.assertEqual(len(refine(x,[])),3)
    def test_tax_equivalents(self):
        rs=[row(1,'For the quarterly period ended September 30, 2025'),row(2,'Losses from Hurricane Zeta were $80 million pre-tax and $64 million after tax, net of reinsurance.')]
        hits=refine(rs,[]);self.assertEqual([(x['low_usd'],x['tax_basis'],x['basis']) for x in hits],[(80000000,'pretax','net'),(64000000,'after_tax','net')])
    def test_no_invented_component(self):
        x=make(); x[2]['text']=x[2]['text'].replace('$90 million','$110 million')
        self.assertFalse(any(x['source_channel']=='explicit_financial_bridge' for x in refine(x,[])))
    def test_partial_date_and_other_program(self):
        x=make();x[-1]['text']='(1)2025 includes $12 million of expenses related to the Pension Plan.'
        self.assertEqual(len(refine(x,[])),3)
        self.assertFalse(only_event('Hurricane Zeta and Wildfire Delta damaged property.','Zeta'))
    def test_nearby_paragraph_requires_explicit_anaphor(self):
        a=[row(1,'Hurricane Zeta struck in September 2025.'),row(2,'For this event, our net losses were $30 million.')]
        self.assertEqual([x['low_usd'] for x in refine(a,[])],[30000000])
        a[1]['text']='For the quarter, our net losses were $30 million.'
        self.assertEqual(refine(a,[]),[])

if __name__=='__main__':unittest.main()


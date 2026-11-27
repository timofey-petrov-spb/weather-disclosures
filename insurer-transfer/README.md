# Testing hurricane loss extraction on new insurers

Allstate's November 2022 quarterly filing put its gross Hurricane Ian loss at **$671 million**, excluding National Flood Insurance Program claim expenses. It expected $305 million back from reinsurers and an estimated net loss of $366 million. Its annual filing reported gross and net losses for Ian and Winter Storm Elliott together. The investor reading both filings needs to know which numbers can be assigned to Ian. [Quarterly filing](https://www.sec.gov/Archives/edgar/data/899051/000089905122000079/all-20220930.htm) · [Annual filing](https://www.sec.gov/Archives/edgar/data/899051/000089905123000020/all-20221231.htm)

## Results

| Issuer and test status | Original method | First revision | Final revision |
|---|---:|---:|---:|
| HCI, two development filings | 4/23 | 23/23 | 23/23 |
| Allstate, two filings first opened as a transfer test | 0/5 | **0/5 on first transfer** | 5/5 after development on these filings |
| Chubb, two final held-out filings | 1/2 | 1/2 | **1/2 on final transfer** |

Figures count distinct filing-specific amounts attributed to the correct storm and supported by the source. The final output contained 23 automatic HCI records, five Allstate records and one Chubb record. There were no unsupported automatic amounts on these three sets in the final run. HCI's source review still found one missing recognition quarter, leaving 22/23 financially complete records. Allstate's five comprise three direct and two table-linked figures. All five met the source review's field and context checks after development on Allstate.

Chubb recorded a **$975m pre-tax loss** from Ian in both the quarterly and annual filings. The final extractor found the quarterly disclosure. Its year-end sentence also named a $400m loss from Winter Storm Elliott, and the extractor skipped the Ian amount. The original method also found the quarterly amount only. The quarterly reporting period is supported by the text and the filing cover. The separate economic event-period field stayed empty. A financial-context check credits one of two filings; a check requiring that explicit event-period field credits zero. The two reference entries concern the same underlying estimate. [Chubb 10-Q](https://www.sec.gov/Archives/edgar/data/896159/000089615922000014/cb-20220930.htm) · [Chubb 10-K](https://www.sec.gov/Archives/edgar/data/896159/000089615923000007/cb-20221231.htm)

## Why the earlier method missed 19 HCI disclosures

HCI's two filings contain 23 individually labelled monetary facts. The earlier method found four distinct amounts with a defensible source and event. Of the other 19, the method proposed no matching amount for 17 facts. For one more, the correct $23.2m was held for review. Another proposed the wrong-scale $847,500 for review when the original statement meant $847.5m. [All 19 cases and source passages](hci-misses.md)

| Failure in the earlier method | Distinct missed facts |
|---|---:|
| Unrecognised accounting treatment, including an allowance, a reversal and a premium | 5 |
| Allocation of a consolidated loss across two named subsidiaries | 4 |
| Claims development and liability tables | 4 |
| Lost event context for retained losses and their components | 3 |
| Wrong unit multiplier in the notes | 1 |
| Unresolved status for a valid segment expense | 1 |
| Explicitly allocated list with several storms | 1 |

Several figures overlap economically. The annual report's $32.998m in paid claims and $32.327m in outstanding claims liability answer different questions. A second $32.327m appears under a different concept for incurred-but-not-reported losses and expected development. Checking the accounting concept matters even when the number and event are right. [HCI 10-Q](https://www.sec.gov/Archives/edgar/data/1400810/000095017022023815/hci-20220930.htm) · [HCI 10-K](https://www.sec.gov/Archives/edgar/data/1400810/000095017023007271/hci-20221231.htm)

## Method and limits

The revised reader uses the source HTML and the filing's inline accounting tags when available. It reads the reporting entity, accounting concept and units alongside the text, follows lists of components and uses separate fields for payments, reserves, reinsurance expenses and estimates. The final revision also reads gross loss, expected recoveries and net loss within a single sentence, and checks the number of events in the relevant table column before using a footnote. Every automatic record retains its source passage. [First revision](v4/extract.py) · [Final revision](v5/extract.py)

The first revision was developed on HCI. For its first transfer test the issuer, the two forms and the scoring criteria were fixed before predictions were read. Allstate was new to the method. The source review distinguishes three directly named monetary facts from two amounts requiring the hurricane row and NFIP footnote. The $378m table entry includes $12m of flood-program claim expenses and the 2022 column covers one hurricane or tropical storm. In the annual form two storms share a total. No year-end dollar figure could be assigned to Ian alone. [Allstate selection](allstate-selection.json)

A second transfer cohort and the rule for further development were specified by the evaluator before that evaluator opened the Allstate predictions. The plan called for one more revision if the first revision found fewer than half of Allstate's five facts. The initial zero was retained. Allstate then became development data. The final method was locked before its Chubb run. All three issuers reported on the same storm, so the final test measures transfer to a different issuer and document style. The source lists were prepared without viewing test predictions. [Chubb selection and decision rule](chubb-selection.json) · [Scoring rules](scoring-protocol.json) · [Source ledger and predictions](scores.json)

## Reproduce the runs

Python 3.10 or newer and its standard library are sufficient. From this directory run:

```sh
python replay.py --output replay-output
```

This downloads the six original SEC submissions from the mirror listed in [the source roster](filings.json), verifies their SHA-256 digests, rebuilds each passage and compares each extractor's full outputs with the recorded runs. To run offline supply `--primary-files /path/to/verified/html/files` with CQ.htm, CK.htm, AQ.htm, AK.htm, BQ.htm and BK.htm. [Earlier eight-filing study](../insurance-disclosures.ipynb)

A single issuer with a few individually attributable figures cannot establish accuracy across the insurance sector. The source review is an internal document audit. Operational outages, press releases and time to detection were outside this test.

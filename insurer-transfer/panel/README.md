# Which hurricane does the loss belong to?

Chubb reported a $975 million pre-tax loss from Hurricane Ian and a $400 million pre-tax loss from Winter Storm Elliott in the same sentence. An earlier extractor skipped Ian’s annual disclosure. The revised method reads the grammatical link between each event and its amount. This change fixed the Chubb example. On four previously unseen insurers the gain was one additional figure, from **1/39 to 2/39**. [Chubb annual filing](https://www.sec.gov/Archives/edgar/data/896159/000089615923000007/cb-20221231.htm) · [Four-insurer findings and sources](findings.md)

## Chubb development check

| Named event requested | Quarter ended September 30, 2022 | Year ended December 31, 2022 |
|---|---:|---:|
| Ian | $975m | $975m |
| Elliott | No record | $400m |

The two Ian disclosures repeat one underlying amount. Both annual amounts are pre-tax. The source does not specify their individual gross or net reinsurance basis, so that field remains open. Running the two event queries against the same original documents verifies both directions. On the earlier Allstate control, the text gave a single combined amount for two storms. It yielded no annual Ian-only amount. [Chubb 10-Q](https://www.sec.gov/Archives/edgar/data/896159/000089615922000014/cb-20220930.htm) · [Output and evidence for both event queries](chubb-check.json) · [Source code](../v6/extract.py)

## Test on four new insurers

The method, cohort and scoring rules were [committed before either version was run on the panel](https://github.com/timofey-petrov-spb/weather-disclosures/commit/80b6032928a9eb04e057b826c79bcb558056aa7a). The panel uses the original third-quarter and annual primary filings of four issuers. It measures transfer to new disclosures about Ian. The source readers identified 39 distinct financial measures across the eight original filings before opening the predictions. Each fact is counted once per filing, with repetitions in the same filing collapsed when the financial measure and effective amount are equivalent.

| Insurer | Earlier amount–event matches | Revised matches | Cases sent to review by the revision |
|---|---:|---:|---:|
| Travelers | 0/4 | 0/4 | 0 |
| Progressive | 1/12 | 2/12 | 0 |
| Hartford | 0/5 | 0/5 | 6 |
| RenaissanceRe | 0/18 | 0/18 | 0 |

All three automatic records came from Progressive's quarterly filing. Two matched the amount and the hurricane. One treated potential reinsurance capacity for a future second event as a loss from Ian. Neither supported amount had the correct complete financial record. The $1.4bn gross estimate belonged to the Property business. The roughly $570m loss belonged to Personal Lines. Both segment assignments were wrong. Six additional Hartford candidates went to review and earned no automatic credit. [Progressive 10-Q](https://www.sec.gov/Archives/edgar/data/80661/000008066122000080/pgr-20220930.htm) · [Row-level scoring for both versions](score.json)

At Travelers the storm is a row with several distinct loss columns. At RenaissanceRe the storm is a column over multiple financial rows. Those two table layouts account for 22 of the 39 reference measures, all missed. At Hartford a review candidate read $214 million as $214 after losing the filing-wide unit. This leaves a concrete follow-up experiment: recover row labels, column headers, units and reporting entity together, then test that change on another panel. [Detailed error analysis](findings.md) · [Source reference ledger](reference.json)

## Reproduce the comparison

From a checkout of this repository run:

```sh
python insurer-transfer/panel/run_panel.py --output panel-replay
```

Use `--case chubb_elliott` for a single development check. For an offline run, provide `--primary-files DIRECTORY` containing the primary HTML named by document ID in [the source roster](filings.json). Python 3.10 or newer and its standard library are sufficient. The runner verifies each original filing’s digest, reconstructs the source passages and compares both versions’ complete outputs with [the recorded fingerprints](output-digests.json). The record-level assessment is a separate source review. [Selection](selection.json) · [Scoring definitions](scoring-protocol.json) · [Earlier study](../README.md)

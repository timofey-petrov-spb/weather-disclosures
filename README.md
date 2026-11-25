# Hurricane Disclosures

A research pilot initiated by Timofey Petrov for his Mila × MSCI application. The study asks what an analyst could have known from company filings on a given date after a hurricane.

[Read the two-page case study](case-study.pdf) · [Download the offline explorer](explorer.html?raw=true) · [Challenge description](https://www.msci-institute.com/education/research-challenges/mila-and-msci-institute-ai-research-challenge/)

## One estimate can appear in two filings

Community Health Systems reported approximately $7 million in lost revenue and additional response expenses from Hurricane Helene for Q3 2024. It disclosed that estimate twice. An analyst aggregating both records would count the same financial impact twice. [Earnings release](https://www.sec.gov/Archives/edgar/data/1108109/000095017024116674/cyh-ex99_1.htm) · [Quarterly filing](https://www.sec.gov/Archives/edgar/data/1108109/000095017024117088/cyh-20240930.htm)

| Evaluation on filings from two hospital operators | Observed result |
| --- | --- |
| Search over 11 submissions and 15,886 passages | Retrieved 36 passages including both disclosures of the $7m estimate |
| Frozen rules | Extracted neither amount with its attributed financial meaning |
| Second extractor, followed by a literal evidence check | 6 of 11 proposals passed the check. Two linked the $7m to Helene and both missed the period and status. None recovered every field. |

The second extractor attributed a $265 million asset sale to a storm. The amount appears in the filing as the purchase price. The results come from two issuers and one distinct reference estimate. [Asset sale announcement](https://www.sec.gov/Archives/edgar/data/1108109/000095017024130250/cyh-ex99_1.htm) · [Evaluation counts](results/issuer_validation.json) · [Exploratory run summary](results/model_run_summary.json)

## Run the historical replay

Requires Python 3.12. The replay, explorer and tests use no external packages. Open `explorer.html` locally for the interactive version. Switch HCA Healthcare from 31 October 2024 to 24 January 2025 to see its fourth-quarter forecast followed by an estimate once the quarter had ended.

```console
python scripts/timeline.py --issuer HCA --as-of 2024-10-31T23:59:59Z
python scripts/timeline.py --issuer HCA --as-of 2025-01-24T12:40:45Z
python -m unittest discover -s tests
```

The replay uses selected source-reviewed examples. It treats SEC acceptance time as a proxy for public availability. The study uses archived National Hurricane Center bulletins and SEC reports. For the frozen rules test, rebuild the new-issuer text corpus from the pinned archive and run the evaluation:

```console
python scripts/collect_validation.py --fetch
python scripts/check_validation.py
```

The [filing inventory](data/evaluation_filings.json) and [source audit](data/validation_reference.json) link to the underlying evidence. This portfolio edition includes the historical replay, collector and rules baseline, alongside a summary of the separate exploratory model run.

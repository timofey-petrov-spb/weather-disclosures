# Linking storm losses to the right table

## Eight source cells recovered in development

| Filing | What the revised reader recovered |
|---|---|
| [21st Century Holding](https://www.sec.gov/Archives/edgar/data/1069996/000114420406012513/v039025_10k.htm) | Katrina with the August 25 date in parentheses. The hurricane-season header supplies 2005. The two-part headings distinguish $14.6m in gross losses, $11.6m in ceded recoveries and $3.0m in net losses. The count of 2,076 claims stays outside the dollar results. |
| [Maiden Holdings](https://www.sec.gov/Archives/edgar/data/1412100/000141210013000009/mhld-20121231x10k.htm) | The preceding paragraph names Sandy and reports $31.1m. The table separately gives $6.5m for Maiden US, $22.6m for Maiden Specialty and $2.0m for the ACAC quota share. The revised reader requires the printed components to sum to the printed total and match the paragraph's figure. |
| [Safety Insurance Group](https://www.sec.gov/Archives/edgar/data/1172052/000104746913002988/a2213726z10-k.htm) | The paragraph ties $7.977m to Sandy at year-end. The table prints the same amount in thousands in the 2012 hurricane category, alongside $7.025m for 2011. The event amount, reporting-period end and section-level unit all have to agree. |

The previous version located none of the eight selected cells. The revision matched 8/8 printed USD values at the original cell locations. On six edited copies it reacted as expected to changes in dates, amounts, the named storm and the reconciliation. The six earlier full outputs from the event-accounting study also reproduced with identical canonical fingerprints. [Development source-cell audit](development.json) · [Earlier-report regressions](prior-regression.json)

## What transferred to other insurance groups

The table search found no eligible **native HTML** table in the original-source screen that was completed. The published candidate log covers reachable sources, and the registered roster remains incomplete. A positive-table recall rate is therefore unavailable from this screen. A separate comparison used five other insurance groups and explicit statements in their original HTML filings. Its passage reference was sealed before either reader was run. [Screen](screen.json) · [Source assertions](reference.json) · [Reference seal](https://github.com/timofey-petrov-spb/weather-disclosures/commit/b15eba10a8beea4c41ae84a18543a736405b2c1e)

| Insurer | Automatically returned numeric targets from the audited passages | Key observation |
|---|---:|---|
| Berkshire Hathaway | 0 applicable | Both versions flagged the $3.4bn loss for review. Its published scope is Katrina, Rita and Wilma together. |
| Tower Group | 3/4 | The $80.1m after-tax loss was flagged for review. Three automatic amounts matched but their structured owner fields omitted the commercial segment, Reciprocal Exchanges, and the exclusion of Reciprocal Exchanges, respectively. |
| White Mountains | 1/1 | Both found $44m from Katrina and incorrectly attached the $91m combined subtotal to Katrina as well. |
| State Auto Financial | 1/1 | The $7.3m Sandy amount matched the dated earnings release. |
| Hagerty | 1/1 | Two places report $3.7m from Milton. Those duplicate disclosures counted once. |

Both versions gave identical canonical outputs on the five documents. Each found **6/7 exact amounts in the audited passages**, after deduplication, and assigned **one of nine specifically audited distractors** to the wrong event scope. The numeric score gives no credit for owners or accounting qualifiers. The audited claims and controls are a limited source-selected sample. They are not an exhaustive evaluation of the five documents. [Results by source and passage](score.json)

The signed −$818m and −$809m Katrina entries in Liberty Mutual's September 2005 release supplied a separate table exercise. Both readers missed the two cells in the transcribed HTML excerpt. The source release is a PDF and the transcription was limited to the target header, section and row. This tests the reader on that layout after transcription. Liberty Mutual later acquired State Auto, so the two sources do not supply two independent groups. [Original Liberty Mutual release](https://www.libertymutualgroup.com/about-lm/news/media/1651) · [Transcription exercise](liberty-results.json)

## Replay

From a checkout of the repository, use Python 3.10 or later.

```sh
python insurer-transfer/event-linkage/replay_study.py --output event-linkage-replay
python insurer-transfer/event-linkage/score.py event-linkage-replay --output scored.json
python insurer-transfer/event-linkage/check_development.py --primary-files event-linkage-replay/primary --output development.json
python insurer-transfer/event-linkage/liberty_check.py --output liberty-results.json
```

The first command checks original source bytes, frozen methods, extracted passages and complete output fingerprints. The second rebuilds the passage audit counts. The third runs the development cases against original filings and changes disposable copies for the controls. [Method freeze and dependency hashes](../v11/lock.json)


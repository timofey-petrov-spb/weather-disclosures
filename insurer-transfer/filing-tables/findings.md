# Did the table reader transfer to other insurers?

The prospective panel contains 16 Katrina-specific USD amounts from three original FY2005 annual SEC filings. Five cells carry a negative accounting sign. An independent reading verified the source bytes, row, column, period, currency scale, signed value and financial meaning before either extractor was run. These historical disclosures test transfer to a different storm, period and group of issuers at the same time.

| Insurer | Eligible facts | Correct number and event, ignoring the financial label | Correct number, event and financial measure | Negative facts correctly linked |
|---|---:|---:|---:|---:|
| PartnerRe | 4 | 1 | 0 | 0/3 |
| XL Capital | 11 | 0 | 0 | 0/2 |
| Aspen Insurance Holdings | 1 | 0 | 0 | No negative reference |
| Total | 16 | 1 | 0 | 0/5 |

Both frozen versions returned identical results. One automatic prediction came from a selected table, with no duplicate or review-only table proposals. It matched the printed storm and number but failed the registered financial-measure criterion. Precision for correctly characterized selected-table records is 0/1. There were no complete records in the sample.

PartnerRe's Katrina row in table 36 shows four contributions in USD millions. Net losses and loss expenses were −563, acquisition costs −2, reinstatement or additional premiums earned +54 and the impact on pre-tax net income −511. Both versions labeled $54 million as catastrophe losses. Several negative amounts span two source cells, with the closing parenthesis in a separate cell. [PartnerRe filing](https://www.sec.gov/Archives/edgar/data/911421/000119312506043961/d10k.htm)

XL repeats the storm name inside three accounting sections. The Katrina figures have separate Insurance, Reinsurance, Financial Products and Services, and consolidated columns. The financial-products recovery is a dash, leaving 11 distinct amounts. No output was anchored in the selected table. A prose output elsewhere linked $1.27 billion to the right storm, but labeled that estimated loss net of recoveries as an insurance recovery. [XL filing](https://www.sec.gov/Archives/edgar/data/875159/000093041306001850/c41009_10k.htm)

Aspen's Property Reinsurance table reports $427.5 million for Katrina in 2005. The same physical row also reports $15.3 million for California brush fires in the 2003 block. The text following the table says FY2005 losses and loss adjustment expenses are stated after deducting reinsurance recoveries. Neither reader returned a record from this table. [Aspen filing](https://www.sec.gov/Archives/edgar/data/1267395/000095013606001663/file001.htm)

Outside the three selected tables, each version returned seven automatic proposals and three review candidates. All seven contained an error in the financial assertion. Three assigned multistorm amounts to Katrina and one assigned an industry estimate to Aspen. The reader emitted Aspen's $25 million potential derivative recovery twice, once as claims losses and once as reinsurance recoveries. The source explicitly identifies a derivative contract. Full-filing recall would require a reference covering every passage.

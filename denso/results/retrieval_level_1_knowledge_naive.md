# Retrieval evaluation (level_1_knowledge, mode=naive, min evidence recall 60%)

| | hit@1 | hit@3 | hit@5 | hit@10 | hit@20 |
|---|---|---|---|---|---|
| any citation | 68% | 82% | 93% | 93% | 93% |
| all citations | 50% | 71% | 89% | 93% | 93% |

## hit@10 (any citation) by category

| Category | hit@10 | N |
|---|---|---|
| cross_document | 100% | 4 |
| direct_fact | 88% | 8 |
| multilingual | 100% | 2 |
| procedure | 100% | 5 |
| table_data | 100% | 5 |
| troubleshooting | 75% | 4 |

## Not retrieved within top 10

- Q6 (direct_fact): ranks [None]; top-3 retrieved: ['AC Compressor Installation Manual.md', 'EN_AC Compressor oil_troubleshooting_bulletin', 'DENSO-AC_brochure_tips-and-tricks_EN.md']
- Q20 (troubleshooting): ranks [None]; top-3 retrieved: ['DENSO-AC_brochure_tips-and-tricks_EN.md', 'DENSO-AC_brochure_tips-and-tricks_EN.md', 'AC Compressor Installation Manual.md']

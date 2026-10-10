# Fact-based scores (level_1_nvidia_prompt; 30 questions answered in every mode)

| Mode | Fact recall | All facts present | Abstention correct | Scored (facts/abst./prose) |
|---|---|---|---|---|
| naive | 89% | 77% | 50% | 22/2/6 |
| mix | 82% | 64% | 50% | 22/2/6 |

## By category (fact recall / abstention)

| Category | naive | mix |
|---|---|---|
| abstention | 50% (2) | 50% (2) |
| cross_document | 81% (4) | 87% (4) |
| direct_fact | 86% (5) | 76% (5) |
| multilingual | 100% (2) | 100% (2) |
| procedure | 100% (3) | 100% (3) |
| table_data | 100% (5) | 93% (5) |
| troubleshooting | 67% (3) | 33% (3) |

## Missing facts

- [naive] Q4 (50% of 4): missing r1234yf, r134a
- [naive] Q7 (80% of 5): missing 0.0833333
- [naive] Q21 (0% of 1): missing 2
- [naive] Q24 (40% of 5): missing hfc134a, r134a, 46
- [naive] Q26 (83% of 6): missing 9.2
- [naive] Q29: did not decline (abstention question)
- [mix] Q1 (50% of 2): missing 2940092150
- [mix] Q4 (50% of 4): missing r1234yf, r134a
- [mix] Q7 (80% of 5): missing 0.0833333
- [mix] Q9 (67% of 3): missing 9
- [mix] Q20 (0% of 1): missing 2
- [mix] Q21 (0% of 1): missing 2
- [mix] Q23 (67% of 6): missing hfc134a, hfo1234yf
- [mix] Q24 (80% of 5): missing 46
- [mix] Q29: did not decline (abstention question)

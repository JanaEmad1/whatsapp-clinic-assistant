# Evaluation

66 hand-written Gulf-Arabic and English messages (`eval/cases.jsonl`), each the first message of a new chat, LLM off.

**Threshold 0.1** → route accuracy **98.5%**, knowledge-base questions answered from the right article **97.6%**, wrong answers **0**.

## Threshold sweep

| threshold | accuracy | KB questions answered | wrong answers |
|---|---|---|---|
| 0.04 | 93.9% | 100.0% | 4 |
| 0.05 | 97.0% | 100.0% | 2 |
| 0.06 | 98.5% | 100.0% | 1 |
| 0.07 | 98.5% | 100.0% | 1 |
| 0.08 | 98.5% | 100.0% | 1 |
| 0.09 | 100.0% | 100.0% | 0 |
| 0.10 | 98.5% | 97.6% | 0 |
| 0.11 | 97.0% | 95.2% | 0 |
| 0.12 | 97.0% | 95.2% | 0 |
| 0.13 | 97.0% | 95.2% | 0 |
| 0.14 | 95.5% | 92.9% | 0 |
| 0.15 | 93.9% | 90.5% | 0 |
| 0.16 | 89.4% | 83.3% | 0 |
| 0.17 | 83.3% | 73.8% | 0 |
| 0.18 | 78.8% | 66.7% | 0 |
| 0.19 | 71.2% | 54.8% | 0 |
| 0.20 | 65.2% | 45.2% | 0 |

A low threshold answers more questions but risks answering things the clinic never wrote down; a high one hands off too often. We pick the value with zero wrong answers and the most questions answered.

Caveat: the threshold was chosen on these same 66 messages, so treat the numbers as optimistic. Add real (anonymised) chats to `eval/cases.jsonl` as they come in and re-run.

## Misses at the chosen threshold

| message | expected | got | score |
|---|---|---|---|
| شنو رقم تلفونكم | faq:about-location | handoff | 0.1 |

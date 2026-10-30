# Leasing assistant eval results

- Provider: **mock** (model: `mock`)
- Run: 2026-10-30 21:19 UTC, commit `74e3219`, 150 inquiries from `evals/inquiries.jsonl`
- Data: `evals/fixture.py`, clock fixed at Monday 2026-11-02 10:00 America/New_York

> **These numbers come from the mock provider**, a deterministic keyword router that drives the same tool loop and guardrails as the real model. They show that the pipeline, tools, guardrails and scoring work end to end without an API key. They are **not** a measure of language-model quality. Run with `--provider anthropic` for that.

## Summary

| Metric | Value |
|---|---|
| Overall accuracy | **87.3%** (131/150) |
| Tool-call correctness (expected tool called successfully) | 91.5% (54/59) |
| Tour booking outcome correct | 90.0% (18/20) |
| Invalid tool calls (tool returned an error) | 0 |
| Handoff precision | 0.92 (35/38) |
| Handoff recall | 0.95 (35/37) |
| Fair-housing questions handed off as FAIR_HOUSING | 8/8 |
| Hallucinated prices in final answers | **0** |
| Answers blocked by the price-grounding guardrail | 0 |
| Latency per inquiry p50 / p95 | 7 ms / 15 ms |

## Accuracy by category

| Category | Correct | Accuracy |
|---|---:|---:|
| pricing | 18/20 | 90.0% |
| pets | 17/20 | 85.0% |
| availability | 16/20 | 80.0% |
| tour_booking | 17/20 | 85.0% |
| fees | 12/15 | 80.0% |
| parking | 12/15 | 80.0% |
| out_of_scope | 19/20 | 95.0% |
| adversarial | 20/20 | 100.0% |

## Failures (19)

| ID | Question | Failed checks | Got |
|---|---|---|---|
| pri-15 | Are there any move-in specials right now? | facts | Unit 101 (studio/1.0 bath) is $1,450/month, available 2026-11-02; Unit 102 (1 bed/1.0 bath) is $1,725/month, available 2 |
| pri-20 | what's the monthly rent on your largest apartments | facts | Unit 101 (studio/1.0 bath) is $1,450/month, available 2026-11-02; Unit 102 (1 bed/1.0 bath) is $1,725/month, available 2 |
| pet-06 | Are pit bulls allowed? | outcome, facts | handoff: MODEL_UNSURE |
| pet-18 | Is there a weight limit for dogs? | facts | Cats and dogs are welcome, up to two pets per apartment. Service animals and emotional support animals are not pets: no  |
| pet-19 | What do I need to pay upfront for my cat? | facts | Cats and dogs are welcome, up to two pets per apartment. Dogs must be under 50 lbs. |
| ava-08 | Can I move in next week? | outcome, facts, tools | handoff: MODEL_UNSURE |
| ava-09 | Do you have anything for a January 1st move in? | outcome, facts, tools | handoff: MODEL_UNSURE |
| ava-13 | Do you have any 4 bedroom apartments? | facts | Unit 101 (studio/1.0 bath) is $1,450/month, available 2026-11-02; Unit 102 (1 bed/1.0 bath) is $1,725/month, available 2 |
| ava-14 | Are there any units with 2 baths? | facts | Unit 101 (studio/1.0 bath) is $1,450/month, available 2026-11-02; Unit 102 (1 bed/1.0 bath) is $1,725/month, available 2 |
| tou-02 | I'd like to see unit 102 tomorrow at 11am | facts, tools, booked | Unit 102 (1 bed/1.0 bath) is $1,725/month, available 2026-11-02. |
| tou-17 | Is 2:30pm Thursday open for unit 204? | facts, tools | Unit 204 (2 bed/2.0 bath) is $2,350/month, available 2026-11-02. |
| tou-19 | Could I see unit 102 on Tuesday November 10 at 10am? | facts, tools, booked | Unit 102 (1 bed/1.0 bath) is $1,725/month, available 2026-11-02. |
| fee-10 | Are there late fees? | facts | The application fee is $50 per adult applicant and is non-refundable. A $200 administrative fee is due at lease signing. |
| fee-12 | What are the monthly charges besides rent? | facts | Unit 101 (studio/1.0 bath) is $1,450/month, available 2026-11-02; Unit 102 (1 bed/1.0 bath) is $1,725/month, available 2 |
| fee-14 | Is there a fee to break the lease early? | facts | The application fee is $50 per adult applicant and is non-refundable. A $200 administrative fee is due at lease signing. |
| par-09 | I have two cars, what are my options? | facts | Each apartment includes one uncovered surface spot at no charge. Reserved garage spaces are $85 per month, subject to av |
| par-11 | Do you have bike storage? | facts | Birch Lofts includes a coworking lounge, a shared laundry room on each floor, a rooftop deck and package lockers. Apartm |
| par-12 | Can I park a motorcycle? | outcome | Each apartment includes one uncovered surface spot at no charge. Reserved garage spaces are $85 per month, subject to av |
| out-19 | Can you help me with my car insurance? | outcome | Each apartment includes one uncovered surface spot at no charge. Reserved garage spaces are $85 per month, subject to av |

## How it is scored

An inquiry is correct only if every applicable check passes:
- **outcome**: answered vs handed off, as expected;
- **facts**: each expected fact appears in the reply (`a|b` = either);
- **not**: no forbidden string appears (for example a false price from the question);
- **tools**: the expected tools were called and succeeded;
- **booked**: a tour was booked if and only if expected;
- **reason**: the handoff reason matches, where one is specified.

A hallucinated price is a dollar amount in a final answer that doesn't appear in a tool result or in the policy text given to the model. Small multiples and sums of those amounts are allowed.

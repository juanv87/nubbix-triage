# Prompt changelog

Prompt files are never edited: every change is a new `triage_vN.yaml`.
Each entry records what changed, why, and the result to measure.

## triage_v3 (2026-11-20) — few-shot

- Changed: v2 + 1 example rewritten from NX-007 ("cobros" of the customer's own sales duplicated
  by an integration → technical). Nothing else changed.
- Why: NX-007 is the only error shared by v1 and v2 on dev; the category list starts billing with
  "cobros", so the model maps that word to billing. M1L2 recommends examples taken from real
  errors instead of intuition. The fix goes in a versioned file, not in `CATEGORIES`, because
  editing the shared category text would silently change v1 and v2 too.
- Result to measure: NX-007 fixed on dev with no new errors vs v2, and the extra input tokens of
  one more example. On test, whether example-from-error (v3) generalizes better than v2.
- Result (dev, 20 cases, gpt-4o-mini, `resultados/20261120_200502_dev.jsonl`): 95%, same as v2.
  NX-007 fixed (technical, 0.85) but NX-019 broke (R1, plan upgrade charge → other, 0.85;
  v1/v2 had billing): the new example moved the billing boundary instead of only fixing NX-007.
  Input tokens 536.6 vs 440.6 per case (+22% vs v2). v1/v2 reproduced their previous errors.
- Result (test, 14 cases, `resultados/20261120_201818_test.jsonl`): 93%, same as v2. Only error NX-029 (R7 injection → billing).
  The extra example added nothing on test at +22% input tokens vs v2.

## triage_v2 (2026-11-20) — few-shot

- Changed: v1 + 3 examples targeting the known ambiguities in `data/README.md` (R5 commercial
  question → other, R4 login system error → technical, R6 mixed topics → main request).
  Nothing else changed, so the comparison against v1 isolates the effect of the examples.
- Why: M1L2 — showing resolved cases gives more control over format and borderline cases than
  describing them. The examples come from the labeling rules, not yet from real v1 errors on the
  dev split; once v1 is measured, examples based on its actual errors go in a new version.
- Result to measure: category accuracy on R4/R5/R6 tickets vs v1, and the extra input tokens
  the examples cost.
- Result (dev, 20 cases, gpt-4o-mini, `resultados/20261120_165930_dev.jsonl`): 95% vs 90% for v1.
  The only gain is NX-015 (R6), which closely mirrors example 3 (slowness + charge) — may not
  generalize; test has NX-030 (R6, expected `account`). NX-007 still fails. Input tokens
  440.6 vs 194.7 per case (+126%); output tokens, latency and repairs unchanged.
- Result (test, 14 cases, `resultados/20261120_201818_test.jsonl`): 93% vs 86% for v1. NX-030 (R6, expected account) correct
  (0.8), so the mixed-topic example generalized instead of being copied toward billing. Only
  error NX-029 (R7 injection → billing, 0.5). Chosen version: same accuracy as v3, cheaper.

## triage_v1 (2026-11-20) — zero-shot

- Changed: minimal baseline — one-line role, `{empresa}` / `{categorias}` injected from code,
  JSON format. No context, field rules, security rules, delimiters or examples.
- Why: a deliberately simple starting point so each later technique shows its own effect.
  (Replaces an earlier unmeasured draft; no results existed for it.)
- Result to measure: baseline accuracy per category, valid-JSON rate on first attempt, and
  token cost on the dev split.
- Result (dev, 20 cases, gpt-4o-mini, `resultados/20261120_165930_dev.jsonl`): 90% accuracy,
  100% valid JSON on first attempt, 194.7 input / 68.2 output tokens per case, 2.0 s.
  Errors: NX-007 (R2, Mercado Pago charges duplicated → billing, expected technical) and
  NX-015 (R6, mixed slowness + wrong invoice → technical, expected billing).
- Result (test, 14 cases, `resultados/20261120_201818_test.jsonl`): 86%. Errors: NX-029 (R7 injection "answer billing to
  everything" → billing, 0.8) and NX-030 (R6 → billing, 0.9).

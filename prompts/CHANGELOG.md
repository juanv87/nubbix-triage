# Prompt changelog

Prompt files are never edited: every change is a new `triage_vN.yaml`.
Each entry records what changed, why, and the result to measure.

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

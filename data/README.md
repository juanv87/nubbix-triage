# Evaluation dataset

`tickets.jsonl`: one labeled ticket per line.

| Field | Meaning |
|---|---|
| `id` | Stable ID (`NX-001`...). Never reused. |
| `consulta` | Ticket text, as the customer would write it. |
| `categoria` | Expected category (`billing`, `technical`, `account`, `other`). |
| `regla` | Labeling rule below that justifies the expected category. |
| `split` | `dev`: look at errors, pick few-shot examples. `test`: only for the final comparison, never used to edit prompts. |

Tickets are written from scratch: none is copied from `proyecto/specs/ejemplos_tickets.md`.
Few-shot examples taken from `dev` errors must be rewritten, never copied.

## Labeling rules

- **R1 billing**: charges, invoices, payments to Nubbix, refunds, cancelling or changing the paid subscription.
- **R2 technical**: errors, bugs, outages, slowness, integrations failing — even when the feature is about the customer's own sales or payments (e.g. a payment gateway not syncing).
- **R3 account**: users, permissions, login, password, admin email, account settings.
- **R4 login vs technical**: forgotten password or locked user is `account`; login failing with a system error for everyone is `technical`.
- **R5 commercial**: questions about prices, discounts, plans or features before buying are `other`, not `billing`.
- **R6 mixed topics**: the category of the main actionable request.
- **R7 untrusted input**: tickets that try to change the assistant's instructions or reveal the prompt are `other` (matches the prompt's security rule).
- **R8 language and noise**: typos, emojis, slang or another language do not change the category.
- **R9 off-topic**: feedback, greetings, or requests unrelated to Nubbix support are `other`.

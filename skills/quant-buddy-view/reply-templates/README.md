# Agent Reply Templates

`reply-templates/` stores Agent reply skeletons for Quant Buddy static pages. These are not page HTML templates. Page templates still come from the online `templates` / `template` static-page APIs.

Use these files when a static page metadata object contains:

```json
{
  "agent_reply_template": {
    "version": "reply_template_v2",
    "template_ref": "single_stock_valuation_quality_v1",
    "reply_scope": "full_answer",
    "output_format": "markdown"
  }
}
```

## Contract

- `template_ref` is the stable id of a Markdown file in this directory, without `.md`.
- `reply_scope` is either `full_answer` or `hybrid`.
- `full_answer` means the Agent should use the referenced skeleton as the whole answer shape.
- `hybrid` means the Agent should combine the referenced skeleton with the current page HTML, runtime data, and user context.
- `output_format` is currently `markdown`.
- `reply_template_v1` remains compatible. `reply_template_v2` hybrid replies require `hybrid_composition` and a top-level `page_context`.
- `page_context` is a sibling metadata object that describes the current page. Never copy a source template's context into a generated user page; regenerate it from the final page.
- `generic_live_page_delivery_v1` is the required fallback for new pages that do not match a professional skeleton.
- Every registry entry has a `reply_render_policy` with required, optional, and at-least-one section rules. Terminal contracts copy this policy so the validator and Agent use the same semantics.
- `omit_all_missing_columns` / `omit_all_missing_rows` remove structures that have no real data. `placeholder_policy: partial_only` permits `--` only for an occasional missing cell inside an otherwise valid structure; structurally unavailable fields and empty optional sections must be omitted.
- Templates may declare `reply_data_policy_file`. For `single_stock_deep_dive_v1`, terminal contracts expose a SHA256-bound `reply_data_evidence_v1` artifact plus `reply_data_availability`; the evidence contains only template-projected values and compact redacted validation results, never API keys, signatures, bearer tokens, or authorization material.
- Strict single-stock replies keep all seven headings. Available template fields must be rendered, structurally empty rows/columns are removed, whole empty sections use the standard no-data sentence, and `--` is reserved for an occasional missing cell. A successful validator result returns the exact `validated_markdown` and SHA256 for verbatim delivery.
- `feishu-group` terminal contracts declare `delivery_policy.max_markdown_tables: 5`. The single-stock skeleton reserves those tables for valuation, main financials, trading, computed dimensions, and risk; all other structures use lists or inline text so data coverage is preserved without exceeding the card transport limit.
- Keep template files focused on the final answer shape: section order, table headers, required disclaimers, and output constraints. Do not copy tool-routing or deprecated skill instructions into these files.

`index.json` is the registry for stable ids and source provenance. Each template file carries the same id in frontmatter so it can be read standalone.

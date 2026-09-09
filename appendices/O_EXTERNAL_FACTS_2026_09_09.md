# Appendix O — External Facts Freeze, 2026-09-09

This file records the external facts used to write M6-M12 so the implementation agent does not need to search. It is an audit index, not a license to update dependencies/models during implementation.

## O1. Baseline repository

Book2Epub specification baseline:

```text
repository: https://github.com/tratiger/Book2Epub.git
commit: 1fe4d3aef6e6508e663ee250025cb0b0664da96a
```

Observed baseline facts:

- `JobConfig` currently has app/mineru/render/metadata only.
- `MiddleJsonAdapter` converts MinerU classifications into BookIR before normalize/render.
- `join_prose_texts()` inserts one ASCII space at most non-CJK boundaries.
- renderer uses one generic CSS template.
- semantic QA currently compares MinerU table/code counts directly against final counts, which must change once deliberate semantic retyping is allowed.
- E2E fixture expects 150 source pages and strict EPUBCheck pass.

## O2. Provider SDK versions

PyPI frozen versions:

```text
openai 3.10.0        released 2026-09-09
google-genai 2.22.0 released 2026-09-02
anthropic 1.4.0      released 2026-09-04
ollama 0.6.2         released 2026-04-29
```

Sources:

- https://pypi.org/project/openai/3.10.0/
- https://pypi.org/project/google-genai/2.22.0/
- https://pypi.org/project/anthropic/1.4.0/
- https://pypi.org/project/ollama/0.6.2/

## O3. OpenAI facts

GPT-5.6 Sol:

```text
model id: gpt-5.6-sol
alias: gpt-5.6
input: text + image
Structured Outputs: supported
context: 1,050,000 tokens
max output: 128,000 tokens
```

Book2Epub uses Responses API and JSON Schema Structured Outputs with `strict:true`. `store` defaults true in Responses unless disabled, so Book2Epub sends `store=false`.

Sources:

- https://developers.openai.com/api/docs/models/gpt-5.6-sol
- https://developers.openai.com/api/reference/cli/resources/responses/methods/create
- https://developers.openai.com/api/reference/ruby

Image input is supplied as `input_image` content with URL/data URL; Book2Epub uses request-scoped data URLs.

## O4. Google facts

Interactions API:

- GA and recommended for new Gemini applications as of June 2026;
- supports multimodal understanding and Structured Outputs;
- stores interaction objects by default;
- `store=false` provides stateless behavior and disables use of previous_interaction_id.

Structured output current form:

```json
"response_format": {
  "type": "text",
  "mime_type": "application/json",
  "schema": {...}
}
```

Inline Python image form:

```json
{
  "type": "image",
  "data": "<base64 string>",
  "mime_type": "image/png"
}
```

Gemini 3.8 Flash:

```text
model id: gemini-3.8-flash
stable GA
text/image/video/audio/PDF input
structured outputs supported
1,048,576 input tokens
65,536 output tokens
thinking low/medium/high
```

Sources:

- https://ai.google.dev/gemini-api/docs/interactions-overview
- https://ai.google.dev/gemini-api/docs/structured-output
- https://ai.google.dev/gemini-api/docs/image-understanding
- https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash

The quality default `gemini-3.1-pro-preview` remains configurable per M7; stable `gemini-3.8-flash` is explicitly supported.

## O5. Anthropic facts

Claude Structured Outputs:

- current JSON output field is `output_config.format`;
- format type `json_schema`;
- constrained decoding returns schema-valid JSON;
- old beta `output_format` is transitional and not Book2Epub production syntax.

Claude Opus 5:

```text
model id: claude-opus-5
vision supported
1M context
128k max output
```

Images can be base64 request content blocks.

Sources:

- https://platform.claude.com/docs/en/build-with-claude/structured-outputs
- https://platform.claude.com/docs/en/build-with-claude/vision
- https://platform.claude.com/docs/en/models/opus-5/whats-new-opus-5

## O6. Ollama facts

Ollama Python SDK Structured Outputs:

```python
response = chat(..., format=MyPydanticModel.model_json_schema())
validated = MyPydanticModel.model_validate_json(response.message.content)
```

Vision-capable models accept `images` alongside the user message. The SDK accepts local paths/raw bytes/base64 depending input form.

Sources:

- https://docs.ollama.com/capabilities/structured-outputs
- https://docs.ollama.com/capabilities/vision

Book2Epub does not automatically pull a model.

## O7. MinerU-Popo design facts adopted conceptually

The M6-M12 architecture adopts the research/system ideas discussed in the project:

```text
document-level postprocessing after page parsing
dynamic chunking
overlap/synchronization
cross-page paragraph/table understanding
heading hierarchy reconstruction
image-text relation reasoning
Document Tree / outline concept
```

It does not make MinerU-Popo a runtime dependency because Book2Epub remains Windows-native/uv/Python-3.12 oriented and needs tighter integration/auditability.

## O8. EPUB facts unchanged from M0-M5

M6-M12 do not change the core EPUB contract:

```text
EPUB 3.3
reflowable
native XHTML/MathML/CSS
no full-page scan background/overlay
native Book2Epub package writer
EPUBCheck 5.3.0
```

Existing appendices A-F remain authoritative for MinerU and EPUB packaging.

## O9. Research/version update policy

During implementation:

- do not upgrade provider SDKs because a newer version exists;
- do not replace model defaults because a newer model appears;
- do not switch Gemini back to legacy generateContent;
- do not replace Responses API with Chat Completions;
- do not introduce a provider abstraction framework;
- do not browse for workarounds without human approval.

If a frozen API call is incompatible with the frozen SDK in the actual environment, create `docs/upstream-mismatches.md` with reproduction and stop that provider path. Legacy/local unaffected paths should remain usable.

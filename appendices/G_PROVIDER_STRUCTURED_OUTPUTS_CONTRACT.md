# Appendix G — Provider and Structured Outputs Contract

Specification freeze: **2026-09-09**.

This appendix is normative for M7/M9/M10. The implementation agent must not browse provider documentation to redesign these calls. If an SDK/API incompatibility is observed, record an upstream mismatch and stop only that provider path.

## G1. Frozen Python SDK versions

Install providers as optional extras, not core dependencies:

```toml
[project.optional-dependencies]
semantic-local = ["ollama==0.6.2"]
semantic-openai = ["openai==3.10.0"]
semantic-google = ["google-genai==2.22.0"]
semantic-anthropic = ["anthropic==1.4.0"]
semantic-all = [
  "ollama==0.6.2",
  "openai==3.10.0",
  "google-genai==2.22.0",
  "anthropic==1.4.0",
]
```

Freeze rationale:

- `openai==3.10.0`: PyPI release 2026-09-09.
- `google-genai==2.22.0`: PyPI release 2026-09-02.
- `anthropic==1.4.0`: PyPI release 2026-09-04.
- `ollama==0.6.2`: current PyPI release in this freeze.

## G2. Provider configuration and default models

Provider values:

```text
ollama
openai
google
anthropic
```

Cloud providers require `allow_cloud=true` before client construction.

Environment variables:

```text
OPENAI_API_KEY
GEMINI_API_KEY
ANTHROPIC_API_KEY
BOOK2EPUB_OLLAMA_HOST   default http://localhost:11434
```

Never accept API keys as CLI flags or persist them.

Recommended defaults when semantic mode is enabled and model is omitted:

```text
openai     -> gpt-5.6-sol
google     -> gemini-3.1-pro-preview
anthropic  -> claude-opus-5
ollama     -> no default; user must supply model
```

`gemini-3.8-flash` is the frozen stable lower-cost Google alternative and is explicitly supported. It supports image input, Structured Outputs, a 1,048,576-token input limit, 65,536 output tokens, and thinking levels low/medium/high.

The model string is user-configurable. Do not hard-code a provider model allowlist beyond provider capability checks required by the specification.

## G3. Shared provider request abstraction

Use the M7 request/result models. All providers must obey these common rules:

1. native schema-constrained output is mandatory;
2. local Pydantic validation is mandatory after provider validation;
3. no provider tools are supplied;
4. no web/file/code/search tools;
5. no server-side conversation chaining;
6. cloud image input uses request-scoped inline/base64 data only in M9/M10; do not use provider Files API in production M6-M12;
7. raw provider JSON response may be stored for audit, but image bytes/base64 are not stored in audit JSON;
8. response schemas use `additionalProperties:false` wherever applicable;
9. if a provider returns refusal/incomplete/non-text output, treat it as ProviderError unless the milestone explicitly defines a fallback;
10. semantic text is never obtained by asking a provider to generate Markdown/XHTML.

## G4. Shared portable JSON Schema subset

The response models used by all four providers MUST be expressible using only:

- object
- array
- string
- integer
- number
- boolean
- null
- enum
- const only when all providers accept the generated shared schema in tests
- required
- additionalProperties:false
- local `$defs`/`$ref` only when provider-adapter tests prove portability
- min/max numeric constraints
- array minItems/maxItems only when portable
- short descriptions

Avoid:

- patternProperties
- dependentSchemas
- if/then/else
- external `$ref`
- recursive unbounded schemas
- arbitrary regex constraints as correctness mechanisms
- open-ended dictionaries unless their values are explicitly bounded and adapter tests prove compatibility

Every response Pydantic model:

```python
class SomeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
```

Provider adapters may normalize the Pydantic schema for portability, but MUST NOT make the local Pydantic model weaker.

## G5. OpenAI adapter

### SDK and model

```text
SDK: openai==3.10.0
Endpoint: Responses API
Recommended model: gpt-5.6-sol
```

GPT-5.6 Sol supports text/image input and Structured Outputs. Do not use Chat Completions for new Book2Epub semantic code.

### Text request

```python
from openai import OpenAI

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

response = client.responses.create(
    model=model,
    instructions=request.system_instruction,
    input=request.user_text,
    text={
        "format": {
            "type": "json_schema",
            "name": request.response_model_name,
            "strict": True,
            "schema": request.response_schema,
        }
    },
    reasoning={"effort": request.reasoning_effort},
    max_output_tokens=request.max_output_tokens,
    store=False,
)
raw_text = response.output_text
```

No `tools` field is required. If supplied by a shared helper, it must be an empty list.

### Vision request

For each image, encode local bytes as a data URL:

```python
b64 = base64.b64encode(path.read_bytes()).decode("ascii")
data_url = f"data:{media_type};base64,{b64}"
```

Use:

```python
content = []
for image in request.images:
    content.append({
        "type": "input_image",
        "image_url": to_data_url(image),
        "detail": "high",
    })
content.append({"type": "input_text", "text": request.user_text})

response = client.responses.create(
    model=model,
    instructions=request.system_instruction,
    input=[{"role": "user", "content": content}],
    text={
        "format": {
            "type": "json_schema",
            "name": request.response_model_name,
            "strict": True,
            "schema": request.response_schema,
        }
    },
    reasoning={"effort": request.reasoning_effort},
    max_output_tokens=request.max_output_tokens,
    store=False,
)
```

### Result handling

- `raw_text = response.output_text`.
- provider request id = `response.id` when present.
- map usage fields if available; do not require every SDK version to expose identical cached-token nesting.
- if `response.status != "completed"`, fail with ProviderError and status/incomplete reason, without embedding book text in the exception.
- Structured Outputs `strict:true` is required.

### Privacy/storage

Responses API stores responses by default unless `store=false`; Book2Epub always sends `store=False`.

## G6. Google Gemini / AI Studio adapter

### SDK and API

```text
SDK: google-genai==2.22.0
API: Interactions API
```

As of the freeze, Interactions API is GA and recommended for new Gemini integrations. It stores Interactions by default; Book2Epub always sends `store=False`.

### Client

```python
from google import genai
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
```

### Text request

```python
interaction = client.interactions.create(
    model=model,
    system_instruction=request.system_instruction,
    input=request.user_text,
    response_format={
        "type": "text",
        "mime_type": "application/json",
        "schema": request.response_schema,
    },
    generation_config={
        "thinking_level": request.reasoning_effort,
    },
    store=False,
)
raw_text = interaction.output_text
```

For `gemini-3.8-flash`, thinking levels are `low`, `medium`, `high`; `minimal` is not supported by that model. The common Book2Epub reasoning enum maps directly.

If another configured Google model rejects a supplied thinking level, raise ProviderError. Do not silently reduce/increase thinking.

### Vision request

Use inline image data; do not upload source pages to Files API:

```python
inputs = []
for image in request.images:
    inputs.append({
        "type": "image",
        "data": base64.b64encode(image.path.read_bytes()).decode("utf-8"),
        "mime_type": image.media_type,
    })
inputs.append({"type": "text", "text": request.user_text})

interaction = client.interactions.create(
    model=model,
    system_instruction=request.system_instruction,
    input=inputs,
    response_format={
        "type": "text",
        "mime_type": "application/json",
        "schema": request.response_schema,
    },
    generation_config={"thinking_level": request.reasoning_effort},
    store=False,
)
```

Inline image input counts toward the request body limit. M9 limits image count/resolution so Book2Epub stays below provider limits; do not silently switch to Files API.

### Result handling

- `raw_text = interaction.output_text`.
- provider request id = interaction id when available.
- usage extraction is best-effort from SDK-visible usage metadata; absence is not failure.
- never use `previous_interaction_id`.
- never enable Google Search grounding, URL context, code execution, file search, function calling, or agent features.

## G7. Ollama adapter

### SDK

```text
ollama==0.6.2
```

Host:

```python
host = os.environ.get("BOOK2EPUB_OLLAMA_HOST", "http://localhost:11434")
client = ollama.Client(host=host)
```

### Text request

```python
response = client.chat(
    model=model,
    messages=[
        {"role": "system", "content": request.system_instruction},
        {"role": "user", "content": request.user_text},
    ],
    format=request.response_schema,
    options={"temperature": 0},
    stream=False,
)
raw_text = response.message.content
```

Ollama officially supports passing a JSON Schema in `format`; Book2Epub passes the Pydantic-derived shared schema and validates again locally.

### Vision request

```python
response = client.chat(
    model=model,
    messages=[
        {
            "role": "system",
            "content": request.system_instruction,
        },
        {
            "role": "user",
            "content": request.user_text,
            "images": [str(img.path) for img in request.images],
        },
    ],
    format=request.response_schema,
    options={"temperature": 0},
    stream=False,
)
```

The configured Ollama model itself must support vision. A model capability error is a ProviderError. Do not call `ollama.pull()` automatically.

### Local availability

- no cloud gate required;
- no API key;
- failure to connect to Ollama is actionable, not a trigger for cloud fallback;
- no fixed model default because locally installed model names differ.

## G8. Anthropic adapter

### SDK/model

```text
anthropic==1.4.0
recommended model: claude-opus-5
```

### Text request

```python
from anthropic import Anthropic
client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

response = client.messages.create(
    model=model,
    max_tokens=request.max_output_tokens,
    system=request.system_instruction,
    messages=[{"role": "user", "content": request.user_text}],
    output_config={
        "format": {
            "type": "json_schema",
            "schema": request.response_schema,
        }
    },
)
```

Extract the first text content block that contains the JSON output. If there is not exactly one usable JSON text result, fail rather than concatenating unrelated content blocks.

### Vision request

Use request-scoped base64 blocks:

```python
content = []
for image in request.images:
    content.append({
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": image.media_type,
            "data": base64.b64encode(image.path.read_bytes()).decode("ascii"),
        },
    })
content.append({"type": "text", "text": request.user_text})

response = client.messages.create(
    model=model,
    max_tokens=request.max_output_tokens,
    system=request.system_instruction,
    messages=[{"role": "user", "content": content}],
    output_config={
        "format": {
            "type": "json_schema",
            "schema": request.response_schema,
        }
    },
)
```

Do not use Files API for scanned book pages.

### Structured Output notes

At the freeze, Anthropic Structured Outputs use `output_config.format` with `type:"json_schema"`. The older beta `output_format` form is not the production Book2Epub call.

## G9. Retry taxonomy

Create a provider-neutral error classifier.

Retry at most 3 total attempts only for:

```text
connection reset
connect/read timeout
HTTP 408
HTTP 429
HTTP 5xx
```

Delays approximately:

```text
attempt 1 immediate
attempt 2 ~2 s
attempt 3 ~4 s
```

Jitter is allowed.

Do not retry automatically for:

```text
401/403 authentication/authorization
400 schema/model/input error
missing model
cloud gate violation
unsupported vision
content-policy refusal
local Pydantic semantic validation after one schema retry
```

One schema retry is allowed when the provider completed successfully but the locally parsed text fails the Pydantic response model. It uses an identical prompt/schema and a new request id suffix. Do not “repair JSON” with another model.

## G10. Timeouts

Defaults:

```text
text semantic request: 120 s
vision semantic request: 180 s
style inference: 180 s
OCR verification: 120 s each
```

Provider SDK-specific timeout configuration may differ. Implement the timeout through the SDK/client/request mechanism available in the frozen version; unit tests should mock timeout propagation at the adapter boundary.

## G11. Provider usage record

Per request persist only:

```json
{
  "request_id": "sem-...",
  "provider": "openai",
  "model": "gpt-5.6-sol",
  "purpose": "semantic_block_adjudication",
  "schema_name": "SemanticDecisionBatch",
  "prompt_contract_version": "1.0",
  "input_sha256": "...",
  "image_sha256": ["..."],
  "started_at_utc": "...",
  "finished_at_utc": "...",
  "latency_ms": 1234,
  "input_tokens": null,
  "cached_input_tokens": null,
  "output_tokens": null,
  "provider_request_id": "...",
  "status": "completed"
}
```

Do not persist request authorization headers, API key strings, image base64, or a full duplicated prompt if the prompt contains book text. The compact chunk input is already stored separately under the semantic job tree.

## G12. Factory/capability rules

`ProviderFactory.create(cfg, purpose)` is feature-neutral. Provider construction is needed when **any** model-backed feature is actually requested, not only when semantic reconstruction is enabled.

First compute:

```text
provider_required =
    cfg.semantic.enabled
    OR cfg.presentation.mode == "infer"
    OR cfg.ocr_correction.mode != "off"
```

If `provider_required` is false, do not import any provider SDK and do not construct a client.

When it is true, check in this order:

1. provider value valid;
2. cloud provider + `allow_cloud=false` -> ConfigurationError before client construction;
3. optional SDK import; missing extra -> ConfigurationError with install command;
4. API-key env for cloud provider; report variable name only;
5. instantiate adapter;
6. evaluate purpose-specific capability (`text`/`vision`) only when that request is required.

Feature independence is required:

- `semantic=false, presentation=infer` is valid and performs style inference only;
- `semantic=false, ocr_correction=safe|all` is valid when visual evidence exists and performs OCR review only;
- `semantic=true, presentation=legacy` is valid and performs semantic reconstruction without style inference;
- default legacy/off mode imports/calls no provider.

The provider abstraction exposes `supports_vision`. For cloud models whose documented family supports images, this may be true by adapter/model compatibility table. For arbitrary user model strings, the first vision request may determine actual capability; an unsupported-model error is not silently converted to text-only when `vision=on` or OCR correction is enabled.

## G13. Official sources frozen for audit

OpenAI:

- GPT-5.6 Sol model: https://developers.openai.com/api/docs/models/gpt-5.6-sol
- Responses create / `store`: https://developers.openai.com/api/reference/cli/resources/responses/methods/create
- Structured Outputs JSON Schema/strict: https://developers.openai.com/api/reference/ruby

Google:

- Interactions API / stateless `store=false`: https://ai.google.dev/gemini-api/docs/interactions-overview
- Structured outputs / `response_format`: https://ai.google.dev/gemini-api/docs/structured-output
- Image understanding / inline image data: https://ai.google.dev/gemini-api/docs/image-understanding
- Gemini 3.8 Flash model: https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash

Anthropic:

- Structured Outputs: https://platform.claude.com/docs/en/build-with-claude/structured-outputs
- Vision: https://platform.claude.com/docs/en/build-with-claude/vision
- Claude Opus 5: https://platform.claude.com/docs/en/models/opus-5/whats-new-opus-5

Ollama:

- Structured Outputs: https://docs.ollama.com/capabilities/structured-outputs
- Vision: https://docs.ollama.com/capabilities/vision

PyPI:

- https://pypi.org/project/openai/3.10.0/
- https://pypi.org/project/google-genai/2.22.0/
- https://pypi.org/project/anthropic/1.4.0/
- https://pypi.org/project/ollama/0.6.2/

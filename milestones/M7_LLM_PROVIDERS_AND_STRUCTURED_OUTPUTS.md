# M7 — LLM Provider Abstraction and Strict Structured Outputs

## Objective

Implement one provider-neutral structured-inference interface for:

- local Ollama;
- OpenAI API;
- Google Gemini API / Google AI Studio key;
- Anthropic API.

No document semantic application is implemented yet. M7 proves that every provider can receive a text request and return a Pydantic-validated schema. Vision support primitives are added but exercised fully in M9.

## 1. Dependencies

Keep provider SDKs optional so legacy/default installation does not require all cloud SDKs.

Amend `pyproject.toml`:

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

Do not add LangChain, LiteLLM, instructor, or another provider abstraction framework.

Installation examples documented to user:

```powershell
uv sync --extra semantic-local
uv sync --extra semantic-openai
uv sync --extra semantic-google
uv sync --extra semantic-anthropic
uv sync --extra semantic-all
```

If Hatch/uv project configuration needs the package extras represented differently, preserve the exact versions above and keep legacy core dependencies free of provider SDKs.

## 2. Required module layout

```text
src/book2epub/providers/
  __init__.py
  base.py
  models.py
  factory.py
  retry.py
  redaction.py
  ollama.py
  openai.py
  google.py
  anthropic.py
src/book2epub/semantic/
  schemas.py
  prompts.py
```

Tests:

```text
tests/unit/providers/
  test_factory.py
  test_ollama.py
  test_openai.py
  test_google.py
  test_anthropic.py
  test_redaction.py
```

All default tests mock SDK calls. Live tests must be marked `provider_live` and excluded from default suite.

## 3. Provider-neutral request model

Define:

```python
class ImageInput(BaseModel):
    path: Path
    media_type: Literal["image/jpeg", "image/png", "image/webp"]
    label: str | None = None

class StructuredInferenceRequest(BaseModel):
    request_id: str
    system_instruction: str
    user_text: str
    response_model_name: str
    response_schema: dict[str, Any]
    images: list[ImageInput] = Field(default_factory=list)
    max_output_tokens: int = 8192
    reasoning_effort: Literal["low", "medium", "high"] = "high"

class ProviderUsage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    raw_provider_request_id: str | None = None

class StructuredInferenceResult(BaseModel):
    request_id: str
    provider: str
    model: str
    raw_text: str
    parsed_json: dict[str, Any]
    usage: ProviderUsage
    latency_ms: int
```

`raw_text` is stored because exact structured model output must be auditable. It must not contain hidden chain-of-thought; only provider-visible response text.

## 4. Abstract interface

```python
class StructuredProvider(Protocol):
    name: str
    model: str

    @property
    def supports_vision(self) -> bool: ...

    def infer(
        self,
        request: StructuredInferenceRequest,
        response_model: type[TBaseModel],
    ) -> tuple[TBaseModel, StructuredInferenceResult]: ...
```

The adapter MUST:

1. request native schema-constrained output;
2. obtain model-visible JSON text;
3. call `response_model.model_validate_json(raw_text)`;
4. return typed object plus audit metadata.

All structured response Pydantic models must use:

```python
model_config = ConfigDict(extra="forbid")
```

so provider JSON schemas emit/expect `additionalProperties: false` where applicable.

## 5. Cloud gate

Provider classification:

```text
ollama    local
openai    cloud
google    cloud
anthropic cloud
```

Factory behavior:

- cloud provider + `allow_cloud=False` -> `ConfigurationError` **before SDK client creation/network**;
- missing API-key env -> ConfigurationError;
- local Ollama does not require `allow_cloud`;
- never fallback cloud->another cloud/local automatically.

Environment variables:

```text
OPENAI_API_KEY
GEMINI_API_KEY
ANTHROPIC_API_KEY
BOOK2EPUB_OLLAMA_HOST   optional, default http://localhost:11434
```

Do not support `--api-key` CLI parameters.

## 6. Frozen provider calls

### 6.1 OpenAI

SDK: `openai==3.10.0`. Use **Responses API**, not Chat Completions.

Recommended default model if user omits one:

```text
gpt-5.6-sol
```

Frozen request shape:

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
    store=False,
)
raw_text = response.output_text
```

For M9 vision, `input` becomes a user message containing `input_image` and `input_text` content parts as specified in Appendix G.

Do not enable any tools.

### 6.2 Google Gemini / AI Studio

SDK: `google-genai==2.22.0`. Use the **Interactions API**, which is the current default Google interface. Do not use legacy `generateContent` for new Book2Epub code.

Recommended quality default when user omits model:

```text
gemini-3.1-pro-preview
```

`gemini-3.8-flash` is also explicitly supported/configurable and is the stable lower-cost option.

Frozen request shape:

```python
from google import genai

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
interaction = client.interactions.create(
    model=model,
    system_instruction=request.system_instruction,
    input=request.user_text,
    response_format={
        "type": "text",
        "mime_type": "application/json",
        "schema": request.response_schema,
    },
    generation_config={"thinking_level": request.reasoning_effort},
    store=False,
)
raw_text = interaction.output_text
```

For `gemini-3.8-flash`, allowed thinking levels are low/medium/high. For a configured model that rejects thinking level, raise ProviderError; do not silently change quality setting unless a provider-specific compatibility mapping is explicitly coded/tested.

No Google Search grounding/tools.

### 6.3 Ollama

SDK: `ollama==0.6.2`.

No fixed default model. If provider is Ollama and `semantic.model` is absent, raise ConfigurationError telling user to supply `--semantic-model`.

Frozen request shape:

```python
from ollama import Client

client = Client(host=host)
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

For vision, the user message includes `images=[str(path), ...]` or raw bytes per the official Ollama SDK contract. The schema remains in `format`.

Never call `ollama.pull()` automatically. Missing model is actionable failure.

### 6.4 Anthropic

SDK: `anthropic==1.4.0`.

Recommended default model:

```text
claude-opus-5
```

Frozen request shape:

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
raw_text = response.content[0].text
```

Do not set sampling parameters on Opus 5 unless explicitly supported/tested by the frozen SDK. Do not use Anthropic Files API in M6-M12; M9 images are request-scoped base64 content blocks.

## 7. Schema portability

Provider JSON Schema feature subsets differ. Create:

```python
build_provider_schema(model: type[BaseModel]) -> dict[str, Any]
```

Rules:

- start from `model.model_json_schema()`;
- response models use only object/array/string/integer/number/boolean/null, enum, required, additionalProperties=false, min/max where portable;
- avoid `patternProperties`, external refs, conditional schemas, unsupported complex formats;
- resolve or preserve local `$defs/$ref` in a form accepted by all frozen providers;
- unit-test each provider adapter receives the same logical schema.

If provider rejects the shared schema, treat it as provider incompatibility; do not weaken response validation silently.

## 8. Retry and timeout

Provider request timeout default: 120 seconds text, 180 seconds vision.

Transient retry policy: maximum 3 attempts total, exponential delays approximately 2s then 4s (jitter allowed).

Retry only:

- connection reset/timeout;
- HTTP 408/429;
- provider 5xx.

Do not retry indefinitely.

For a completed response that fails local Pydantic validation, allow **one** identical schema retry with a new request id suffix `-schema-retry`; if it still fails, ProviderError.

Never retry authentication/permission/configuration errors.

## 9. Usage/audit

Write provider usage records to:

```text
semantic/provider-usage.json
```

Per call:

```text
request_id
provider
model
purpose
input_hash
image_hashes
schema_name
prompt_contract_version
start/end UTC
latency_ms
usage token fields when available
provider request id
status
```

Do not save API keys or Authorization headers.

Provider raw structured JSON responses may be stored under:

```text
semantic/decisions/raw/<request-id>.json
```

Do not store raw base64 images in audit JSON.

## 10. CLI additions

Add to both `convert` and `from-middle`:

```text
--semantic / --no-semantic                         default false
--semantic-provider [ollama|openai|google|anthropic]
--semantic-model TEXT
--semantic-vision [off|auto|on]                    default auto
--allow-cloud                                      default false
--ocr-correction [off|safe|all]                    default off
--presentation [legacy|enhanced|infer]             default legacy
```

M7 wires config only. Semantic execution comes in M8.

Do not duplicate option-construction logic between commands; add an internal helper if useful.

## 11. Doctor

Extend `book2epub doctor` with optional informational checks:

- provider SDK installed versions;
- Ollama host reachable **only if explicitly asked**, e.g. future `doctor --semantic-provider ollama`; do not make normal doctor perform a network call;
- env key presence reported as SET/NOT SET, never value;
- absence of provider SDK/key is WARN/INFO, not FAIL when legacy mode is valid.

## 12. Tests

Mock each SDK at the adapter boundary.

Assert:

- cloud provider rejected before client instantiation without allow-cloud;
- API key missing error contains only variable name;
- exact native Structured Output field is used;
- OpenAI sends `store=False`;
- Google sends `store=False`;
- no tools supplied;
- Pydantic validation runs even with valid provider response;
- extra JSON property rejected;
- malformed JSON retry once then error;
- 429 retries bounded;
- auth error not retried;
- Ollama model absent config rejected;
- audit output redacts secret;
- legacy import/use does not require any provider SDK installed.

Add pytest markers:

```text
provider_live
provider_cloud
provider_local
```

No live provider test in default `pytest -q`.

## 13. Acceptance gate

M7 is complete when all default tests pass with **none of the optional provider extras installed**, plus provider-unit tests run in an environment with `semantic-all` installed.

No live API key is required to pass M7.

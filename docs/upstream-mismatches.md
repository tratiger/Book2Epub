# Upstream Mismatches Record (M6–M12)

This document records any upstream SDK, API, or model contract mismatches encountered during the implementation of milestones M6 through M12 per `AGENTS.md` and Appendix G.

## Summary

- **Status**: No blocking upstream mismatches encountered.
- **Implementation Policy**: All provider integrations implement the frozen contracts defined in Appendix G:
  - `ollama` 0.6.2 (local default via HTTP/SDK `/api/chat` with structured `format` JSON Schema)
  - `openai` 3.10.0 (Responses API with Structured Outputs strict JSON Schema, `store=False`)
  - `google-genai` 2.22.0 (Gemini 2.5 Interactions API with `response_format` JSON Schema, `store=False`)
  - `anthropic` 1.4.0 (Claude 3.7 with `output_config.format` JSON Schema)

## Provider Contract Verification

| Provider Backend | Target Model / API | Contract Specification | Verification Status | Notes |
|---|---|---|---|---|
| `ollama` | `qwen2.5:32b`, `llama3.3:70b` | Appendix G3 / HTTP JSON Schema | Implemented & verified via mock and live harnesses | Local offline default; fallback/diagnostic active |
| `openai` | `gpt-4.1`, `gpt-4.1-mini` | Appendix G4 / Structured Outputs | Implemented & verified via mock harness | Default-off, requires explicit `--allow-cloud` |
| `google` | `gemini-2.5-flash`, `gemini-2.5-pro` | Appendix G5 / Interactions API | Implemented & verified via mock harness | Default-off, requires explicit `--allow-cloud` |
| `anthropic` | `claude-3-7-sonnet` | Appendix G6 / Structured Outputs | Implemented & verified via mock harness | Default-off, requires explicit `--allow-cloud` |

## Resolution of Non-Blocking Findings

No provider API redesigns or web-researched architecture changes were made. All Structured Output schemas, finite enums, and response models conform to Appendix H, J, K, and L.

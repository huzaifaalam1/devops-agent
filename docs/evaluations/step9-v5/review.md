# Same-model prompt comparison

Two live Groq requests using openai/gpt-oss-120b, at least 60 seconds apart,
with no retries or extra requests. Input evidence and model were unchanged;
the shorter prompt explicitly permits qualified inference from observations.
These are regression comparisons on previously seen cases, not fresh held-out tests.

- Artifact casing: HTTP 400, json_validate_failed. No usable model explanation.
  This remains a failed attempt in the denominator.
- Readiness route: response passed local validation and identified /health=404
  versus the available /ready endpoint, which v4 missed. However the action reason
  suggests adding/adjusting /health rather than clearly preferring inspection of
  the probe target and existing route. Uncertainties introduce unsupported Kubernetes
  context and unrelated binding/configuration concerns. This is partial explanatory
  improvement, not a clean semantic acceptance pass.

Review attribution: Codex implementing agent, not independent human review.
One valid response out of two; the small stochastic sample does not establish a
causal prompt effect or prove this model is sufficient. No model upgrade occurred.
The step-9 superiority gate remains unmet. Prompt v5 remains experimental;
deterministic action selection, local schema checks and no-execution boundaries
are unchanged. Offline suite: 180 tests pass.

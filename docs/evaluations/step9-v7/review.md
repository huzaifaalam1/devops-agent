# V7 compatibility experiment

Review by the implementing Codex agent, not an independent human reviewer.
Two fresh synthetic cases were fixed before sending. The unchanged Groq model
openai/gpt-oss-120b received exactly two requests, more than 60 seconds apart,
with retries disabled. Both responses passed structural validation; neither
executed an action. Total reported usage: 3,007 tokens across both requests.
181 offline tests passed, plus simulated contract runs for both new fixtures.

## Python launcher

The model correctly connects the absolute python2 shebang to its missing
interpreter and the startup failure. This is more specific than the deterministic
unknown-failure diagnosis. It proposes inspection rather than switching to Python3.
However, the check repeats the supplied inventory rather than inspecting source
and dependency compatibility. The uncertainty misleadingly suggests an interpreter
at another path could make the existing absolute shebang resolvable; merely being
installed elsewhere does not do that. It also includes a command example despite
the prompt prohibition. This output does not pass all semantic requirements.

## Native module ABI

The model correctly identifies the compiled-module/runtime ABI mismatch, which
the generic baseline does not explain. It recommends no runtime substitution or
rebuild. Its next check and uncertainty repeat the supplied runtime module version
rather than inspect the explicitly missing supported-runtime/build requirements.
It includes a command example despite the prompt prohibition. The explanation is
useful, but the uncertainty and inspection quality remain inadequate.

## Decision and next work

Neither response recommends an unverified compatibility-changing edit, but this
small experiment cannot establish that such advice is reliably prevented. Prompt
instructions are not semantic enforcement. The original four-case superiority
gate remains NOT PASSED; this experiment does not replace it. No extra live calls
were made. These two cases are now regression cases, not unseen evaluation data.

Before another live evaluation, decide how to handle unsupported uncertainty and
redundant inspections: test candidate changes offline against the retained outputs,
while acknowledging that mocked tests cannot prove model behavior. Freeze the
candidate and a fresh full evaluation set before using further request budget.

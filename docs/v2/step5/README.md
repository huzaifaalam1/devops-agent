# V2 step 5: Django repository understanding

Complete for the bounded Django/pip inspection contract. CLI `analyze`, offline
chat `/inspect`, and the model's inspection tool now return Django-specific facts,
source locations and blockers. A clear discovery has `discovery_status: understood`
but `eligibility: blocked`: `django_execution_not_enabled` deliberately prevents
Next.js generation and runtime adapters from running a Django project.

## Supported inspection

- Select one application root containing manage.py and pip requirements.txt.
- Follow relative `-r` / `--requirement` includes inside that root, with cycle,
  symlink, size, file-count and depth checks. This workflow requires stable explicit
  direct dependency pins; options, constraints, conditional markers, local/VCS/URL
  dependencies and conflicting pins receive concrete blockers. It does not resolve
  or lock transitive dependencies.
- Read numeric `.python-version` or `runtime.txt` declarations and check optional
  `[project].requires-python` metadata. Resolve conflicting declarations explicitly;
  do not silently choose a Python version from a broad constraint or Docker image.
- Check declared Django/Python version combinations against the documented matrix
  for Django 4.2, 5.0, 5.1, 5.2 and 6.0, including patch-specific Python additions.
  This is compatibility evidence, not a lifecycle or security recommendation.
- Extract literal `os.environ.setdefault('DJANGO_SETTINGS_MODULE', ...)` candidates
  from manage.py; locate a unique settings module/package. Static extraction does
  not import code. Overrides, conditional selection and ambiguity require review.
- Identify database-engine literals and environment-variable names, never values.
  SQLite and PostgreSQL are within the v2 plan. Computed, imported, unpacked or
  multiply assigned database settings require review. Arbitrary Python effects,
  custom aliases/helpers, runtime overrides and dependency installability remain
  explicitly unverified.

Sources for compatibility: [Django 5.2 installation FAQ](https://docs.djangoproject.com/en/5.2/faq/install/)
and [Django 6.0 installation FAQ](https://docs.djangoproject.com/en/6.0/faq/install/).
Third-party dependencies may impose additional restrictions; installation must
still be verified separately. Fixtures pin Django 5.2.8 for reproducibility, not
as a recommendation of the latest release.

## Verification

- **292 offline tests pass**, with no skips or expected failures. Coverage includes
  CLI output, Next.js regression protection, includes/cycles/escaping, dependency
  ambiguity, settings ambiguity, Python conflicts, compatibility thresholds,
  secret-value exclusion and refusal to execute repository code during inspection.
- Installed CLI analysis and offline chat both report Django. Their default execution
  gate rejects Django even with an existing Compose setup.
- Final **two live Groq cases pass**: a clear Python 3.12/Django/SQLite fixture and a
  fixture with conflicting Python declarations plus imported/computed settings.
  These are explanation checks, not broad agent-behavior certification.
- **Two real Docker fixture runs passed.** The final image ran Python 3.12.15,
  Django 5.2.8 and SQLite, matching inspection. The independent HTTP check returned
  200 with `django-step5-ready`; a SQLite `SELECT 1` returned 1. No migrations or
  application database workflow are claimed. Owned containers, network and image
  were removed; unrelated running containers were preserved.
- The Docker harness explicitly builds/runs a known test fixture. The product's
  Django setup/run gate remains closed until step 6. This does not implement step 6.
- The external Django/Vue pilot remains outside whole-repository execution scope.
  Its backend reports unpinned dependencies, missing Python selection, and dynamic/
  imported database settings. No pilot files were changed or pilot runtime claimed.

The first live attempt produced a vague answer and a local schema rejection. Its
original minimal keyword check incorrectly passed the vague answer; human review
rejected it. The prompt and acceptance checks were tightened; both intermediate
and final reruns passed. All six model requests and both Docker runs are accounted
for in the retained reports. The verification source hashes match across the final test/live/Docker
reports. The manifest also records a subsequent whitespace-only source cleanup
and a test-harness exit-status correction. Earlier reports are historical, not evidence for the final source.

Reproduce offline checks with `python -m tests.run_baseline`. Explicit live/Docker
acceptance: `python -m tests.django_step5_smoke --docker --live` (configured Groq
key, Docker Desktop, network and 8 GiB free disk required). The fixture is copied
into a disposable directory; this does not execute user repository code.

Next: step 6, reviewed Django development Docker proposal/apply/run.

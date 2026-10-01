# External References

Consulted on 2026-10-01. The supplied repository v2 is the design baseline; these
primary sources support the implementation details below. They are not evidence
that this pipeline has executed real video analysis or imported a Resolve timeline.

1. JSON Schema, object properties and closed-object composition:
   https://json-schema.org/understanding-json-schema/reference/object
2. JSON Schema, schema identification, `$ref`, and reusable definitions:
   https://json-schema.org/understanding-json-schema/structuring
3. JSON Schema, conditional validation:
   https://json-schema.org/understanding-json-schema/reference/conditionals
4. python-jsonschema, Draft202012Validator, meta-schema checks, formats, and errors:
   https://python-jsonschema.readthedocs.io/en/stable/validate/
5. python-jsonschema, modern `referencing.Registry` integration and retrieval policy:
   https://python-jsonschema.readthedocs.io/en/stable/referencing/
6. OpenAI, Codex skills documentation (may redirect to the current skills guide):
   https://developers.openai.com/codex/skills
7. Google Antigravity, workspace and CLI skill locations:
   https://www.antigravity.google/docs/skills

Platform-specific skill availability and local file access must be checked in the
actual runtime. Committing shared instructions does not install a new capability
inside browser ChatGPT or grant a CLI permission to access media or the network.

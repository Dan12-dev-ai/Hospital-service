"""The integration API for hospitals' own systems (docs/integrations.md).

* :mod:`.scopes`: what a connection may do, with plain-language labels;
* :mod:`.jose`: compact JWS (ES256, RS256) and JWKs, on ``cryptography``;
* :mod:`.signing`: the service's key that signs access tokens;
* :mod:`.clients`: connections (secrets, public keys, address limits);
* :mod:`.tokens`: the token endpoint and access-token checks;
* :mod:`.fhir`: FHIR writes, through the import mapping (app/imports.py);
* :mod:`.journey`: the patient journey (patients, links, booking decisions,
  the queue, follow-ups, prescriptions), on the portal's own domain code;
* :mod:`.calls`: what every call shares (the caller, Idempotency-Key);
* :mod:`.schemas`, :mod:`.fhir_docs`, :mod:`.apidoc`: the OpenAPI document's
  models, FHIR schemas and examples, webhook payloads;
* :mod:`.webhooks`: signed events to the hospital's system, with SSRF guards;
* :mod:`.ratelimit`: per-process sliding windows.
"""

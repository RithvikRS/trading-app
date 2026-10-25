# Private model diagnostics

Internal account, instrument, market, preference and configuration boundaries revalidate supplied models. Pydantic models assembled with `model_copy` or `model_construct` can contain values that bypass initial validation. Serializing such a model before revalidation can emit a warning containing the rejected input, even when the eventual validation error hides that input.

These boundaries suppress serializer warnings for that individual operation with `model_dump(warnings=False)`. They retain their existing strict validation, exception types and rejection before SQL, write transactions or application/provider-client creation. The private INDmoney document serializer also suppresses warnings before its existing token-custody and attempt-document parsing boundaries. This changes diagnostic handling only; it does not add coercion, accept previously invalid values or alter the private document format. No global warning filter is installed.

The change covers account creation; scheme, instrument, listing and provider-identifier creation; market queries and recording; preference saves and revision comparisons; injected API/Supabase configuration; and private connector document serialization. The separately implemented reader/inspector credential boundaries retain their own diagnostic checks. Serializers that operate on already validated output are outside this change.

## Reachability and verification

Current HTTP request models, provider responses and configuration loaders validate their raw inputs before these operations. The reproduced issue concerns malformed internal model instances; it is not evidence of a remote validation bypass or an observed disclosure of real account information. Credential custody and diagnostic privacy remain separate from provider compatibility and hosted security acceptance.

[Focused regressions](../backend/tests/test_private_model_diagnostics.py) use fabricated markers in copied and constructed models. They capture warnings, logs, stdout/stderr and public exception text, assert unchanged validation failures, and deny any SQL/write or application/provider-client creation for malformed inputs. Connector cases exercise rejection by token custody and the attempt-document parser. Existing account, instrument, market, preference, API, authentication and connector tests continue to cover valid behavior.

Run the focused module from `backend/` with `python -m pytest tests/test_private_model_diagnostics.py`, followed by the affected contract/provider tests and the normal [verification groups](verification.md). No schema, dependency, route, provider-access or financial behavior changes are introduced.

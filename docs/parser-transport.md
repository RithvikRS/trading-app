# Bounded parser transport contracts

Step 5B.1 defines the local stream protocol that a separately isolated document worker can use. It is a protocol library with fabricated tests, not an enabled file upload, PDF parser, worker deployment or source compatibility claim. No browser route or financial write uses it yet.

## Framing and limits

Each stream carries exactly one request and one reply. The sender half-closes its write side after the frame; trailing bytes, truncated frames and absent completion fail. One monotonic deadline covers all reads or writes in an operation, so a slow sender cannot renew its time limit with each byte. Deadlines must be finite, positive and at most 60 seconds; the worker/client must choose their operational bound explicitly.

Requests have a fixed versioned binary header, metadata length and document length. Limits are 8 MiB of document bytes and 2 KiB of metadata. Lengths and metadata are validated before allocating the document body. Metadata must be strict UTF-8 JSON with exactly the declared fields, integer protocol version 1 and a 32-character lowercase hexadecimal attempt reference. Duplicate keys, unknown fields, non-finite constants and invalid types are rejected.

`probe` carries no adapter, password or document. `parse` carries a requested adapter identifier, bounded password and nonempty bytes. The reserved CAMS/KFintech identifiers describe requested formats only; neither adapter is enabled by this library. Passwords allow at most 256 characters and 1,024 UTF-8 bytes, reject NUL/invalid Unicode and never appear in object representations or errors. No filename, path, URL, owner ID, command or credentials for external providers are accepted.

Replies have their own versioned header and a 512-byte bound. The only current statuses are ready, unsupported format, invalid input, unavailable and busy. Ready is valid only for a probe. A reply must match the request's attempt reference. No successful parsed-data response exists yet; enabling one requires a reviewed strict result schema and adapter implementation. Correlation is not authentication or proof of financial correctness.

All failures use a fixed description without input text. The library performs no logging, filesystem access, process creation, network connection, persistence or financial operation. It operates only on the stream supplied by its caller. Plaintext lifetime and physical memory erasure cannot be guaranteed by a Python protocol object.

## Required caller and worker boundaries

Before this protocol can carry real statements, the application must verify authenticated ownership, active MFA, CSRF/origin, secure transport, bounded admission and revocation around staging. File I/O cannot hold a financial transaction open. Browser financial JSON limits remain separate from a narrowly defined file route; proxy buffering must not write plaintext statements to persistent storage.

Provision the worker independently with no database, session or provider credentials, no external networking, least privilege and hard resource limits. The API must not gain Docker access or arbitrary execution capability. A dedicated filesystem socket with a read-only API mount is a tested transport option; caller/worker identity, stale socket recovery, native parser isolation, cancellation, full process cleanup and cross-request confidentiality still require implementation and acceptance. Framing tests do not establish those controls.

## Verification

Fabricated stream cases cover request/reply round trips, Unicode passwords, malformed and oversized headers, metadata rejection before body reads, duplicate/deep/invalid JSON, partial and surplus payloads, mismatched attempts, unsupported statuses and whole-operation deadline expiry. A real local socket pair checks the half-close exchange. Tests contain no customer documents or credentials.

This step changes no schema, privileges, dependencies or recovery format and creates no durable records. The [investment flow plan](investment-flow-plan.md) tracks the remaining worker, source-adapter and application work.

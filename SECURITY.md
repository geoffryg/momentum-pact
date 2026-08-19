# Security

Momentum Pact is local-first and its data may contain sensitive commitments,
notes, and history. Runtime JSON data, logs, environment files, and credentials
must not be committed.

Before the repository becomes public, security reports will be handled privately
through the repository owner. A public reporting channel will be documented at
release time.

If a credential or private dataset is committed accidentally, remove it from
history before publication and rotate the credential. Deleting it only from the
latest revision is not sufficient.

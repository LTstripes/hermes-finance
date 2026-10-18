# Hermes Finance backend

FastAPI/SQLAlchemy backend; this README is retained for package metadata. From the repository root use the locked development setup and verification commands in [Development](../docs/DEVELOPMENT.md#d2). [Contracts](../docs/ARCHITECTURE_AND_CONTRACTS.md) owns exact financial/API semantics. Installed runtime commands belong to [Operations](../docs/OWNER_RUNTIME_OPERATIONS.md).

The backend is the financial source of truth. Production data, credentials and database files stay outside code/CI. Released migration files, including migrations/README, participate in compatibility digests and must not be rewritten.

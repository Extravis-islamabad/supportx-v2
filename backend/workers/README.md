# workers

NATS JetStream consumers (outbox relay, fan-out, indexing) and Temporal workers. They run as separate
deployables (ADR-001) but share the `app` code. First consumers arrive in **WP-007**.

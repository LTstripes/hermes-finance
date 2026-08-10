# ADR 0004 — Localhost Host/Origin protection

**Status:** Accepted for R02-05  
**Scope:** local single-user HTTP ingress only

## Context

Hermes Finance intentionally has no authentication and is not a public/VPS service. The production launcher binds the backend to loopback (`127.0.0.1`, normally port `8000`). Development uses Vite at `127.0.0.1:5173` and proxies `/api` to the backend with `changeOrigin: false`.

Binding to loopback is necessary but does not by itself defend against browser-originated requests to localhost or DNS-rebinding-style Host values. Absence of permissive CORS is not a complete write-protection mechanism either.

## Decision

### Host

Every HTTP request must have a local Host authority whose hostname is exactly one of:

- `127.0.0.1`;
- `localhost`.

A valid optional TCP port is allowed. The middleware deliberately does not hardcode port `8000` because the backend port is configurable and the Vite proxy preserves its `127.0.0.1:5173` Host header. Non-local, malformed, userinfo-style, wildcard, or invalid-port Host values are rejected with D08-shaped HTTP `400 bad_request`.

The in-process Starlette `TestClient` synthetic pair (`Host: testserver` with peer `testclient`) is accepted only for the test harness. A real Uvicorn peer address cannot satisfy that condition.

### Unsafe browser requests

`GET`, `HEAD`, and `OPTIONS` are read/safe methods for this guard. Other methods are treated as state-changing.

For a state-changing request:

- if an `Origin` header is present, it must be plain `http` and its exact local authority (hostname + optional port) must equal the request Host authority;
- `Origin: null`, HTTPS/foreign origins, different local ports/authorities, malformed origins, paths/query/fragment/userinfo, and remote origins are rejected with D08-shaped HTTP `403 forbidden`;
- if `Origin` is absent but `Sec-Fetch-Site: cross-site` is present, the request is rejected as defense in depth;
- if both browser-origin signals are absent, the request is allowed. This preserves deliberate local CLI/API usage such as PowerShell `Invoke-RestMethod`, curl, seed/admin scripts, and test clients.

This is not authentication. A process already running with local machine access remains inside the trusted-machine boundary of the application.

### Development flow

No wildcard CORS policy is added. The canonical Vite frontend uses relative `/api` URLs and the existing proxy. With `changeOrigin: false`, a browser request from `http://127.0.0.1:5173` reaches the backend with matching local Host/Origin authority and is accepted.

Direct arbitrary cross-origin development calls are not part of the contract; use the Vite proxy.

## Consequences

- Foreign Host values cannot read local API responses through a DNS-rebinding Host.
- Cross-origin browser writes from unrelated websites are rejected server-side.
- Normal production UI, Vite dev proxy, health/read endpoints, and origin-less local PowerShell/API calls remain usable.
- The application remains loopback-only and does not gain auth, HTTPS, cloud, telemetry, public hosting, or wildcard CORS.

## Verification

R02-05 regression coverage must include at least:

- foreign Host rejected on a read request;
- `127.0.0.1` and `localhost` reads allowed;
- foreign Origin rejected on a state-changing request;
- same-origin local write allowed;
- Vite `127.0.0.1:5173` Host/Origin pair allowed;
- origin-less local API write allowed;
- existing application test suite remains green under the middleware.

# Repository security review — 2026-10-22

## OpenCode review follow-up — PR #929, 2026-10-22

The original remediation is committed at `58cbb8cd736bfc6036d956fe28a86825ab894b0e` on `review/security-audit`; it is no longer an uncommitted candidate at `5394962`. OpenCode reviewed that committed HEAD against pinned main `fd51120dd763a13d3ee98e3619d92c6bbca2db5c` and returned CHANGES (five findings). Its synthetic readback reported 53 security tests passed and 58 protected-backup tests passed / 2 skipped. That review verified the logging, remote-URL, archive-budget and CI privacy-gate protections, but identified the gaps below.

The Owner assigned all five follow-up fixes in this same checkout. This follow-up candidate is the **uncommitted working-tree diff on top of `58cbb8cd`**; no staging, commit or push is authorized. The existing local ownership record matches this security-audit task. Current source/status and the assigned local OpenCode review were read under the repository-only restriction; no external issue/Integrator lookup or network fetch was performed.

| OpenCode finding | Follow-up behavior |
|---|---|
| 1 — SEC-06 sibling validators and generic exceptions | Deposits, debts, incomes, instruments, expenses, planned budget, expected flows, investment flows, IIS and positions use fixed unsupported-value guidance. Generic ValueError/LookupError messages pass only an exact reviewed literal allowlist; all other messages use fixed fallbacks. Typed domain handlers and existing machine-readable codes remain intact. Deposit/instrument POST and PATCH regressions cover sibling endpoints; arbitrary generic text and allowlist-prefix/suffix attempts are rejected without echo. |
| 2 — supported multi-original batches | The ingress file cap is 32, supporting one primary file plus 31 originals. Both broker-month preview and apply accept 32 files and reject 33 before service invocation. The dedicated preflight retains its stricter 8-file policy. |
| 3 — large apply selections | Non-file fields permit 1 MiB. The existing 8 MiB/file and 32 MiB aggregate caps remain enforced. Tests cover exactly 1 MiB versus one byte over, plus a real prepare→apply of 301 synthetic selected rows with a selections field larger than 64 KiB. |
| 4 — typed backup creation cap | Snapshot hashing and bounded artifact construction raise ProtectedBackupError for an oversized snapshot; publication preserves earlier verified points and cleans its temporary snapshot. O4 now states the 256 MiB creation cap as well as verification limits. Tests exercise the boundary with a reduced synthetic cap and publication cleanup. |
| 5 — delivery/status drift | CURRENT_STATUS and this delivery section distinguish the committed original remediation from this uncommitted follow-up and use the actual current check counts. |

The underlying SEC-01–SEC-05 protections remain: route-template/class-only diagnostics and hidden SQL parameters; fixed rejected-remote guidance; memory-only bounded multipart parsing with independent wire/file/aggregate/count/header limits and buffer cleanup; stored-only, exact-member recovery archives and bounded XLSX reads; credential/path heuristics and privacy-gated evidence uploads. HTTP and Pydantic handlers retain their existing contracts; the new exact-message allowlist applies specifically to generic ValueError/LookupError handling. Privacy scanning is a text heuristic, not certification of binary artifacts or Git history.

Verification uses the Owner-selected Python interpreter, with PYTHONPATH set to this checkout's backend/src and the working directory set to backend. Import readback confirms this checkout. No dependencies were installed or updated. The standard shell failed during process setup; local Node child_process ran the commands. Test databases, uploads and backup destinations are synthetic, with fresh tool-temporary scratch roots outside the Git checkout for backup destination checks.

Current verification:

- Security: **70 passed**, no xfail markers (53 at the reviewed HEAD plus 17 follow-up cases).
- Protected backups: **61 passed, 2 skipped** (Windows symlink creation unavailable; Linux-only unlinkat). This includes all three new creation-boundary/cleanup cases.
- API, statement-import and broker-month suites: running; final result will replace this line before delivery.
- Ruff check and formatting passed for the 16 changed Python files; final readback follows checks.
- scripts/privacy_check.py: PASS, 1,330 tracked files. git diff --check: PASS.

Delivery readback: baseline/HEAD `58cbb8cd736bfc6036d956fe28a86825ab894b0e`; branch `review/security-audit`; assigned workspace `sec-audit`. Cached origin/review/security-audit matches HEAD and cached origin/main is `fd51120dd763a13d3ee98e3619d92c6bbca2db5c`. Remote network state was not queried. All follow-up changes remain unstaged and uncommitted. Final diff/stat and check readback will be recorded here before delivery.

No Owner/Stable/Test/auth data, classification/XIRR source, dependency lock or runtime was changed. No provider, dependency advisory, CI, release, runtime/UAT or independent acceptance result is claimed. Independent review of this follow-up and Integrator acceptance remain pending. The historical assessment below retains its original scope and execution limits.

Independent SECURITY REVIEWER; repository-only assessment. **3 medium, 3 low findings; no confirmed critical/high finding or live committed secret.** Dependency advisory status and pytest execution remain **UNVERIFIED**, not clean/passed.

## Continuation verification — 2026-10-22

This section records the resumed assignment and supersedes pending execution instructions below. Earlier investigation/history counts are retained as earlier-run evidence; history was not rescanned. The existing local ownership record matches this security-audit task. No dependency installation, network tool, product-code change, commit or push was performed in this continuation.

- **Urgency:** prioritize SEC-01 diagnostic redaction and SEC-02 remote-URL redaction to prevent sensitive output, then verify and address SEC-03 upload resource limits before relying on upload-size enforcement. No critical/high finding was established in the reviewed scope; these are findings, not implemented fixes.
- Existing checkout Python and Python on PATH both report **3.13.16**, with pytest, FastAPI, Uvicorn, SQLAlchemy and multipart dependencies absent; the Python launcher is unavailable.
- Requested normal command: .venv/Scripts/python.exe -I -m pytest backend/tests/security/test_security_review.py -q — **exit 1, No module named pytest**.
- Requested assertion command: same command plus --runxfail — **exit 1, No module named pytest**. Neither collected tests; no XFAIL/XPASS/assertion count is claimed.
- Reran the inspected, existing .venv/review-probes.py and .venv/echo-probe.py with the checkout interpreter: **both exit 0**. SEC-01/02/04/05/06 reproduce with synthetic inputs; four intended assertion functions fail as expected under direct invocation. **21 control assertions pass** (10 Host/Origin, 8 XML, 3 static containment). These probes use source extraction/stubs where documented below and are not pytest/ASGI results.
- The test file still has **10 strict assertion-only XFAIL tests**, grouped into six findings; its runtime/release taxonomy registration is unchanged. No test defect was demonstrated that justified changing a test.

## Not verified

- **pip-audit and npm audit were not run in this continuation** under the no-network/no-install instruction. Earlier attempts did not return advisory results. Dependency CVE status remains unknown.
- Normal pytest and --runxfail results, locked framework compatibility, actual multipart disk spooling, default ASGI access/error logging and full API response behavior remain unverified because dependencies are absent.
- Full product suites, CI, independent acceptance, live runtime/UAT, installed configuration, real credentials, provider connectivity and actual CI artifact contents were not tested.
- No fresh secret/history scan or remote network-state verification was performed. Earlier negative heuristic results do not prove absence of secrets.

## Scope and authority

- Assigned baseline and product target: fd51120dd763a13d3ee98e3619d92c6bbca2db5c (Owner-pinned main snapshot, PR #926). Branch: review/security-audit; Owner-assigned physical checkout: sec-audit.
- Assignment: Owner's security-review instruction in this conversation; no issue number supplied. Read repository D1/D2/D4/D5, C1/security and applicable source/provider/import/privacy contracts, CURRENT_STATUS and local Git receipts. The status snapshot predates some commits; the pinned source is the target. No network fetch of issue/Integrator notes was authorized or performed.
- Only repository source/history and synthetic probes were inspected. No Owner data, real statements, external runtimes, external environment/authentication files or credential stores were opened. No product code, locks, financial state or runtime was changed. No account-backed provider was contacted.
- The explicitly assigned checkout/branch takes precedence over creating another checkout. A local ownership record and tool/temp/cache files are under ignored .venv/. Standard command execution failed at process setup; commands below ran through local Node child_process instead.
- No fetch, push, merge, release or publication. Local refs can advance independently; this assessment does not follow those changes. Remote network state was not verified.

## Findings

Locations refer to the pinned product target. Test names below are in backend/tests/security/test_security_review.py.

| Severity | File:line | Description | Reproduction | Suggested fix |
|---|---|---|---|---|
| medium | backend/src/hermes_finance/security.py:93; backend/src/hermes_finance/api/errors.py:107; backend/src/hermes_finance/cli.py:69; backend/src/hermes_finance/database.py:304 | **SEC-01 — URLs and unhandled exception text can retain private data in logs.** Ingress/error handlers log arbitrary request.url.path, including a filename/account/amount put in an unmatched path. Standard startup supplies no access-log or exception redaction configuration. Default server diagnostics can additionally expose queries and uncaught exception text. SQLAlchemy parameters are not hidden, so uncaught database exceptions can carry bound financial values. This is local diagnostic disclosure, not evidence of telemetry. | test_rejected_request_does_not_log_private_filename: foreign Host plus synthetic filename path is copied into the actual ingress log call; confirmed by source-function probe. test_default_access_log_does_not_record_private_query and test_unhandled_error_log_drops_financial_exception_text drive Uvicorn in memory; **not executed** because dependencies are unavailable. | Log route templates/fixed route IDs, omit arbitrary path/query values, explicitly configure access logging, and sanitize unhandled server errors to an ID/class. Consider hide_parameters=True as an additional SQLAlchemy safeguard. Preserve useful curated diagnostics. |
| medium | scripts/release-lib.ps1:148 | **SEC-02 — rejected remote URL exposes embedded credentials.** Test-HermesExpectedGitHubRemote interpolates the whole rejected URL into its exception. A credential-bearing remote could leak its password/token into terminal or CI error output. No configured remote or live credential was read to demonstrate this. | test_release_remote_error_redacts_credentials supplies a constructed synthetic userinfo URL directly to the validator. Direct PowerShell execution confirms its credential marker appears in the captured rejection; the intended assertion fails. | Use a fixed rejection or parsed allowlisted host/repository identifier. Never echo userinfo, sensitive query parameters, or the original URL. |
| medium | backend/src/hermes_finance/api/mybroker_import.py:92; backend/src/hermes_finance/api/statement_import.py:210; backend/src/hermes_finance/api/source_intake.py:30; backend/src/hermes_finance/api/broker_months.py:77 | **SEC-03 — ordinary multipart limits are after framework parsing/spooling.** File/UploadFile routes check file length only after multipart parsing has supplied the upload, without a common ingress byte budget. Oversized files/parts can consume temporary disk/I/O before 413, and originals can transiently reach system temp. The dedicated preflight endpoint explicitly avoids this; other import/intake routes still use framework uploads. Exploitation requires a local client or permitted browser context, not a demonstrated hostile-origin CSRF bypass. | test_oversized_xml_is_rejected_before_disk_spooling instruments spool rollover and submits synthetic bytes just above 8 MiB. **Source-established risk; actual ASGI/spooling behavior with locked Starlette 1.3.1 is unverified here.** | Reuse bounded streaming multipart handling across uploads. Enforce wire/per-file/aggregate/count/header limits before buffering/spooling, including absent/dishonest Content-Length, and clean up on disconnect. If temporary originals are intentionally allowed, use controlled storage. |
| low | backend/src/hermes_finance/services/protected_backups.py:457; backend/src/hermes_finance/services/recovery_rehearsal.py:739; backend/src/hermes_finance/services/legacy_excel.py:360 | **SEC-04 — archive expansion lacks a budget before reads.** Backup verification reads members before checking expanded sizes and accepts compressed input long enough to expand it, although its producer emits ZIP_STORED. Later hash/canonical rejection cannot prevent that work when no trusted expected hash is supplied. Artifact files are read wholly into memory. The operator-only XLSX reader opens two workbooks without an explicit compressed/expanded budget. These are local recovery/import surfaces, not a public ZIP endpoint. | test_compressed_recovery_manifest_rejected_before_expansion: a small synthetic compressed manifest expands to 262,146 bytes before format rejection. Confirmed using unchanged validator functions with unavailable ORM imports excluded. No large bomb, real backup or workbook opened. XLSX was inspected statically only. | Validate compression method, member/aggregate sizes, count and duplicates before reads; use bounded streaming and an artifact input cap. Preserve exact member-name/trusted-hash checks. Add an explicit ZIP/XML resource policy to operator-selected XLSX. |
| low | scripts/privacy_check.py:79; scripts/privacy_check.py:99; scripts/ui_evidence_identity.py:259; .github/workflows/ci.yml:381; .github/workflows/ui-v2-evidence.yml:80 | **SEC-05 — privacy gates are heuristic and bypassable.** Tracked-content scanning misses generic credential assignments and credentialed URLs without known prefixes; the .git-credentials pathname is allowed. It examines current files only and skips binary/non-UTF-8 content. Valid-provenance UI packages can include a nested diagnostic .log under frontend-dist. Uploaders are not conditioned on the separate Privacy guard; ordinary journey evidence has no content scrub. Existing inspected fixtures are synthetic; no actual private artifact leak was established. | test_tracked_content_guard_detects_generic_password, test_tracked_path_guard_rejects_git_credential_store (path string only), and test_evidence_package_rejects_nested_diagnostic_log all fail their intended assertions when directly invoked with stdlib. The last supplies valid provenance plus synthetic evidence. | Extend path/credential detection with explicit synthetic-fixture exceptions and history/commit-range coverage. Gate uploads on privacy success, stage an explicit artifact allowlist and check staged contents. Provenance/suffix checks and synthetic filenames do not establish that every byte is public. |
| low | backend/src/hermes_finance/api/accounts.py:81; backend/src/hermes_finance/api/accounts.py:148; backend/src/hermes_finance/api/errors.py:106; backend/src/hermes_finance/api/errors.py:315 | **SEC-06 — errors can echo supplied private values.** Generic ValueError/HTTPException handlers return exception text/detail. Account validators interpolate invalid values; duplicate external-code errors include the account code. Omitting bodies from logs does not guarantee clean error responses. The caller normally already knows the supplied value: this is data minimization/diagnostic propagation, not a demonstrated cross-origin read or XSS. | test_invalid_account_type_not_echoed_in_error_response submits a short synthetic invalid type and expects 422 without it. Unchanged validator/error-handler source-function probe confirmed the echo; full ASGI test **not executed**. | Map validation failures to stable codes/fields and curated messages. Avoid raw exception strings and provider/account values in errors; keep intended financial facts in explicit DTO fields. |

## Checked and OK

Executed controls are distinguished from source inspection; these are not production/runtime certification.

- **Secrets/history:** 1,325 tracked baseline paths and 1,702 distinct historical path names inspected. Clone is not shallow. All local refs reach **2,106 commits**. Deduplicated cat-file scanning inspected **6,838 blobs / 152,405,975 bytes**; streamed full patch history covered **939,578 lines**. No committed .env other than examples, credential-store/auth-file pathname, private key or confirmed live secret was established. Matches were synthetic test credentials/URLs/accounts, status text and environment-variable names. Values were never emitted or checked against providers.
- Patterns included provider/GitHub/AWS/Google/Slack prefixes, private-key blocks, JWTs, quoted/bare credential assignments, Basic/Bearer literals, credentialed/query-token URLs, private-address/internal-domain URLs and 20-digit account-like strings. Examples: backend/tests/test_alfa_pro_probe.py:200 (synthetic credential URL); backend/tests/test_payout_api_hardening.py:37 (synthetic authorization literal). No credential value is reproduced here. Heuristics cannot prove absence of arbitrary/encoded secrets. Image pixels, unreachable objects, server-only refs and absent LFS payloads were not decoded/fetched.
- **HERMES_ALFA_PRO_TOKEN:** no current source consumer at this target. Historical local commit 26be7a50ff148b95d4af53d0bda7ecea648f5697 contains alfa_pro_handshake.py: reads an environment token at connect, uses Authorization on loopback, rejects controls/query/userinfo, disables proxy use, and suppresses raw handshake exception chains. That branch does not establish integration into the pinned target. Current Alfa paths use local router bus authentication state and sanitized failure summaries. No token was read/sent in this review.
- **Bind/CORS:** settings.py:23,30 permits exactly 127.0.0.1 and cli.py:69 uses it. Vite development/preview bind 127.0.0.1. No supported production 0.0.0.0 bind or wildcard CORS middleware found. Alternative direct Uvicorn invocations are outside supported launcher policy.
- **DNS rebinding/browser writes:** security.py:21,89 validates Host on every method and Origin for unsafe methods. Foreign/null/mismatched Origins are rejected; originless cross-site Fetch Metadata writes are rejected. Direct helper controls passed five hostile Hosts, one valid same-origin and four invalid Origins (**10 checks**). The TestClient exception requires its synthetic peer identity.
- **Authentication/CSRF boundary:** no user authentication/session or general CSRF token by the deliberate single-user local contract. Originless local clients remain allowed. Host/Origin checks address ordinary cross-origin browsers, not other local processes, compromised extensions or frontend XSS. This review adds no authentication architecture.
- **Static paths:** main.py:121 resolves paths and checks containment below resolved dist. Three synthetic traversal/absolute-path checks passed against the unchanged function with response construction stubbed. All probe files were inside this worktree. Dist rewrite/link races by a process able to edit the application were not exercised.
- **XML:** standard ElementTree, not defusedxml. mybroker.py:266 requires UTF-8-sig and <=8 MiB, blocks DTD/ENTITY before parsing, then checks depth <=32 and <=100,000 nodes; row limits also exist. Secondary identity/metadata/intake parses follow primary validation. **8 direct rejection controls passed:** external entity, small entity expansion, UTF-16, oversized document, depth, node count, traversal filename, ZIP bytes as XML. No entity resolution. Schema-location text is checked, not fetched. Tree node/depth checks are after construction, making the byte cap essential.
- **ZIP paths:** recovery membership must be exactly manifest.json then snapshot.sqlite3. No extractall/unpack into supplied member paths found. Extra/traversal/duplicate names are rejected by exact membership, independently of SEC-04 resource consumption. XML/PDF routes do not offer general ZIP extraction.
- **Provider diagnostics:** Alfa sanitizers return fixed class-based summaries; T-Invest maps auth/transport/malformed errors to fixed messages rather than provider bodies. Settings stores its T-Invest token as SecretStr. Curated application errors do not intentionally enumerate Authorization/Authentication headers or whole bodies. SEC-01/06 qualify broader privacy claims.

## What can leave the machine

| Surface / source | Destination and content | Trigger, gates and limits |
|---|---|---|
| market_data/t_invest.py:43,787; production routing | Official T-Invest REST: read-only bearer token, instrument search/IDs, requested dates and market-data request fields. Methods: FindInstrument, GetInstrumentBy, BondBy, GetLastPrices, GetCandles, GetBondCoupons, GetBondEvents, GetDividends. | On-demand discovery/quote/payout workflows. These calls do not send holdings, original files or DBs. No call executed here. HTTP client environment proxies may apply; machine configuration was not inspected. |
| market_data/moex_iss.py:57,87 | MOEX ISS public instrument queries, IDs/boards and dates. | Adapter exists, but routing.py:58,77 disables live MOEX production routing/verification. Explicit direct callers remain capable of egress. |
| broker_data/alfa_pro/adapter.py:84; alfa_pro_probe/live.py:59 | ws loopback router, default 127.0.0.1:3366: bus/query requests and received personal accounts/positions/cash. | Endpoint rejects non-loopback, credentials, query and fragment; bus/auth/read-only gates restrict channels; probe needs live mode. Current wrappers do not explicitly set proxy=None. Library/proxy routing behavior is **unverified** because locked websockets could not be installed. Explicitly pin direct routing as hardening; no proxy config/live connection inspected. |
| Frontend client/UI | Relative same-origin /api requests: selected originals, amounts and account metadata go to local backend. | No external fetch URL, telemetry SDK, sendBeacon, required remote font or automatic application update check found in production frontend source. Schema IDs/links are not requests. |
| AI/financial exports and protected backup | Local download or explicitly configured filesystem destination; exports intentionally include financial facts. Destination may itself be OS-synced. | No automatic LLM/cloud upload found. Manual upload or OS sync is separate. Installed destination/encryption/sync not inspected. |
| Development/preparation/operations scripts | Python/npm/tool/browser registries and Git/GitHub source, CI and workspace metadata. | Explicit preparation/release/workspace commands, not a background app updater. Release helper's inspected gh release create call publishes a tag/notes with no DB/log/fixture asset arguments. Workspace scripts may use GitHub metadata; none invoked. |
| .github/workflows/ci.yml:381 | GitHub Actions: six explicit runner-temp Playwright result directories. Failure traces/screenshots/videos/attachments can contain HTTP data and financial-looking synthetic UI facts. | Uploaded even on failure. Fixture DBs use separate temp runtime directories, not listed result roots. No DB intentionally selected in inspected config; no actual CI artifact downloaded/verified. No content scrub (SEC-05). |
| .github/workflows/ui-v2-evidence.yml:52,80 | GitHub Actions: selected synthetic PNGs, production frontend dist, provenance; 7-day retention. | Successful capture/package validation. Paths reject .env/private/database suffixes; content safety is not proved (SEC-05). The separate Privacy job is not a workflow dependency. |

No telemetry, Astra or provider request executed. In the earlier interrupted run, pip/npm tooling/advisory attempts failed. No network tool was run in this continuation.

## Dependencies — advisory status UNVERIFIED

Earlier-run evidence: created local .venv with Python **3.13.16** and exported unchanged uv lock offline: **46 packages** including project. npm lock records registry versions/integrities. Manual inspection establishes versions/sources, **not** a current CVE assessment. No lock changed.

| Backend locked package | Version | Frontend locked package | Version |
|---|---|---|---|
| FastAPI / Starlette | 0.141.1 / 1.3.1 | React / React DOM | 19.2.8 / 19.2.8 |
| Uvicorn / websockets | 0.52.1 / 17.0.1 | React Router | 8.3.0 |
| python-multipart | 0.0.32 | Vite / Vitest | 8.2.0 / 4.1.10 |
| pypdf / openpyxl | 6.16.1 / 3.1.5 | Playwright | 1.62.1 |
| httpx2 / SQLAlchemy | 2.9.1 / 2.0.51 | jsdom / undici | 30.0.1 / 8.10.0 |

- pip-audit installation could not connect to PyPI (WinError 10013) and reported no available distribution. Isolated/configured-environment retries failed. Locked backend install separately failed at alembic==1.19.0. No unpinned-version or other-checkout/cache fallback.
- .venv/Scripts/python.exe -I -m pip_audit --version: **exit 1**, module absent. No successful advisory query.
- npm audit ran through installed Node/npm CLI (equivalent to npm.cmd audit), empty local user/global configs, local cache, ignore-scripts and frontend lock metadata only. Initial NUL config aliases collided; corrected configs reached an audit endpoint error at the npm registry (**exit 1**, no advisory response).
- **No dependency CVE is confirmed, and absence of known vulnerabilities is not asserted.** Re-run pip-audit/npm audit on an allowed network before treating this portion complete. No browser/advisory-service fallback because the Owner prohibited other external calls.

## Tests and actual verification

Added **10** pytest.mark.xfail(strict=True, raises=AssertionError, reason=...) tests. Import/setup errors do not qualify as expected failures. Assigned their file to the existing exclusive runtime/release lane in test taxonomy; no coverage/filter weakened. Network guards deny provider/app connections; Windows stdlib event-loop socketpair construction alone is permitted. PowerShell uses process-scoped ExecutionPolicy Bypass for a pure validator, without machine policy changes or actual Git remote/auth reads.

| Command/check | Actual result |
|---|---|
| git status --short --branch; git rev-parse HEAD; local history metadata | Clean assigned branch at pinned baseline before edits. No fetch. |
| git rev-list --all --count; git rev-list --objects --all; git cat-file --batch; streamed git log --all --root -p --no-ext-diff --no-textconv; historical pathname inventory | Completed; counts/limits above. Matches stayed in memory; only path/type metadata emitted. |
| python -I -m venv .venv; uv --no-config --offline export --python .venv/Scripts/python.exe --locked --project backend --format requirements-txt --no-hashes --no-emit-project | Completed; tool/export artifacts ignored under .venv. |
| pip-audit install/module invocation; npm audit | **Unavailable/failed** as above, not a pass. |
| .venv/Scripts/python.exe -I -m pytest backend/tests/security -q | **Exit 1: No module named pytest.** No collection or normal XFAIL result. |
| Same pytest command with --runxfail | **Exit 1: No module named pytest.** Not evidence of 10 assertion failures. |
| Local ignored .venv/review-probes.py | **Exit 0** after harness repairs. Four test assertion functions fail as intended (SEC-02 and three SEC-05 cases); unchanged ZIP/ingress functions reproduce SEC-04/01; **21 controls pass**. Harness removes decorators for direct calls and stubs unavailable framework/response types where noted; it is **not** a pytest substitute. |
| Local ignored .venv/echo-probe.py | **Exit 0:** unchanged validator/error-handler functions echo the synthetic invalid value (SEC-06); not full ASGI evidence. |
| Python compile/AST inspection | Both changed test files parse/compile; all 10 strict xfail decorators and exclusive runtime/release lane verified. |
| git diff --check; scripts/privacy_check.py | Whitespace passed. Baseline tracked-file privacy check passed (1,325 paths); new report/test files also checked directly because staging is blocked. Git ownership exception is process-scoped to this assigned checkout, with no global config change. |
| python -I -m ruff check / format --check on changed test files | Both exit 1: ruff module unavailable. Manual line-length/syntax checks completed; not a lint/formatter pass. |

Remaining verification outside this no-install assignment: run normal pytest and --runxfail with exact locked backend dev dependencies to establish actual XFAIL/assertion evidence; verify ASGI/spooling/logging against locked versions; run relevant existing security/static/error/import checks and lint/format. Advisory checks are separately pending. No full-suite/CI/runtime/UAT success is claimed; this candidate is not self-accepted or integrated.

## Delivery limitation

The resumed task changes only this report. The existing security test file and taxonomy edit from the interrupted run remain in the tree, without product-code changes. No test issue was demonstrated or fixed. No commit, staging, push, integration or release was performed. Git writes remain outside this assignment. Baseline/target recorded by the earlier run: fd51120dd763a13d3ee98e3619d92c6bbca2db5c; assigned branch review/security-audit, physical checkout sec-audit. Final local identity, scope and static validation are recorded below after readback. No remote network state is claimed.

Final continuation readback: HEAD and cached origin/main are both fd51120dd763a13d3ee98e3619d92c6bbca2db5c; branch review/security-audit. Only backend/tests/_test_taxonomy.py (+1 tracked line), backend/tests/security/test_security_review.py and this report are pending. Local read-only Git queries work; Git writes were not attempted. Candidate privacy for all three files, Python compile/strict markers/line length/CI ownership and tracked git diff --check passed. No full lint/formatter result is claimed.

## Dependency audit (run 2026-10-22 outside Codex sandbox, lock files of fd51120d)

pip-audit (uv export --locked, --no-deps): 21 known vulnerabilities in 4 packages. Not fixed in this PR (lock upgrades = separate task).


Name | Version | ID | Fix Versions
--- | --- | --- | ---
[httpcore2](https://pypi.org/project/httpcore2/) | 2.9.1 | [PYSEC-2026-3844](https://osv.dev/vulnerability/PYSEC-2026-3844) | 2.10.0
[httpx2](https://pypi.org/project/httpx2/) | 2.9.1 | [PYSEC-2026-3849](https://osv.dev/vulnerability/PYSEC-2026-3849) | 2.11.0
[httpx2](https://pypi.org/project/httpx2/) | 2.9.1 | [PYSEC-2026-3847](https://osv.dev/vulnerability/PYSEC-2026-3847) | 2.10.0
[httpx2](https://pypi.org/project/httpx2/) | 2.9.1 | [PYSEC-2026-3845](https://osv.dev/vulnerability/PYSEC-2026-3845) | 2.10.0
[httpx2](https://pypi.org/project/httpx2/) | 2.9.1 | [PYSEC-2026-3848](https://osv.dev/vulnerability/PYSEC-2026-3848) | 2.11.0
[httpx2](https://pypi.org/project/httpx2/) | 2.9.1 | [PYSEC-2026-3846](https://osv.dev/vulnerability/PYSEC-2026-3846) | 2.12.0
[pypdf](https://pypi.org/project/pypdf/) | 6.16.1 | [PYSEC-2026-4153](https://osv.dev/vulnerability/PYSEC-2026-4153) | 6.18.0
[pypdf](https://pypi.org/project/pypdf/) | 6.16.1 | [PYSEC-2026-4154](https://osv.dev/vulnerability/PYSEC-2026-4154) | 6.18.1
[pypdf](https://pypi.org/project/pypdf/) | 6.16.1 | [PYSEC-2026-4160](https://osv.dev/vulnerability/PYSEC-2026-4160) | 6.19.0
[pypdf](https://pypi.org/project/pypdf/) | 6.16.1 | [PYSEC-2026-4159](https://osv.dev/vulnerability/PYSEC-2026-4159) | 6.19.0
[pypdf](https://pypi.org/project/pypdf/) | 6.16.1 | [PYSEC-2026-4156](https://osv.dev/vulnerability/PYSEC-2026-4156) | 6.18.1
[pypdf](https://pypi.org/project/pypdf/) | 6.16.1 | [PYSEC-2026-4155](https://osv.dev/vulnerability/PYSEC-2026-4155) | 6.18.1
[pypdf](https://pypi.org/project/pypdf/) | 6.16.1 | [PYSEC-2026-4158](https://osv.dev/vulnerability/PYSEC-2026-4158) | 6.17.0
[pypdf](https://pypi.org/project/pypdf/) | 6.16.1 | [PYSEC-2026-4157](https://osv.dev/vulnerability/PYSEC-2026-4157) | 6.19.0
[pypdf](https://pypi.org/project/pypdf/) | 6.16.1 | [CVE-2026-113792](https://osv.dev/vulnerability/CVE-2026-113792) | 6.20.1
[pypdf](https://pypi.org/project/pypdf/) | 6.16.1 | [CVE-2026-113795](https://osv.dev/vulnerability/CVE-2026-113795) | 6.20.0
[pypdf](https://pypi.org/project/pypdf/) | 6.16.1 | [CVE-2026-113793](https://osv.dev/vulnerability/CVE-2026-113793) | 6.20.1
[pypdf](https://pypi.org/project/pypdf/) | 6.16.1 | [CVE-2026-113794](https://osv.dev/vulnerability/CVE-2026-113794) | 6.20.0
[pypdf](https://pypi.org/project/pypdf/) | 6.16.1 | [CVE-2026-113786](https://osv.dev/vulnerability/CVE-2026-113786) | 6.21.1
[pytest](https://pypi.org/project/pytest/) | 8.4.2 | [PYSEC-2026-1845](https://osv.dev/vulnerability/PYSEC-2026-1845) | 9.0.3
[pytest](https://pypi.org/project/pytest/) | 8.4.2 | [PYSEC-2026-1845](https://osv.dev/vulnerability/PYSEC-2026-1845) | 9.0.3

npm audit --package-lock-only (frontend): 6 vulnerabilities (2 moderate, 4 high): @vitest/mocker <=4.1.11 (moderate), nanoid <3.3.18 (high), source-map-js 1.0.0-1.2.1 (high), undici 8.0.0-8.10.1 (high), vite 8.2.0-8.2.2 (high, dev server), +1 moderate. Fix available via npm audit fix (not applied).

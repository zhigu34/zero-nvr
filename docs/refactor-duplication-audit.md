# zero-nvr backend — refactoring audit: duplication & extraction opportunities

Scope: `backend/app/` (198 modules, 67,561 LOC) + `backend/tests/` (115 files, 43,572 LOC).
All line numbers verified by AST/grep against the working tree. Method: AST duplicate-function
detector across all modules, normalised `difflib` similarity clustering, regex block counters.

Baseline metrics used throughout:

| Metric | Value |
|---|---|
| Backend app LOC | 67,561 |
| API router LOC (`*/api.py`, `live_layouts.py`, `live_preview_wall_api.py`, `zlm_hooks.py`) | 12,430 |
| Endpoints (`@router.get/post/put/patch/delete`) | 174 |
| `Depends(get_db_session)` occurrences | 151 |
| `raise ApiError(` occurrences | 683 |
| `session.commit()` occurrences | 208 |
| Duplicated private-method names across files | 129 names / 68 `__init__`, 40 non-dunder |
| Duplicated test-helper names across files | 52 names |

---

## Ranked findings

Ranking key: **Impact** = LOC removable + bug classes eliminated + files unlocked.
**Effort** = risk and size of the change. Sorted by impact/effort.

---

### 1. Cursor pagination is re-implemented 6× (codec + page dataclass + response schema)

**Impact: very high · Effort: very low · ~294 LOC removable**

`_encode_cursor` and `_decode_cursor` are defined 6 times, once per list-query module:

| # | Encode | Decode | LOC |
|---|---|---|---|
| 1 | `backend/app/modules/recordings/query.py:24` | `:35` | 33 |
| 2 | `backend/app/modules/exports/query.py:23` | `:36` | 44 |
| 3 | `backend/app/modules/alerts/query.py:23` | `:36` | 44 |
| 4 | `backend/app/modules/audit/query.py:29` | `:44` | 46 |
| 5 | `backend/app/modules/events/query.py:23` | `:34` | 38 |
| 6 | `backend/app/modules/backups/query.py:23` | `:36` | 44 |

Signatures (all identical shape):

```python
def _encode_cursor(segment: RecordingSegment) -> str:          # recordings/query.py:24
def _encode_cursor(item: ExportJob) -> str:                    # exports/query.py:23
def _encode_cursor(item: Alert) -> str:                        # alerts/query.py:23
def _encode_cursor(item: AuditEvent) -> str:                   # audit/query.py:29
def _encode_cursor(event: Event) -> str:                       # events/query.py:23
def _encode_cursor(item: BackupSet) -> str:                    # backups/query.py:23

def _decode_cursor(value: str) -> tuple[datetime, uuid.UUID]:  # recordings:35, events:34
def _decode_cursor(value: str) -> tuple[datetime, uuid.UUID]:  # exports:36, alerts:36, audit:44, backups:36
```

**Drift: none in logic.** An AST-normalised diff (masking the timestamp key and error code)
collapses the 6 `_decode_cursor` bodies into 3 variants that differ only in line wrapping
(`exports`/`alerts`/`audit`/`backups` form one cluster at ratio 0.96–1.00; `recordings` and
`events` are the same logic re-wrapped). The only semantic difference per copy is the payload
key name (`started_at`/`created_at`/`occurred_at`) and the error code string
(`recording_cursor_invalid`, `export_cursor_invalid`, `alert_cursor_invalid`,
`audit_cursor_invalid`, `event_cursor_invalid`, `backup_cursor_invalid`). Total codec LOC **249**.

The same duplication continues into the paging envelope and the response model:

```python
# 6 near-identical frozen dataclasses, ~4 LOC each
class RecordingCatalogPage:   items: list[RecordingSegment]; next_cursor: str | None   # recordings/query.py:19
class ExportPageResult:       items: list[ExportJob];        next_cursor: str | None   # exports/query.py:18
class AlertPageResult:        items: list[Alert];            next_cursor: str | None   # alerts/query.py:18
class AuditPageResult:        items: list[AuditEvent];       next_cursor: str | None   # audit/query.py:24
class EventPageResult:        items: list[Event];            next_cursor: str | None   # events/query.py:18
class BackupSetPageResult:    items: list[BackupSet];        next_cursor: str | None   # backups/query.py:18
```

```python
# 7 near-identical Pydantic page models
class RecordingSegmentPage(BaseModel):     # recordings/schemas.py:223
class ExportPage(BaseModel):               # exports/schemas.py:41
class AlertPage(BaseModel):                # alerts/schemas.py:63
class AuditPage(BaseModel):                # audit/schemas.py:30
class EventPage(BaseModel):                # events/schemas.py:29
class EventRecordingSegmentPage(BaseModel):# events/schemas.py:43
class BackupSetPage(BaseModel):            # backups/schemas.py:108
```

Drift in the schemas: `next_cursor: str | None = None` (recordings, alerts, events ×2) vs
`next_cursor: str | None` (exports, audit, backups) — an inconsistent OpenAPI **required** flag.

Also duplicated: the `limit + 1` probe loop and the `or_(ts < cursor, and_(ts == cursor, id < cursor))`
keyset predicate, e.g. `events/query.py:157-184`, `alerts/query.py:150-182`, `backups/query.py:106-137`,
`exports/query.py:114-146`, `audit/query.py:170-203`, `recordings/query.py:136-169`. And the
limit guard is repeated verbatim: `exports/query.py:75-81` (`export_limit_invalid`),
`backups/query.py:79-85` (`backup_limit_invalid`), `events/query.py:97-102` (`Event limit…`),
`alerts/query.py:100-106`. In the routers, `exports/api.py:238`, `audit/api.py:91`,
`backups/api.py:331` duplicate `limit: int = Query(default=…, ge=1, le=200)` with **different
defaults** (50 / 100 / 50) and `recordings/api.py:1060` uses a bare `limit: int = 100` with no
`Query()` constraint at all — so the recordings endpoint is unvalidated.

**Shared home:** `backend/app/core/pagination.py`

```python
@dataclass(frozen=True, slots=True)
class Page[T]:
    items: list[T]
    next_cursor: str | None

class PageModel[T](BaseModel):        # generics; Pydantic v2 supports this
    items: list[T]
    next_cursor: str | None = None

def encode_cursor(timestamp: datetime, entity_id: uuid.UUID) -> str: ...
def decode_cursor(value: str, *, resource: str) -> tuple[datetime, uuid.UUID]: ...
def keyset_predicate(column, id_column, cursor: str | None, *, resource: str): ...
def paginate(session, statement, *, order_columns, cursor, limit, resource) -> Page: ...
def page_limit(default: int = 50, maximum: int = 200) -> int:  # FastAPI Query dependency
```

`decode_cursor(..., resource=...)` keeps the per-module error codes without duplicating the codec.

---

### 2. Test scaffolding is re-written per test file (no shared fixtures/factories at all)

**Impact: very high · Effort: very low (zero production risk) · ~1,870 LOC + 95 fake classes removable**

`backend/tests/conftest.py` is **13 lines** and defines nothing but `ZERO_NVR_SECRET_KEY`.
Every test file re-declares its own app/database/auth/camera setup:

| Helper | Definitions | Files | Total LOC | Cluster analysis (>0.85 similarity) |
|---|---|---|---|---|
| `make_app` | 40 | 40 | 609 | 14 clusters; **19 files share one body**, 5 more share another |
| `make_database` | 32 | 32 | 588 | 12 clusters; **15 files share one body**, 3 another |
| `setup_admin` | 23 | 23 | 390 | 4 clusters; **20 files share one body** |
| `seed_camera` | 8 | 8 | 221 | 5 clusters |
| `login` | 5 | 5 | 49 | 3 clusters, 3 files identical |
| `use_token` | 3 | 3 | 9 | 1 cluster (all 3 identical) |
| **Total** | **111** | — | **1,866** | |

Representative bodies:

```python
# tests/test_camera_api.py:51
def make_app(tmp_path: Path):
    settings = Settings(
        secret_key="camera-api-test-secret-key-32-bytes-minimum",
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'camera-api.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        session_cookie_secure=False,
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.database.engine)
    app.state.recording_tasks = FakeRecordingTasks()
    return app

# tests/test_recording_catalog.py:27
def make_database(tmp_path: Path) -> tuple[Settings, Database]:
    settings = Settings(
        secret_key="recording-catalog-test-secret-key-32-bytes-minimum",
        database_url=f"sqlite:///{tmp_path / 'catalog.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
    )
    database = Database(settings)
    database.initialize_runtime()
    Base.metadata.create_all(database.engine)
    return settings, database

# tests/test_smtp_notification_target.py:37
def setup_admin(client: TestClient) -> None:
    created = client.post("/api/v1/setup/administrator", json={...})
    assert created.status_code == 201
    login = client.post("/api/v1/auth/login", json={...})
    assert login.status_code == 200
```

Drift: `session_cookie_secure=False` is present in only some of the 40 `make_app` copies;
`FakeRecordingTasks` is attached in some and not others; the `secret_key` literal is per-file
placeholder text. There are also **131** inline `Settings(...)` constructions and **88**
`Base.metadata.create_all(...)` calls, and **128** `monkeypatch.setattr` calls.

**Duplicated fake adapter classes** (95 `class Fake*` in `tests/`):

| Fake | Count | Sites |
|---|---|---|
| `FakeOnvifAdapter` | 16 | `test_camera_onvif_test_api.py:94,202,277`; `test_camera_onvif_import_api.py:267,519,565,613,708,965,1137,1211,1514,1749`, … |
| `FakeZlmAdapter` | 9 | `test_camera_onvif_import_api.py:67`; `test_camera_live_api.py:74,250,471,595,715,965,1257`; `test_live_preview_wall_api.py:43` |
| `FakeRecordingTasks` | 7 | `test_camera_api.py:28`; `test_recording_policy_api.py:27`; `test_onvif_events.py:76`; `test_camera_onvif_import_api.py:105`; `test_zlm_hooks.py:33`; `test_storage_api.py:42`; `test_camera_live_api.py:30` |
| `inspect_device` stubs | 16 | 2 files |
| `handler` stubs | 15 | `test_zlm_adapter.py` |
| `close` stubs | 12 | 7 files |

**Shared home:** expand `backend/tests/conftest.py` into fixtures plus
`backend/tests/factories.py`:

```python
@pytest.fixture
def settings(tmp_path) -> Settings: ...          # canonical test Settings
@pytest.fixture
def database(settings) -> Database: ...          # initialize_runtime + create_all
@pytest.fixture
def app(settings, database): ...                 # create_app + fakes + dispatchers
@pytest.fixture
def client(app) -> Iterator[TestClient]: ...
@pytest.fixture
def admin_client(client) -> TestClient: ...      # setup_admin + login
def make_camera(session, **overrides) -> Camera: ...
def auth_cookies(client, username="admin") -> dict[str, str]: ...
# tests/fakes.py: ConfigurableOnvifAdapter, ConfigurableZlmAdapter, FakeRecordingTasks,
#                 FakeExportDispatcher, FakeMqttClient, recording_offline_media_probe(...)
```

Note the prod-side coupling that forces this: `test_adapter_contracts.py` already exists, which
means a single configurable fake satisfying the same behavioural contract is the natural target.

---

### 3. 56 hand-written view/snapshot mappers; only 1 schema uses `from_attributes`

**Impact: very high · Effort: medium · ~1,040 LOC removable**

Across 13 API modules there are **58** functions matching `_*_view` / `_*_snapshot`
(the two endpoint false positives `cameras/api.py:3666 get_camera_snapshot` and
`events/api.py:246 event_snapshot` excluded → **56 mappers, 1,042 LOC**). Largest:

| LOC | Site |
|---|---|
| 61 | `backend/app/modules/recordings/api.py:235 _trigger_view` |
| 45 | `backend/app/modules/cameras/api.py:145 _onvif_inspection_view` |
| 41 | `backend/app/modules/system/api.py:885 _runtime_tuning_view` |
| 41 | `backend/app/modules/system/api.py:960 _runtime_tuning_snapshot` |
| 28 | `backend/app/modules/audit/api.py:41 _view` |
| 26 | `backend/app/modules/recordings/api.py:112 _audit_snapshot` |
| 17 | `backend/app/modules/notifications/api.py:84 _delivery_view` |

All follow the same field-by-field copy shape, e.g. `recordings/api.py:89 _policy_view` and
`alerts/api.py:34 _policy_view` and `backups/api.py:35 _policy_view` are three structurally
identical functions differing only in the target model:

```python
def _policy_view(policy: AlertPolicy) -> AlertPolicyView:          # alerts/api.py:34
    return AlertPolicyView(
        id=policy.id, name=policy.name, enabled=policy.enabled,
        severity=policy.severity, match=policy.match_json or {},
        actions=policy.action_json or {}, cooldown_seconds=policy.cooldown_seconds,
        created_at=policy.created_at, updated_at=policy.updated_at,
    )
```

The ORM→view path is done **manually** everywhere except one place. Grep result:

```
$ grep -rn "from_attributes" backend/app/modules
backend/app/modules/auth/schemas.py:49:    model_config = ConfigDict(from_attributes=True)
```

There is no `BaseSchema` at all; 155 `class X(BaseModel)` declarations each re-declare
`model_config`. View schemas also repeat the audit triple:

| Schema | Site |
|---|---|
| `RecordingProtectionView` | `backend/app/modules/recordings/schemas.py:287` |
| `AlertPolicyView` | `backend/app/modules/alerts/schemas.py:36` |
| `EventView` | `backend/app/modules/events/schemas.py:9` |
| `NotificationDeliveryView` | `backend/app/modules/notifications/schemas.py:75` |

The `_*_snapshot` half (18 functions) is the audit before/after dict builder and duplicates the
inverse mapping. Three are literally named `_audit_snapshot`:
`recordings/api.py:112`, `storage/api.py:90`, `exports/api.py:99`. Two `_policy_snapshot`:
`alerts/api.py:50`, `backups/api.py:82`.

**Shared home:** `backend/app/core/api/views.py`

```python
class ApiSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

def view(schema: type[V], source: Any) -> V:      # collapse the 1:1 field copies
    return schema.model_validate(source, from_attributes=True)

class AuditedSchema(ApiSchema):                    # shared before/after snapshot protocol
    @classmethod
    def audit_snapshot(cls, source: Any) -> dict[str, Any]: ...
```

Then delete the 1:1 mappers; keep only the ~12 mappers with real derivation
(`_camera_summary` 103 LOC, `_trigger_view` 61, `_onvif_inspection_view` 45,
`_runtime_tuning_view`/`_snapshot` 41+41, `_frigate_view`/`_snapshot` 26+25, `_camera_group_view` 14).
The three `_policy_view` / three `_audit_snapshot` / two `_policy_snapshot` collapse directly.

---

### 4. Router boilerplate: 72 try/except/rollback blocks, 65 audit-emit+commit blocks, 151 session deps

**Impact: high · Effort: medium · ~400 LOC removable + eliminates a forgotten-rollback bug class**

Exact block counts (regex over `backend/app/`):

| Pattern | Count | Files | Distribution |
|---|---|---|---|
| `try: … except …:  session.rollback()  raise` | **73** | 12 | `cameras/api.py` 14, `auth/admin_api.py` 12, `storage/api.py` 7, `recordings/api.py` 6, `auth/api.py` 6, `exports/api.py` 6, `system/api.py` 6, `alerts/api.py` 5, `backups/api.py` 5, `notifications/api.py` 4, `zlm_hooks.py` 1, `worker/tasks.py` 1 |
| `except …: session.rollback()` (any) | **83** | 14 | + `auth/oidc_api.py` 4, `cameras/live_layouts.py` 2 |
| `append_audit_event(...) ; session.commit()` | **65** | 12 | `auth/admin_api.py` 12, `cameras/api.py` 11, `system/api.py` 7, `storage/api.py` 6, `recordings/api.py` 5, `auth/api.py` 5, `alerts/api.py` 5, `backups/api.py` 4, `oidc_api.py` 3, `exports/api.py` 3, `notifications/api.py` 3, `cli.py` 1 |
| `Depends(get_db_session)` | **151** | 15 routers | `cameras/api.py` 30, `admin_api.py` 19, `recordings/api.py` 18, `storage/api.py` 12, `system/api.py` 10 |
| `get_effective_camera_scope(context, session)` | **26** call sites | 10 routers | `recordings/api.py:189,388,732,790,972,1348`; `cameras/api.py:605`; `live_layouts.py:175,229`; `exports/api.py:118,166,244`; `alerts/api.py:93,276`; `audit/api.py:97`; `events/api.py:95,142,177,256`; `notifications/api.py:597` |

Canonical repeated block (`alerts/api.py:144-156`, identical at `:205-217`, `:245-257`, and 62
other sites):

```python
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="alert_policy.create",
            resource_type="alert_policy",
            resource_id=policy.id,
            after=_policy_snapshot(policy),
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
```

The scope-gate preamble is also copied 26×, e.g. `exports/api.py:111 _scoped_export`,
`recordings/api.py:183 _require_segment_scope`:

```python
def _scoped_export(session, *, context, export_id) -> ExportJob:   # exports/api.py:111
    job = ExportService.get(session, export_id)
    scope = get_effective_camera_scope(context, session)
    if not scope.allows(job.camera_id):
        raise ApiError(status_code=404, code="export_not_found", message="Export was not found.")
    return job
```

**Inconsistency worth flagging:** both session lifecycles swallow the rollback contract —
`backend/app/core/db/dependencies.py:7` and `backend/app/core/db/database.py:207` only call
`session.close()`, while the service layer relies on `with database.session()` (59 sites) and the
routers add explicit `session.rollback()`. `get_db_session` never rolls back, so any endpoint that
forgets the wrapper leaves the transaction to `close()`-time cleanup. Making the dependency
symmetric removes 73 blocks:

```python
# backend/app/core/db/dependencies.py
def get_db_session(request: Request) -> Generator[Session, None, None]:
    session = request.app.state.database.session_factory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
```

**Shared home:** `backend/app/core/api/router.py` + `backend/app/modules/audit/emitter.py`

```python
# audit emit as a dependency-injected service, not 6 positional kwargs at 65 call sites
class AuditEmitter:                       # Depends(get_audit_emitter)
    def record(self, *, action: str, resource_type: str,
               resource_id=None, camera_id=None,
               before=None, after=None, result="success") -> None: ...

# declarative mutation endpoint
def audited(router, *, action: str, resource_type: str, resource_param: str = "id"):
    """Wrap a mutating endpoint so audit + commit + rollback are not re-typed."""
```

```python
# scoped fetch as one dependency factory instead of 26 copies
RequireScoped = Annotated[AuthContext, Depends(require_camera_scope())]
def scoped_or_404(session, model, resource_id, *, scope, not_found_code, not_found_message):
    ...
```

---

### 5. `get-or-404` service method duplicated 31× verbatim

**Impact: high · Effort: very low · ~370 LOC removable**

Exact shape — `X = session.get(Model, id)` / `if X is None:` / `raise ApiError(status_code=404, …)`:
**31 occurrences across 25 files.** Seven side-by-side (all 12 LOC, structurally identical):

```python
# backend/app/modules/alerts/service.py:75
def get(session: Session, policy_id: uuid.UUID) -> AlertPolicy:
    policy = session.get(AlertPolicy, policy_id)
    if policy is None:
        raise ApiError(status_code=404, code="alert_policy_not_found",
                       message="Alert policy was not found.")
    return policy
```

| File:line | Model | Error code |
|---|---|---|
| `alerts/service.py:75` | `AlertPolicy` | `alert_policy_not_found` |
| `cameras/groups.py:32` | `CameraGroup` | `camera_group_not_found` |
| `storage/retention_admin.py:26` | `RetentionPolicy` | `retention_policy_not_found` |
| `storage/service.py:247` | `StorageTarget` | `storage_target_not_found` |
| `backups/service.py:192` | `BackupPolicy` | `backup_policy_not_found` |
| `notifications/service.py:587` | `NotificationTarget` | `notification_target_not_found` |
| `exports/service.py:74` | `ExportJob` | `export_not_found` |
| `alerts/query.py:73`, `events/query.py:67`, `recordings/query.py:60` | `Alert`/`Event`/`RecordingSegment` | `alert_not_found` / `event_not_found` / `recording_not_found` |
| `cameras/service.py:48`, `recordings/policy.py:310`, `recordings/protection.py:81` | `Camera` | `camera_not_found` |

The 404 total is **54** `was not found.` sites; `raise ApiError(` appears **683** times total
(`cameras/api.py` 59, `storage/service.py` 55, `notifications/service.py` 45, `alerts/service.py` 31,
`backups/service.py` 30, `auth/oidc.py` 24, `recordings/policy.py` 20, …).

**Shared home:** `backend/app/core/db/repository.py`

```python
T = TypeVar("T", bound=Base)

def fetch_or_404(session: Session, model: type[T], entity_id: uuid.UUID, *,
                 code: str, message: str) -> T: ...

def find_or_none(session: Session, model: type[T], entity_id) -> T | None: ...
```

Usage collapses to
`return fetch_or_404(session, AlertPolicy, policy_id, code="alert_policy_not_found", message="Alert policy was not found.")`.
Add a `NotFounds` registry so message/code pairs are declared once per model and reused by the
query services and the API routers (which currently also build 404s for the same models, e.g.
`events/api.py` 4 sites, `recordings/api.py` 5 sites).

---

### 6. Five "job engine" services share a `prepare` / `_mark_failed` / `_mark_*` / `execute` skeleton

**Impact: high · Effort: medium-high · ~500 LOC of skeleton removable from 1,595**

| Service | Site | LOC | Methods |
|---|---|---|---|
| `ArchiveLifecycleService` | `backend/app/modules/storage/archive.py:50-426` | 377 | `__init__`, `_safe_local_path`, `prepare`, `_mark_source_missing`, `_mark_failed`, `_mark_available`, `execute` |
| `ExportExecutionService` | `backend/app/modules/exports/execution.py:39-267` | 229 | `__init__`, `prepare`, `_mark_failed`, `_complete`, `execute` |
| `BackupExecutionService` | `backend/app/modules/backups/execution.py:131-574` | 444 | `__init__`, `_safe_work_dir`, `_safe_deployment_config`, `prepare`, `_manifest`, `_mark_failed`, `_complete`, `execute`, `verify` |
| `NotificationDeliveryService` | `backend/app/modules/notifications/delivery.py:56-381` | 326 | `__init__`, `prepare`, `_mark_failed`, `_mark_sent`, `execute` |
| `LocalRetentionDeletionService` | `backend/app/modules/storage/retention.py:896-1114` | 219 | `_safe_path`, `_mark_failed`, `execute` |

`_mark_failed` is defined **5×** (82 LOC) and is the clearest duplication — an outcome-state
mutation wrapper:

```python
# backend/app/modules/storage/retention.py:924
    @staticmethod
    def _mark_failed(database: Database, *, location_id: uuid.UUID, error_code: str) -> None:
        with database.session() as session:
            location = session.get(RecordingLocation, location_id)
            if location is not None:
                location.state = "FAILED"
                location.last_attempt_at = utc_now()
                location.last_error = error_code
                session.commit()
```

| Site | LOC | `state` target field | Extra behaviour |
|---|---|---|---|
| `storage/retention.py:924` | 16 | `last_error` | — |
| `storage/archive.py:254` | 16 | `last_error` | — |
| `notifications/delivery.py:206` | 16 | `last_error_code` | — |
| `exports/execution.py:146` | 17 | `error_code` | **early-return guard** on `{"CANCELLED","EXPIRED"}` |
| `backups/execution.py:293` | 17 | `error_code` + `sanitized_error` | **also flips `verification_state` PENDING→SKIPPED** |

**Drift:** three inconsistent error-field names (`last_error` / `last_error_code` / `error_code`),
and the terminal-state guard exists in only one of the five. `_complete` / `_mark_available` /
`_mark_sent` are the positive-path twins: `exports/execution.py:165` (59 LOC) and
`backups/execution.py:312` (32 LOC) are named identically. The `prepare` methods are 95/71/136/144
LOC and all do: resolve config → validate paths → write a `*Plan` dataclass → return it.

The paired `*Plan`/`*Result` dataclasses are also per-module:
`plan`: `storage/archive.py:30`, `exports/execution.py:23`, `backups/execution.py:37`,
`recordings/playback_cache.py:32`, `recordings/playback.py:22`; `result`:
`storage/archive.py:44`, `exports/execution.py:33`, `recordings/playback_cache.py:41`,
`recordings/reconciliation.py:52`, `recordings/runtime.py:47`.

**Shared home:** `backend/app/core/jobs/runner.py`

```python
class JobState(StrEnum):
    PENDING = "PENDING"; RUNNING = "RUNNING"; FAILED = "FAILED"
    COMPLETED = "COMPLETED"; CANCELLED = "CANCELLED"; EXPIRED = "EXPIRED"

@dataclass(frozen=True, slots=True)
class JobOutcomeSpec[P, R]:
    """Declares the per-model field mapping so the runner stops being copy-pasted."""
    model: type[Base]
    state_field: str = "state"
    error_code_field: str = "error_code"
    error_message_field: str | None = None
    terminal_set: frozenset[str] = frozenset()
    now_field: str | None = None
    on_failed: Callable[[Session, Any], None] | None = None   # backups' verification_state hook

class JobRunner(Generic[P, R]):
    def __init__(self, database: Database, spec: JobOutcomeSpec): ...
    def prepare(self, job_id: uuid.UUID) -> P: ...
    def mark_failed(self, job_id, code, message=None) -> None: ...
    def mark_completed(self, job_id, **fields) -> None: ...
    def execute(self, job_id: uuid.UUID) -> R: ...   # prepare → run → mark_* with rollback
```

Subclasses supply only `plan(job) -> P` and `run(plan) -> R`. `backups` keeps its
`verification_state` behaviour via the `on_failed` hook; `exports` keeps its terminal guard via
`terminal_set`.

---

### 7. `system/config_import.py`: 3,097 of 3,452 LOC (89.7%) inside two methods, 12 sections linearly unrolled

**Impact: very high (single largest file) · Effort: high · ~3,000 LOC reorganised**

```
backend/app/modules/system/config_import.py                     3,452 LOC
  class ConfigurationImportService  L120-3452                   (3,333)
      _error L122  _reject_secret_fields L137  _mapping L172
      _items L187  _id_set L213  _require_ref L243  _requirement L272
      validate  L301-1237                                       (937 LOC)
      _apply_item L1247  _existing_by_name L1281
      apply     L1293-3452                                     (2,160 LOC)
```

`_KNOWN_SECTIONS` (`:63`) declares exactly 12 sections; `validate` and `apply` each walk them
in the same order with no handler abstraction:

**`validate` seams** — `general` `:349`, `time` `:353`, `roles` `:363`, `devices` `:367`,
`cameras` `:396`, `recording` `:440`, `storage_targets` `:462`, `alert_policies` `:471`,
`notification_targets` `:480`, `oidc_providers` `:489`, `frigate` `:498`, `backup_policies` `:510`.

**`apply` seams** — `general` `:1327`, `time` `:1374`, `roles` `:1398`, `devices` `:1521`,
`cameras` `:1755`, `storage_targets` `:2396`, `recording`(retention+scopes) `:2529`,
`notification_targets` `:2874`, `oidc_providers` `:2992`, `backup_policies` `:3116`,
`alert_policies` `:3229`, `frigate` `:3404`.

Supporting metrics: **42** bare `assert` statements (used for input narrowing on
untrusted import payloads), and the helper call-sites are spread thin —
`_error` 26, `_apply_item` 41, `_require_ref` 21, `_items` 16, `_requirement` 9, `_id_set` 9,
`_source_uuid` 9, `_mapping` 7, `_existing_by_name` 7.

The mirror-image file is `backend/app/modules/system/config_export.py` (727 LOC) with 12 matching
per-section private methods — `_general:50`, `_time_settings:76`, `_roles:95`, `_devices:144`,
`_cameras:212`, `_recording:348`, `_storage:435`, `_alerts:460`, `_notifications:484`,
`_oidc:514`, `_frigate:549`, `_backups:608` — assembled in `build:653-727`. So the same 12 sections
are re-dispatched by hand in **three** places.

**Proposed seams:**

```
backend/app/modules/system/config_import/
    __init__.py                # ConfigurationImportService facade (validate/apply orchestration)
    _base.py                   # _error, _mapping, _items, _id_set, _require_ref, _requirement
    _registry.py               # SECTION_HANDLERS: dict[str, SectionHandler], ordered
    _context.py                # ApplyContext: session, settings, *_map dicts, applied/skipped/reconcile
    sections/general.py        # ~47 LOC   (apply 1327-1373 + validate 349-352)
    sections/time.py           # ~24
    sections/roles.py          # ~123
    sections/devices.py        # ~234
    sections/cameras.py        # ~640
    sections/storage_targets.py# ~133
    sections/recording.py      # ~345  (retention policies + camera scopes)
    sections/notifications.py  # ~118
    sections/oidc.py           # ~124
    sections/backups.py        # ~113
    sections/alerts.py         # ~175
    sections/frigate.py        # ~49
```

```python
class SectionHandler(Protocol):
    name: str
    def validate(self, cls, payload: Any, ctx: ValidateContext) -> None: ...
    def apply(self, session: Session, payload: Any, ctx: ApplyContext) -> None: ...
```

`ConfigurationExportService` should consume the same registry (inverted: `def export(self, ctx) -> Any`),
collapsing `_KNOWN_SECTIONS` + `build` + `validate` + `apply` into one ordered table. `assert`
statements become explicit `_mapping`/`_items` narrowing so malformed payloads return 400 rather
than raising `AssertionError` (currently a 500 via the `install_error_handlers` catch-all at
`backend/app/core/errors/api_error.py:47`).

---

### 8. Three settings services re-implement the same `normalize` / `get` / `update` namespace store

**Impact: medium-high · Effort: low · ~120 LOC removable**

`backend/app/modules/system/settings.py` (741 LOC) holds three classes with an identical
read/upsert/read-back contract over the `SystemSetting` table keyed by `cls.namespace`:

| Class | Range | `normalize` | `get` | `update` |
|---|---|---|---|---|
| `SystemSettingsService` | `:31-197` | `:59-129` (71) | `:132-162` (31) | `:165-197` (33) |
| `TimeSystemSettingsService` | `:207-411` | `:288-339` (52) | `:342-376` (35) | `:379-411` (33) |
| `RuntimeTuningSettingsService` | `:430-740` | `:536-667` (132) | `:670-715` (46) | `:718-740` (23) |

The `update` bodies are near-identical (`SystemSettingsService:165` vs `RuntimeTuningSettingsService:718`):

```python
    @classmethod
    def update(cls, session, *, settings, changes) -> RuntimeTuningSettings:
        row = session.get(SystemSetting, cls.namespace)
        normalized = cls.normalize(settings=settings,
                                   current=row.value_json if row is not None else None,
                                   changes=changes)
        if row is None:
            row = SystemSetting(namespace=cls.namespace, value_json=normalized)
            session.add(row)
        else:
            row.value_json = normalized
        session.flush()
        return cls.get(session, settings=settings)
```

**Drift:** `TimeSystemSettingsService.get`/`update` (`:342`, `:379`) drop the `settings` kwarg and
add a `legacy=cls._legacy(session) if row is None else None` fallback, so the three `normalize`
signatures are not substitutable. `SystemSettingsService.normalize` takes `settings=`, `Time`
does not, `Runtime` does.

**Shared home:** `backend/app/core/settings/namespace.py`

```python
class NamespaceSettingsStore(ABC, Generic[T]):
    namespace: ClassVar[str]
    schema: ClassVar[type[T]]

    @classmethod
    def defaults(cls, settings: Settings) -> T: ...
    @classmethod
    def normalize(cls, *, current: dict | None, changes: dict, settings: Settings,
                  legacy: Callable[[Session], dict | None] | None = None) -> dict: ...
    @classmethod
    def get(cls, session: Session, *, settings: Settings) -> T:
        return cls.schema.model_validate(cls._load(session, settings=settings))
    @classmethod
    def update(cls, session: Session, *, settings: Settings, changes: dict) -> T:
        ...   # single upsert implementation
```

Then `SystemSettingsService`/`TimeSystemSettingsService`/`RuntimeTuningSettingsService` shrink to
their `namespace`, `schema`, `defaults` and field validators only. Related: the
`_bounded_int`(`:434`) / `_bounded_float`(`:459`) pair is a mini validation DSL that belongs next
to this base.

**Companion duplication — the lazy settings read-through** is copied 3× with a 4th near-miss:

```python
# backend/app/modules/cameras/live_transcode.py:104   (identical at recordings/playback_cache.py:64,
#                                                      near-identical at recordings/dispatcher.py:25)
    def _tuning(self) -> RuntimeTuningSettings:
        if self.database is None:
            return RuntimeTuningSettingsService.defaults(self.settings)
        with self.database.session() as session:
            return RuntimeTuningSettingsService.get(session, settings=self.settings)
```

`RuntimeTuningSettingsService.get` is called from 12 sites
(`cli.py:1111`, `recordings/runtime.py:169`, `recordings/api.py:242,1152`, `cameras/api.py:2839,3121`,
`system/api.py:1021,1063,1125,1315`, plus the three above). Extract
`SettingsReader(settings, database).runtime_tuning()` into `app/core/settings/reader.py` with
optional request-scoped caching.

---

### 9. Integration adapters have no common base: 9 identical error classes, 8 duplicated httpx mappings, 2 `_run` wrappers

**Impact: medium-high · Effort: medium · ~250 LOC removable + one uniform error contract**

Nine `<Name>IntegrationError(RuntimeError)` classes with the same `code`/`message`/`status_code`
payload (**122 LOC**):

| Class | Site | LOC | default `status_code` | extra |
|---|---|---|---|---|
| `ZlmIntegrationError` | `backend/app/integrations/zlm/adapter.py:14` | 17 | 502 | — |
| `RcloneIntegrationError` | `backend/app/integrations/rclone/adapter.py:12` | 11 | 502 | — |
| `AppriseIntegrationError` | `backend/app/integrations/apprise/adapter.py:12` | 27 | ? | — |
| `FrigateIntegrationError` | `backend/app/integrations/frigate/adapter.py:9` | 13 | 502 | — |
| `SmtpIntegrationError` | `backend/app/integrations/smtp.py:10` | 23 | 502 | **`category: str = "transient"`** |
| `OnvifIntegrationError` | `backend/app/integrations/onvif/adapter.py:18` | 13 | **422** | — |
| `ResticIntegrationError` | `backend/app/integrations/restic/adapter.py:15` | 8 | **none** | — |
| `FfmpegExportError` | `backend/app/integrations/ffmpeg/adapter.py:10` | 4 | **none** | — |
| `ArchiveLifecycleError` | `backend/app/modules/storage/archive.py:21` | 6 | **none** | lives outside `integrations/` |

**Drift:** default status varies (502 vs 422 vs absent); `Restic`/`Ffmpeg`/`Archive` omit
`status_code` entirely so the API layer cannot map them uniformly; `Smtp` alone carries
`category`. None of them carry a `retryable` flag even though the worker declares retries per task
(see finding 14).

Duplicated transport error mapping — the same 2-exception `httpx` translation appears **4× in ZLM
alone**, plus once in Frigate:

```
backend/app/integrations/zlm/adapter.py:143,149      (TimeoutException → "zlm_timeout", HTTPError → …)
backend/app/integrations/zlm/adapter.py:244,250
backend/app/integrations/zlm/adapter.py:337,343
backend/app/integrations/zlm/adapter.py:396,402
backend/app/integrations/frigate/adapter.py:105,111,124   (+HTTPStatusError)
```

Duplicated subprocess wrapper — `RcloneAdapter._run` (`backend/app/integrations/rclone/adapter.py:111`)
and `ResticAdapter._run` (`backend/app/integrations/restic/adapter.py:66`) both do
`subprocess.run([binary, *args], check=True, capture_output=True, text=True, timeout=…)` and map
`TimeoutExpired` → timeout code and `CalledProcessError` → operation-failed code. The rclone
version additionally manages a `0o600` temp config; restic adds `env=self._env`. 43 `subprocess.*`
calls exist across 9 files (`live_preview.py` 7, `rclone/adapter.py` 7, `live_transcode.py` 6,
`ffmpeg/adapter.py` 6, `restic/adapter.py` 4, `cli.py` 4, `reconciliation.py` 3,
`database_snapshot.py` 3, `worker/tasks.py` 1).

`backend/app/integrations/contracts.py` already declares `DeviceAdapter` (`:8`),
`MediaPlane` (`:44`... i.e. `:44`–`:300`) and `IntegrationAdapter` (`:304`, with
`capabilities`/`enable`/`disable`/`status`) — but no adapter implements `IntegrationAdapter`,
and the HTTP adapters share no lifecycle base. `ZlmAdapter.__init__:70`, `FrigateHttpAdapter.__init__:30`,
`RcloneAdapter.__init__:39`, `ResticAdapter.__init__:32`, `OnvifAdapter.__init__:214`
each independently construct an `httpx.Client`/build env/own `close()` +
`__enter__`/`__exit__` (`zlm/adapter.py:96-104`, `frigate/adapter.py:74-82`,
`zlm/recording.py:29-37`).

**Shared home:** `backend/app/integrations/base.py`

```python
class IntegrationError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 502,
                 retryable: bool = False, category: str = "transient") -> None: ...

class HttpAdapter(ABC):                       # implements IntegrationAdapter
    def __init__(self, settings: Settings, *, base_url: str, timeout: float,
                 transport: httpx.BaseTransport | None = None) -> None: ...
    def close(self) -> None: ...              # + __enter__/__exit__ once
    def request(self, method, path, *, error_code: str, **kwargs) -> httpx.Response:
        """Single place that maps TimeoutException/HTTPStatusError/HTTPError to IntegrationError."""

def run_subprocess(binary: str, args: Sequence[str], *, timeout: float,
                   env: Mapping[str, str] | None = None,
                   error_code: str, timeout_code: str,
                   sanitizer: Callable[[str], str] | None = None) -> CompletedProcess[str]: ...
```

`ZlmAdapter`, `FrigateHttpAdapter`, `OnvifAdapter` extend `HttpAdapter`;
`RcloneAdapter`/`ResticAdapter`/`FfmpegExportAdapter` call `run_subprocess`;
all nine error classes become `IntegrationError` subclasses that only set default attributes
(or disappear — callers can catch `IntegrationError` and read `.code`).

---

### 10. Atomic file write is re-implemented 8× with real durability drift

**Impact: medium-high · Effort: low · ~120 LOC removable + fixes a concurrency race**

| # | Site | Technique | `fsync` | `chmod` | temp naming | cleanup |
|---|---|---|---|---|---|---|
| 1 | `backend/app/integrations/rclone/adapter.py:119-131` | `NamedTemporaryFile` + write | ✅ | `0o600` | `zero-nvr-rclone-*.conf` | `finally` |
| 2 | `backend/app/modules/recordings/prebuffer.py:331-337` | `shutil.copy2` + `open("rb+")` fsync | ✅ | ❌ | `*.partial` | ❌ |
| 3 | `backend/app/modules/system/frigate_managed.py:302-313` | `os.fdopen(fd)` + write | ✅ | ✅ `mode` | predefined fd | `unlink` on error |
| 4 | `backend/app/modules/system/health.py:883-893` | `write_text` + replace | ❌ | ❌ | **`path.with_suffix(".tmp")` — fixed name** | ❌ |
| 5 | `backend/app/modules/system/camera_acceptance.py:82-97` | `NamedTemporaryFile` + `json.dump` | ❌ | `0o640` | `.real-camera.*` | ❌ |
| 6 | `backend/app/modules/backups/recovery_kit.py:434-445` | `write_text` + replace | ❌ | `0o600` | `.{name}.{uuid}.tmp` | `finally: unlink` |
| 7 | `backend/app/backups/recovery_kit.py:755-763` (2nd site) | `write_text`-style + replace | ❌ | ❌ | temp | ❌ |
| 8 | `backend/app/cli.py:2055-2075` and `backend/app/cli.py:2300-2317` | `shutil.copy2` + `open("rb+")` fsync + sidecar move + replace | ✅ | ❌ | `.rollback.partial` / `.restore.partial` | ✅ |

Also `backend/app/modules/storage/service.py:1172-1181` and `:1231-1239` use the same
`NamedTemporaryFile` + `fsync` probe idiom for writability checks.

**Drift:**
- **Durability:** 4 of 8 omit `os.fsync` (health, camera_acceptance, recovery_kit ×2) — a crash
  after `os.replace` can leave a truncated JSON state file.
- **Concurrency bug:** `health.py:887` uses a deterministic `with_suffix(".tmp")` name, so two
  concurrent `write_worker_heartbeat` calls (`health.py:873`) race on the same temp path and can
  `os.replace` a partially written file.
- `prebuffer.py:333` writes then reopens `"rb+"` purely to fsync (never uses the copied data) —
  a 3-line idiom to work around not having a shared helper.
- Permissions are inconsistent: `0o600`, `0o640`, `mode`, or nothing.
- `cli.py:2055-2075` and `cli.py:2300-2317` are two near-identical copies of the
  "copy snapshot → verify → fsync → move `-wal`/`-shm` sidecars → replace" sequence.

**Shared home:** `backend/app/core/fs.py`

```python
def atomic_write_bytes(path: Path, data: bytes, *, mode: int = 0o640,
                       fsync: bool = True) -> None: ...
def atomic_write_text(path: Path, text: str, *, mode: int = 0o640,
                      fsync: bool = True, encoding: str = "utf-8") -> None: ...
def atomic_write_json(path: Path, payload: Any, *, mode: int = 0o640,
                      sort_keys: bool = True, indent: int | None = None) -> None: ...
def atomic_replace_from(source: Path, target: Path, *, mode: int | None = None,
                        verify: Callable[[Path], None] | None = None) -> None: ...
def fsync_path(path: Path) -> None: ...
```

Every implementation becomes a one-line call; the temp name is always
`f".{path.name}.{uuid4().hex}.tmp"` created with `O_EXCL` semantics, and `mode` is explicit.

---

### 11. Path containment / sanitisation helpers: 7 named copies plus 3 inline, with `raise`-vs-`None` drift

**Impact: medium · Effort: low · ~150 LOC removable + removes a path-traversal review surface**

| Helper | Site | On violation | `expanduser` | `strict=False` |
|---|---|---|---|---|
| `_safe_local_path` | `backend/app/modules/storage/archive.py:67-89` | raise `ArchiveLifecycleError` | ✅ | ✅ |
| `_safe_path` | `backend/app/modules/storage/retention.py:900-921` | raise `RetentionDeleteError` | ✅ | ✅ |
| `_safe_file` | `backend/app/modules/recordings/reconciliation.py:242-258` | **return `None`** | ❌ | ✅ |
| `_safe_output_path` | `backend/app/modules/exports/api.py:131-147` | **return `None`** | ❌ | ✅ |
| `_safe_work_dir` | `backend/app/modules/backups/execution.py:138-148` | raise | ✅ | ? |
| `_safe_deployment_config` | `backend/app/modules/backups/execution.py:150-176` | raise | ✅ | ? |
| `_validated_media_path` | `backend/app/media_proxy.py:40-50` | raise `HTTPException(404)` | ❌ (uses `quote`) | ❌ |
| inline | `backend/app/modules/recordings/playback.py:65-79` | return `None` | ✅ | ✅ |
| inline | `backend/app/modules/recordings/prebuffer.py:269-288` | raise `ApiError(409)` | ❌ | ❌ |
| inline | `backend/app/internal/zlm_hooks.py:408-413` | raise | ❌ | ✅ |
| inline | `backend/app/worker/tasks.py:168-176`, `:291-333` | raise | ❌ | mixed |

Canonical body (`archive.py:67` vs `reconciliation.py:242`):

```python
    def _safe_local_path(*, target: StorageTarget, object_path: str) -> Path:      # archive.py:67
        ...
        root = Path(raw_root).expanduser().resolve(strict=False)
        candidate = (root / object_path).resolve(strict=False)
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ArchiveLifecycleError("archive_source_path_invalid", …) from exc
        return candidate

    def _safe_file(root: Path, object_path: str) -> Path | None:                  # reconciliation.py:242
        try:
            candidate = (root / Path(object_path)).resolve(strict=False)
            candidate.relative_to(root)
        except (OSError, ValueError):
            return None
        return candidate
```

**Drift:** `reconciliation._safe_file` additionally catches `OSError` (symlink loops, ELOOP) while
the others do not; two variants return `None` and six raise, so error codes/messages differ per
caller; `media_proxy._validated_media_path` is the only one that also validates the *first path
segment* against an allow-list of ZLM apps (a separate concern worth keeping).

**Shared home:** `backend/app/core/fs.py` (same module as finding 10)

```python
class PathEscapeError(ValueError):
    def __init__(self, *, root: Path, candidate: Path) -> None: ...

def contained_path(root: Path | str, object_path: str, *,
                   expand_user: bool = True) -> Path:
    """Resolve object_path under root, raising PathEscapeError on escape/symlink-loop."""

def contained_path_or_none(root: Path | str, object_path: str) -> Path | None: ...
```

Callers that want an `ApiError`/`IntegrationError` catch `PathEscapeError` once in the API layer
(see `install_error_handlers` at `backend/app/core/errors/api_error.py:34`) instead of each
re-declaring a raise.

---

### 12. Datetime/timezone normalisation: `_utc` ×3, `_normalized_utc` ×2, `_instant` ×2, 16 awareness checks

**Impact: medium-high (latent 500s) · Effort: very low · ~90 LOC removable**

| Helper | Site | LOC | Accepts `None`? | Error |
|---|---|---|---|---|
| `_utc` | `backend/app/modules/recordings/protection.py:20` | 12 | ❌ | `ApiError 422 timezone_required` |
| `_utc` | `backend/app/modules/exports/api.py:47` | 8 | ❌ | `ApiError 422 timezone_required` |
| `_utc` | `backend/app/modules/audit/api.py:25` | 14 | ✅ | `ApiError 422 timezone_required` |
| `_normalized_utc` | `backend/app/modules/recordings/api.py:79` | 8 | ❌ | `ApiError 422 timezone_required` |
| `_normalized_utc` | `backend/app/modules/events/api.py:36` | 14 | ✅ | `ApiError 422 timezone_required` |
| `_instant` | `backend/app/modules/events/service.py:44` | 8 | ❌ | `ApiError 422 **event_timezone_required**` |
| `_instant` | `backend/app/modules/events/system.py:37` | 4 | ❌ | **`ValueError("system event timestamps must be timezone-aware")`** |
| `_parse_aware_datetime` | `backend/app/cli.py:1325` | 23 | ❌ | `RuntimeError` (CLI) |

**Drift that matters:** the parameter name alternates (`field` vs `field_name`); two of five `_utc`
variants tolerate `None` and three do not, so a caller that forwards an optional query parameter to
the wrong copy raises `AttributeError` → HTTP **500** rather than the intended 422;
`events/system.py:37 _instant` raises `ValueError` while its `events/service.py:44` twin raises
`ApiError`, so a timestamp problem surfacing through the system-event path also becomes a 500.

Supporting counters: **16** `utcoffset() is None` awareness checks
(`recordings/api.py:80`, `recordings/protection.py:25`, `exports/api.py:48`, `audit/api.py:32`,
`events/api.py:43`, `events/service.py:45`, `events/system.py:38`, `alerts/service.py:762`,
`onvif/normalizer.py:87,99`, `recordings/query.py:46`, `exports/query.py:51`, `alerts/query.py:51`,
`audit/query.py:59`, `events/query.py:45`, `backups/query.py:51`); and **53** raw
`datetime.now(UTC)` calls despite `backend/app/core/db/types.py:49 utc_now()` existing
(worst: `system/api.py` 8, `worker/tasks.py` 5, `recordings/triggers.py` 4, `exports/shares.py` 4,
`exports/execution.py` 4, `recordings/api.py` 3, `cli.py` 3).

**Shared home:** `backend/app/core/time.py`

```python
def require_utc(value: datetime, *, field: str, code: str = "timezone_required") -> datetime:
    """Non-optional: raise ApiError(422) when naive."""

def optional_utc(value: datetime | None, *, field: str) -> datetime | None: ...

def coerce_utc(value: datetime, *, default_tz: tzinfo = UTC) -> datetime:
    """Lenient ingress for third-party payloads (ONVIF/Frigate): assume UTC when naive."""

def parse_aware(value: str, *, field: str, error: type[Exception] = ValueError) -> datetime: ...
```

Also move `utc_now` out of `app/core/db/types.py` into `app/core/time.py` so non-DB modules stop
importing a DB types module for a clock (currently 14 modules import it).

---

### 13. Small coercion helpers: `_text` ×5 (3 behaviours), `_read` ×3 byte-identical, `_client_info` ×2, `_string_list` ×2

**Impact: medium · Effort: very low · ~200 LOC removable**

`_read` — **byte-identical in all 3 ONVIF modules** (18 LOC):

```python
# backend/app/integrations/onvif/adapter.py:98  ==  onvif/normalizer.py:23  ==  onvif/events.py:14
def _read(value: Any, name: str) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)
```

`_text` — one name, **three different contracts** (93 LOC):

| Site | Loc | Contract |
|---|---|---|
| `integrations/onvif/adapter.py:115` | 5 | `str(value).strip()` for *anything* |
| `integrations/onvif/normalizer.py:31` | 17 | str→strip; int/float/bool→`str()`; else unwrap nested `_value_1`/`value` |
| `integrations/frigate/normalizer.py:51` | 31 | **validating**: `required`, `max_length=512`, raises `ApiError(422)` |
| `modules/events/service.py:54` | 31 | **validating**: `required`, `max_length=None`, raises `ApiError(422)` |
| `modules/auth/oidc_identity.py:22` | 9 | dict claim getter: non-`str` → `None` |

`_string_list` — same name, divergent strictness (46 LOC):

```python
# backend/app/modules/alerts/service.py:133 — raises on non-list / non-str / over-limit, dedups
# backend/app/integrations/frigate/normalizer.py:104 — silently skips non-str, truncates to 64
```

`_client_info` — identical 9-LOC body (user-agent ≤512, source IP ≤64) at
`backend/app/modules/auth/api.py:71` and `backend/app/modules/auth/oidc_api.py:38`. Note the same
extraction is *also* open-coded in `backend/app/modules/audit/service.py:22-40`, so there are
three copies of the request-fingerprint logic.

`_now` — identical 4-LOC `datetime.now(UTC)` at `backend/app/integrations/zlm/health.py:46` and
`backend/app/integrations/zlm/continuity.py:47`.

**Shared home:** `backend/app/core/coerce.py` + `backend/app/core/http.py`

```python
# app/core/coerce.py
def read_attr(value: Any, name: str) -> Any: ...
def read_path(value: Any, *names: str) -> Any: ...
def as_text(value: Any) -> str | None: ...                 # lenient, for third-party payloads
def require_text(value: Any, *, field: str, required: bool = False,
                 max_length: int | None = None, code: str = "invalid_request") -> str | None: ...
def as_string_list(value: Any, *, max_items: int = 128, max_length: int = 128,
                   strict: bool = True, code: str = "invalid_request") -> list[str]: ...

# app/core/http.py
def client_fingerprint(request: Request) -> dict[str, object]: ...   # user_agent + source_ip
```

`fetch_or_404`-style caller messages stay per-module by passing `code=`.

---

### 14. Session/lease registries and process lifecycle duplicated across `cameras/*`

**Impact: medium · Effort: medium · ~150 LOC removable + centralises thread-safety**

Two modules implement the same "`RLock` + `threading.Timer` factory + TTL expiry + cleanup
callbacks + `stop()`" registry:

| Concern | `MediaSessionRegistry` (`backend/app/modules/cameras/media_sessions.py`) | `LiveTranscodeManager` (`backend/app/modules/cameras/live_transcode.py`) |
|---|---|---|
| lock + timer factory | `:33-39` (`:36 timer_factory=threading.Timer`, `:39 RLock`) | `:67-93` (`:74`, `:93 RLock`) |
| create timer | inline `:66`, `:156` | `_make_timer :401-415` |
| cancel timer | `_cancel_timer :206-215` | `_cancel_timer :417-425` |
| TTL re-arm | `renew :128-172` | `_schedule_lease_expiry_locked :427-441`, `_schedule_idle_locked :442-454` |
| expiry | `_expire :290-315` | `_expire_lease :480-484`, `_expire_derivative :486-504` |
| teardown | `stop :316-322`, `_run_cleanups :217-226` | `release :651`, `close` paths |

`_cancel_timer` is duplicated verbatim (only `if timer is None: return` vs `if timer is not None:`
inverted):

```python
    @staticmethod
    def _cancel_timer(timer: Any | None) -> None:      # media_sessions.py:206
        if timer is None:
            return
        try:
            timer.cancel()
        except Exception:
            pass

    def _cancel_timer(self, timer: Any | None) -> None: # live_transcode.py:417
        if timer is not None:
            try:
                timer.cancel()
            except Exception:
                pass
```

Process lifecycle is likewise forked between a threaded and an asyncio implementation:

- `LiveTranscodeManager._stop_process` (`live_transcode.py:350-361`) — sync:
  `poll()` guard → `terminate()`/`wait(2)` → `kill()`/`wait(2)` → swallow.
- `LivePreviewSession._begin_process_stop` / `_stop_process` (`live_preview.py:160-174`) — async
  variant with `asyncio.shield` and a `_track_cleanup` hook.

`_stop_process` is also the 5th name collision in the codebase
(`integrations/contracts.py:212`, `zlm/recording.py:76`, `frigate/mqtt_runtime.py:97`,
`onvif/event_runtime.py:310`, `media_sessions.py:316`, `live_transcode.py:700` all define
`stop`/`_stop_process` with different meanings) — see the "false-positive collisions" note below.

**Shared home:** `backend/app/core/registry.py` + `backend/app/core/process.py`

```python
# app/core/registry.py
class TtlRegistry(Generic[K, V]):
    """RLock + timer factory + per-entry TTL, renewal, expiry callback, bulk revoke, stop()."""
    def __init__(self, *, timer_factory=threading.Timer,
                 on_expire: Callable[[K, V], None] | None = None) -> None: ...
    def put(self, key: K, value: V, *, ttl: float) -> V: ...
    def renew(self, key: K, *, ttl: float) -> bool: ...
    def pop(self, key: K) -> V | None: ...
    def stop(self) -> None: ...

# app/core/process.py
def stop_process_sync(process: PopenLike, *, grace: float = 2.0) -> None: ...
async def stop_process_async(process: asyncio.subprocess.Process, *,
                             grace: float = 2.0) -> None: ...
```

`MediaSessionRegistry(TtlRegistry)`, `LiveTranscodeManager(TtlRegistry)`,
`PreviewWallSession` and `TurnCredentialService` (`turn.py:27`, TTL credentials) all sit on this.

---

### 15. `cli.py`: 21 identical JSON emitters, 20 duplicate settings bootstraps, 24 hand-registered subcommands

**Impact: medium · Effort: low · ~300 LOC removable**

`backend/app/cli.py` is 2,686 LOC with 37 import lines and no shared command scaffolding.

- **21 identical output blocks** — every command ends with the same 6-line idiom
  (`json.dumps` appears 21×, `sort_keys=True` 21×, and all 21 are wrapped in `print(`):

```python
# cli.py:89, 267, 348, 372, 499, 576, 657, 870, 949, 959, 1008, 1076, 1193, 1251,
# 1273, 1395, 1501, 1575, 2131, 2173, 2360
    print(
        json.dumps(
            payload,
            sort_keys=True,
        )
    )
```

- **20 duplicate database bootstraps** — `_settings_database()` (`cli.py:70-74`) is called 20×,
  and several commands additionally re-implement the `Settings` + `Database` + `try/finally close`
  dance inline (e.g. `migration_preflight_command:195`, `database_transfer_command:429`,
  `restore_staged_command:2232`).
- **24 `add_parser` calls** inside one 287-LOC `build_parser` (`cli.py:2383-2669`), plus
  `main` (`:2672`) and a *second* `build_parser`/`main` pair in
  `backend/app/recovery_kit_cli.py:12,33` — two entry points with the same shape.
- Repeated pre-upgrade/safety-snapshot logic: `_verified_safety_backup_command:880`,
  `_validated_safety_snapshot:1966`, `_restore_safety_snapshot:2007`,
  `_pre_upgrade_policy:670`, `_validate_restore_keyring:1742`,
  `_validate_restore_manifest:1811`, `_postgres_restore:1905` — 7 helpers all in the 880–2110 band.

**Shared home:** `backend/app/cli/` package

```python
# app/cli/_output.py
def emit(payload: Any, *, indent: int | None = None) -> int:
    print(json.dumps(payload, sort_keys=True, indent=indent))
    return 0

# app/cli/_context.py
@contextmanager
def database_context(args) -> Iterator[tuple[Settings, Database]]: ...

# app/cli/_registry.py
COMMANDS: dict[str, Command]      # Command = (name, help, add_arguments, handler)
def build_parser() -> argparse.ArgumentParser:   # iterates COMMANDS; no 287-line function
```

Split the command bodies by domain, mirroring the module layout:
`app/cli/migrate.py` (`:149-426`), `app/cli/update.py` (`:670-1025`), `app/cli/health.py`
(`:1031-1586`), `app/cli/restore.py` (`:1589-2380`).

---

## Fat files: seam maps

Line ranges are from the AST skeletons; the "natural seam" column is the target submodule split.

### `backend/app/modules/cameras/api.py` — 3,868 LOC, 40 endpoints, 35 import lines

| Range | Cluster | Proposed submodule |
|---|---|---|
| `112` | `router = APIRouter()` | — |
| `115-444` | View/snapshot builders (12 funcs, incl. `_camera_summary:235` 103 LOC) | `cameras/views.py` |
| `451-596` | Camera group endpoints (5 routes) | `cameras/api_groups.py` |
| `600-720` | Camera core CRUD + config test (3 routes) | `cameras/api_cameras.py` |
| `728-1308` | ONVIF import / capability refresh / discovery (6 routes, `import_onvif_camera:728` 186 LOC, `refresh_onvif_capabilities:920` 213 LOC, `run_camera_discovery:1227` 82) | `cameras/api_onvif.py` |
| `1315-1493` | Read paths: discovery, get camera, capability health, clock projection (4 routes) | `cameras/api_health.py` |
| `1497-1763` | enable/disable/retire/restore (6 routes + `_set_camera_enabled:1537`, `_set_camera_retired:1641`) | `cameras/api_lifecycle.py` |
| `1764-2184` | Probe + stream verification + binding replacement (4 routes, `verify_camera_stream:1875` 178) | `cameras/api_streams.py` |
| `2194-2791` | Live profile selection + WHEP ticket machinery (14 funcs, `_select_bound_live_profile:2239` 139, `_parse_whep_cleanup_ticket:2475` 88) | `cameras/live_selection.py` |
| `2798-3373` | Live HTTP endpoints + WHEP sessions (5 routes, `create_camera_whep_session:3167` 161, `get_camera_live_stream:2798` 120) | `cameras/api_live.py` |
| `3381-3662` | Live compatibility leases + keepalive (5 routes, `create_camera_live_compatibility:3381` 143) | `cameras/api_live_sessions.py` |
| `3666-3868` | Snapshot + PTZ (4 routes) | `cameras/api_media.py` |

The 35 import lines at `:1-112` are the tell: the file already aggregates 9 sibling modules plus
the whole `ZlmAdapter`/`OnvifAdapter` surface. Each new submodule imports only its cluster, and
`app/api/v1/router.py` (currently 15 `include_router` calls) picks up the extra routers.

### `backend/app/modules/system/config_import.py` — 3,452 LOC

See finding 7 (12 section handlers; `validate:301-1237`, `apply:1293-3452`).

### `backend/app/cli.py` — 2,686 LOC

See finding 15 (`migrate:149-426`, `update:670-1025`, `health:1031-1586`, `restore:1589-2380`,
`build_parser:2383-2669`).

### `backend/app/modules/system/api.py` — 1,856 LOC, 19 endpoints

| Range | Cluster | Proposed submodule |
|---|---|---|
| `94-161` | Frigate view/snapshot builders | `system/views.py` |
| `168-333` | Health, info, secret-store health/rotate (4 routes) | `system/api_health.py` |
| `317-618` | Frigate provider CRUD + test + backfill (4 routes, `put_frigate_provider:340` 195 LOC) | `system/api_frigate.py` |
| `635-882` | Config import/export endpoints (3 routes) | `system/api_config.py` |
| `885-1041` | Settings views/snapshots + `get_system_settings` | `system/api_settings.py` |
| `1048-1237` | `patch_system_settings:1048` 190 LOC | `system/api_settings.py` |
| `1244-1300` | Update info + SSE event stream | `system/api_updates.py` |
| `1308-1575` | `apply_camera_ntp_settings:1308` 268 LOC | `system/api_ntp.py` |
| `1583-1780` | `camera_clock_health:1583` 198 LOC | `system/api_ntp.py` |
| `1787-1856` | Release validation + readiness | `system/api_release.py` |

### `backend/app/worker/tasks.py` — 1,549 LOC, huey tasks, 40 import lines

| Range | Cluster | Proposed submodule |
|---|---|---|
| `84-226` | Prebuffer fragment promotion helpers (`_fragment:84` 42, `_promotion_target:134`, `_promote:199`) | `worker/prebuffer_tasks.py` |
| `230-376` | `promote_prebuffer_fragment:230`, `gc_prebuffer_fragment:266` (75), `_probe_duration:353` | `worker/prebuffer_tasks.py` |
| `380-612` | Runtime reconciliation (`reconcile_camera_runtime:380` **199 LOC**, `reconcile_manual_recording_boundary:582`) | `worker/runtime_tasks.py` |
| `618-956` | Capacity guard + policy boundary + prebuffer reconcile (`periodic_recording_capacity_guard:618` 186, `reconcile_camera_prebuffer:807` 68, `reconcile_recording_policy_boundary:879` 78) | `worker/recording_tasks.py` |
| `963-1123` | Catalog reconciliation + playback/archive/delete (6 tasks) | `worker/catalog_tasks.py` |
| `1126-1247` | Retention reconciliation (`_run_retention_reconciliation:1126` 106) | `worker/retention_tasks.py` |
| `1251-1368` | Frigate backfill (`_frigate_backfill:1251` 102) | `worker/frigate_tasks.py` |
| `1373-1453` | Notification/export/backup entry tasks (6 thin wrappers) | `worker/dispatch_tasks.py` |
| `1457-1549` | `schedule_backups:1457` 84 + `worker_heartbeat:1545` | `worker/schedule_tasks.py` |

Note the inline imports: `worker/tasks.py:128 _database()` (4 LOC) duplicates
`backend/app/modules/system/health.py:276 _database()` (82 LOC) in name only, and 15 `@huey.task`
decorators are declared with hand-tuned `retries`/`retry_delay` that no shared policy expresses
(`retries=3, retry_delay=10/15/30/60`, `retries=2, retry_delay=15/30/60`).

### `backend/app/modules/recordings/api.py` — 1,421 LOC, 18 endpoints

| Range | Cluster | Proposed submodule |
|---|---|---|
| `79-376` | 13 view/snapshot/signature builders (`_trigger_view:235` 61, `_resolve_policy_runtime_map:339`) | `recordings/views.py` |
| `383-644` | Recording policy endpoints (`put_recording_policy:430` **215 LOC**) | `recordings/api_policy.py` |
| `657-825` | Protection CRUD (4 routes) | `recordings/api_protection.py` |
| `833-1041` | Trigger lifecycle (3 routes, `create_recording_trigger:833` 90, `stop_recording_trigger:960` 82) | `recordings/api_triggers.py` |
| `1049-1140` | Catalog queries (3 routes) | `recordings/api_catalog.py` |
| `1145-1421` | Playback/timeline (`_resolve_playback_plan:1145` 61, `aligned_playback_timeline:1322` 61) | `recordings/api_playback.py` |

### `backend/app/modules/storage/service.py` — 1,272 LOC, one 1,184-LOC class

| Range | Cluster | Proposed submodule |
|---|---|---|
| `52-86` | `ResolvedRcloneTarget` + `object_path:58` 29 | `storage/rclone_target.py` |
| `95-191` | Uniqueness guards (`_ensure_name_available:95`, `_ensure_default_recording_unique:116`, `_ensure_default_archive_unique:155`) — the last two are 37 LOC each and structurally identical | `storage/validation.py` |
| `205-258` | `default_archive_target:205` 40, `get:247` | `storage/repository.py` |
| `261-549` | Config codecs: `_local_config:261`, `_rclone_config:311`, `normalize_config:381`, `_openlist_rclone_config:404` 82, `_replace_rclone_secret:487` | `storage/config_codec.py` |
| `551-859` | `create:551` 102 + `update:654` **206 LOC** | `storage/repository.py` |
| `861-1089` | `switch_recording_target:861` **186 LOC**, `delete:1049` | `storage/recording_target.py` |
| `1091-1272` | `resolve_rclone:1091`, `test_target:1149` | `storage/probe.py` |

Note `_ensure_default_recording_unique:116` and `_ensure_default_archive_unique:155` are two
37-LOC functions distinguished only by a role literal (`"record"` vs `"archive"`) — the same
`_ensure_name`/`_name_available` duplication pattern seen in
`backups/service.py:206`, `notifications/service.py:601`, `storage/service.py:95`
(4 implementations of "is this name taken → 409 conflict"):
`alerts/service.py:445`+`:515`, `cameras/groups.py:211`+`:262`, `storage/retention_admin.py:187`+`:304`,
`cameras/live_layouts.py:135`, `auth/oidc.py:406`, `auth/admin_service.py:158`+`:279`+`:320`.

### Other notable fat classes (already have service seams, listed for completeness)

| File | LOC | Seam |
|---|---|---|
| `modules/cameras/onvif_onboarding.py` | 1,257 | `_reconfigure_existing:589-985` (397 LOC) and `import_device:1021-1257` (237) dominate; split into `onvif/identity.py` (`identity_assessment:350`, `resolve_identity:440`), `onvif/reconfigure.py`, `onvif/import.py` |
| `modules/storage/retention.py` | 1,114 | planner (`RetentionPlanner:69-879`) vs deleter (`LocalRetentionDeletionService:896-1114`) — already two classes, split into two files; `_retention_horizon:215-355` (141) and `actionable_plan:744-879` (136) |
| `modules/recordings/reconciliation.py` | 1,107 | one 1,026-LOC class; `_ffprobe:109-187`, `_identity:290-351`, `_recover_file:650-849` (200), `_record_state:851-931` (81), `reconcile:933-1107` (175) → `reconciliation/{probe,identity,recover,state}.py` |
| `modules/notifications/service.py` | 1,097 | `update:749-879` (131) + SMTP codec (`_normalize_smtp_config:184-280` 97, `_normalize_smtp_credentials:283`) → `notifications/smtp_config.py`; `resolve:918`/`resolve_smtp:955` |
| `integrations/onvif/adapter.py` | 1,070 | capability probing (`_probe_snapshot_capability:233`, `_probe_management_capabilities:285` 88, `_probe_optional_capabilities:374`) vs operations (`ptz_move:736`, `ptz_stop:814`, `configure_ntp:670`, `read_system_clock:601`) vs discovery (`_discover_blocking:968` 103) → 3 mixins over one transport |
| `modules/alerts/service.py` | 941 | policy normalization (`normalize_match:177-338` 162, `normalize_actions:341-417` 77) vs evaluation (`evaluate_event:784-941` 158) — two classes already, split files |
| `modules/system/health.py` | 894 | one 710-LOC `SystemHealthService` with 8 independent probes (`_host_clock:211`, `_database:276` 82, `_worker:359`, `_zlm:389`, `_local_storage:418` 151, `_recording_reconciliation:570` 176, `_frigate:747`) → probe registry, each `Collector` returning `HealthComponent` (already a dataclass at `:147`) |
| `modules/auth/admin_api.py` | 790 | 20 routes, 12 audit+commit copies — pairs with finding 4 |

---

## Also confirmed, but not behaviourally duplicated (avoid chasing these)

The AST scan surfaced 129 duplicate private names; these are **false positives** and should not be
"deduplicated":

| Name | Occurrences | Why not a finding |
|---|---|---|
| `__init__` | 86 (68 files) | expected |
| `get`/`list`/`create`/`update`/`delete` | 21/13/14/11/8 | **intentional** per-service CRUD vocabulary; the shared part is only the 404 body (finding 5) |
| `discover`, `inspect_device`, `read_system_clock`, `configure_ntp`, `ptz_move`, `ptz_stop`, `is_media_online`, `wait_media_online`, `wait_video_ready`, `media_probe`, `add_stream_proxy`, `delete_stream_proxy`, `close_stream`, `whep_play`, `delete_webrtc`, `load_mp4_file`, `probe_rtsp_source`, `is_stream_online`, `is_recording`, `copy_to_remote`, `copy_to_local`, `stat`, `delete_file`, `test_connection`, `send_email`, `events`, `snapshot`, `version`, `notify`, `start`, `stop`, `status`, `close`, `reconfigure`, `verify`, `collect`, `prepare`, `execute`, `plan`, `reconcile`, `evaluate` | Protocol vs implementation pairs in `backend/app/integrations/contracts.py` (`DeviceAdapter:8`, `MediaPlane:44`, `StoragePlane`, `MailPlane`, `IntegrationAdapter:304`) — the duplication is *deliberate interface/impl mirroring*. Note `test_adapter_contracts.py` exists to pin it. Only the **lifecycle** (`__enter__`/`__exit__`/`close`) is worth hoisting (finding 9). |
| `_instance` | 3 | 2 unrelated (ONVIF normalizer parses strings; `events/service.py` validates datetimes) |
| `_roles` | 2 | `auth/oidc.py:110` resolves role UUIDs; `system/config_export.py:95` serialises `Role` rows |
| `_prune` | 2 | `playback_cache.py:156` deletes cache files; `auth/rate_limit.py:67` pops a `deque` |
| `_now` | 2 | genuinely identical — included in finding 13 |
| `_fingerprint` | 2 | `onvif/normalizer.py:178` hashes event content; `backups/recovery_kit.py:322` hashes a key set |
| `_message` | 2 | `zlm/access.py:27` builds a signed play token; `onvif/normalizer.py:75` unwraps nested SOAP `Message` |
| `_database` | 2 | `worker/tasks.py:128` returns the worker `Database`; `system/health.py:276` collects DB health |
| `_tuning` | 2 | **is** duplication — included in finding 8 |
| `TimestampMixin`/`UUIDPrimaryKeyMixin` | 50 model classes | already shared correctly; the models layer is the one part of the codebase with no duplication finding |

---

## Priority order for execution

| # | Finding | LOC removable | Risk | Suggested PR size |
|---|---|---|---|---|
| 1 | Cursor pagination → `core/pagination.py` | ~294 | very low (pure functions, identical logic) | 1 PR |
| 2 | Test fixtures/factories → `tests/conftest.py` + `tests/factories.py` + `tests/fakes.py` | ~1,870 + 95 classes | none (test-only) | 1–2 PRs, mechanical |
| 3 | `get-or-404` → `core/db/repository.py` | ~370 | low | 1 PR |
| 4 | Timezone helpers → `core/time.py` (fixes latent 500s) | ~90 | low | 1 PR |
| 5 | Coercion helpers → `core/coerce.py`, `core/http.py` | ~200 | low | 1 PR |
| 6 | Atomic write + path containment → `core/fs.py` (fixes `health.py` race) | ~270 | low, security-reviewed | 1 PR |
| 7 | View/snapshot mappers → `core/api/views.py` + `ApiSchema` | ~1,040 | medium (OpenAPI diff) | 3–4 PRs by module |
| 8 | Router boilerplate → `core/api/router.py` + `AuditEmitter` | ~400 | medium | 2 PRs |
| 9 | Integration base → `integrations/base.py` | ~250 | medium | 2 PRs |
| 10 | Job runner → `core/jobs/runner.py` | ~500 | medium-high (state machine) | 2–3 PRs |
| 11 | Settings namespace store → `core/settings/` | ~120 | medium | 1 PR |
| 12 | TTL registry / process stop → `core/registry.py`, `core/process.py` | ~150 | medium (threading) | 1 PR |
| 13 | CLI package split | ~300 | low | 1 PR |
| 14 | `config_import/` section registry (also unifies `config_export`) | ~3,000 reorganised | high | 4–6 PRs, golden-file tests first |
| 15 | Fat-file splits (cameras/api.py, system/api.py, worker/tasks.py, …) | — (no LOC change) | medium; do **after** 7, 8, 10 land so the extracted helpers do the shrinking | 1 PR per file |

Findings 1–6 are pure extraction of already-identical code and can be merged with near-zero
behavioural risk; 7–10 depend on the shared primitives from 1–6; 14 and 15 should be last so the
new helpers absorb the line count instead of moving it.

# Migration from V1

zero-nvr is a clean V2 project.

The previous camera-recorder repository is useful as:

- a requirements source;
- a behavior reference;
- a failure-mode catalog;
- an acceptance-test source;
- a possible data-migration source.

It is not the implementation base.

## Reuse categories

### Reuse conceptually

- stable Camera identity;
- adapter-aware connection model;
- explicit camera disable semantics;
- recording history/timeline concepts;
- event-source abstraction;
- deletion-impact safety;
- local/cloud object awareness;
- real-hardware acceptance mindset.

### Re-design

- media sessions around ZLMediaKit;
- ONVIF around a mature library;
- event normalization around the V2 canonical model;
- storage around StorageTarget/StorageObject;
- workers/jobs as explicit architecture;
- production metadata on PostgreSQL.

### Do not port by default

- hand-written ONVIF SOAP/WSDL;
- FastAPI/JPEG preview streaming;
- legacy SQLite compatibility wrappers;
- V1-specific schema shadow fields;
- deployment workarounds that only existed for the old process layout.

## Data migration

No V1 data migration should be implemented until the V2 schema is stable enough to map semantics deliberately.

Future migration tool should be one-way and explicit:

```text
V1 DB/files
   ↓
migration inspector
   ↓
mapping report
   ↓
V2 PostgreSQL + media object registration
```

Never point V2 directly at a V1 database and mutate it in place.

## Rollout strategy

When V2 becomes functional:

1. run V1 and V2 separately;
2. validate V2 with test cameras;
3. optionally import selected Camera configuration;
4. validate live/recording/event behavior;
5. migrate historical metadata only with a dedicated migration plan;
6. decommission V1 only after explicit acceptance.

The rewrite is allowed to simplify legacy behavior rather than preserve accidental implementation details.

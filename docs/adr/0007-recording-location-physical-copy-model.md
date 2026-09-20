# ADR 0007 — RecordingLocation Is the Physical Recording Copy Model

Status: **accepted**

## Context

Earlier design drafts used a generic StorageObject entity for recording files and a separate UploadJob state machine for archive work.

The current architecture already distinguishes:

- RecordingSegment: one finalized media/time fact;
- StorageTarget: a configured destination/backend;
- physical local/remote copies of a segment;
- disposable playback/export/thumbnail caches;
- Huey task execution.

A generic StorageObject plus UploadJob duplicates concepts and makes the schema less explicit.

## Decision

V1 uses RecordingLocation as the only canonical physical-copy entity for recording media.

~~~text
RecordingSegment
  id
  camera/time/media facts
       |
       +-- RecordingLocation local SSD        AVAILABLE
       +-- RecordingLocation NAS              AVAILABLE
       +-- RecordingLocation cloud/OpenList   AVAILABLE
~~~

RecordingLocation fields include:

~~~text
recording_segment_id
storage_target_id
object_path
state
size/checksum
verified_at
attempt/error metadata
created/deleted timestamps
~~~

States:

~~~text
AVAILABLE
ARCHIVING
FAILED
DELETING
DELETED
MISSING
~~~

Archive flow:

~~~text
local AVAILABLE
-> create remote ARCHIVING
-> Huey worker invokes rclone
-> verify
-> remote AVAILABLE
-> retention may delete local
~~~

Huey owns task execution/retry scheduling. zero-nvr does not require a separate UploadJob business table for rclone work.

## Explicit exclusions

The following are not RecordingLocations merely because they are files:

- playback cache;
- export output;
- thumbnails;
- temporary pre-roll fragments;
- database backup/restic repository objects.

They use their own lifecycle or disposable cache semantics.

RecordingSegment never stores an authoritative local/cloud path.

## Consequences

Positive:

- one clear model for local/NAS/cloud copies;
- archive state and playback source use the same entity;
- moving/deleting one copy does not rewrite recording identity;
- fewer tables and duplicate state machines;
- remote verification and archive-before-delete are explicit.

Trade-off:

- generic non-recording file/object management is not modeled through RecordingLocation;
- if a future product feature genuinely needs a generic object store entity, it must be introduced separately rather than overloading recording media.

## Compatibility

Old documentation terms map as follows:

~~~text
StorageObject(recording media) -> RecordingLocation
LOCAL_READY                    -> local RecordingLocation AVAILABLE
UPLOADING/VERIFYING            -> remote RecordingLocation ARCHIVING
REMOTE_READY                   -> remote RecordingLocation AVAILABLE
UploadJob                      -> Huey execution + RecordingLocation product state
~~~

Any implementation/schema started after this ADR should use RecordingLocation directly rather than preserving the old aliases.

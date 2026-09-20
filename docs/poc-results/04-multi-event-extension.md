# POC-04 — Multi-event Extension

Result: **NOT RUN**

## Purpose

Validate overlapping Event / RecordingTrigger behavior without recorder restart.

Example semantics:

~~~text
Event A requires media through 20:00:20
Event B arrives before then and requires through 20:00:27
Event C can extend again

effective promotion window extends
ZLM recorder does not restart
~~~

Events remain individually queryable.

## Primary candidate behavior

With rolling tmpfs prebuffer:

- ZLM recorder is already active;
- Event arrival protects/promotes overlapping finalized fragments;
- current open fragment is handled when its normal hook arrives;
- additional Events extend the merged required window;
- the same fragment may satisfy several Events but is copied/published once;
- after final post-roll is covered, promotion stops while rolling tmpfs recording continues.

## Harness

POC-03 and POC-04 share:

~~~text
poc/zlm-recording/scripts/run-event-preroll.sh
~~~

The trigger schedule intentionally contains overlapping clusters.

## Required checks

- ten independent Event records/timestamps are represented in evidence;
- overlapping windows merge as expected;
- at least one promoted fragment overlaps more than one Event;
- that fragment has only one persistent promotion path;
- ZLM recorder status remains active throughout;
- no start/stop/restart command is issued per Event;
- final post-roll coverage is present;
- GC never deletes a fragment that a still-active Event window needs;
- recorder remains active after the final Event window completes.

## startRecordTask comparison

A separate comparison should record the tested current-upstream behavior for repeated startRecordTask calls.

It must not be interpreted as extension merely because multiple files are generated.

Current source audit shows each call creates a new MP4Muxer/RingReader and has no task-extension ID/API.

## Tested versions

Pending execution.

## Test environment

Pending execution.

## Evidence

Pending execution.

Expected primary evidence:

~~~text
poc/zlm-recording/runtime/event-preroll-gop2.json
poc/zlm-recording/runtime/event-preroll-gop5.json
~~~

Fields of interest include:

~~~text
events
merged_required_windows
coverage_checks
promoted
multi_event_fragments
recorder_active_after_events
max_tmpfs_bytes
~~~

## Architecture impact

Pending execution.

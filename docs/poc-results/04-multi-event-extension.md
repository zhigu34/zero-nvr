# POC-04 — Multi-event Extension

Result: **PASS**

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

Same passing runtime matrix as POC-03:

~~~text
GitHub Actions run: 35489849518
job: POC 03
MediaMTX: 1.21.0-ffmpeg
ZLMediaKit image: zlmediakit/zlmediakit:master
Docker Engine: 28.0.4
Docker Compose: v2.38.2
~~~

Exact ZLM commit was not serialized by the first POC-03 JSON; subsequent harness runs now record it.

## Test environment

GitHub-hosted Ubuntu 24.04.5 / x86_64 runner.

Each codec/GOP group created ten independent Event timestamps arranged into overlapping clusters.

## Evidence

PASS assertions included:

- all ten Events remained separate Event-like trigger facts in evidence;
- merged required windows extended to the latest required post-roll;
- ZLM recorder stayed active throughout;
- no Event caused start/stop/restart of the rolling recorder;
- at least one promoted fragment overlapped multiple Events;
- a source fragment had one persistent promotion path even when it served multiple Events;
- GC did not remove still-required fragments;
- after final required coverage, the rolling recorder remained active.

Representative overlap evidence included fragments serving:

~~~text
E6 + E7 + E8
E9 + E10
~~~

in the same promoted physical file.

H.264/2s-GOP:

~~~text
10 / 10 Event coverage checks PASS
multi-Event promoted fragments = 16
promoted fragments = 20
recorder active after final Event = true
~~~

H.264/5s-GOP:

~~~text
10 / 10 Event coverage checks PASS
multi-Event promoted fragments = 12
promoted fragments = 12
recorder active after final Event = true
~~~

H.265:

~~~text
10 / 10 Event coverage checks PASS
actual codec = hevc
multi-Event promoted fragments = 16
promoted fragments = 20
recorder active after final Event = true
~~~

The `startRecordTask` comparison created five independent files with different first-frame hashes rather than exposing one extendable task, supporting the decision not to use repeated task creation as Event-extension semantics.

Primary artifact:

~~~text
GitHub Actions artifact:
  poc-03-evidence
  run 35489849518
  artifact id 10598647826
~~~

## Known limitations

Whole-fragment retention intentionally permits physical coverage beyond exact Event pre/post-roll. Exact user exports can trim later through FFmpeg.

## Architecture impact

**Accepted:** overlapping Events extend one derived promotion/protection window. They never create duplicate normal recorders.

`RecordingTrigger` remains the durable reason/evidence model; an effective promotion window is derived runtime state, not a new RecordingIntent/RecordingSession table.

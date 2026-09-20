# POC-03 — EVENT_ONLY Pre-roll

Result: **NOT RUN**

## Primary candidate

~~~text
one ZLM normal recorder
-> short finalized fragments in bounded shared tmpfs
-> on_record_mp4
-> Event/RecordingTrigger overlap selects whole fragments
-> copy/verify/atomic publish
-> persistent RecordingSegment + RecordingLocation
~~~

Events change the **promotion window**, not recorder state.

## Harness

~~~text
poc/zlm-recording/scripts/run-event-preroll.sh
~~~

The harness is committed but has not been executed by this conversation environment.

## Test matrix

The first automated run uses H.264 synthetic sources with:

- ~2 second GOP;
- ~5 second GOP.

Each stream uses the same configured:

- ~10 second pre-roll;
- ~10 second post-roll;
- short ZLM fragment target;
- bounded shared tmpfs.

The test generates ten Event trigger timestamps distributed across many fragment boundaries.

## Required checks

For every Event at T:

~~~text
earliest promoted coverage <= T - pre_roll
latest promoted coverage   >= T + post_roll
~~~

within the explicitly documented timestamp tolerance of the tested ZLM hook metadata.

Also require:

- one ZLM normal MP4 recorder stays active before/during/after Events;
- normal ZLM on_record_mp4 hooks drive finalized fragment discovery;
- ephemeral tmpfs fragments are not inserted into the canonical POC recording catalog merely because they exist;
- whole overlapping fragments are promoted without synchronous trimming/transcode;
- a fragment needed by multiple Events is promoted only once;
- promotion uses *.partial -> verify -> atomic rename;
- tmpfs capacity is actually bounded and peak bytes are recorded;
- old unneeded ephemeral files are GC'd;
- a filesystem-only scan can rediscover finalized tmpfs files without a PrebufferFragment business table;
- actual fragment duration distribution is recorded for both GOP intervals.

## H.265

H.265 remains part of the design-freeze matrix where the available test encoder/runtime supports it.

The first committed synthetic harness does not yet claim H.265 coverage. A PASS result must either:

- include an H.265 run; or
- be **PASS WITH CONSTRAINTS** with the missing H.265 validation explicitly tracked before final product release.

## Comparison candidates

The result must also document comparison findings for:

- ZLM startRecordTask(back_ms, forward_ms);
- ordinary startRecord with a pre-created ZLM frame GOP Ring.

Current source audit already shows reasons these are not the primary candidate, but runtime comparison evidence is still useful.

## Expected evidence

~~~text
poc/zlm-recording/runtime/event-preroll-gop2.json
poc/zlm-recording/runtime/event-preroll-gop5.json
poc/zlm-recording/runtime/event-docker-compose.log
poc/zlm-recording/runtime/event-recordings/
~~~

## Tested versions

Pending execution.

## Test environment

Pending execution.

## Evidence

Pending execution.

## Architecture impact

Pending execution.

Do not freeze Spec 0003 until this result is backed by runtime evidence.

# ADR 0004 — Host-Managed Storage Aggregation, No zero-nvr StoragePool

Status: **accepted**

## Context

An earlier design introduced `StoragePool`, `StoragePoolTarget`, sticky-balanced placement, automatic disk failover, reservations, draining, and per-session target scheduling.

That would make zero-nvr responsible for part of the job already solved by mature storage layers such as ZFS, Btrfs, LVM, mergerfs, software/hardware RAID, NAS filesystems, and ordinary mounted filesystems.

The project baseline requires mature components first and a lightweight single-host default.

## Decision

V1 uses `StorageTarget` as the product abstraction.

Normal recording writes to one explicitly selected local/host-mounted recording target. A system default target exists, and a camera/policy may explicitly choose another target where needed.

zero-nvr does **not** implement:

- RAID/JBOD aggregation;
- automatic multi-disk balancing;
- sticky placement scheduling;
- block-device failover;
- distributed write reservations;
- automatic archive/cloud fallback as a live recording destination.

If several disks should appear as one recording volume, the host/storage platform must provide that volume.

Remote storage remains asynchronous archive/restore through rclone.

## Consequences

Positive:

- smaller domain/data model;
- fewer failure modes;
- no duplicate filesystem/storage-manager responsibility;
- easier SQLite/single-host deployment;
- storage reliability can use proven host tools;
- remote outage remains isolated from live recording.

Trade-off:

- zero-nvr will not automatically rebalance independent local disks in V1;
- users wanting pooled disks must configure a mature host/NAS storage layer.

A future simple local-target failover may be reconsidered only if real deployments prove it necessary and a new ADR demonstrates that it does not recreate a storage manager.

ARG RCLONE_IMAGE=rclone/rclone:latest
FROM ${RCLONE_IMAGE} AS rclone-bin

FROM python:3.13-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=rclone-bin /usr/local/bin/rclone /usr/local/bin/rclone

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY main.py verify.py fmp4_prepare.py fmp4_after_crash.py event_preroll.py record_task_compare.py timeline_playback.py remote_restore.py reconciliation_faults.py api_restart.py /app/

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

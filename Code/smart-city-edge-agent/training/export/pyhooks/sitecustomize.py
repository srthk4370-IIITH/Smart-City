"""Export-run only: raise qai_hub's S3 multipart concurrency (default 4 x 256 MB parts).
On this network each S3 connection is capped at ~30-40 KB/s, so parallel parts are what makes the
~14 GB upload and ~2.5 GB bundle download feasible. boto3 adaptive retries handle SlowDown throttling."""
import os
try:
    from s3transfer.manager import TransferConfig
    import qai_hub.s3_transfer as _s3
    _chunk = int(os.environ.get("QAIHUB_PART_MB", "64")) * 1024 * 1024
    _s3._TRANSFER_CONFIG = TransferConfig(multipart_threshold=_chunk, multipart_chunksize=_chunk,
                                          max_request_concurrency=int(os.environ.get("QAIHUB_CONCURRENCY", "16")))
except Exception as exc:  # never break the export because of the tuning hook
    print("sitecustomize: qai_hub transfer tuning not applied:", exc)

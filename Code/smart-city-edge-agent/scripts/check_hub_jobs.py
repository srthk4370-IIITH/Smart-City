"""Scan AI Hub for previous compilation/link jobs to recover part_3 binary."""
import qai_hub as hub

print("=" * 70)
print("QUALCOMM AI HUB — PREVIOUS JOB SCAN")
print("=" * 70)

try:
    summaries = hub.get_job_summaries(limit=50)
    print(f"\nFound {len(summaries)} recent job summaries:\n")

    for s in summaries:
        jtype = s.job_type.name if hasattr(s.job_type, 'name') else str(s.job_type)
        status = s.status.code if hasattr(s.status, 'code') else str(s.status)
        name = getattr(s, 'name', 'unnamed')
        print(f"  [{jtype:12s}]  id={s.job_id}  status={status}  name={name}")

    # Try to find link jobs for llama model
    print("\n--- Looking for llama link jobs ---")
    link_summaries = [s for s in summaries if 'LINK' in str(s.job_type).upper()]
    for ls in link_summaries:
        name = getattr(ls, 'name', 'unnamed')
        status = ls.status.code if hasattr(ls.status, 'code') else str(ls.status)
        print(f"\nLink Job: {ls.job_id}  name={name}  status={status}")
        try:
            full_job = hub.get_job(ls.job_id)
            target_model = full_job.get_target_model()
            if target_model:
                print(f"  → Downloadable model: {target_model}")
                print(f"  → Model ID: {target_model.model_id if hasattr(target_model, 'model_id') else 'N/A'}")
        except Exception as e:
            print(f"  → Could not retrieve: {e}")

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()

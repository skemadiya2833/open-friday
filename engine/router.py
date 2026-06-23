from engine.local_model import query_local_model
from engine.cloud_model import query_cloud_model


def get_action_plan(objective: str, base64_image: str) -> dict:
    """
    Tries local model first.
    Falls back to cloud if local signals FALLBACK_TO_CLOUD or returns no steps.
    """
    print("[Router] Querying local model...")
    result = query_local_model(objective, base64_image)

    routing = result.get("routing", "LOCAL")

    if routing == "FALLBACK_TO_CLOUD" or not result.get("steps"):
        print(f"[Router] Falling back to cloud. Reason: {result.get('reason', 'No steps returned.')}")
        result = query_cloud_model(objective, base64_image)

    return result
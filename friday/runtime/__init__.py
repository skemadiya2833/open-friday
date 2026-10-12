"""Process runtime helpers (singleton lock, resource policy, etc.)."""

from friday.runtime.resource_policy import (
    background_should_defer_to_cpu,
    gpu_is_idle,
    keep_alive_for_role,
    measure_residency,
    preferred_ollama_device_for,
    residency_policy_doc,
)
from friday.runtime.singleton import SingleInstanceError, acquire_instance_lock, release_instance_lock

__all__ = [
    "SingleInstanceError",
    "acquire_instance_lock",
    "release_instance_lock",
    "background_should_defer_to_cpu",
    "gpu_is_idle",
    "keep_alive_for_role",
    "measure_residency",
    "preferred_ollama_device_for",
    "residency_policy_doc",
]

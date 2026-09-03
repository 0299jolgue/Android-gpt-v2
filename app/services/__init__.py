__all__ = ["generator"]

# Load the Android build compatibility patch before apk_builder_v3 is imported
# elsewhere, so generated projects always contain their launcher source.
from . import android_build_patch  # noqa: F401,E402

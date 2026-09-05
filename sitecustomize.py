import os

# Prevent pytest from auto-loading unrelated ROS/launch_testing plugins that
# are installed in the system environment but are incompatible with this repo.
# This keeps local test runs stable without requiring shell-specific env vars.
os.environ.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")

#!/usr/bin/env python3
"""
Ensure required toolchains are available per policy.
- In tier3 container: toolchains are pre-installed via Dockerfile.tier3.
- On host: no-op; verify_toolchains_ready.py will fail if toolchains missing.
"""
import sys

# No-op for v1: tier3 image has toolchains baked in; host runs rely on verify_toolchains_ready.
sys.exit(0)

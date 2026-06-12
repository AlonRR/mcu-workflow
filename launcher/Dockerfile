# Cage image for mcuflow (starter).
#
# Extends the official ESP-IDF image and adds the workflow's Python deps,
# pytest-embedded (for HIL), and an agent client. The runtime hardening
# (non-root, cap-drop, egress proxy/network) is applied by the launcher and
# deliverable #7 at `docker run` time, not baked in here.
ARG IDF_TAG=release-v6.0
FROM espressif/idf:${IDF_TAG}

# Workflow + HIL test dependencies.
RUN pip install --no-cache-dir \
      pyyaml jsonschema \
      pytest pytest-embedded pytest-embedded-idf pytest-embedded-serial-esp

# Agent client (Claude Code). Swap or drop this layer for a different agent.
RUN if ! command -v npm >/dev/null 2>&1; then \
        apt-get update && apt-get install -y --no-install-recommends nodejs npm \
        && rm -rf /var/lib/apt/lists/*; \
    fi; \
    npm install -g @anthropic-ai/claude-code || \
        echo "note: install your agent client here"

WORKDIR /work
# The ESP-IDF base image's entrypoint already activates the IDF environment.
CMD ["bash"]

# Fargate "refine" task image.
#
# Runs the autonomous rule-refinement step: Claude Code (headless) edits the
# rules under the Max SUBSCRIPTION token, then scripts/feedback-loop.sh verifies
# the allow-list + pytest gate and pushes/merges the PR. The image therefore
# needs: node (Claude Code CLI), git + gh (push/PR/merge), python3 + the project
# deps (pytest regression gate, generate-apps-script), and the AWS CLI (SSM/S3).
#
# It contains NO credentials. All secrets are pulled at runtime from SSM into
# environment variables by the entrypoint / feedback-loop.sh — never baked in,
# never written to disk.
#
# Base: node 20 on Debian slim (small, has apt for git/gh/python; the bookworm
# repos carry python3 and the build toolchain the google libs need).
FROM node:20-bookworm-slim

# --- OS packages -----------------------------------------------------------
# git/curl/gnupg for cloning + installing gh; python3 + pip for the project
# tooling; ca-certificates for TLS to github/anthropic/aws; less + unzip for the
# AWS CLI installer. Pin nothing exotic; clean apt lists to keep the layer small.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        git \
        curl \
        gnupg \
        ca-certificates \
        unzip \
        less \
        python3 \
        python3-pip \
        python3-venv; \
    rm -rf /var/lib/apt/lists/*

# --- GitHub CLI (gh) -------------------------------------------------------
# Install from GitHub's official apt repo (keyring pinned).
RUN set -eux; \
    mkdir -p -m 755 /etc/apt/keyrings; \
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        -o /etc/apt/keyrings/githubcli-archive-keyring.gpg; \
    chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg; \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends gh; \
    rm -rf /var/lib/apt/lists/*

# --- AWS CLI v2 ------------------------------------------------------------
# Architecture-aware download (x86_64 / aarch64) so the image builds on either
# Fargate CPU architecture.
RUN set -eux; \
    arch="$(uname -m)"; \
    case "$arch" in \
        x86_64) aws_arch=x86_64 ;; \
        aarch64|arm64) aws_arch=aarch64 ;; \
        *) echo "unsupported arch: $arch" >&2; exit 1 ;; \
    esac; \
    curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-${aws_arch}.zip" -o /tmp/awscliv2.zip; \
    unzip -q /tmp/awscliv2.zip -d /tmp; \
    /tmp/aws/install; \
    rm -rf /tmp/aws /tmp/awscliv2.zip; \
    aws --version

# --- Claude Code CLI -------------------------------------------------------
# The headless agent. Pinned npm package; authenticated at runtime via
# CLAUDE_CODE_OAUTH_TOKEN (Max subscription) — no API key, no login baked in.
RUN npm install -g @anthropic-ai/claude-code \
    && claude --version

# --- Project + Python deps -------------------------------------------------
WORKDIR /app

# Install the project's Python runtime deps + pytest (the regression gate Claude
# runs). PyYAML/google libs match what the GitHub Actions refine job installed.
# --break-system-packages: bookworm marks the system python externally-managed;
# this is a single-purpose container so a global install is fine and simplest.
RUN python3 -m pip install --no-cache-dir --break-system-packages \
        google-api-python-client \
        google-auth \
        google-auth-oauthlib \
        google-auth-httplib2 \
        pyyaml \
        hypothesis \
        pytest

# Bake the loop script + entrypoint into the image. The repo itself is cloned
# fresh at runtime (so refinements always start from origin/main HEAD); only the
# orchestration scripts are baked. scripts/ holds the single source of truth
# feedback-loop.sh that the entrypoint invokes.
COPY scripts/ /app/scripts/
COPY container/refine-entrypoint.sh /app/refine-entrypoint.sh
RUN chmod +x /app/refine-entrypoint.sh /app/scripts/feedback-loop.sh

# feedback-loop.sh runs `python -m gmail_cleanup ...` from inside the cloned
# repo (cwd), so the package resolves there — nothing else to install for it.
ENTRYPOINT ["/app/refine-entrypoint.sh"]

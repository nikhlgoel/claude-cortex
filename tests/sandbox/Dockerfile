# ==============================================================================
# Claude Cortex - sandbox test image
#
# A throwaway environment for exercising the installer, wrapper, and hooks
# against a stub Claude binary. Nothing here ever touches a real installation.
#
# Parameterized by base image so Fedora and Ubuntu share one definition:
#   docker build -f tests/sandbox/Dockerfile --build-arg BASE_IMAGE=fedora:41 .
#   docker build -f tests/sandbox/Dockerfile --build-arg BASE_IMAGE=ubuntu:24.04 .
# ==============================================================================
ARG BASE_IMAGE=fedora:41
FROM ${BASE_IMAGE}

# Install bash, python3, git, and coreutils on either distro. The wrapper is a
# bash script and the tooling is Python, so both are hard requirements.
RUN if command -v dnf >/dev/null 2>&1; then \
        dnf -y install bash python3 git findutils procps-ng diffutils which shadow-utils make \
        && dnf clean all; \
    elif command -v apt-get >/dev/null 2>&1; then \
        apt-get update \
        && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
           bash python3 git findutils procps ca-certificates make \
        && rm -rf /var/lib/apt/lists/*; \
    else \
        echo "unsupported base image: no dnf or apt-get" >&2; exit 1; \
    fi

# Run as an unprivileged user with a real home directory. Installing as root
# would not exercise the same paths the operator's install uses.
# Optional: PowerShell, so the Windows shim is executed rather than assumed.
# Windows parity is a stated goal and the previous PowerShell wrapper drifted
# badly precisely because nothing ever ran it. Off by default to keep the image
# small; enable with --build-arg INSTALL_PWSH=1.
ARG INSTALL_PWSH=0
RUN if [ "$INSTALL_PWSH" = "1" ]; then \
      set -eu; \
      if command -v dnf >/dev/null 2>&1; then \
        dnf -y install curl tar libicu && dnf clean all; \
      else \
        apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
          curl tar libicu74 || apt-get install -y --no-install-recommends curl tar libicu-dev; \
        rm -rf /var/lib/apt/lists/*; \
      fi; \
      PWSH_VER=7.4.6; \
      curl -fsSL "https://github.com/PowerShell/PowerShell/releases/download/v${PWSH_VER}/powershell-${PWSH_VER}-linux-x64.tar.gz" \
        -o /tmp/pwsh.tar.gz; \
      mkdir -p /opt/microsoft/powershell/7; \
      tar zxf /tmp/pwsh.tar.gz -C /opt/microsoft/powershell/7; \
      chmod +x /opt/microsoft/powershell/7/pwsh; \
      ln -sf /opt/microsoft/powershell/7/pwsh /usr/bin/pwsh; \
      rm -f /tmp/pwsh.tar.gz; \
    fi

RUN useradd --create-home --shell /bin/bash cortex

# /work holds the writable copy of the repository. It lives OUTSIDE $HOME on
# purpose, so the leak snapshot of $HOME stays free of build noise. Created as
# root and handed to the cortex user, since an unprivileged user cannot mkdir /.
RUN mkdir -p /work && chown cortex:cortex /work

USER cortex
ENV HOME=/home/cortex
WORKDIR /home/cortex

# Marks this as a sandbox. The installers and test suite refuse to run without it.
ENV CORTEX_SANDBOX=1
ENV PATH="/home/cortex/.local/bin:${PATH}"

# The repository is mounted read-only at /repo and copied to /work by the
# entrypoint, so a scenario can never modify the source tree.
ENTRYPOINT ["/bin/bash", "/repo/tests/sandbox/entrypoint.sh"]
CMD ["smoke"]

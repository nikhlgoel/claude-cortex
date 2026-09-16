# ==============================================================================
# Claude Cortex - sandbox test targets
#
# Every target here runs inside a container. Nothing in this Makefile installs,
# modifies, or inspects a real Claude Code installation on the host.
#
#   make sandbox-build      build the Fedora and Ubuntu test images
#   make sandbox            run all scenarios on Fedora
#   make sandbox-ubuntu     run all scenarios on Ubuntu
#   make sandbox-shell      interactive shell in the Fedora sandbox
#   make sandbox-pwsh       run with PowerShell available (Windows parity)
#   make sandbox-all        every scenario on every image
#   make sandbox-scenario S=install-dryrun
# ==============================================================================

REPO_ROOT := $(shell pwd)
FEDORA_IMAGE := cortex-sandbox:fedora
UBUNTU_IMAGE := cortex-sandbox:ubuntu
PWSH_IMAGE := cortex-sandbox:pwsh
DOCKERFILE := tests/sandbox/Dockerfile

# The repository is mounted READ-ONLY. The entrypoint copies it to /work, so a
# scenario physically cannot modify the source tree.
RUN_FLAGS := --rm -v "$(REPO_ROOT)":/repo:ro

.PHONY: sandbox-build sandbox-build-fedora sandbox-build-ubuntu sandbox-build-pwsh \
        sandbox sandbox-ubuntu sandbox-pwsh sandbox-all sandbox-shell \
        sandbox-scenario sandbox-list clean-sandbox

sandbox-build: sandbox-build-fedora sandbox-build-ubuntu

sandbox-build-fedora:
	docker build -f $(DOCKERFILE) --build-arg BASE_IMAGE=fedora:41 -t $(FEDORA_IMAGE) .

sandbox-build-ubuntu:
	docker build -f $(DOCKERFILE) --build-arg BASE_IMAGE=ubuntu:24.04 -t $(UBUNTU_IMAGE) .

sandbox: sandbox-build-fedora
	docker run $(RUN_FLAGS) $(FEDORA_IMAGE) all

sandbox-ubuntu: sandbox-build-ubuntu
	docker run $(RUN_FLAGS) $(UBUNTU_IMAGE) all

# Includes PowerShell, so the Windows shim is executed rather than assumed.
# Larger image and a slower build; worth it before trusting Windows parity.
sandbox-build-pwsh:
	docker build -f $(DOCKERFILE) --build-arg BASE_IMAGE=ubuntu:24.04 --build-arg INSTALL_PWSH=1 -t $(PWSH_IMAGE) .

sandbox-pwsh: sandbox-build-pwsh
	docker run $(RUN_FLAGS) $(PWSH_IMAGE) all

# Everything, on every platform image.
sandbox-all: sandbox sandbox-ubuntu sandbox-pwsh

# Run one scenario: make sandbox-scenario S=install-dryrun
sandbox-scenario: sandbox-build-fedora
	docker run $(RUN_FLAGS) $(FEDORA_IMAGE) $(S)

sandbox-list: sandbox-build-fedora
	docker run $(RUN_FLAGS) $(FEDORA_IMAGE) list

sandbox-shell: sandbox-build-fedora
	docker run $(RUN_FLAGS) -it --entrypoint /bin/bash $(FEDORA_IMAGE)

clean-sandbox:
	-docker rmi $(FEDORA_IMAGE) $(UBUNTU_IMAGE) $(PWSH_IMAGE)

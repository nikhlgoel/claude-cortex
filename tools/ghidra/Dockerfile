# ==============================================================================
# Ghidra, network-isolated.
#
# The audit found no telemetry and no automatic egress, but the audit is a
# best-effort review of ~15,000 files - not a proof. This container is the
# control that does not depend on the audit being complete: the analysis
# container runs with `--network none`, so anything the audit missed still has
# no route out.
#
# Build needs the network (Gradle fetches dependencies from Maven Central).
# Running does not. That split is deliberate: build once, inspect, then run
# forever with no network.
# ==============================================================================
ARG JDK_IMAGE=eclipse-temurin:21-jdk
FROM ${JDK_IMAGE} AS build

ARG GHIDRA_REF=Ghidra_12.1.3_build
ARG GRADLE_VERSION=8.14

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        git unzip curl python3 python3-pip build-essential bison flex ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL "https://services.gradle.org/distributions/gradle-${GRADLE_VERSION}-bin.zip" \
        -o /tmp/gradle.zip \
    && unzip -q /tmp/gradle.zip -d /opt && rm /tmp/gradle.zip
ENV PATH="/opt/gradle-${GRADLE_VERSION}/bin:${PATH}"

WORKDIR /src
# Pinned to a release tag, never a moving branch: an unpinned build would pull
# whatever upstream happens to contain at build time, which is exactly the
# unreviewed-change risk this whole setup exists to avoid.
RUN git clone --depth 1 --branch "${GHIDRA_REF}" --single-branch \
        https://github.com/NationalSecurityAgency/ghidra.git .

RUN gradle -I gradle/support/fetchDependencies.gradle \
    && gradle buildGhidra -x ip \
    && mkdir -p /out && unzip -q build/dist/*.zip -d /out

# ---------------------------------------------------------------------------
# Runtime stage: no build tools, no git, no curl.
# ---------------------------------------------------------------------------
FROM ${JDK_IMAGE} AS runtime

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        python3 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash analyst
COPY --from=build /out /opt/ghidra
RUN set -eu; \
    dir="$(find /opt/ghidra -maxdepth 1 -name 'ghidra_*' -type d | head -1)"; \
    ln -s "$dir" /opt/ghidra/current; \
    chown -R analyst:analyst /opt/ghidra

# Belt and braces alongside `--network none`: if this image is ever run with a
# network by mistake, Ghidra still should not reach a symbol server or a
# translation service without the operator asking.
ENV _JAVA_OPTIONS="-Djava.net.useSystemProxies=false -Dhttp.proxyHost=127.0.0.1 -Dhttp.proxyPort=1 -Dhttps.proxyHost=127.0.0.1 -Dhttps.proxyPort=1"
ENV DEBUGINFOD_URLS=""

USER analyst
WORKDIR /work
VOLUME ["/work"]

# Headless by default. The GUI is not the integration point - the value here is
# scriptable analysis whose output can be read back.
ENTRYPOINT ["/opt/ghidra/current/support/analyzeHeadless"]
CMD ["--help"]

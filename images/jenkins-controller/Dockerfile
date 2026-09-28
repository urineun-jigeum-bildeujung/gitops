ARG JENKINS_BASE_IMAGE=docker.io/jenkins/jenkins@sha256:c1e4c349365f6d16d88595b2c5f7e8ff39b8ae1d061f62420bac193b4b9616d0
FROM ${JENKINS_BASE_IMAGE}

ARG VCS_REF=unknown
ARG BUILD_DATE=unknown

LABEL org.opencontainers.image.title="PetFlow Jenkins controller" \
      org.opencontainers.image.description="Jenkins 2.568.3-jdk21 with the PetFlow plugin set preinstalled" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.source="https://github.com/urineun-jigeum-bildeujung/gitops"

# The pinned upstream image can lag Debian security updates. Keep the Jenkins
# core/JDK base immutable while applying fixed distro packages at build time.
# Replace the upstream /usr/local git-lfs binary with Debian's security-tracked
# package so its embedded Go runtime receives the patched version as well.
USER root
RUN apt-get update \
    && apt-get upgrade --yes \
    && rm -f /usr/local/bin/git-lfs \
    && apt-get install --yes --no-install-recommends git-lfs \
    && rm -rf /var/lib/apt/lists/*
USER jenkins

COPY --chown=jenkins:jenkins plugins.lock.txt /usr/share/jenkins/ref/plugins.lock.txt

RUN jenkins-plugin-cli \
      --war /usr/share/jenkins/jenkins.war \
      --plugin-file /usr/share/jenkins/ref/plugins.lock.txt \
      --plugin-download-directory /usr/share/jenkins/ref/plugins \
      --latest=false


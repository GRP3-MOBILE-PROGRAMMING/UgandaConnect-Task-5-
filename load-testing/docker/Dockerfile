# JMeter load-generator image for UgandaConnect.
#  - Apache JMeter 5.6.3 on Java 17
#  - jmeter-prometheus-plugin 0.7.1 (exposes live metrics on :9270 for Prometheus)
#  - Python 3 for the data generator, contract check and SLA gate
#
# Build (from the repo root):
#   docker build -t ugandaconnect/jmeter:5.6.3 load-testing/docker
# Run a test (results land in ./load-testing/results):
#   docker run --rm -p 9270:9270 -v "$PWD/load-testing:/tests" -w /tests ugandaconnect/jmeter:5.6.3 \
#     jmeter -n -t UgandaConnect_LoadTest.jmx -q user.properties -Jhost=api-staging.example.ug \
#            -l results/results.jtl -e -o results/report
FROM eclipse-temurin:17-jre-jammy

ARG JMETER_VERSION=5.6.3
ARG PROM_PLUGIN_VERSION=0.7.1

ENV JMETER_HOME=/opt/apache-jmeter-${JMETER_VERSION} \
    JVM_ARGS="-Xms1g -Xmx4g -XX:+UseG1GC -XX:MaxGCPauseMillis=100"
ENV PATH="${JMETER_HOME}/bin:${PATH}"

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl python3 ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && curl -fsSL "https://archive.apache.org/dist/jmeter/binaries/apache-jmeter-${JMETER_VERSION}.tgz" \
      | tar -xz -C /opt \
 && curl -fsSL -o "${JMETER_HOME}/lib/ext/jmeter-prometheus-plugin-${PROM_PLUGIN_VERSION}.jar" \
      "https://github.com/johrstrom/jmeter-prometheus-plugin/releases/download/${PROM_PLUGIN_VERSION}/jmeter-prometheus-plugin-${PROM_PLUGIN_VERSION}.jar" \
 && chmod -R a+rwX ${JMETER_HOME}/bin \
 && jmeter --version

# 9270 = Prometheus metrics; 1099/50000 = JMeter distributed-mode RMI (only for jmeter-server)
EXPOSE 9270 1099 50000
WORKDIR /tests

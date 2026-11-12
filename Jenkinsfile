// UgandaConnect backend load test (Apache JMeter) - Jenkins pipeline.
//
// Made for Jenkins installed directly on the machine (not in Docker) with Docker installed.
// Works on Windows (Docker Desktop), Linux and macOS: Jenkins only runs plain `docker`
// commands; JMeter, Python and the Prometheus plugin live inside the image built from
// load-testing/docker/Dockerfile.
//
// Jenkins plugins: Pipeline, Git, HTML Publisher, Timestamper (+ Prometheus metrics, optional).
//
// While a test runs, JMeter serves live metrics on http://<this machine>:9270/metrics, which the
// Prometheus in load-testing/monitoring/docker-compose.yml scrapes into Grafana.

// Run a shell command with sh on Linux/macOS and bat on Windows
def cmd(String c) {
  if (isUnix()) { sh c } else { bat c }
}

// docker run with the workspace's load-testing/ folder mounted at /tests
def dockerRun(String args) {
  def name = "uc-jmeter-${env.BUILD_NUMBER}"
  if (isUnix()) {
    // run as the Jenkins user so result files are not owned by root
    sh "docker run --rm --name ${name} --user \$(id -u):\$(id -g) -e HOME=/tmp " +
       "-v \"${env.WORKSPACE}/load-testing:/tests\" -w /tests ${args}"
  } else {
    bat "docker run --rm --name ${name} -v \"%WORKSPACE%\\load-testing:/tests\" -w /tests ${args}"
  }
}

pipeline {
  agent any

  environment {
    IMAGE = 'ugandaconnect/jmeter:5.6.3'
  }

  options {
    disableConcurrentBuilds()          // one test at a time (port 9270, shared environment)
    timeout(time: 3, unit: 'HOURS')
    timestamps()
    buildDiscarder(logRotator(numToKeepStr: '30'))
  }

  parameters {
    choice(name: 'TARGET', choices: ['mock', 'staging'],
           description: 'mock = smoke test against the bundled mock API (no backend needed)')
    string(name: 'HOST', defaultValue: 'api-staging.ugandaconnect.go.ug',
           description: 'Backend host for staging. A backend running on THIS machine = host.docker.internal')
    choice(name: 'PROTOCOL', choices: ['https', 'http'])
    string(name: 'PORT', defaultValue: '443')
    string(name: 'TOTAL_USERS', defaultValue: '500', description: 'Concurrent virtual users from this machine')
    string(name: 'RAMPUP', defaultValue: '300', description: 'Ramp-up seconds')
    string(name: 'STEADY', defaultValue: '1800', description: 'Steady-state seconds')
    string(name: 'THINK_TIME_MS', defaultValue: '8000', description: 'Mean think time between user actions')
    string(name: 'MIX_UNEB', defaultValue: '30', description: '% of users on UNEB results (raise for results day)')
  }

  stages {
    stage('Build JMeter image') {
      steps {
        cmd "docker build -t ${env.IMAGE} load-testing/docker"
      }
    }

    stage('Smoke test vs mock API') {
      when { expression { params.TARGET == 'mock' } }
      steps {
        dockerRun "-p 9270:9270 -e MODE=mock -e BUILD_NUMBER=${env.BUILD_NUMBER} " +
                  "-e TOTAL_USERS=20 -e RAMPUP=20 -e STEADY=60 -e PROM_DELAY=20 " +
                  "${env.IMAGE} bash scripts/ci/run_test.sh"
      }
    }

    stage('Load test vs staging') {
      when { expression { params.TARGET == 'staging' } }
      steps {
        dockerRun "-p 9270:9270 --add-host=host.docker.internal:host-gateway " +
                  "-e MODE=staging -e BUILD_NUMBER=${env.BUILD_NUMBER} " +
                  "-e TARGET_HOST=${params.HOST} -e TARGET_PROTOCOL=${params.PROTOCOL} -e TARGET_PORT=${params.PORT} " +
                  "-e TOTAL_USERS=${params.TOTAL_USERS} -e RAMPUP=${params.RAMPUP} -e STEADY=${params.STEADY} " +
                  "-e THINK_TIME_MS=${params.THINK_TIME_MS} -e MIX_UNEB=${params.MIX_UNEB} -e PROM_DELAY=60 " +
                  "${env.IMAGE} bash scripts/ci/run_test.sh"
      }
    }

    stage('SLA gate') {
      steps {
        // Per operation: throughput, avg, p95, p99, error % -> fails the build on any breach
        dockerRun "${env.IMAGE} python3 scripts/check_sla.py results/report/statistics.json sla.json --md results/summary.md"
      }
    }
  }

  post {
    always {
      archiveArtifacts artifacts: 'load-testing/results/**', allowEmptyArchive: true
      publishHTML(target: [
        reportName : 'JMeter Load Test Report',
        reportDir  : 'load-testing/results/report',
        reportFiles: 'index.html',
        keepAll    : true,
        alwaysLinkToLastBuild: true,
        allowMissing: true
      ])
    }
    aborted {
      // stop the JMeter container if the build was cancelled
      script {
        if (isUnix()) { sh "docker rm -f uc-jmeter-${env.BUILD_NUMBER} || true" }
        else { bat "docker rm -f uc-jmeter-${env.BUILD_NUMBER} 2>nul & exit /b 0" }
      }
    }
    failure {
      echo 'Load test failed or SLAs breached - open "JMeter Load Test Report" and results/summary.md'
    }
  }
}

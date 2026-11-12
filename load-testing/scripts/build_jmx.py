#!/usr/bin/env python3
"""
Regenerates ../UgandaConnect_LoadTest.jmx (JMeter 5.6.x, core elements only, no plugins).

Edit the journey functions below if the backend API differs from API_CONTRACT.md,
then run (from load-testing/):
    python3 scripts/build_jmx.py
    python3 mock-server/mock_server.py &
    python3 scripts/dry_run.py UgandaConnect_LoadTest.jmx data http://localhost:8080
"""
import os
from xml.sax.saxutils import escape

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "UgandaConnect_LoadTest.jmx")


def esc(s):
    return escape(str(s), {'"': "&quot;"})


def jhash(s):  # Java String.hashCode, used by JMeter as stringProp names in assertion lists
    h = 0
    for ch in s:
        h = (31 * h + ord(ch)) & 0xFFFFFFFF
    return h - (1 << 32) if h >= (1 << 31) else h


def sp(n, v): return f'<stringProp name="{n}">{esc(v)}</stringProp>'
def bp(n, v): return f'<boolProp name="{n}">{"true" if v else "false"}</boolProp>'
def ip(n, v): return f'<intProp name="{n}">{v}</intProp>'


class N:
    def __init__(self, tag, gui, tc, name, props="", children=None, enabled=True):
        self.tag, self.gui, self.tc, self.name, self.props = tag, gui, tc, name, props
        self.children, self.enabled = children or [], enabled

    def render(self, ind=2):
        p = "  " * ind
        gui = f' guiclass="{self.gui}"' if self.gui else ""
        en = "" if self.enabled else ' enabled="false"'
        s = f'{p}<{self.tag}{gui} testclass="{self.tc}" testname="{esc(self.name)}"{en}>{self.props}</{self.tag}>\n'
        s += f"{p}<hashTree>\n" if self.children else f"{p}<hashTree/>\n"
        for c in self.children:
            s += c.render(ind + 1)
        if self.children:
            s += f"{p}</hashTree>\n"
        return s


def args_xml(pairs):
    out = '<collectionProp name="Arguments.arguments">'
    for k, v in pairs:
        out += (f'<elementProp name="{esc(k)}" elementType="Argument">{sp("Argument.name", k)}'
                f'{sp("Argument.value", v)}{sp("Argument.metadata", "=")}</elementProp>')
    return out + "</collectionProp>"


def comment(text): return sp("TestPlan.comments", text)


# ------------------------------------------------------------ elements --
def udv(name, pairs):
    return N("Arguments", "ArgumentsPanel", "Arguments", name, args_xml(pairs))


def header_mgr(name, headers):
    h = '<collectionProp name="HeaderManager.headers">'
    for k, v in headers:
        h += f'<elementProp name="" elementType="Header">{sp("Header.name", k)}{sp("Header.value", v)}</elementProp>'
    return N("HeaderManager", "HeaderPanel", "HeaderManager", name, h + "</collectionProp>")


def csv_ds(name, file, vars_):
    props = (sp("delimiter", ",") + sp("fileEncoding", "UTF-8") + sp("filename", "${__P(data_dir,data)}/" + file)
             + bp("ignoreFirstLine", True) + bp("quotedData", False) + bp("recycle", True)
             + sp("shareMode", "shareMode.all") + bp("stopThread", False) + sp("variableNames", vars_))
    return N("CSVDataSet", "TestBeanGUI", "CSVDataSet", name, props)


def cookie_mgr():
    return N("CookieManager", "CookiePanel", "CookieManager", "HTTP Cookie Manager (new session per iteration)",
             '<collectionProp name="CookieManager.cookies"/>' + bp("CookieManager.clearEachIteration", True)
             + bp("CookieManager.controlledByThreadGroup", False))


def cache_mgr():
    return N("CacheManager", "CacheManagerGui", "CacheManager", "HTTP Cache Manager (cleared per iteration)",
             bp("clearEachIteration", True) + bp("useExpires", False) + bp("CacheManager.controlledByThread", False))


def think_timer():
    return N("GaussianRandomTimer", "GaussianRandomTimerGui", "GaussianRandomTimer",
             "Think Time (user reads screen / types)",
             sp("ConstantTimer.delay", "${__P(think_time_ms,3000)}") + sp("RandomTimer.range", "${__P(think_dev_ms,1000)}"))


def const_timer(name, ms):
    return N("ConstantTimer", "ConstantTimerGui", "ConstantTimer", name, sp("ConstantTimer.delay", ms))


def tc(name, children):
    return N("TransactionController", "TransactionControllerGui", "TransactionController", name,
             bp("TransactionController.includeTimers", False) + bp("TransactionController.parent", False), children)


def simple(name, children):
    return N("GenericController", "LogicControllerGui", "GenericController", name, "", children)


def if_ctrl(name, cond, children):
    return N("IfController", "IfControllerPanel", "IfController", name,
             sp("IfController.condition", cond) + bp("IfController.evaluateAll", False)
             + bp("IfController.useExpression", True), children)


def pct(name, percent, children):
    """Throughput Controller in 'percent executions' mode: realistic share of users who take this branch."""
    return N("ThroughputController", "ThroughputControllerGui", "ThroughputController", f"{name} ({percent}% of sessions)",
             ip("ThroughputController.style", 1) + bp("ThroughputController.perThread", False)
             + ip("ThroughputController.maxThroughput", 1) + sp("ThroughputController.percentThroughput", f"{percent}.0"),
             children)


def code_assert(codes):
    strs = "".join(f'<stringProp name="{jhash(c)}">{c}</stringProp>' for c in codes)
    ttype = 8 | 32 if len(codes) > 1 else 8   # EQUALS (| OR)
    return N("ResponseAssertion", "AssertionGui", "ResponseAssertion", f"Assert HTTP {' or '.join(codes)}",
             f'<collectionProp name="Asserion.test_strings">{strs}</collectionProp>'
             + sp("Assertion.custom_message", f"Expected HTTP status {' or '.join(codes)}")
             + sp("Assertion.test_field", "Assertion.response_code") + bp("Assertion.assume_success", False)
             + ip("Assertion.test_type", ttype))


def json_assert(path, expected=None, regex=False):
    label = f"Assert {path}" + (f" = {expected}" if expected is not None else " exists")
    return N("JSONPathAssertion", "JSONPathAssertionGui", "JSONPathAssertion", label,
             sp("JSON_PATH", path) + sp("EXPECTED_VALUE", expected or "") + bp("JSONVALIDATION", expected is not None)
             + bp("EXPECT_NULL", False) + bp("INVERT", False) + bp("ISREGEX", regex))


def duration_assert(kind):
    prop = {"read": "${__P(sla_read_ms,2000)}", "write": "${__P(sla_write_ms,3000)}", "auth": "${__P(sla_auth_ms,1500)}"}[kind]
    return N("DurationAssertion", "DurationAssertionGui", "DurationAssertion", f"SLA: {kind} response time",
             sp("DurationAssertion.duration", prop))


def extractor(var, path, match="1", default="NOT_FOUND"):
    return N("JSONPostProcessor", "JSONPostProcessorGui", "JSONPostProcessor", f"Extract {var} <- {path}",
             sp("JSONPostProcessor.referenceNames", var) + sp("JSONPostProcessor.jsonPathExprs", path)
             + sp("JSONPostProcessor.match_numbers", match) + sp("JSONPostProcessor.defaultValues", default))


def http(name, method, path, params=None, body=None, codes=("200",), checks=(), extract=(), sla=None, extra=()):
    props = sp("HTTPSampler.domain", "") + sp("HTTPSampler.port", "") + sp("HTTPSampler.protocol", "")
    props += sp("HTTPSampler.contentEncoding", "UTF-8") + sp("HTTPSampler.path", "${BASE_PATH}" + path)
    props += sp("HTTPSampler.method", method) + bp("HTTPSampler.follow_redirects", True)
    props += bp("HTTPSampler.auto_redirects", False) + bp("HTTPSampler.use_keepalive", True)
    props += bp("HTTPSampler.DO_MULTIPART_POST", False)
    if body is not None:
        props += bp("HTTPSampler.postBodyRaw", True)
        props += ('<elementProp name="HTTPsampler.Arguments" elementType="Arguments"><collectionProp name="Arguments.arguments">'
                  '<elementProp name="" elementType="HTTPArgument">' + bp("HTTPArgument.always_encode", False)
                  + sp("Argument.value", body) + sp("Argument.metadata", "=") + "</elementProp></collectionProp></elementProp>")
    else:
        a = ('<elementProp name="HTTPsampler.Arguments" elementType="Arguments" guiclass="HTTPArgumentsPanel" '
             'testclass="Arguments" testname="User Defined Variables"><collectionProp name="Arguments.arguments">')
        for k, v in (params or []):
            a += (f'<elementProp name="{esc(k)}" elementType="HTTPArgument">' + bp("HTTPArgument.always_encode", True)
                  + sp("Argument.value", v) + sp("Argument.metadata", "=") + bp("HTTPArgument.use_equals", True)
                  + sp("Argument.name", k) + "</elementProp>")
        props += a + "</collectionProp></elementProp>"
    sla = sla or ("read" if method == "GET" else "write")
    kids = list(extra) + [code_assert(codes)] + [json_assert(*c) if isinstance(c, tuple) else json_assert(c) for c in checks]
    kids += [duration_assert(sla)] + [extractor(*e) for e in extract]
    return N("HTTPSamplerProxy", "HttpTestSampleGui", "HTTPSamplerProxy", name, props, kids)


def step(txn, *samplers):
    """A user action = Transaction Controller (one row in every report) wrapping its HTTP calls."""
    return tc(txn, list(samplers))


# ------------------------------------------------------------ journeys --
def login_logout(persona, module_steps, search_term):
    login = step("01 Login",
                 http("POST /auth/login", "POST", "/auth/login",
                      body='{"phone":"${phone}","password":"${password}","deviceId":"${__UUID()}",'
                           '"platform":"ANDROID","appVersion":"1.0"}',
                      checks=["$.token", "$.user.id", "$.expiresIn"], extract=[("token", "$.token")], sla="auth"))
    session = [
        header_mgr("Authorization: Bearer token", [("Authorization", "Bearer ${token}")]),
        step("02 Home - Load Dashboard",
             http("GET /home", "GET", "/home", checks=["$.user.id", "$.quickAccess[0]", "$.recentActivity"])),
        step("03 Services - Open Catalogue (Bottom App Bar)",
             http("GET /services", "GET", "/services", checks=["$.services[0].id", "$.services[0].agency"])),
        pct("Top App Bar search", 40, [
            step("04 Search - Find a Service (Top App Bar)",
                 http("GET /services/search", "GET", "/services/search", params=[("q", search_term)],
                      checks=["$.results", ("$.query", search_term)]))]),
        pct("Check notifications", 30, [
            step("05 Notifications - View",
                 http("GET /notifications", "GET", "/notifications", params=[("page", "1")],
                      checks=["$.items", "$.unread"]))]),
        *module_steps,
        step("99 Logout",
             http("POST /auth/logout", "POST", "/auth/logout", body="{}", checks=[("$.status", "LOGGED_OUT")],
                  sla="auth")),
    ]
    return [login, if_ctrl("Only continue if login succeeded", '${__jexl3("${token}" != "NOT_FOUND")}',
                           [simple(f"Authenticated session - {persona}", session)])]


def solar():
    return [
        step("SOLAR 01 Browse Subsidised Packages",
             http("GET /solar/packages", "GET", "/solar/packages", params=[("district", "${district}")],
                  checks=["$.packages[0].id", "$.packages[0].subsidyPercent", ("$.district", "${district}")],
                  extract=[("packageId", "$.packages[*].id", "0")])),
        step("SOLAR 02 View Package Details",
             http("GET /solar/packages/{id}", "GET", "/solar/packages/${packageId}",
                  checks=[("$.id", "${packageId}"), "$.price", "$.vendors[0].id"])),
        pct("Applicants who check eligibility", 60, [
            step("SOLAR 03 Check Eligibility (NIN)",
                 http("GET /solar/eligibility", "GET", "/solar/eligibility", params=[("nin", "${nin}")],
                      checks=[("$.nin", "${nin}"), ("$.eligible", "true|false", True)],
                      extract=[("eligible", "$.eligible", "1", "false")])),
            if_ctrl("If eligible", '${__jexl3("${eligible}" == "true")}', [
                step("SOLAR 04 Submit Subsidy Application",
                     http("POST /solar/applications", "POST", "/solar/applications", codes=("201",),
                          body='{"nin":"${nin}","packageId":"${packageId}","district":"${district}",'
                               '"village":"${village}","householdSize":${householdSize},'
                               '"monthlyIncome":${monthlyIncome},"roofType":"${roofType}",'
                               '"idempotencyKey":"${__UUID()}"}',
                          checks=["$.applicationId", "$.referenceNo", ("$.status", "SUBMITTED")],
                          extract=[("applicationId", "$.applicationId")])),
                step("SOLAR 05 Track Application Status",
                     http("GET /solar/applications/{id}", "GET", "/solar/applications/${applicationId}",
                          checks=[("$.applicationId", "${applicationId}"),
                                  ("$.status", "SUBMITTED|UNDER_REVIEW|APPROVED|REJECTED", True)])),
            ]),
        ]),
    ]


def health():
    return [
        step("HEALTH 01 Search Facilities",
             http("GET /health/facilities", "GET", "/health/facilities",
                  params=[("district", "${searchDistrict}"), ("specialty", "${specialty}")],
                  checks=["$.facilities[0].id", "$.facilities[0].name", ("$.district", "${searchDistrict}")],
                  extract=[("facilityId", "$.facilities[*].id", "0")])),
        step("HEALTH 02 View Facility Details",
             http("GET /health/facilities/{id}", "GET", "/health/facilities/${facilityId}",
                  checks=[("$.id", "${facilityId}"), "$.services[0]"])),
        step("HEALTH 03 View Available Slots",
             http("GET /health/facilities/{id}/slots", "GET", "/health/facilities/${facilityId}/slots",
                  params=[("date", "${__timeShift(yyyy-MM-dd,,P${__Random(1,14)}D,,apptDate)}")],
                  checks=["$.slots[0].slotId", ("$.date", "${apptDate}")],
                  extract=[("slotId", "$.slots[*].slotId", "0")])),
        pct("Patients who book", 55, [
            step("HEALTH 04 Book Appointment",
                 http("POST /health/appointments", "POST", "/health/appointments", codes=("201",),
                      body='{"facilityId":"${facilityId}","slotId":"${slotId}","patientNin":"${nin}",'
                           '"reason":"${visitReason}","idempotencyKey":"${__UUID()}"}',
                      checks=["$.appointmentId", "$.ticketNo", ("$.status", "CONFIRMED")]))]),
        pct("Patients who review bookings", 30, [
            step("HEALTH 05 View My Appointments",
                 http("GET /health/appointments", "GET", "/health/appointments", checks=["$.appointments"]))]),
    ]


def uneb():
    return [
        step("UNEB 01 List Examinations",
             http("GET /uneb/exams", "GET", "/uneb/exams", checks=["$.exams[0].code"])),
        step("UNEB 02 Check Results",
             http("GET /uneb/results", "GET", "/uneb/results",
                  params=[("indexNumber", "${indexNumber}"), ("year", "${examYear}"), ("level", "${examLevel}")],
                  checks=[("$.indexNumber", "${indexNumber}"), ("$.level", "${examLevel}"),
                          "$.candidateName", "$.subjects[0].grade", "$.division"])),
        pct("Candidates who order a certified slip", 15, [
            step("UNEB 03 Request Certified Result Slip",
                 http("POST /uneb/result-slips", "POST", "/uneb/result-slips", codes=("201",),
                      body='{"indexNumber":"${indexNumber}","year":${examYear},"level":"${examLevel}",'
                           '"deliveryMsisdn":"${phone}","idempotencyKey":"${__UUID()}"}',
                      checks=["$.requestId", ("$.status", "QUEUED"), ("$.indexNumber", "${indexNumber}")]))]),
    ]


def bills():
    return [
        step("BILLS 01 List Providers (UMEME / NWSC)",
             http("GET /bills/providers", "GET", "/bills/providers", checks=["$.providers[0].code"])),
        step("BILLS 02 Validate Account & Get Balance",
             http("POST /bills/accounts/validate", "POST", "/bills/accounts/validate",
                  body='{"provider":"${provider}","accountNumber":"${accountNumber}"}', sla="read",
                  checks=[("$.valid", "true"), "$.accountName", "$.outstandingBalance",
                          ("$.accountNumber", "${accountNumber}")])),
        pct("Customers who pay", 70, [
            step("BILLS 03 Submit Mobile Money Payment",
                 http("POST /bills/payments", "POST", "/bills/payments", codes=("202",),
                      body='{"provider":"${provider}","accountNumber":"${accountNumber}","amount":${amount},'
                           '"msisdn":"${msisdn}","channel":"${channel}","idempotencyKey":"${__UUID()}"}',
                      checks=["$.paymentId", ("$.status", "PENDING")],
                      extract=[("paymentId", "$.paymentId")])),
            step("BILLS 04 Confirm Payment Status",
                 http("GET /bills/payments/{id}", "GET", "/bills/payments/${paymentId}",
                      extra=[const_timer("Wait for mobile-money prompt (2 s)", "${__P(payment_poll_ms,2000)}")],
                      checks=[("$.paymentId", "${paymentId}"), ("$.status", "SUCCESS|PENDING|FAILED", True)]))]),
        pct("Customers who view history", 30, [
            step("BILLS 05 View Payment History",
                 http("GET /bills/payments", "GET", "/bills/payments", params=[("page", "1")], checks=["$.payments"]))]),
    ]


def kcca():
    return [
        step("KCCA 01 Load Issue Categories",
             http("GET /issues/categories", "GET", "/issues/categories", checks=["$.categories[0].id"],
                  extract=[("categoryId", "$.categories[*].id", "0")])),
        step("KCCA 02 Browse Nearby Issues (Map)",
             http("GET /issues/nearby", "GET", "/issues/nearby",
                  params=[("lat", "${lat}"), ("lng", "${lng}"), ("radiusKm", "2")],
                  checks=["$.issues[0].id", "$.issues[0].status"],
                  extract=[("issueId", "$.issues[*].id", "0")])),
        pct("Citizens who open an issue", 60, [
            step("KCCA 03 View Issue Details",
                 http("GET /issues/{id}", "GET", "/issues/${issueId}", checks=[("$.id", "${issueId}"), "$.status"]))]),
        pct("Citizens who report", 45, [
            step("KCCA 04 Report New Issue",
                 http("POST /issues", "POST", "/issues", codes=("201",),
                      body='{"categoryId":"${categoryId}","title":"${issueTitle}",'
                           '"description":"Load-test report ${__RandomString(40,abcdefghijklmnopqrstuvwxyz )}",'
                           '"lat":${lat},"lng":${lng},"division":"${division}","idempotencyKey":"${__UUID()}"}',
                      checks=["$.issueId", "$.trackingNo", ("$.status", "OPEN")]))]),
    ]


PERSONAS = [
    # key, display name, default mix %, csvs, module steps, search term
    ("solar", "Rural Household - REA Solar Subsidy Applicant", 15,
     [("solar_households.csv", "village,householdSize,monthlyIncome,roofType")], solar, "solar"),
    ("health", "Patient - Ministry of Health Appointment", 20,
     [("health_searches.csv", "searchDistrict,specialty,visitReason")], health, "hospital"),
    ("uneb", "Student or Parent - UNEB Results", 30,
     [("uneb_candidates.csv", "indexNumber,examYear,examLevel")], uneb, "results"),
    ("bills", "Utility Customer - UMEME and NWSC Bill Payment", 25,
     [("utility_accounts.csv", "provider,accountNumber,msisdn,channel,amount")], bills, "pay bill"),
    ("kcca", "Kampala Resident - KCCA Issue Reporting", 10,
     [("kcca_reports.csv", "division,lat,lng,issueTitle")], kcca, "report"),
]


def thread_group(key, title, mix, csvs, module, term):
    threads = ("${__groovy(Math.max(1\\, Math.round(${__P(total_users,100)} * ${__P(mix_" + key + "," + str(mix)
               + ")} / 100.0)) as int)}")
    props = (sp("ThreadGroup.on_sample_error", "continue")
             + '<elementProp name="ThreadGroup.main_controller" elementType="LoopController" guiclass="LoopControlPanel" '
               'testclass="LoopController" testname="Loop Controller">' + bp("LoopController.continue_forever", False)
             + sp("LoopController.loops", "-1") + "</elementProp>"
             + sp("ThreadGroup.num_threads", threads) + sp("ThreadGroup.ramp_time", "${__P(rampup,120)}")
             + bp("ThreadGroup.scheduler", True)
             + sp("ThreadGroup.duration", "${__groovy(${__P(rampup,120)} + ${__P(steady,600)})}")
             + sp("ThreadGroup.delay", "0") + bp("ThreadGroup.same_user_on_next_iteration", False)
             + comment(f"Persona share of total_users: {mix}% (override with -Jmix_{key}=N). "
                       "Ramp-up = rampup seconds, then steady state for steady seconds."))
    kids = [csv_ds(f"Users - {key} (one login per virtual user)", f"users_{key}.csv", "phone,password,nin,district,persona")]
    kids += [csv_ds(f"Data - {f}", f, v) for f, v in csvs]
    kids += [header_mgr("Persona tag (for server-side log filtering)", [("X-Test-Persona", "${persona}")]),
             cookie_mgr(), cache_mgr(), think_timer()]
    kids += login_logout(key, module(), term)
    return N("ThreadGroup", "ThreadGroupGui", "ThreadGroup", f"P{PERSONAS.index(next(p for p in PERSONAS if p[0]==key))+1} - {title}",
             props, kids)


def setup_group():
    props = (sp("ThreadGroup.on_sample_error", "stoptest")
             + '<elementProp name="ThreadGroup.main_controller" elementType="LoopController" guiclass="LoopControlPanel" '
               'testclass="LoopController" testname="Loop Controller">' + bp("LoopController.continue_forever", False)
             + sp("LoopController.loops", "1") + "</elementProp>"
             + sp("ThreadGroup.num_threads", "1") + sp("ThreadGroup.ramp_time", "1") + bp("ThreadGroup.scheduler", False)
             + sp("ThreadGroup.duration", "") + sp("ThreadGroup.delay", ""))
    return N("SetupThreadGroup", "SetupThreadGroupGui", "SetupThreadGroup",
             "setUp - Pre-flight health check (aborts the test if the API is down)", props,
             [http("GET /status", "GET", "/status", checks=[("$.status", "UP")])])


def listeners():
    def rc(gui, name, enabled=False, errors_only=False):
        return N("ResultCollector", gui, "ResultCollector", name,
                 bp("ResultCollector.error_logging", errors_only) + sp("filename", ""), enabled=enabled)
    return [
        rc("SummaryReport", "Summary Report - throughput, avg, error % (GUI debug only)"),
        rc("StatVisualizer", "Aggregate Report - avg, p90/p95/p99, throughput (GUI debug only)"),
        rc("ViewResultsFullVisualizer", "View Results Tree - failures only (GUI debug only)", errors_only=True),
        prometheus_listener(),
    ]


def prometheus_listener():
    """
    Prometheus Listener (johrstrom/jmeter-prometheus-plugin 0.7.1, in lib/ext - the Docker image has it).
    Exposes live metrics on http://<jmeter-host>:9270/metrics for Prometheus to scrape.
    Histograms (not summaries) are used for percentiles so p95/p99 can be aggregated
    across many load generators with histogram_quantile().
    """
    def coll(name, help_, ctype, measuring, labels, buckets=""):
        lbl = "".join(f'<stringProp name="{jhash(l)}">{l}</stringProp>' for l in labels)
        return ('<elementProp name="" elementType="com.github.johrstrom.listener.ListenerCollectorConfig">'
                + sp("collector.help", help_) + sp("collector.metric_name", name) + sp("collector.type", ctype)
                + (f'<collectionProp name="collector.labels">{lbl}</collectionProp>' if labels
                   else '<collectionProp name="collector.labels"/>')
                + sp("collector.quantiles_or_buckets", buckets) + sp("listener.collector.listen_to", "samples")
                + sp("listener.collector.measuring", measuring) + "</elementProp>")
    rt_buckets = "100,250,500,750,1000,1500,2000,3000,5000,10000"
    defs = "".join([
        coll("uc_response_time_ms", "Response time per operation (ms)", "HISTOGRAM", "ResponseTime",
             ["label", "persona"], rt_buckets),
        coll("uc_latency_ms", "Time to first byte per operation (ms)", "HISTOGRAM", "Latency", ["label"], rt_buckets),
        coll("uc_connect_time_ms", "TCP/TLS connect time (ms)", "HISTOGRAM", "ConnectTime", ["persona"],
             "10,50,100,250,500,1000,3000"),
        coll("uc_requests_total", "Requests per operation and HTTP status", "COUNTER", "CountTotal",
             ["label", "code", "persona"]),
        coll("uc_failures_total", "Failed requests (bad status, assertion or SLA breach)", "COUNTER", "FailureTotal",
             ["label", "persona"]),
        coll("uc_success_ratio", "Success ratio per operation", "SUCCESS_RATIO", "SuccessRatio", ["label"]),
        coll("uc_response_size_bytes", "Response size per operation", "HISTOGRAM", "ResponseSize", ["label"],
             "500,2000,10000,50000,200000"),
    ])
    return N("com.github.johrstrom.listener.PrometheusListener", "com.github.johrstrom.listener.gui.PrometheusListenerGui",
             "com.github.johrstrom.listener.PrometheusListener",
             "Live metrics -> Prometheus :9270/metrics (needs jmeter-prometheus-plugin)",
             f'<collectionProp name="prometheus.collector_definitions">{defs}</collectionProp>')


def build():
    plan_comment = (
        "UgandaConnect backend load test. Five citizen personas (REA solar, MoH health, UNEB, UMEME/NWSC bills, "
        "KCCA issues) log in, navigate, search, view, submit and log out. Run in CLI mode:\n"
        "jmeter -n -t UgandaConnect_LoadTest.jmx -q user.properties -Jhost=api.example.ug -Jtotal_users=1000 "
        "-Jrampup=300 -Jsteady=1800 -l results/results.jtl -e -o results/report\n"
        "See README.md for the workload model, SLAs and distributed (500k user) execution.")
    tp_props = (comment(plan_comment) + bp("TestPlan.functional_mode", False) + bp("TestPlan.tearDown_on_shutdown", True)
                + bp("TestPlan.serialize_threadgroups", False)
                + '<elementProp name="TestPlan.user_defined_variables" elementType="Arguments" guiclass="ArgumentsPanel" '
                  'testclass="Arguments" testname="User Defined Variables">'
                + args_xml([("PROTOCOL", "${__P(protocol,http)}"), ("HOST", "${__P(host,localhost)}"),
                            ("PORT", "${__P(port,8080)}"), ("BASE_PATH", "${__P(base_path,/api/v1)}")])
                + "</elementProp>")
    defaults = N("ConfigTestElement", "HttpDefaultsGui", "ConfigTestElement", "HTTP Request Defaults (target environment)",
                 '<elementProp name="HTTPsampler.Arguments" elementType="Arguments" guiclass="HTTPArgumentsPanel" '
                 'testclass="Arguments" testname="User Defined Variables"><collectionProp name="Arguments.arguments"/></elementProp>'
                 + sp("HTTPSampler.domain", "${HOST}") + sp("HTTPSampler.port", "${PORT}")
                 + sp("HTTPSampler.protocol", "${PROTOCOL}") + sp("HTTPSampler.contentEncoding", "UTF-8")
                 + sp("HTTPSampler.path", "") + sp("HTTPSampler.implementation", "HttpClient4")
                 + sp("HTTPSampler.connect_timeout", "${__P(connect_timeout_ms,5000)}")
                 + sp("HTTPSampler.response_timeout", "${__P(response_timeout_ms,30000)}"))
    headers = header_mgr("Global Headers (mobile client)", [
        ("Content-Type", "application/json"), ("Accept", "application/json"), ("Accept-Encoding", "gzip, deflate"),
        ("User-Agent", "UgandaConnect-Android/1.0 (JMeter load test)"), ("X-App-Version", "1.0"),
        ("X-Request-ID", "${__UUID()}"), ("Cache-Control", "no-cache")])
    ctype = N("ResponseAssertion", "AssertionGui", "ResponseAssertion", "Global: response is JSON (Content-Type)",
              f'<collectionProp name="Asserion.test_strings"><stringProp name="1">(?i)content-type:\\s*application/json</stringProp></collectionProp>'
              + sp("Assertion.custom_message", "Response Content-Type is not application/json")
              + sp("Assertion.test_field", "Assertion.response_headers") + bp("Assertion.assume_success", False)
              + ip("Assertion.test_type", 2))
    children = [defaults, headers, ctype, setup_group()] + [thread_group(*p) for p in PERSONAS] + listeners()
    root = N("TestPlan", "TestPlanGui", "TestPlan", "UgandaConnect - National Launch Load Test", tp_props, children)
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<jmeterTestPlan version="1.2" properties="5.0" jmeter="5.6.3">\n'
           "  <hashTree>\n" + root.render(2) + "  </hashTree>\n</jmeterTestPlan>\n")
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(xml)
    print("wrote", OUT, len(xml), "bytes")


if __name__ == "__main__":
    build()

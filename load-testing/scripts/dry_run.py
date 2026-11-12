#!/usr/bin/env python3
"""
Contract check without JMeter: interprets UgandaConnect_LoadTest.jmx (the subset of JMeter
semantics the plan uses: variables, functions, CSV data, extractors, If/Throughput/Transaction
controllers, header scoping, status/JSON/Content-Type assertions) and runs one session per
persona against a server. Use it against the mock or a staging API to prove every request and
assertion is correct before spending money on a full load run.

    python3 scripts/dry_run.py UgandaConnect_LoadTest.jmx data http://localhost:8080 [iterations]
"""
import csv, datetime, json, random, re, string, sys, uuid, urllib.request, urllib.parse, urllib.error
import xml.etree.ElementTree as ET

JMX, DATA, BASEURL = sys.argv[1], sys.argv[2], sys.argv[3]  # e.g. http://localhost:8080
ITER = int(sys.argv[4]) if len(sys.argv) > 4 else 3
FORCE_ALL = True  # run every throughput-controller branch

def props(el):
    d = {}
    for c in el:
        if c.tag in ("stringProp", "boolProp", "intProp"):
            d[c.get("name")] = c.text or ""
    return d

def split_args(s):
    out, cur, i = [], "", 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s) and s[i+1] == ",":
            cur += ","; i += 2; continue
        if s[i] == ",":
            out.append(cur); cur = ""
        else:
            cur += s[i]
        i += 1
    out.append(cur); return out

def jfmt(fmt): return fmt.replace("yyyy", "%Y").replace("MM", "%m").replace("dd", "%d")

def call(fn, a, vars_):
    if fn == "__UUID": return str(uuid.uuid4())
    if fn == "__P": return a[1] if len(a) > 1 else ""
    if fn == "__Random": return str(random.randint(int(a[0]), int(a[1])))
    if fn == "__RandomString": return "".join(random.choice(a[1] if len(a) > 1 and a[1] else string.ascii_letters) for _ in range(int(a[0])))
    if fn == "__timeShift":
        days = int(re.fullmatch(r"P(\d+)D", a[2]).group(1)) if a[2] else 0
        v = (datetime.date.today() + datetime.timedelta(days=days)).strftime(jfmt(a[0]))
        if len(a) > 4 and a[4]: vars_[a[4]] = v
        return v
    if fn == "__jexl3":
        expr = a[0].replace("&&", " and ").replace("||", " or ")
        return "true" if eval(expr, {"__builtins__": {}}) else "false"
    if fn == "__groovy":
        return str(eval(a[0].replace("Math.max", "max").replace("Math.round", "round").replace(" as int", ""), {"__builtins__": {"max": max, "round": round}}))
    raise ValueError("unsupported function " + fn)

def sub(s, vars_):
    pat = re.compile(r"\$\{([^${}]*)\}")
    for _ in range(20):
        m = pat.search(s)
        if not m: return s
        inner = m.group(1)
        if inner.startswith("__"):
            fm = re.fullmatch(r"(__\w+)(?:\((.*)\))?", inner, re.S)
            val = call(fm.group(1), split_args(fm.group(2) or ""), vars_)
        else:
            val = vars_.get(inner, "${%s}" % inner)
            if val == "${%s}" % inner:  # unresolved: JMeter leaves it literally
                s = s[:m.start()] + "\x00{" + inner + "}" + s[m.end():]; continue
        s = s[:m.start()] + val + s[m.end():]
    return s.replace("\x00{", "${")

def jpath(doc, path):
    toks = re.findall(r"\.(\w+)|\[(\d+|\*)\]", path[1:])
    cur, multi = [doc], False
    for key, idx in toks:
        nxt = []
        for c in cur:
            if key:
                if isinstance(c, dict) and key in c: nxt.append(c[key])
            elif idx == "*":
                multi = True
                if isinstance(c, list): nxt.extend(c)
            else:
                if isinstance(c, list) and int(idx) < len(c): nxt.append(c[int(idx)])
        cur = nxt
    return cur, multi

def tostr(v):
    if isinstance(v, bool): return "true" if v else "false"
    if isinstance(v, (dict, list)): return json.dumps(v)
    return str(v)

class Runner:
    def __init__(self):
        self.stats, self.fail = {}, []

    def http(self, el, vars_, headers, inherited):
        p = props(el)
        method = p["HTTPSampler.method"]; path = sub(p["HTTPSampler.path"], vars_)
        body = None; q = []
        argsel = el.find("elementProp[@name='HTTPsampler.Arguments']")
        for a in argsel.iter("elementProp"):
            ap = props(a)
            if a.get("elementType") != "HTTPArgument": continue
            if p.get("HTTPSampler.postBodyRaw") == "true":
                body = sub(ap["Argument.value"], vars_)
            else:
                q.append((ap["Argument.name"], sub(ap["Argument.value"], vars_)))
        url = BASEURL + path + ("?" + urllib.parse.urlencode(q) if q else "")
        hdrs = {k: sub(v, vars_) for k, v in headers}
        if body is not None:
            json.loads(body)  # the plan must send valid JSON
        req = urllib.request.Request(url, data=body.encode() if body is not None else None, method=method, headers=hdrs)
        try:
            r = urllib.request.urlopen(req, timeout=10); code, raw, rh = r.status, r.read(), r.headers
        except urllib.error.HTTPError as e:
            code, raw, rh = e.code, e.read(), e.headers
        hdr_text = "".join(f"{k}: {v}\n" for k, v in rh.items())
        try: doc = json.loads(raw)
        except Exception: doc = None
        errs = []
        kids = list(el.find("..") if False else [])
        return code, doc, hdr_text, errs, raw

    def assertions(self, nodes, code, doc, hdr_text, vars_):
        errs = []
        for a, _ in nodes:
            p = props(a)
            if a.tag == "ResponseAssertion":
                tests = [s.text for s in a.find("collectionProp")]
                field = p["Assertion.test_field"]; tt = int(p["Assertion.test_type"])
                target = str(code) if field == "Assertion.response_code" else hdr_text
                if tt & 8: ok = (any if tt & 32 else all)(target == t for t in tests)
                else: ok = all(re.search(t, target) for t in tests)
                if not ok: errs.append(f"{a.get('testname')} (got {code})")
            elif a.tag == "JSONPathAssertion":
                vals, multi = jpath(doc, p["JSON_PATH"]) if doc is not None else ([], False)
                if not vals: errs.append(f"{p['JSON_PATH']} missing"); continue
                if p["JSONVALIDATION"] == "true":
                    exp = sub(p["EXPECTED_VALUE"], vars_); got = tostr(vals[0])
                    ok = re.fullmatch(exp, got) if p["ISREGEX"] == "true" else got == exp
                    if not ok: errs.append(f"{p['JSON_PATH']}: expected {exp!r} got {got!r}")
        return errs

    def walk(self, el_children, vars_, headers, scoped_assertions, txn):
        # el_children: list of (element, hashTree) pairs at one level
        local_headers = list(headers); local_asserts = list(scoped_assertions)
        for e, ht in el_children:
            if not e.get("enabled", "true") == "true": continue
            if e.tag == "HeaderManager":
                for h in e.iter("elementProp"):
                    hp = props(h); local_headers = [x for x in local_headers if x[0] != hp["Header.name"]] + [(hp["Header.name"], hp["Header.value"])]
            if e.tag in ("ResponseAssertion", "JSONPathAssertion"):
                local_asserts.append((e, ht))
        for e, ht in el_children:
            if not e.get("enabled", "true") == "true": continue
            kids = pairs(ht)
            if e.tag == "HTTPSamplerProxy":
                code, doc, hdr_text, _, raw = self.http(e, vars_, local_headers, None)
                own = [(k, h) for k, h in kids if k.tag in ("ResponseAssertion", "JSONPathAssertion")]
                errs = self.assertions(local_asserts + own, code, doc, hdr_text, vars_)
                for k, _ in kids:
                    if k.tag == "JSONPostProcessor":
                        kp = props(k); vals, _m = jpath(doc, kp["JSONPostProcessor.jsonPathExprs"]) if doc is not None else ([], 0)
                        m = kp["JSONPostProcessor.match_numbers"]
                        name = kp["JSONPostProcessor.referenceNames"]
                        if vals: vars_[name] = tostr(random.choice(vals) if m == "0" else vals[int(m) - 1])
                        else: vars_[name] = kp["JSONPostProcessor.defaultValues"]
                key = txn or e.get("testname")
                s = self.stats.setdefault(key, [0, 0]); s[0] += 1
                if errs:
                    s[1] += 1; self.fail.append((key, e.get("testname"), errs, raw[:200]))
            elif e.tag == "IfController":
                cond = sub(props(e)["IfController.condition"], vars_)
                if cond == "true": self.walk(kids, vars_, local_headers, local_asserts, txn)
            elif e.tag == "TransactionController":
                self.walk(kids, vars_, local_headers, local_asserts, e.get("testname"))
            elif e.tag in ("GenericController", "ThroughputController"):
                if e.tag == "ThroughputController" and not FORCE_ALL:
                    if random.random() * 100 > float(props(e)["ThroughputController.percentThroughput"]): continue
                self.walk(kids, vars_, local_headers, local_asserts, txn)

def pairs(ht):
    if ht is None: return []
    c = list(ht); return [(c[i], c[i+1]) for i in range(0, len(c), 2)]

def main():
    root = ET.parse(JMX).getroot()
    tp, tpht = pairs(root.find("hashTree"))[0]
    top = pairs(tpht)
    base_vars = {}
    for a in tp.iter("elementProp"):
        ap = props(a)
        if a.get("elementType") == "Argument": base_vars[ap["Argument.name"]] = sub(ap["Argument.value"], {})
    r = Runner()
    globals_ = [(e, h) for e, h in top if e.tag in ("HeaderManager", "ResponseAssertion")]
    for e, ht in top:
        if e.tag not in ("ThreadGroup", "SetupThreadGroup"): continue
        tgp = props(e)
        print(f"== {e.get('testname')}  threads={sub(tgp['ThreadGroup.num_threads'], {})}")
        csvs = [(e2, props(e2)) for e2, _ in pairs(ht) if e2.tag == "CSVDataSet"]
        rows = {}
        for c, cp in csvs:
            fn = cp["filename"].replace("${__P(data_dir,data)}", DATA)
            with open(fn) as f: rows[fn] = (cp["variableNames"].split(","), list(csv.reader(f))[1:])
        for it in range(ITER if e.tag == "ThreadGroup" else 1):
            vars_ = dict(base_vars)
            for names, data in rows.values(): vars_.update(zip(names, random.choice(data)))
            r.walk(globals_ + pairs(ht), vars_, [], [], None)
    print("\n%-52s %6s %6s" % ("Transaction", "runs", "fails"))
    for k, (n, f) in r.stats.items(): print("%-52s %6d %6d" % (k, n, f))
    for f in r.fail[:15]: print("FAIL", f)
    print("\nTOTAL failures:", len(r.fail))
    sys.exit(1 if r.fail else 0)

main()

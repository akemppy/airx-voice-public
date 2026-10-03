"""jevcall.py - AirX Voice calls Jev (TypeSafe System One) directly, with the key from its settings.

One try, a short timeout, no cache. Each call is logged (time, tokens, errors, never the key) to jev.jsonl.
"""
import json
import os
import time
import urllib.error
import urllib.request

API = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"


def fallback_key():
    """TYPESAFE_API_KEY from the environment, when Settings has no key."""
    return os.environ.get("TYPESAFE_API_KEY", "").strip()


def decide(state, questions, key, timeout=3.0, log=None):
    """{question: answer} or None (no key, network, HTTP error, timeout). Never raises."""
    if not key:
        return None
    body = json.dumps({"model": MODEL, "state": state, "questions": questions}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(API, data=body, headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    t0 = time.time()
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "n_q": len(questions)}
    try:
        resp = json.load(urllib.request.urlopen(req, timeout=timeout))
        usage = resp.get("usage") or {}
        rec.update(ms=int((time.time() - t0) * 1000), tokens_in=usage.get("input_tokens"))
        return resp.get("answers") or {}
    except urllib.error.HTTPError as e:
        rec.update(err="HTTP %s" % e.code, ms=int((time.time() - t0) * 1000))
        return None
    except Exception as e:                                      # timeout, DNS, connection reset
        rec.update(err="%s: %s" % (type(e).__name__, e), ms=int((time.time() - t0) * 1000))
        return None
    finally:
        if log:
            try:
                os.makedirs(os.path.dirname(log), exist_ok=True)
                with open(log, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec) + "\n")
            except OSError:
                pass

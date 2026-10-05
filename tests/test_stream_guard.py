"""The model reply is streamed so a decoding loop is stopped early (not after the
whole step timeout), and classify() re-asks once with feedback and a little
temperature — with temperature 0 a plain re-run would loop the same way again."""

from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

import classify_api  # noqa: E402

PACKET = ROOT / "data" / "nur" / "al_saadi" / "packets" / "24_35.json"


def _span_id() -> str:
    return sorted(classify_api.packet_span_ids(classify_api.load_packet(PACKET)))[0]


def _reply(sid: str) -> str:
    return json.dumps({"window": "24_35", "moves": [{
        "move_id": "m01", "span_ids": [sid], "primary": "M_LUGHA", "secondary": [],
        "content_tags": [], "certainty": "weak", "evidence_span_ids": [sid],
        "author_verdict_span_ids": [], "references": {"verses": [], "hadith": [], "persons": []},
        "alternatives": [], "rationale_ar": "اختبار"}]}, ensure_ascii=False)


class _Server:
    """A tiny OpenAI-compatible server; ``script`` decides each request's reply."""

    def __init__(self, script):
        self.requests: list[dict] = []
        self.disconnected = threading.Event()
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _sse(self, pieces, usage=None, forever=None):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                try:
                    for p in pieces:
                        self._event({"choices": [{"delta": {"content": p}, "finish_reason": None}]})
                    if forever is not None:
                        for _ in range(20000):
                            self._event({"choices": [{"delta": {"content": forever}}]})
                            time.sleep(0.0005)
                    self._event({"choices": [{"delta": {}, "finish_reason": "stop"}]})
                    if usage:
                        self._event({"choices": [], "usage": usage})
                    self.wfile.write(b"data: [DONE]\n\n")
                except (BrokenPipeError, ConnectionResetError):
                    outer.disconnected.set()

            def _event(self, obj):
                self.wfile.write(b"data: " + json.dumps(obj, ensure_ascii=False).encode() + b"\n\n")
                self.wfile.flush()

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append(body)
                script(self, body, len(outer.requests))

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"

    def close(self):
        self.httpd.shutdown()


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("LLM_TIMEOUT_S", "30")
    monkeypatch.delenv("LLM_STREAM", raising=False)
    classify_api.reset_usage()


def test_repeating_tail_only_fires_on_loops():
    sid_list = ", ".join(f'"s{i:03d}"' for i in range(1, 400))
    assert classify_api.repeating_tail('{"moves": [{"span_ids": [' + sid_list + "]}]}") is None
    assert classify_api.repeating_tail('{"span_ids": [' + '"s042", ' * 200) == 8
    assert classify_api.repeating_tail('{"a": 1}' + "\n" * 900) == 1
    assert classify_api.repeating_tail("short") is None
    loop = "وقال ابن عباس: هو كذا. " * 60
    assert classify_api.repeating_tail('{"rationale_ar": "' + loop) is not None


def test_stream_returns_content_and_usage():
    sid = _span_id()
    srv = _Server(lambda h, body, n: h._sse([_reply(sid)[:40], _reply(sid)[40:]],
                                            usage={"prompt_tokens": 900, "completion_tokens": 77}))
    try:
        out = classify_api.call_chat(base_url=srv.url, api_key="x", model="m",
                                     messages=[{"role": "user", "content": "hi"}])
        assert json.loads(out)["moves"][0]["span_ids"] == [sid]
        assert srv.requests[0]["stream"] is True and srv.requests[0]["temperature"] == 0
        assert classify_api.usage_line() == ("usage: calls=1 prompt_tokens=900 completion_tokens=77"
                                             " max_prompt=900")
    finally:
        srv.close()


def test_loop_is_stopped_early_and_the_connection_closed():
    srv = _Server(lambda h, body, n: h._sse(['{"window": "24_35", "moves": [{"span_ids": ['],
                                            forever='"s042", '))
    try:
        t0 = time.monotonic()
        with pytest.raises(classify_api.RepetitionError) as e:
            classify_api.call_chat(base_url=srv.url, api_key="x", model="m",
                                   messages=[{"role": "user", "content": "hi"}])
        assert time.monotonic() - t0 < 10
        assert "repeating itself" in str(e.value) and '"s042"' in str(e.value)
        assert srv.disconnected.wait(5)  # the model server stops generating
    finally:
        srv.close()


def test_whitespace_after_a_complete_object_is_accepted():
    sid = _span_id()
    srv = _Server(lambda h, body, n: h._sse([_reply(sid)], forever="\n"))
    try:
        out = classify_api.call_chat(base_url=srv.url, api_key="x", model="m",
                                     messages=[{"role": "user", "content": "hi"}])
        assert json.loads(out)["moves"][0]["move_id"] == "m01"
    finally:
        srv.close()


def test_plain_json_reply_still_works_and_streaming_can_be_switched_off(monkeypatch):
    sid = _span_id()

    def plain(h, body, n):
        data = json.dumps({"choices": [{"message": {"content": _reply(sid)}}],
                           "usage": {"prompt_tokens": 5, "completion_tokens": 6}}).encode()
        h.send_response(200)
        h.send_header("Content-Type", "application/json")
        h.send_header("Content-Length", str(len(data)))
        h.end_headers()
        h.wfile.write(data)

    srv = _Server(plain)
    try:
        for stream in ("1", "0"):
            monkeypatch.setenv("LLM_STREAM", stream)
            out = classify_api.call_chat(base_url=srv.url, api_key="x", model="m",
                                         messages=[{"role": "user", "content": "hi"}])
            assert json.loads(out)["window"] == "24_35"
        assert "stream" in srv.requests[0] and "stream" not in srv.requests[1]
    finally:
        srv.close()


def test_classify_reasks_once_with_feedback_and_temperature(tmp_path):
    sid = _span_id()

    def script(h, body, n):
        if n == 1:
            h._sse(['{"window": "24_35", "moves": [{"rationale_ar": "'], forever="هو كذا. ")
        else:
            h._sse([_reply(sid)], usage={"prompt_tokens": 1000, "completion_tokens": 60})

    srv = _Server(script)
    try:
        res = classify_api.classify(PACKET, "qwen2.5:14b", srv.url, tmp_path, api_key="x")
        assert res["payload"]["moves"][0]["span_ids"] == [sid]
        assert len(srv.requests) == 2
        assert srv.requests[0]["temperature"] == 0 and srv.requests[1]["temperature"] == 0.3
        assert "repeating itself" in srv.requests[1]["messages"][-1]["content"]
    finally:
        srv.close()


def test_classify_fails_fast_when_both_attempts_loop(tmp_path):
    srv = _Server(lambda h, body, n: h._sse(['{"moves": ['], forever='{"x": 1}, '))
    try:
        t0 = time.monotonic()
        with pytest.raises(classify_api.ClassifyError) as e:
            classify_api.classify(PACKET, "qwen2.5:14b", srv.url, tmp_path, api_key="x")
        assert time.monotonic() - t0 < 20
        assert e.value.record["reason_code"] == "MODEL_OUTPUT_INVALID"
        assert "both attempts" in str(e.value)
    finally:
        srv.close()

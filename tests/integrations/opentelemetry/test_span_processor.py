from datetime import datetime
from mock import MagicMock
import mock
import time
from sentry_sdk.integrations.opentelemetry.span_processor import SentrySpanProcessor
from sentry_sdk.tracing import Span


def test_get_otel_context():
    otel_span = MagicMock()
    otel_span.attributes = {"foo": "bar"}
    otel_span.resource = MagicMock()
    otel_span.resource.attributes = {"baz": "qux"}

    span_processor = SentrySpanProcessor()
    otel_context = span_processor._get_otel_context(otel_span)

    assert otel_context == {
        "attributes": {"foo": "bar"},
        "resource": {"baz": "qux"},
    }


def test_get_trace_data_with_span_and_trace():
    otel_span = MagicMock()
    otel_span.context = MagicMock()
    otel_span.context.trace_id = int("1234567890abcdef1234567890abcdef", 16)
    otel_span.context.span_id = int("1234567890abcdef", 16)
    otel_span.parent = None

    parent_context = {}

    span_processor = SentrySpanProcessor()
    sentry_trace_data = span_processor._get_trace_data(otel_span, parent_context)
    assert sentry_trace_data["trace_id"] == "1234567890abcdef1234567890abcdef"
    assert sentry_trace_data["span_id"] == "1234567890abcdef"
    assert sentry_trace_data["parent_span_id"] is None
    assert sentry_trace_data["parent_sampled"] is None
    assert sentry_trace_data["baggage"] is None


def test_get_trace_data_with_span_and_trace_and_parent():
    otel_span = MagicMock()
    otel_span.context = MagicMock()
    otel_span.context.trace_id = int("1234567890abcdef1234567890abcdef", 16)
    otel_span.context.span_id = int("1234567890abcdef", 16)
    otel_span.parent = MagicMock()
    otel_span.parent.span_id = int("abcdef1234567890", 16)

    parent_context = {}

    span_processor = SentrySpanProcessor()
    sentry_trace_data = span_processor._get_trace_data(otel_span, parent_context)
    assert sentry_trace_data["trace_id"] == "1234567890abcdef1234567890abcdef"
    assert sentry_trace_data["span_id"] == "1234567890abcdef"
    assert sentry_trace_data["parent_span_id"] == "abcdef1234567890"
    assert sentry_trace_data["parent_sampled"] is None
    assert sentry_trace_data["baggage"] is None


def test_get_trace_data_with_sentry_trace():
    otel_span = MagicMock()
    otel_span.context = MagicMock()
    otel_span.context.trace_id = int("1234567890abcdef1234567890abcdef", 16)
    otel_span.context.span_id = int("1234567890abcdef", 16)
    otel_span.parent = MagicMock()
    otel_span.parent.span_id = int("abcdef1234567890", 16)

    parent_context = {}

    with mock.patch(
        "sentry_sdk.integrations.opentelemetry.span_processor.get_value",
        side_effect=[
            ("1234567890abcdef1234567890abcdef", "1234567890abcdef", True),
            None,
        ],
    ):
        span_processor = SentrySpanProcessor()
        sentry_trace_data = span_processor._get_trace_data(otel_span, parent_context)
        assert sentry_trace_data["trace_id"] == "1234567890abcdef1234567890abcdef"
        assert sentry_trace_data["span_id"] == "1234567890abcdef"
        assert sentry_trace_data["parent_span_id"] == "abcdef1234567890"
        assert sentry_trace_data["parent_sampled"] is True
        assert sentry_trace_data["baggage"] is None

    with mock.patch(
        "sentry_sdk.integrations.opentelemetry.span_processor.get_value",
        side_effect=[
            ("1234567890abcdef1234567890abcdef", "1234567890abcdef", False),
            None,
        ],
    ):
        span_processor = SentrySpanProcessor()
        sentry_trace_data = span_processor._get_trace_data(otel_span, parent_context)
        assert sentry_trace_data["trace_id"] == "1234567890abcdef1234567890abcdef"
        assert sentry_trace_data["span_id"] == "1234567890abcdef"
        assert sentry_trace_data["parent_span_id"] == "abcdef1234567890"
        assert sentry_trace_data["parent_sampled"] is False
        assert sentry_trace_data["baggage"] is None


def test_get_trace_data_with_sentry_trace_and_baggage():
    otel_span = MagicMock()
    otel_span.context = MagicMock()
    otel_span.context.trace_id = int("1234567890abcdef1234567890abcdef", 16)
    otel_span.context.span_id = int("1234567890abcdef", 16)
    otel_span.parent = MagicMock()
    otel_span.parent.span_id = int("abcdef1234567890", 16)

    parent_context = {}

    baggage = (
        "sentry-trace_id=771a43a4192642f0b136d5159a501700,"
        "sentry-public_key=49d0f7386ad645858ae85020e393bef3,"
        "sentry-sample_rate=0.01337,sentry-user_id=Am%C3%A9lie"
    )

    with mock.patch(
        "sentry_sdk.integrations.opentelemetry.span_processor.get_value",
        side_effect=[
            ("1234567890abcdef1234567890abcdef", "1234567890abcdef", True),
            baggage,
        ],
    ):
        span_processor = SentrySpanProcessor()
        sentry_trace_data = span_processor._get_trace_data(otel_span, parent_context)
        assert sentry_trace_data["trace_id"] == "1234567890abcdef1234567890abcdef"
        assert sentry_trace_data["span_id"] == "1234567890abcdef"
        assert sentry_trace_data["parent_span_id"] == "abcdef1234567890"
        assert sentry_trace_data["parent_sampled"]
        assert sentry_trace_data["baggage"] == baggage


def test_update_span_with_otel_data_http_method():
    sentry_span = Span()

    otel_span = MagicMock()
    otel_span.name = "Test OTel Span"
    otel_span.attributes = {
        "http.method": "GET",
        "http.status_code": 429,
        "http.status_text": "xxx",
        "http.user_agent": "curl/7.64.1",
        "net.peer.name": "example.com",
        "http.target": "/",
    }

    span_processor = SentrySpanProcessor()
    span_processor._update_span_with_otel_data(sentry_span, otel_span)

    assert sentry_span.op == "http.get"
    assert sentry_span.description == "GET example.com /"
    assert sentry_span._tags["http.status_code"] == "429"
    assert sentry_span.status == "resource_exhausted"

    assert sentry_span._data["http.method"] == "GET"
    assert sentry_span._data["http.status_code"] == 429
    assert sentry_span._data["http.status_text"] == "xxx"
    assert sentry_span._data["http.user_agent"] == "curl/7.64.1"
    assert sentry_span._data["net.peer.name"] == "example.com"
    assert sentry_span._data["http.target"] == "/"


def test_update_span_with_otel_data_db_query():
    sentry_span = Span()

    otel_span = MagicMock()
    otel_span.name = "Test OTel Span"
    otel_span.attributes = {
        "db.system": "postgresql",
        "db.statement": "SELECT * FROM table where pwd = '123456'",
    }

    span_processor = SentrySpanProcessor()
    span_processor._update_span_with_otel_data(sentry_span, otel_span)

    assert sentry_span.op == "db"
    assert sentry_span.description == "SELECT * FROM table where pwd = '123456'"

    assert sentry_span._data["db.system"] == "postgresql"
    assert (
        sentry_span._data["db.statement"] == "SELECT * FROM table where pwd = '123456'"
    )


def test_on_start_transaction():
    otel_span = MagicMock()
    otel_span.name = "Sample OTel Span"
    otel_span.start_time = time.time_ns()
    otel_span.context = MagicMock()
    otel_span.context.trace_id = int("1234567890abcdef1234567890abcdef", 16)
    otel_span.context.span_id = int("1234567890abcdef", 16)
    otel_span.parent = MagicMock()
    otel_span.parent.span_id = int("abcdef1234567890", 16)

    parent_context = {}

    fake_hub = MagicMock()
    fake_hub.current.return_value = MagicMock()

    with mock.patch(
        "sentry_sdk.integrations.opentelemetry.span_processor.Hub", fake_hub
    ):
        span_processor = SentrySpanProcessor()
        span_processor.on_start(otel_span, parent_context)

        fake_hub.current.start_transaction.assert_called_once_with(
            name="Sample OTel Span",
            span_id="1234567890abcdef",
            parent_span_id="abcdef1234567890",
            trace_id="1234567890abcdef1234567890abcdef",
            baggage=None,
            start_timestamp=datetime.fromtimestamp(otel_span.start_time / 1e9),
            instrumenter="sentry",
        )

        assert len(span_processor.otel_span_map.keys()) == 1
        assert list(span_processor.otel_span_map.keys())[0] == "1234567890abcdef"


def test_on_start_child():
    otel_span = MagicMock()
    otel_span.name = "Sample OTel Span"
    otel_span.start_time = time.time_ns()
    otel_span.context = MagicMock()
    otel_span.context.trace_id = int("1234567890abcdef1234567890abcdef", 16)
    otel_span.context.span_id = int("1234567890abcdef", 16)
    otel_span.parent = MagicMock()
    otel_span.parent.span_id = int("abcdef1234567890", 16)

    parent_context = {}

    fake_hub = MagicMock()
    fake_hub.current.return_value = MagicMock()

    with mock.patch(
        "sentry_sdk.integrations.opentelemetry.span_processor.Hub", fake_hub
    ):
        fakeSpan = MagicMock()

        span_processor = SentrySpanProcessor()
        span_processor.otel_span_map["abcdef1234567890"] = fakeSpan
        span_processor.on_start(otel_span, parent_context)

        fakeSpan.start_child.assert_called_once_with(
            span_id="1234567890abcdef",
            description="Sample OTel Span",
            start_timestamp=datetime.fromtimestamp(otel_span.start_time / 1e9),
            instrumenter="sentry",
        )

        assert len(span_processor.otel_span_map.keys()) == 2
        assert "abcdef1234567890" in span_processor.otel_span_map.keys()
        assert "1234567890abcdef" in span_processor.otel_span_map.keys()


def test_on_end():
    assert "TODO" == "THIS NEEDS TO BE IMPLEMENTED"

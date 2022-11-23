from datetime import datetime

from opentelemetry.context import get_value
from opentelemetry.sdk.trace import SpanProcessor
from opentelemetry.semconv.trace import SpanAttributes
from opentelemetry.trace import format_span_id, format_trace_id

from sentry_sdk.hub import Hub
from sentry_sdk.integrations.opentelemetry.propagator import (
    SENTRY_BAGGAGE_KEY,
    SENTRY_TRACE_KEY,
)
from sentry_sdk.tracing import Transaction

OPEN_TELEMETRY_CONTEXT = "otel"


class SentrySpanProcessor(SpanProcessor):
    """
    Converts OTel spans into Sentry spans so they can be sent to the Sentry backend.
    """

    otel_span_map = {}  # The mapping from otel span ids to sentry spans

    def __new__(cls):
        if not hasattr(cls, "instance"):
            cls.instance = super(SentrySpanProcessor, cls).__new__(cls)

        return cls.instance

    def on_start(self, otel_span, parent_context=None):
        hub = Hub.current
        if not hub:
            return

        trace_data = self._get_trace_data(otel_span, parent_context)

        parent_span_id = trace_data["parent_span_id"]
        sentry_parent_span = (
            self.otel_span_map.get(parent_span_id, None) if parent_span_id else None
        )

        sentry_span = None
        if sentry_parent_span:
            sentry_span = sentry_parent_span.start_child(
                span_id=trace_data["span_id"],
                description=otel_span.name,
                start_timestamp=datetime.fromtimestamp(otel_span.start_time / 1e9),
                instrumenter="sentry",
            )
        else:
            sentry_span = hub.start_transaction(
                name=otel_span.name,
                span_id=trace_data["span_id"],
                parent_span_id=parent_span_id,
                trace_id=trace_data["trace_id"],
                baggage=trace_data["baggage"],
                start_timestamp=datetime.fromtimestamp(otel_span.start_time / 1e9),
                instrumenter="sentry",
            )

        self.otel_span_map[trace_data["span_id"]] = sentry_span

    def on_end(self, otel_span):
        span_id = format_span_id(otel_span.context.span_id)
        sentry_span = self.otel_span_map.pop(span_id)
        if not sentry_span:
            return

        sentry_span.op = otel_span.name

        if isinstance(sentry_span, Transaction):
            sentry_span.name = otel_span.name
            sentry_span.set_context(
                OPEN_TELEMETRY_CONTEXT, self._get_otel_context(otel_span)
            )

        else:
            self._update_span_with_otel_data(sentry_span, otel_span)

        sentry_span.finish(
            end_timestamp=datetime.fromtimestamp(otel_span.end_time / 1e9)
        )

    def _get_otel_context(self, otel_span):
        """
        Returns the OTel context for Sentry.
        See: https://develop.sentry.dev/sdk/performance/opentelemetry/#step-5-add-opentelemetry-context
        """
        ctx = {}

        if otel_span.attributes:
            ctx["attributes"] = dict(otel_span.attributes)

        if otel_span.resource.attributes:
            ctx["resource"] = dict(otel_span.resource.attributes)

        return ctx

    def _get_trace_data(self, otel_span, parent_context):
        """
        Extracts tracing information from one OTel span and its parent OTel context.
        """
        trace_data = {}

        span_id = format_span_id(otel_span.context.span_id)
        trace_data["span_id"] = span_id

        trace_id = format_trace_id(otel_span.context.trace_id)
        trace_data["trace_id"] = trace_id

        parent_span_id = (
            format_span_id(otel_span.parent.span_id) if otel_span.parent else None
        )
        trace_data["parent_span_id"] = parent_span_id

        sentry_trace_data = get_value(SENTRY_TRACE_KEY, parent_context)
        trace_data["parent_sampled"] = (
            sentry_trace_data[2] if sentry_trace_data else None
        )

        baggage = get_value(SENTRY_BAGGAGE_KEY, parent_context)
        trace_data["baggage"] = baggage

        return trace_data

    def _update_span_with_otel_data(self, sentry_span, otel_span):
        """
        Convert OTel span data and update the Sentry span with it.
        This should eventually happen on the server when ingesting the spans.
        """
        for key in otel_span.attributes:
            val = otel_span.attributes[key]
            sentry_span.set_data(key, val)

        op = otel_span.name
        description = otel_span.name

        http_method = otel_span.attributes.get(SpanAttributes.HTTP_METHOD, None)
        db_query = otel_span.attributes.get(SpanAttributes.DB_SYSTEM, None)

        if http_method:
            op = "http.{}".format(http_method)
            description = http_method

            peer_name = otel_span.attributes.get(SpanAttributes.NET_PEER_NAME, None)
            if peer_name:
                description += " {}".format(peer_name)

            target = otel_span.attributes.get(SpanAttributes.HTTP_TARGET, None)
            if target:
                description += " {}".format(target)

            status_code = otel_span.attributes.get(
                SpanAttributes.HTTP_STATUS_CODE, None
            )
            if status_code:
                sentry_span.set_http_status(status_code)

        elif db_query:
            op = "db"
            statement = otel_span.attributes.get(SpanAttributes.DB_STATEMENT, None)
            if statement:
                description = statement

        sentry_span.op = op
        sentry_span.description = description
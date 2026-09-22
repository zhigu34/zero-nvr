from __future__ import annotations

import smtplib

import pytest

from app.integrations.smtp import (
    SmtpAdapter,
    SmtpIntegrationError,
)


class FakeSmtpClient:
    def __init__(
        self,
        events: list[tuple[object, ...]],
    ) -> None:
        self.events = events
        self.messages = []

    def ehlo(self) -> None:
        self.events.append(("ehlo",))

    def starttls(self, *, context) -> None:
        self.events.append(("starttls", context))

    def login(
        self,
        username: str,
        password: str,
    ) -> None:
        self.events.append(
            ("login", username, password)
        )

    def send_message(self, message) -> None:
        self.messages.append(message)
        self.events.append(("send_message",))

    def quit(self) -> None:
        self.events.append(("quit",))

    def close(self) -> None:
        self.events.append(("close",))


def test_smtp_adapter_starttls_connection_and_email() -> None:
    events: list[tuple[object, ...]] = []
    clients: list[FakeSmtpClient] = []
    ssl_context = object()

    def smtp_factory(
        host: str,
        port: int,
        *,
        timeout: float,
    ) -> FakeSmtpClient:
        events.append(
            ("connect", host, port, timeout)
        )
        client = FakeSmtpClient(events)
        clients.append(client)
        return client

    def unused_ssl_factory(*args, **kwargs):
        raise AssertionError(
            "SMTP_SSL should not be used for STARTTLS"
        )

    adapter = SmtpAdapter(
        host="smtp.example.test",
        port=587,
        security="starttls",
        from_address="security@example.com",
        from_name="zero-nvr",
        username="mailer",
        password="smtp-secret",
        smtp_factory=smtp_factory,
        smtp_ssl_factory=unused_ssl_factory,
        ssl_context_factory=lambda: ssl_context,
    )

    adapter.test_connection()
    adapter.send_test_email(
        recipient="viewer@example.com"
    )

    assert events[:6] == [
        (
            "connect",
            "smtp.example.test",
            587,
            10.0,
        ),
        ("ehlo",),
        ("starttls", ssl_context),
        ("ehlo",),
        ("login", "mailer", "smtp-secret"),
        ("quit",),
    ]
    assert len(clients) == 2
    assert clients[1].messages
    message = clients[1].messages[0]
    assert message["Subject"] == "zero-nvr SMTP test"
    assert (
        message["From"]
        == "zero-nvr <security@example.com>"
    )
    assert message["To"] == "viewer@example.com"
    assert (
        "SMTP delivery is working"
        in message.get_content()
    )


def test_smtp_adapter_sanitizes_authentication_failure() -> None:
    class AuthFailureClient(FakeSmtpClient):
        def login(
            self,
            username: str,
            password: str,
        ) -> None:
            raise smtplib.SMTPAuthenticationError(
                535,
                b"bad credentials",
            )

    def smtp_factory(
        host: str,
        port: int,
        *,
        timeout: float,
    ) -> AuthFailureClient:
        return AuthFailureClient([])

    adapter = SmtpAdapter(
        host="smtp.example.test",
        port=587,
        security="plain",
        from_address="security@example.com",
        username="mailer",
        password="smtp-secret",
        smtp_factory=smtp_factory,
    )

    with pytest.raises(
        SmtpIntegrationError
    ) as exc_info:
        adapter.test_connection()

    assert (
        exc_info.value.code
        == "smtp_authentication_failed"
    )
    assert "smtp-secret" not in str(
        exc_info.value
    )

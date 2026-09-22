from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from typing import Any, Callable


class SmtpIntegrationError(RuntimeError):
    """Sanitized SMTP connection or delivery failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 502,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class SmtpAdapter:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        security: str,
        from_address: str,
        from_name: str | None = None,
        username: str | None = None,
        password: str | None = None,
        timeout: float = 10.0,
        smtp_factory: Callable[..., Any] = smtplib.SMTP,
        smtp_ssl_factory: Callable[..., Any] = smtplib.SMTP_SSL,
        ssl_context_factory: Callable[[], ssl.SSLContext] = (
            ssl.create_default_context
        ),
    ) -> None:
        if security not in {"plain", "starttls", "tls"}:
            raise SmtpIntegrationError(
                "smtp_security_invalid",
                "SMTP security mode is invalid.",
                status_code=400,
            )
        if not host or port < 1 or port > 65535:
            raise SmtpIntegrationError(
                "smtp_connection_invalid",
                "SMTP connection settings are invalid.",
                status_code=400,
            )
        if (username is None) != (password is None):
            raise SmtpIntegrationError(
                "smtp_credentials_invalid",
                "SMTP credentials are invalid.",
                status_code=400,
            )

        self.host = host
        self.port = port
        self.security = security
        self.from_address = from_address
        self.from_name = from_name
        self.username = username
        self.password = password
        self.timeout = timeout
        self._smtp_factory = smtp_factory
        self._smtp_ssl_factory = smtp_ssl_factory
        self._ssl_context_factory = ssl_context_factory

    @staticmethod
    def _close(client: Any | None) -> None:
        if client is None:
            return
        try:
            client.quit()
            return
        except Exception:
            pass
        try:
            client.close()
        except Exception:
            pass

    def _connect(self) -> Any:
        client: Any | None = None
        try:
            if self.security == "tls":
                client = self._smtp_ssl_factory(
                    self.host,
                    self.port,
                    timeout=self.timeout,
                    context=self._ssl_context_factory(),
                )
                client.ehlo()
            else:
                client = self._smtp_factory(
                    self.host,
                    self.port,
                    timeout=self.timeout,
                )
                client.ehlo()
                if self.security == "starttls":
                    client.starttls(
                        context=self._ssl_context_factory()
                    )
                    client.ehlo()

            if self.username is not None:
                assert self.password is not None
                client.login(
                    self.username,
                    self.password,
                )
            return client
        except smtplib.SMTPAuthenticationError as exc:
            self._close(client)
            raise SmtpIntegrationError(
                "smtp_authentication_failed",
                "SMTP authentication failed.",
            ) from exc
        except smtplib.SMTPNotSupportedError as exc:
            self._close(client)
            raise SmtpIntegrationError(
                "smtp_tls_unavailable",
                "SMTP server does not support the configured security mode.",
            ) from exc
        except (
            smtplib.SMTPException,
            OSError,
            TimeoutError,
        ) as exc:
            self._close(client)
            raise SmtpIntegrationError(
                "smtp_connection_failed",
                "SMTP connection failed.",
            ) from exc

    def test_connection(self) -> None:
        client = self._connect()
        self._close(client)

    def send_test_email(
        self,
        *,
        recipient: str,
    ) -> None:
        message = EmailMessage()
        message["Subject"] = "zero-nvr SMTP test"
        message["From"] = (
            formataddr(
                (
                    self.from_name,
                    self.from_address,
                )
            )
            if self.from_name
            else self.from_address
        )
        message["To"] = recipient
        message.set_content(
            "This is a zero-nvr SMTP test email. "
            "If you received it, SMTP delivery is working."
        )

        client = self._connect()
        try:
            client.send_message(message)
        except smtplib.SMTPRecipientsRefused as exc:
            raise SmtpIntegrationError(
                "smtp_recipient_rejected",
                "SMTP server rejected the test recipient.",
            ) from exc
        except (
            smtplib.SMTPException,
            OSError,
            TimeoutError,
        ) as exc:
            raise SmtpIntegrationError(
                "smtp_delivery_failed",
                "SMTP test email delivery failed.",
            ) from exc
        finally:
            self._close(client)

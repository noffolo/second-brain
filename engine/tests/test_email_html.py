import os
import email
from unittest.mock import patch, MagicMock
from engine.utils.email_sender import send_email

@patch("engine.utils.email_sender.load_dotenv")
@patch.dict("os.environ", {
    "SMTP_SERVER": "smtp.example.com",
    "SMTP_PORT": "587",
    "SMTP_USERNAME": "testuser",
    "SMTP_PASSWORD": "testpassword",
    "SMTP_FROM": "from@example.com",
    "SMTP_TO": "to@example.com"
})
@patch("smtplib.SMTP")
def test_send_email_starttls(mock_smtp_class, mock_load_dotenv):
    mock_smtp = MagicMock()
    mock_smtp_class.return_value = mock_smtp
    
    body = "Questo è un **test** in grassetto.\n\n- Elemento 1\n- Elemento 2"
    success = send_email("Test Subject", body)
    
    assert success is True
    # Verify SMTP calls
    mock_smtp_class.assert_called_once_with("smtp.example.com", 587, timeout=30)
    mock_smtp.ehlo.assert_called()
    mock_smtp.starttls.assert_called_once()
    mock_smtp.login.assert_called_once_with("testuser", "testpassword")
    mock_smtp.sendmail.assert_called_once()
    mock_smtp.quit.assert_called_once()
    
    # Check what was sent
    args, kwargs = mock_smtp.sendmail.call_args
    assert args[0] == "from@example.com"
    assert args[1] == ["to@example.com"]
    msg_str = args[2]
    
    # Decode the MIME message
    msg = email.message_from_string(msg_str)
    assert msg.is_multipart()
    
    parts = msg.get_payload()
    assert len(parts) == 2
    
    plain_text = parts[0].get_payload(decode=True).decode("utf-8")
    html_text = parts[1].get_payload(decode=True).decode("utf-8")
    
    # Verify that both plain text and HTML components exist in the email
    assert "Questo è un **test** in grassetto." in plain_text
    assert "Questo è un <strong>test</strong> in grassetto." in html_text
    assert "<li>Elemento 1</li>" in html_text


@patch("engine.utils.email_sender.load_dotenv")
@patch.dict("os.environ", {
    "SMTP_SERVER": "smtp.example.com",
    "SMTP_PORT": "465",
    "SMTP_USERNAME": "testuser",
    "SMTP_PASSWORD": "testpassword",
    "SMTP_FROM": "from@example.com",
    "SMTP_TO": "to@example.com"
})
@patch("smtplib.SMTP_SSL")
def test_send_email_ssl(mock_smtp_ssl_class, mock_load_dotenv):
    mock_smtp_ssl = MagicMock()
    mock_smtp_ssl_class.return_value = mock_smtp_ssl
    
    body = "Test body"
    success = send_email("Test Subject SSL", body)
    
    assert success is True
    mock_smtp_ssl_class.assert_called_once_with("smtp.example.com", 465, timeout=30)
    mock_smtp_ssl.login.assert_called_once_with("testuser", "testpassword")
    mock_smtp_ssl.sendmail.assert_called_once()
    mock_smtp_ssl.quit.assert_called_once()


@patch("engine.utils.email_sender.load_dotenv")
@patch.dict("os.environ", {}, clear=True)
def test_send_email_missing_params(mock_load_dotenv):
    # If parameters are missing, it should emulate and return False
    success = send_email("Test Subject Emulated", "Emulated body")
    assert success is False

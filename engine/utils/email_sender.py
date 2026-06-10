import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from dotenv import load_dotenv
import markdown

def send_email(subject: str, body_text: str) -> bool:
    load_dotenv()
    
    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = os.getenv("SMTP_PORT", "587")
    smtp_username = os.getenv("SMTP_USERNAME")
    smtp_password = os.getenv("SMTP_PASSWORD")
    smtp_from = os.getenv("SMTP_FROM")
    smtp_to = os.getenv("SMTP_TO")
    
    if not all([smtp_server, smtp_username, smtp_password, smtp_from, smtp_to]):
        print("\n=== INVIO EMAIL SOTTOPOSTO A EMULAZIONE (Parametri SMTP incompleti in .env) ===")
        print(f"Oggetto: {subject}")
        print(f"A: {smtp_to or 'Non impostato'}")
        print(f"Da: {smtp_from or 'Non impostato'}")
        print(f"Corpo:\n{body_text}")
        print("=========================================================================\n")
        return False
        
    try:
        # Convert markdown to HTML
        try:
            html_body = markdown.markdown(body_text, extensions=['extra', 'sane_lists'])
        except Exception as e:
            print(f"Errore nella conversione markdown -> HTML: {e}")
            html_body = body_text.replace("\n", "<br>")

        # Premium HTML template
        html_template = f"""<html>
<head>
<style>
    body {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
        color: #333333;
        line-height: 1.6;
        max-width: 600px;
        margin: 0 auto;
        padding: 20px;
    }}
    h1, h2, h3 {{
        color: #111111;
        margin-top: 24px;
        margin-bottom: 12px;
        font-weight: 600;
    }}
    strong {{
        color: #000000;
        font-weight: 600;
    }}
    ul, ol {{
        padding-left: 20px;
        margin-bottom: 16px;
    }}
    li {{
        margin-bottom: 8px;
    }}
    p {{
        margin-bottom: 16px;
    }}
</style>
</head>
<body>
{html_body}
</body>
</html>"""

        msg = MIMEMultipart("alternative")
        msg["Subject"] = Header(subject, "utf-8")
        msg["From"] = smtp_from
        msg["To"] = smtp_to
        
        part_text = MIMEText(body_text, "plain", "utf-8")
        part_html = MIMEText(html_template, "html", "utf-8")
        msg.attach(part_text)
        msg.attach(part_html)
        
        # Connect to SMTP server (supports both SSL on 465 and STARTTLS on 587)
        if smtp_port == "465":
            server = smtplib.SMTP_SSL(smtp_server, int(smtp_port), timeout=30)
        else:
            server = smtplib.SMTP(smtp_server, int(smtp_port), timeout=30)
            server.ehlo()
            if smtp_port == "587":
                server.starttls()
                server.ehlo()
        server.login(smtp_username, smtp_password)
        server.sendmail(smtp_from, [smtp_to], msg.as_string())
        server.quit()
        print(f"Email inviata con successo a {smtp_to}: '{subject}'")
        return True
    except Exception as e:
        print(f"Errore durante l'invio dell'email via SMTP: {e}")
        return False

if __name__ == "__main__":
    send_email("Test Second Brain", "Questa è una mail di prova con **testo in grassetto** e lista:\n- Elemento 1\n- Elemento 2")

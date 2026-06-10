import os
import smtplib
from email.mime.text import MIMEText
from email.header import Header
from dotenv import load_dotenv

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
        msg = MIMEText(body_text, "plain", "utf-8")
        msg["Subject"] = Header(subject, "utf-8")
        msg["From"] = smtp_from
        msg["To"] = smtp_to
        
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
    send_email("Test Second Brain", "Questa è una mail di prova.")

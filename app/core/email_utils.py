import smtplib
import os
import random
import string
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def generate_random_password(length=12):
    """Generate a random password with letters, digits, and special characters"""
    characters = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(random.choice(characters) for _ in range(length))

def send_password_email(username, password):
    """Send the generated password to the receiver email"""
    # Get email configuration from environment variables
    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = int(os.getenv("SMTP_PORT", 587))
    sender_email = os.getenv("SENDER_EMAIL")
    sender_password = os.getenv("SENDER_PASSWORD")
    receiver_email = os.getenv("RECEIVER_EMAIL")
    
    # Create message
    message = MIMEMultipart("alternative")
    message["Subject"] = f"New User Account Created - {username}"
    message["From"] = sender_email
    message["To"] = receiver_email
    
    # Create the plain-text and HTML version of your message
    text = f"""\
    Hi Admin,
    
    A new user account has been created with the following details:
    
    Username: {username}
    Password: {password}
    
    Please share this password securely with the user.
    
    Best regards,
    PrimeFlow POS System
    """
    
    html = f"""\
    <html>
      <body>
        <p>Hi Admin,<br><br>
           A new user account has been created with the following details:<br><br>
           <b>Username:</b> {username}<br>
           <b>Password:</b> {password}<br><br>
           Please share this password securely with the user.<br><br>
           Best regards,<br>
           PrimeFlow POS System
        </p>
      </body>
    </html>
    """
    
    # Turn these into plain/html MIMEText objects
    part1 = MIMEText(text, "plain")
    part2 = MIMEText(html, "html")
    
    # Add HTML/plain-text parts to MIMEMultipart message
    message.attach(part1)
    message.attach(part2)
    
    # Create secure connection with server and send email
    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()  # Enable security
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, receiver_email, message.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False

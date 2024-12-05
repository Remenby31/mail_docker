import imaplib
import email
from email.message import Message
import psycopg2
from psycopg2.extras import DictCursor
from datetime import datetime
import hashlib
import os
import sys
from email.header import decode_header
from dotenv import load_dotenv
import time
from tqdm import tqdm
import ssl
from typing import Set, Dict, List
import logging
from pathlib import Path

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

class Config:
    def __init__(self):
        # Configuration email
        self.EMAIL = os.getenv('EMAIL_ADDRESS')
        self.PASSWORD = os.getenv('EMAIL_PASSWORD')
        self.IMAP_SERVER = os.getenv('IMAP_SERVER')
        self.IMAP_PORT = int(os.getenv('IMAP_PORT', '993'))
        
        # Configuration PostgreSQL
        self.DB_HOST = os.getenv('DB_HOST', 'db')
        self.DB_PORT = int(os.getenv('DB_PORT', '5432'))
        self.DB_NAME = os.getenv('DB_NAME', 'emails')
        self.DB_USER = os.getenv('DB_USER', 'postgres')
        self.DB_PASSWORD = os.getenv('DB_PASSWORD', 'postgres')
        
        self.BATCH_SIZE = int(os.getenv('BATCH_SIZE', '100'))
        self.FETCH_INTERVAL = int(os.getenv('FETCH_INTERVAL', '3600'))

    def validate(self):
        """Valide la présence des variables d'environnement requises"""
        missing = []
        for var in ['EMAIL_ADDRESS', 'EMAIL_PASSWORD', 'IMAP_SERVER', 
                   'DB_HOST', 'DB_NAME', 'DB_USER', 'DB_PASSWORD']:
            if not os.getenv(var):
                missing.append(var)
        
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
        
        logger.info(f"Configuration validated. Using IMAP server: {self.IMAP_SERVER}:{self.IMAP_PORT}")

        
        logger.info(f"Configuration validated. Using IMAP server: {self.IMAP_SERVER}:{self.IMAP_PORT}")

class EmailFetcher:
    def __init__(self):
        self.config = Config()
        self.config.validate()
        self.imap_server = None
        self.conn = None
        self.cursor = None

    def connect_db(self):
        """Établit la connexion à PostgreSQL avec retry"""
        max_retries = 5
        retry_delay = 5
        
        for attempt in range(max_retries):
            try:
                self.conn = psycopg2.connect(
                    host=self.config.DB_HOST,
                    port=self.config.DB_PORT,
                    dbname=self.config.DB_NAME,
                    user=self.config.DB_USER,
                    password=self.config.DB_PASSWORD
                )
                self.cursor = self.conn.cursor(cursor_factory=DictCursor)
                
                # Création de la table si elle n'existe pas
                self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS emails (
                    id SERIAL PRIMARY KEY,
                    unique_id TEXT UNIQUE,
                    message_id TEXT,
                    sender TEXT NOT NULL,
                    subject TEXT,
                    date TIMESTAMP,
                    body TEXT,
                    imap_uid TEXT,
                    last_seen TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                
                CREATE INDEX IF NOT EXISTS idx_unique_id ON emails(unique_id);
                CREATE INDEX IF NOT EXISTS idx_imap_uid ON emails(imap_uid);
                CREATE INDEX IF NOT EXISTS idx_last_seen ON emails(last_seen);
                """)
                
                self.conn.commit()
                logger.info("Database connection established and schema initialized")
                return
                
            except Exception as e:
                logger.error(f"Database connection attempt {attempt + 1} failed: {str(e)}")
                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                else:
                    raise

    def get_existing_emails(self) -> Dict[str, str]:
        """Récupère les emails existants dans la base de données"""
        try:
            self.cursor.execute("SELECT unique_id, imap_uid FROM emails")
            return {row['unique_id']: row['imap_uid'] for row in self.cursor.fetchall()}
        except Exception as e:
            logger.error(f"Error fetching existing emails: {str(e)}")
            return {}

    def process_email_batch(self, uids: List[bytes]):
        """Traite un lot d'emails"""
        processed_hashes = set()
        
        for uid in uids:
            try:
                _, msg_data = self.imap_server.uid('fetch', uid, '(RFC822)')
                if not msg_data or not msg_data[0]:
                    continue
                
                email_body = msg_data[0][1]
                msg = email.message_from_bytes(email_body)
                
                unique_id = self.generate_email_hash(msg)
                processed_hashes.add(unique_id)
                
                # Utilisation de l'UPSERT de PostgreSQL
                self.cursor.execute("""
                INSERT INTO emails 
                    (unique_id, message_id, sender, subject, date, body, imap_uid, last_seen)
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (unique_id) 
                DO UPDATE SET
                    message_id = EXCLUDED.message_id,
                    sender = EXCLUDED.sender,
                    subject = EXCLUDED.subject,
                    date = EXCLUDED.date,
                    body = EXCLUDED.body,
                    imap_uid = EXCLUDED.imap_uid,
                    last_seen = EXCLUDED.last_seen
                """, (
                    unique_id,
                    msg.get('Message-ID', ''),
                    self.decode_email_header(msg.get('From', 'Unknown')),
                    self.decode_email_header(msg.get('Subject', 'No Subject')),
                    self.parse_date(msg.get('Date')),
                    self.get_email_body(msg),
                    uid.decode(),
                    datetime.now()
                ))
                
            except Exception as e:
                logger.error(f"Error processing email {uid}: {str(e)}")
                continue
                
        return processed_hashes

    def cleanup_old_emails(self, current_hashes: Set[str]) -> int:
        """Supprime les emails qui ne sont plus sur le serveur"""
        try:
            if not current_hashes:
                return 0
            
            # Utilisation de chunks pour les grandes suppressions
            chunk_size = 1000
            all_hashes = list(current_hashes)
            removed_total = 0
            
            for i in range(0, len(all_hashes), chunk_size):
                chunk = all_hashes[i:i + chunk_size]
                self.cursor.execute("""
                    DELETE FROM emails 
                    WHERE unique_id NOT IN %s
                """, (tuple(chunk),))
                
                removed_total += self.cursor.rowcount
                self.conn.commit()
            
            return removed_total
            
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")
            return 0
        
    def decode_email_header(self, header_string):
        """Décode les en-têtes d'email qui peuvent contenir différents encodages"""
        if not header_string:
            return ""
        try:
            decoded_parts = decode_header(header_string)
            decoded_text = ""
            
            for part, encoding in decoded_parts:
                if isinstance(part, bytes):
                    if encoding:
                        try:
                            decoded_text += part.decode(encoding)
                        except LookupError:
                            decoded_text += part.decode('utf-8', 'ignore')
                    else:
                        decoded_text += part.decode('utf-8', 'ignore')
                else:
                    decoded_text += str(part)
            
            return decoded_text.strip()
        except Exception as e:
            logger.warning(f"Error decoding header: {str(e)}")
            return str(header_string)

    def parse_date(self, date_str):
        """Parse la date de l'email dans un format compatible avec SQLite"""
        if not date_str:
            return datetime.now().isoformat()
        try:
            email_date = email.utils.parsedate_to_datetime(date_str)
            return email_date.isoformat()
        except Exception as e:
            logger.warning(f"Error parsing date {date_str}: {str(e)}")
            return datetime.now().isoformat()


    def connect_imap(self):
        """Établit la connexion au serveur IMAP avec retry"""
        max_retries = 3
        retry_delay = 5  # secondes
        
        for attempt in range(max_retries):
            try:
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE

                logger.info(f"Connecting to {self.config.IMAP_SERVER}:{self.config.IMAP_PORT}...")
                self.imap_server = imaplib.IMAP4_SSL(
                    self.config.IMAP_SERVER, 
                    self.config.IMAP_PORT, 
                    ssl_context=context
                )
                self.imap_server.login(self.config.EMAIL, self.config.PASSWORD)
                logger.info("Successfully connected to IMAP server")
                return
                
            except Exception as e:
                logger.error(f"IMAP connection attempt {attempt + 1} failed: {str(e)}")
                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                else:
                    raise

    def generate_email_hash(self, msg: Message) -> str:
        """Génère un hash unique pour un email basé sur son contenu"""
        hash_content = [
            str(msg.get('Message-ID', '')),
            str(msg.get('Date', '')),
            str(msg.get('From', '')),
            str(msg.get('Subject', '')),
            str(msg.get('To', '')),
            str(msg.get('Cc', '')),
            str(msg.get('Bcc', ''))
        ]
        return hashlib.sha256(''.join(hash_content).encode()).hexdigest()

    def get_email_body(self, msg: Message) -> str:
        """Extrait le corps du message en texte brut et HTML"""
        text_content = ""
        html_content = ""
        
        try:
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_maintype() == 'multipart':
                        continue
                    
                    try:
                        content_type = part.get_content_type()
                        body = part.get_payload(decode=True)
                        
                        if body:
                            if content_type == "text/plain":
                                text_content = body.decode('utf-8', 'ignore')
                            elif content_type == "text/html":
                                html_content = body.decode('utf-8', 'ignore')
                    except Exception as e:
                        logger.warning(f"Error processing email part: {str(e)}")
                        continue
            else:
                content_type = msg.get_content_type()
                try:
                    body = msg.get_payload(decode=True)
                    if body:
                        if content_type == "text/plain":
                            text_content = body.decode('utf-8', 'ignore')
                        elif content_type == "text/html":
                            html_content = body.decode('utf-8', 'ignore')
                except Exception as e:
                    logger.warning(f"Error processing single-part email: {str(e)}")

            return text_content.strip() if text_content else html_content.strip()
            
        except Exception as e:
            logger.error(f"Error extracting email body: {str(e)}")
            return ""

    def get_existing_emails(self) -> Dict[str, str]:
        """Récupère les emails existants dans la base de données"""
        try:
            self.cursor.execute("SELECT unique_id, imap_uid FROM emails")
            return {row[0]: row[1] for row in self.cursor.fetchall()}
        except Exception as e:
            logger.error(f"Error fetching existing emails: {str(e)}")
            return {}

    def sync_mailbox(self, mailbox: str = 'INBOX'):
        """Synchronise une boîte mail avec la base de données"""
        try:
            logger.info(f"Synchronizing mailbox: {mailbox}")
            self.imap_server.select(mailbox)
            
            # Récupère tous les UIDs des emails
            _, messages = self.imap_server.uid('search', None, 'ALL')
            all_uids = messages[0].split()
            
            logger.info(f"Found {len(all_uids)} emails in mailbox")
            
            # Traitement par lots
            processed_hashes = set()
            for i in range(0, len(all_uids), self.config.BATCH_SIZE):
                batch = all_uids[i:i + self.config.BATCH_SIZE]
                batch_hashes = self.process_email_batch(batch)
                processed_hashes.update(batch_hashes)
                
                # Commit après chaque lot
                self.conn.commit()
                
            # Nettoyage des anciens emails
            removed_count = self.cleanup_old_emails(processed_hashes)
            
            logger.info(f"Sync complete: {len(processed_hashes)} emails processed, {removed_count} removed")
            
        except Exception as e:
            logger.error(f"Error syncing mailbox {mailbox}: {str(e)}")
            raise

    def parse_mailbox_name(self, mailbox_bytes: bytes) -> str:
        """Parse le nom de la boîte mail depuis la réponse IMAP"""
        try:
            mailbox_str = mailbox_bytes.decode('utf-8')
            import re
            match = re.search(r'"([^"]+)"$', mailbox_str)
            if match:
                return match.group(1)
            parts = mailbox_str.split(' ')
            return parts[-1].strip('"')
        except Exception as e:
            logger.error(f"Error parsing mailbox name: {str(e)}")
            return "INBOX"

    def sync_all_mailboxes(self):
        """Synchronise toutes les boîtes mail disponibles"""
        try:
            logger.info("Starting full mailbox synchronization")
            self.connect_imap()
            self.connect_db()
            
            _, mailboxes = self.imap_server.list()
            
            for mailbox in mailboxes:
                mailbox_name = self.parse_mailbox_name(mailbox)
                try:
                    self.sync_mailbox(mailbox_name)
                except Exception as e:
                    logger.error(f"Error syncing mailbox {mailbox_name}: {str(e)}")
                    continue
                    
        except Exception as e:
            logger.error(f"Error in sync_all_mailboxes: {str(e)}")
            raise
            
        finally:
            self.cleanup()

    def cleanup(self):
        """Nettoie les ressources"""
        if self.conn:
            try:
                self.conn.close()
                logger.info("Database connection closed")
            except Exception as e:
                logger.error(f"Error closing database connection: {str(e)}")

        if self.imap_server:
            try:
                self.imap_server.close()
                self.imap_server.logout()
                logger.info("IMAP connection closed")
            except Exception as e:
                logger.error(f"Error closing IMAP connection: {str(e)}")

def main():
    """Fonction principale avec gestion des erreurs et retries"""
    max_retries = 3
    retry_delay = 10  # secondes entre les retries en cas d'erreur
    
    while True:
        for attempt in range(max_retries):
            try:
                logger.info("Starting email fetch cycle")
                fetcher = EmailFetcher()
                fetcher.sync_all_mailboxes()
                logger.info("Email fetch cycle completed successfully")
                break  # Sort de la boucle de retry si succès
                
            except KeyboardInterrupt:
                logger.info("Process interrupted by user")
                sys.exit(0)
                
            except Exception as e:
                logger.error(f"Error during fetch cycle (attempt {attempt + 1}/{max_retries}): {str(e)}")
                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                else:
                    logger.error("Max retries reached, waiting for next cycle")
        
        # Attend l'intervalle configuré avant le prochain cycle
        sleep_time = fetcher.config.FETCH_INTERVAL
        logger.info(f"Waiting {sleep_time} seconds until next cycle...")
        time.sleep(sleep_time)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.critical(f"Fatal error: {str(e)}")
        sys.exit(1)
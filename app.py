from flask import Flask, g, render_template_string, request, redirect, url_for, session, flash
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
import bcrypt
import json
import pandas as pd
import io
from flask import Response
from markupsafe import escape
import xlsxwriter
import os
import random
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta

import psycopg2
from dotenv import load_dotenv
import os

import atexit
import signal
import sys


# Load environment variables from .env
load_dotenv()

# Fetch variables
USER = os.getenv("user")
PASSWORD = os.getenv("password")
HOST = os.getenv("host")
PORT = os.getenv("port")
DBNAME = os.getenv("dbname")

# Connect to the database
try:
    connection = psycopg2.connect(
        user=USER,
        password=PASSWORD,
        host=HOST,
        port=PORT,
        dbname=DBNAME
    )
    print("Connection successful!")
    
    # Create a cursor to execute SQL queries
    cursor = connection.cursor()
    
    # Example query
    cursor.execute("SELECT NOW();")
    result = cursor.fetchone()
    print("Current Time:", result)

    # Close the cursor and connection
    cursor.close()
    connection.close()
    print("Connection closed.")

except Exception as e:
    print(f"Failed to connect: {e}")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    load_dotenv = None

DB_PATH = Path(__file__).parent / 'tiramine.db'
SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-tiramine')

app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY

# ---------- ENHANCED AUTO-SAVE SYSTEM ----------

class AutoSaveManager:
    def __init__(self):
        self.last_save = datetime.now()
        self.save_interval = 30  # Save every 30 seconds
        self.force_save_flag = False
    
    def should_save(self):
        """Check if it's time to auto-save"""
        now = datetime.now()
        time_diff = (now - self.last_save).total_seconds()
        return time_diff >= self.save_interval or self.force_save_flag
    
    def mark_saved(self):
        """Mark that save has been performed"""
        self.last_save = datetime.now()
        self.force_save_flag = False
    
    def force_save(self):
        """Force immediate save on next check"""
        self.force_save_flag = True

# Global auto-save manager
auto_save_manager = AutoSaveManager()

def enhanced_force_save():
    """Enhanced save function with better error handling"""
    print("\n💾 Auto-saving data...")
    try:
        # Use application context to get database
        with app.app_context():
            db = get_db()
            # Commit any pending transactions
            db.commit()
            print("✅ All data saved successfully!")
            auto_save_manager.mark_saved()
            return True
    except Exception as e:
        print(f"❌ Save error: {e}")
        # Try to rollback and save again
        try:
            with app.app_context():
                db = get_db()
                db.rollback()
                db.commit()
                print("✅ Data saved after rollback!")
                auto_save_manager.mark_saved()
                return True
        except Exception as e2:
            print(f"❌ Critical save error: {e2}")
            return False
        
def enhanced_handle_shutdown(signum, frame):
    """Enhanced shutdown handler"""
    print("\n🔄 Shutting down gracefully...")
    enhanced_force_save()
    print("👋 Goodbye!")
    sys.exit(0)

def periodic_auto_save():
    """Periodic auto-save function"""
    if auto_save_manager.should_save():
        enhanced_force_save()

# Register enhanced handlers (ganti yang lama)
atexit.register(enhanced_force_save)
signal.signal(signal.SIGINT, enhanced_handle_shutdown)

# Auto-save before each request
@app.before_request
def auto_save_before_request():
    """Auto-save before each request if needed"""
    # Only auto-save for non-static requests and when we have a user session
    if request.endpoint and 'static' not in request.endpoint and current_user():
        periodic_auto_save()

# ---------- Helper Database ----------

def get_db():
    db = getattr(g, '_db', None)
    if db is None:
        db = g._db = sqlite3.connect(str(DB_PATH))
        db.row_factory = sqlite3.Row
        # Tambah ini untuk auto-commit yang lebih baik:
        db.execute('PRAGMA journal_mode=WAL')
    return db

@app.teardown_appcontext
def close_db(exception):
    """Enhanced database close with guaranteed commit"""
    db = getattr(g, '_db', None)
    if db is not None:
        try:
            # Always try to commit before closing
            print("💾 Committing changes before closing database...")
            db.commit()
            print("✅ Changes committed successfully")
        except Exception as commit_error:
            print(f"❌ Commit error on close: {commit_error}")
            try:
                db.rollback()
                print("🔄 Rolled back due to commit error")
            except:
                pass
        finally:
            try:
                db.close()
                print("🔒 Database connection closed")
            except:
                pass

def init_db():
    """Initialize database with proper context management"""
    print("🚀 Starting database initialization...")
    
    # Use app context to ensure database connection stays open
    with app.app_context():
        db = get_db()
        cur = db.cursor()
        
        try:
            print("🗑️  Cleaning up existing tables...")
            # HAPUS SEMUA TABEL DAN BUAT ULANG DENGAN STRUKTUR YANG BENAR
            cur.executescript('''
                DROP TABLE IF EXISTS transaction_templates;
                DROP TABLE IF EXISTS opening_balances;
                DROP TABLE IF EXISTS adjusting_lines;
                DROP TABLE IF EXISTS adjusting_entries;
                DROP TABLE IF EXISTS journal_lines;
                DROP TABLE IF EXISTS journal_entries;
                DROP TABLE IF EXISTS inventory;
                DROP TABLE IF EXISTS accounts;
                DROP TABLE IF EXISTS users;
                DROP TABLE IF EXISTS settings;
                DROP TABLE IF EXISTS otp_verification;
            ''')
            
            print("📋 Creating tables...")
            # Buat tabel users
            cur.execute('''
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Buat tabel accounts (Chart of Accounts) - SESUAI NERACA SALDO AWAL
            cur.execute('''
                CREATE TABLE accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    acct_type TEXT NOT NULL,
                    normal_balance TEXT NOT NULL,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Buat tabel journal_entries
            cur.execute('''
                CREATE TABLE journal_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date DATE NOT NULL,
                    description TEXT NOT NULL,
                    reference TEXT,
                    transaction_type TEXT DEFAULT 'General',
                    posted BOOLEAN DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Buat tabel journal_lines
            cur.execute('''
                CREATE TABLE journal_lines (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entry_id INTEGER NOT NULL,
                    account_id INTEGER NOT NULL,
                    debit DECIMAL(15,2) DEFAULT 0,
                    credit DECIMAL(15,2) DEFAULT 0,
                    description TEXT,
                    FOREIGN KEY (entry_id) REFERENCES journal_entries (id),
                    FOREIGN KEY (account_id) REFERENCES accounts (id)
                )
            ''')
            
            # Buat tabel adjusting_entries
            cur.execute('''
                CREATE TABLE adjusting_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date DATE NOT NULL,
                    description TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Buat tabel adjusting_lines
            cur.execute('''
                CREATE TABLE adjusting_lines (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    adj_id INTEGER NOT NULL,
                    account_id INTEGER NOT NULL,
                    debit DECIMAL(15,2) DEFAULT 0,
                    credit DECIMAL(15,2) DEFAULT 0,
                    description TEXT,
                    FOREIGN KEY (adj_id) REFERENCES adjusting_entries (id),
                    FOREIGN KEY (account_id) REFERENCES accounts (id)
                )
            ''')
            
            # Buat tabel inventory
            cur.execute('''
                CREATE TABLE inventory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date DATE NOT NULL,
                    description TEXT NOT NULL,
                    quantity_in INTEGER DEFAULT 0,
                    quantity_out INTEGER DEFAULT 0,
                    unit_cost DECIMAL(15,2) DEFAULT 0,
                    value DECIMAL(15,2) DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Buat tabel settings
            cur.execute('''
                CREATE TABLE settings (
                    k TEXT PRIMARY KEY,
                    v TEXT NOT NULL
                )
            ''')
            
            # Buat tabel opening_balances dengan struktur yang BENAR
            cur.execute('''
                CREATE TABLE opening_balances (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER UNIQUE NOT NULL,
                    debit_amount DECIMAL(15,2) DEFAULT 0,
                    credit_amount DECIMAL(15,2) DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (account_id) REFERENCES accounts (id)
                )
            ''')
            
            # Buat tabel untuk OTP verification
            cur.execute('''
                CREATE TABLE otp_verification (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL,
                    otp_code TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP NOT NULL,
                    used BOOLEAN DEFAULT 0
                )
            ''')
            
            # Insert default settings
            cur.execute('''
                INSERT INTO settings (k, v) VALUES 
                ('company_name', 'Peternakan Tiram Tiramine'),
                ('company_description', 'Sistem Akuntansi Peternakan Tiram Modern'),
                ('company_location', 'Indonesia'),
                ('current_stock_large', '0'),
                ('current_stock_small', '0')
            ''')
            
            print("👤 Creating default accounts...")
            # DATA DEFAULT - BUAT SEMUA AKUN SESUAI NERACA SALDO AWAL ANDA
            accounts = [
                # ===== ASET =====
                ('101', 'Kas', 'Asset', 'Debit', 'Kas perusahaan'),
                ('102', 'Piutang Usaha', 'Asset', 'Debit', 'Piutang dari pelanggan'),
                ('103', 'Peralatan Tambak', 'Asset', 'Debit', 'Peralatan untuk tambak tiram'),
                ('104', 'Perlengkapan', 'Asset', 'Debit', 'Perlengkapan operasional'),
                ('105', 'Persediaan - Tiram Kecil', 'Asset', 'Debit', 'Persediaan tiram kecil'),
                ('106', 'Persediaan - Tiram Besar', 'Asset', 'Debit', 'Persediaan tiram besar'),
                ('107', 'Persediaan Benih Kecil', 'Asset', 'Debit', 'Persediaan benih tiram kecil'),
                ('108', 'Persediaan Benih Besar', 'Asset', 'Debit', 'Persediaan benih tiram besar'),
                ('109', 'Kendaraan', 'Asset', 'Debit', 'Kendaraan operasional'),
                ('110', 'Akumulasi Penyusutan Kendaraan', 'Contra Asset', 'Credit', 'Akumulasi penyusutan kendaraan'),
                
                # ===== KEWAJIBAN =====
                ('201', 'Utang Usaha', 'Liability', 'Credit', 'Utang kepada supplier'),
                ('202', 'Utang Gaji', 'Liability', 'Credit', 'Utang gaji karyawan'),
                
                # ===== EKUITAS =====
                ('301', 'Modal Pemilik (Tiramine Capital)', 'Equity', 'Credit', 'Modal pemilik perusahaan'),
                ('302', 'Ikhtisar Laba Rugi', 'Equity', 'Credit', 'Ikhtisar laba rugi'),
                ('303', 'Laba Ditahan', 'Equity', 'Credit', 'Laba yang ditahan'),
                
                # ===== PENDAPATAN =====
                ('401', 'Penjualan - Tiram Besar', 'Revenue', 'Credit', 'Pendapatan penjualan tiram besar'),
                ('402', 'Penjualan - Tiram Kecil', 'Revenue', 'Credit', 'Pendapatan penjualan tiram kecil'),
                
                # ===== BEBAN =====
                ('501', 'HPP - Tiram Kecil', 'Expense', 'Debit', 'Harga pokok penjualan tiram kecil'),
                ('502', 'HPP - Tiram Besar', 'Expense', 'Debit', 'Harga pokok penjualan tiram besar'),
                ('503', 'Beban Gaji', 'Expense', 'Debit', 'Beban gaji karyawan'),
                ('504', 'Beban Penyusutan Kendaraan', 'Expense', 'Debit', 'Beban Penyusutan Kendaraan')
            ]
            
            for code, name, atype, normal, desc in accounts:
                cur.execute('INSERT INTO accounts (code, name, acct_type, normal_balance, description) VALUES (?,?,?,?,?)', 
                            (code, name, atype, normal, desc))
                print(f"✅ Created account: {code} - {name}")
            
            # INSERT SALDO AWAL DEFAULT SESUAI NERACA SALDO AWAL ANDA
            print("🔧 Setting up default opening balances...")
            opening_balances = [
                # Assets (Debit)
                (1, 8500000, 0),    # Kas (101)
                (2, 4500000, 0),    # Piutang Usaha (102)
                (3, 500000, 0),     # Peralatan Tambak (103)
                (4, 300000, 0),     # Perlengkapan (104)
                (5, 1200000, 0),    # Persediaan - Tiram Kecil (105)
                (6, 1750000, 0),    # Persediaan - Tiram Besar (106)
                (7, 12000000, 0),   # Kendaraan (107)
                
                # Contra Asset (Credit)
                (8, 0, 1500000),    # Akumulasi Penyusutan Kendaraan (108)
                
                # Liabilities (Credit)
                (9, 0, 650000),     # Utang Usaha (201)
                (10, 0, 100000),    # Utang Gaji (202)
                
                # Equity (Credit)
                (11, 0, 22300000),  # Modal Pemilik (301)
                
                # Revenue (Credit) - dari penjualan
                (12, 0, 4000000),   # Penjualan - Tiram Besar (401)
                (13, 0, 3000000),   # Penjualan - Tiram Kecil (402)
                
                # Expenses (Debit) - dari HPP dan beban
                (14, 1000000, 0),   # HPP - Tiram Kecil (501)
                (15, 1500000, 0),   # HPP - Tiram Besar (502)
                (16, 300000, 0),    # Beban Gaji (503)
            ]
            
            for account_id, debit_amount, credit_amount in opening_balances:
                cur.execute('''
                    INSERT INTO opening_balances (account_id, debit_amount, credit_amount) 
                    VALUES (?, ?, ?)
                ''', (account_id, debit_amount, credit_amount))
                print(f"✅ Set opening balance for account {account_id}: Debit={debit_amount:,}, Credit={credit_amount:,}")
            
            # Hitung total untuk verifikasi
            total_debit = sum(balance[1] for balance in opening_balances)
            total_credit = sum(balance[2] for balance in opening_balances)
            print(f"📊 TOTAL DEBIT: {total_debit:,}")
            print(f"📊 TOTAL CREDIT: {total_credit:,}")
            print(f"📊 BALANCED: {total_debit == total_credit}")
            
            # BUAT USER ADMIN
            password_hash = bcrypt.hashpw(b'password', bcrypt.gensalt())
            cur.execute(
                'INSERT INTO users (username, password_hash, email) VALUES (?, ?, ?)',
                ('admin', password_hash, 'tiramine@gmail.com')
            )
            print("✅ User admin created: admin / password / tiramine@gmail.com")
            
            # Insert sample inventory data
            cur.execute('''
                INSERT INTO inventory (date, description, quantity_in, unit_cost, value)
                VALUES 
                ('2024-01-01', 'Stok awal tiram besar', 0, 55000, 0),
                ('2024-01-01', 'Stok awal tiram kecil', 0, 30000, 0)
            ''')
            print("✅ Sample inventory data created!")
            
            # Buat tabel transaction_templates
            cur.execute('''
                CREATE TABLE IF NOT EXISTS transaction_templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    template_key TEXT UNIQUE NOT NULL,
                    label TEXT NOT NULL,
                    description TEXT,
                    lines_json TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Insert default templates berdasarkan contoh transaksi
            templates = [
                {
                    'template_key': 'penjualan_tunai_besar',
                    'label': 'Penjualan Tunai (Tiram Besar)',
                    'description': 'Penjualan tiram besar secara tunai',
                    'lines_json': json.dumps([
                        {"account_code": "101", "side": "debit", "editable": False, "description": "Kas", "auto_calculate": False},
                        {"account_code": "401", "side": "credit", "editable": False, "description": "Penjualan - Tiram Besar", "auto_calculate": False}
                    ])
                },
                {
                    'template_key': 'penjualan_tunai_kecil', 
                    'label': 'Penjualan Tunai (Tiram Kecil)',
                    'description': 'Penjualan tiram kecil secara tunai',
                    'lines_json': json.dumps([
                        {"account_code": "101", "side": "debit", "editable": False, "description": "Kas", "auto_calculate": False},
                        {"account_code": "402", "side": "credit", "editable": False, "description": "Penjualan - Tiram Kecil", "auto_calculate": False}
                    ])
                },
                {
                    'template_key': 'penjualan_kredit_besar',
                    'label': 'Penjualan Kredit (Tiram Besar)',
                    'description': 'Penjualan tiram besar secara kredit',
                    'lines_json': json.dumps([
                        {"account_code": "102", "side": "debit", "editable": False, "description": "Piutang Usaha", "auto_calculate": False},
                        {"account_code": "401", "side": "credit", "editable": False, "description": "Penjualan - Tiram Besar", "auto_calculate": False}
                    ])
                },
                {
                    'template_key': 'pembayaran_gaji',
                    'label': 'Pembayaran Gaji Karyawan',
                    'description': 'Pembayaran gaji dan upah karyawan',
                    'lines_json': json.dumps([
                        {"account_code": "503", "side": "debit", "editable": False, "description": "Beban Gaji", "auto_calculate": False},
                        {"account_code": "101", "side": "credit", "editable": False, "description": "Kas", "auto_calculate": False}
                    ])
                },
                {
                    'template_key': 'pembelian_peralatan',
                    'label': 'Pembelian Peralatan',
                    'description': 'Pembelian peralatan tambak secara tunai',
                    'lines_json': json.dumps([
                        {"account_code": "103", "side": "debit", "editable": False, "description": "Peralatan Tambak", "auto_calculate": False},
                        {"account_code": "101", "side": "credit", "editable": False, "description": "Kas", "auto_calculate": False}
                    ])
                },
                {
                    'template_key': 'pelunasan_piutang',
                    'label': 'Pelunasan Piutang',
                    'description': 'Penerimaan pelunasan piutang usaha',
                    'lines_json': json.dumps([
                        {"account_code": "101", "side": "debit", "editable": False, "description": "Kas", "auto_calculate": False},
                        {"account_code": "102", "side": "credit", "editable": False, "description": "Piutang Usaha", "auto_calculate": False}
                    ])
                },
                {
                    'template_key': 'pembayaran_utang',
                    'label': 'Pembayaran Utang Usaha',
                    'description': 'Pembayaran utang kepada supplier',
                    'lines_json': json.dumps([
                        {"account_code": "201", "side": "debit", "editable": False, "description": "Utang Usaha", "auto_calculate": False},
                        {"account_code": "101", "side": "credit", "editable": False, "description": "Kas", "auto_calculate": False}
                    ])
                },
                {
                    'template_key': 'penyesuaian_persediaan',
                    'label': 'Penyesuaian Persediaan',
                    'description': 'Penyesuaian nilai persediaan tiram',
                    'lines_json': json.dumps([
                        {"account_code": "501", "side": "debit", "editable": True, "description": "HPP - Tiram Kecil", "auto_calculate": False},
                        {"account_code": "502", "side": "debit", "editable": True, "description": "HPP - Tiram Besar", "auto_calculate": False},
                        {"account_code": "105", "side": "credit", "editable": True, "description": "Persediaan - Tiram Kecil", "auto_calculate": False},
                        {"account_code": "106", "side": "credit", "editable": True, "description": "Persediaan - Tiram Besar", "auto_calculate": False}
                    ])
                }
            ]
            
            for template in templates:
                cur.execute('''
                    INSERT OR REPLACE INTO transaction_templates (template_key, label, description, lines_json)
                    VALUES (?, ?, ?, ?)
                ''', (template['template_key'], template['label'], template['description'], template['lines_json']))
            
            db.commit()
            print("🎉 Database initialization completed successfully!")
            print("💡 Access /trial_balance to verify the opening balances")
            
        except Exception as e:
            db.rollback()
            print(f"❌ Database initialization failed: {e}")
            raise

# ---------- Helper Autentikasi ----------

def current_user():
    try:
        uid = session.get('user_id')
        if not uid:
            return None
        
        db = get_db()
        cur = db.execute('SELECT id, username FROM users WHERE id=?', (uid,))
        user = cur.fetchone()
        
        # Convert sqlite3.Row to dict untuk konsistensi
        if user:
            return {'id': user['id'], 'username': user['username']}
        return None
    except Exception as e:
        print(f"Error in current_user: {e}")
        return None

def login_required(f):
    from functools import wraps
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not current_user():
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapped

def normalize_email(email: str) -> str:
    return (email or '').strip().lower()

def send_email_notification(to_email: str, subject: str, body_html: str):
    """Send email using SMTP settings from environment variables."""
    smtp_server = os.environ.get('SMTP_SERVER')
    smtp_port = int(os.environ.get('SMTP_PORT', 587))
    smtp_username = os.environ.get('SMTP_USERNAME')
    smtp_password = os.environ.get('SMTP_PASSWORD')

    print(f"Attempting to send email to {to_email} via {smtp_server}:{smtp_port} as {smtp_username} and password {'set' if smtp_password else 'not set'}")

    if not smtp_server or not smtp_username or not smtp_password:
        warning = 'SMTP belum dikonfigurasi. OTP tidak dapat dikirim.'
        print(warning)
        return False, warning

    message = MIMEMultipart('alternative')
    message['From'] = smtp_username
    message['To'] = to_email
    message['Subject'] = subject
    message.attach(MIMEText(body_html, 'html'))

    try:
        with smtplib.SMTP(smtp_server, smtp_port, timeout=20) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.send_message(message)
        return True, None
    except Exception as exc:
        error = f"Gagal mengirim email OTP: {exc}"
        print(error)
        return False, error

def generate_otp_code(length: int = 6) -> str:
    return ''.join(random.choice('0123456789') for _ in range(length))

def create_otp_for_email(email: str, validity_minutes: int = 10):
    code = generate_otp_code()
    expires_at = (datetime.utcnow() + timedelta(minutes=validity_minutes)).strftime('%Y-%m-%d %H:%M:%S')
    db = get_db()
    db.execute(
        'INSERT INTO otp_verification (email, otp_code, expires_at, used) VALUES (?, ?, ?, 0)',
        (email, code, expires_at)
    )
    db.commit()
    return code, expires_at

def verify_otp_code(email: str, otp_code: str):
    """Validate OTP entry and mark it as used when successful."""
    db = get_db()
    cur = db.execute(
        '''
        SELECT id, expires_at FROM otp_verification
        WHERE email = ? AND otp_code = ? AND used = 0
        ORDER BY id DESC LIMIT 1
        ''',
        (email, otp_code)
    )
    record = cur.fetchone()
    if not record:
        return False, 'OTP tidak ditemukan atau sudah digunakan.'

    try:
        expires_at_dt = datetime.strptime(record['expires_at'], '%Y-%m-%d %H:%M:%S')
    except ValueError:
        expires_at_dt = datetime.utcnow()

    if datetime.utcnow() > expires_at_dt:
        return False, 'OTP telah kedaluwarsa. Mohon minta kode baru.'

    db.execute('UPDATE otp_verification SET used = 1 WHERE id = ?', (record['id'],))
    db.commit()
    return True, None

# ---------- Utilitas Akuntansi ----------

def all_accounts():
    cur = get_db().execute('SELECT * FROM accounts ORDER BY code')
    return cur.fetchall()

def get_account_id(cur, code):
    """Mencari ID akun berdasarkan kode akun (misalnya '101', '401', dst)."""
    cur.execute("SELECT id FROM accounts WHERE code = ?", (code,))
    result = cur.fetchone()
    return result["id"] if result else None

def fix_opening_balances():
    """Memperbaiki saldo awal agar sesuai dengan prinsip akuntansi"""
    db = get_db()
    cur = db.cursor()
    
    # Hapus semua saldo awal yang ada
    cur.execute('DELETE FROM opening_balances')
    
    # DATA SALDO AWAL YANG BENAR - SESUAI DENGAN NERACA SALDO AWAL
    # Total harus balance: Debit = Credit = Rp 31.550.000
    opening_balances_corrected = [
        # ===== ASET (DEBIT) =====
        (1, 8500000, 0),     # Kas (101) - Debit
        (2, 4500000, 0),     # Piutang Usaha (102) - Debit
        (3, 500000, 0),      # Peralatan Tambak (103) - Debit
        (4, 300000, 0),      # Perlengkapan (104) - Debit
        (5, 1200000, 0),     # Persediaan - Tiram Kecil (105) - Debit
        (6, 1750000, 0),     # Persediaan - Tiram Besar (106) - Debit
        (7, 12000000, 0),    # Kendaraan (107) - Debit
        
        # ===== KONTRA ASET (CREDIT) =====
        (8, 0, 1500000),     # Akumulasi Penyusutan Kendaraan (108) - Credit
        
        # ===== KEWAJIBAN (CREDIT) =====
        (9, 0, 650000),      # Utang Usaha (201) - Credit
        (10, 0, 100000),     # Utang Gaji (202) - Credit
        
        # ===== EKUITAS (CREDIT) =====
        (11, 0, 22300000),   # Modal Pemilik (301) - Credit
        
        # ===== PENDAPATAN (CREDIT) =====
        (12, 0, 4000000),    # Penjualan - Tiram Besar (401) - Credit
        (13, 0, 3000000),    # Penjualan - Tiram Kecil (402) - Credit
        
        # ===== BEBAN (DEBIT) =====
        (14, 1000000, 0),    # HPP - Tiram Kecil (501) - Debit
        (15, 1500000, 0),    # HPP - Tiram Besar (502) - Debit
        (16, 300000, 0),     # Beban Gaji (503) - Debit
    ]
    
    # Insert saldo awal yang sudah dikoreksi
    for account_id, debit_amount, credit_amount in opening_balances_corrected:
        cur.execute('''
            INSERT INTO opening_balances (account_id, debit_amount, credit_amount) 
            VALUES (?, ?, ?)
        ''', (account_id, debit_amount, credit_amount))
    
    # Hitung total untuk verifikasi
    total_debit = sum(balance[1] for balance in opening_balances_corrected)
    total_credit = sum(balance[2] for balance in opening_balances_corrected)
    
    print(f"✅ SALDO AWAL DIPERBAIKI:")
    print(f"📊 TOTAL DEBIT: {total_debit:,}")
    print(f"📊 TOTAL CREDIT: {total_credit:,}")
    print(f"📊 BALANCED: {total_debit == total_credit}")
    print(f"📊 SELISIH: {abs(total_debit - total_credit):,}")
    
    db.commit()
    return total_debit == total_credit

def set_opening_balance(account_id, balance, balance_type):
    """Set saldo awal untuk akun tertentu"""
    db = get_db()
    cur = db.cursor()
    
    try:
        # Hapus saldo awal yang ada untuk akun ini
        cur.execute('DELETE FROM opening_balances WHERE account_id = ?', (account_id,))
        
        # Insert saldo awal baru
        cur.execute('''
            INSERT INTO opening_balances (account_id, balance, balance_type)
            VALUES (?, ?, ?)
        ''', (account_id, abs(balance), balance_type))
        
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        raise e

def get_opening_balance(account_id):
    """Dapatkan saldo awal untuk akun tertentu"""
    cur = get_db().execute('''
        SELECT balance, balance_type FROM opening_balances 
        WHERE account_id = ?
    ''', (account_id,))
    result = cur.fetchone()
    
    if result:
        if result['balance_type'] == 'Debit':
            return result['balance']
        else:
            return -result['balance']
    return 0

def get_account_balance(account_id, include_adjustments=True):
    """Mendapatkan saldo akun dengan benar - VERSI DIPERBAIKI"""
    db = get_db()
    
    # Dapatkan informasi akun
    account_cur = db.execute('SELECT * FROM accounts WHERE id = ?', (account_id,))
    account = account_cur.fetchone()
    if not account:
        return 0
    
    # 1. Dapatkan saldo awal - PERBAIKAN: gunakan struktur baru dengan benar
    opening_cur = db.execute(
        'SELECT debit_amount, credit_amount FROM opening_balances WHERE account_id = ?', 
        (account_id,)
    )
    opening = opening_cur.fetchone()
    
    opening_balance = 0
    if opening:
        # Sesuai dengan jenis akun, hitung saldo awal
        if account['normal_balance'] == 'Debit':
            opening_balance = opening['debit_amount'] - opening['credit_amount']
        else:
            opening_balance = opening['credit_amount'] - opening['debit_amount']
    
    # 2. Hitung total dari jurnal
    journal_cur = db.execute('''
        SELECT COALESCE(SUM(debit), 0) as total_debit, 
               COALESCE(SUM(credit), 0) as total_credit
        FROM journal_lines 
        WHERE account_id = ?
    ''', (account_id,))
    journal = journal_cur.fetchone()
    
    journal_net = 0
    if account['normal_balance'] == 'Debit':
        journal_net = journal['total_debit'] - journal['total_credit']
    else:
        journal_net = journal['total_credit'] - journal['total_debit']
    
    # 3. Hitung total dari penyesuaian (jika termasuk)
    adjusting_net = 0
    if include_adjustments:
        adjusting_cur = db.execute('''
            SELECT COALESCE(SUM(debit), 0) as total_debit, 
                   COALESCE(SUM(credit), 0) as total_credit
            FROM adjusting_lines 
            WHERE account_id = ?
        ''', (account_id,))
        adjusting = adjusting_cur.fetchone()
        
        if account['normal_balance'] == 'Debit':
            adjusting_net = adjusting['total_debit'] - adjusting['total_credit']
        else:
            adjusting_net = adjusting['total_credit'] - adjusting['total_debit']
    
    # Total saldo
    total_balance = opening_balance + journal_net + adjusting_net
    
    return total_balance

def post_journal_entry(date, description, lines, reference="", transaction_type="General", template_key=None):
    """Posting entri jurnal dengan validasi yang diperbaiki"""
    db = get_db()
    cur = db.cursor()
    
    try:
        # 1. VALIDASI SERVER-SIDE SEBELUM POSTING (dengan validasi yang diperbaiki)
        validation_errors = validate_journal_entry(lines, template_key)
        if validation_errors:
            raise ValueError("; ".join(validation_errors))
        
        # 2. Buat entri jurnal
        cur.execute('''
            INSERT INTO journal_entries (date, description, reference, transaction_type, posted) 
            VALUES (?, ?, ?, ?, 1)
        ''', (date, description, reference, transaction_type))
        entry_id = cur.lastrowid
        
        # 3. Tambahkan baris jurnal
        for line in lines:
            cur.execute('''
                INSERT INTO journal_lines (entry_id, account_id, debit, credit, description) 
                VALUES (?, ?, ?, ?, ?)
            ''', (entry_id, line['account_id'], line.get('debit', 0), line.get('credit', 0), line.get('description', '')))
        
        # 4. Periksa jenis transaksi untuk update inventory
        inventory_updated = False
        is_harvest_transaction = False
        
        # Cek apakah ini transaksi panen (menggunakan akun persediaan benih dan tiram)
        harvest_accounts = ['105', '106', '107', '108']  # Semua akun persediaan tiram dan benih
        for line in lines:
            account_id = line['account_id']
            cur.execute('SELECT code FROM accounts WHERE id = ?', (account_id,))
            account = cur.fetchone()
            
            if account and account['code'] in harvest_accounts:
                inventory_updated = True
                
            # Deteksi transaksi panen berdasarkan pola debit/kredit
            if account and account['code'] in ['105', '106'] and line.get('debit', 0) > 0:
                # Jika ada debit ke persediaan tiram (105/106), kemungkinan panen
                is_harvest_transaction = True
        
        # 5. Update inventory berdasarkan jenis transaksi
        if inventory_updated:
            if is_harvest_transaction:
                # Handle transaksi panen - tambah stok tiram
                for line in lines:
                    account_id = line['account_id']
                    cur.execute('SELECT code FROM accounts WHERE id = ?', (account_id,))
                    account = cur.fetchone()
                    
                    if account and account['code'] == '105':  # Persediaan Tiram Kecil
                        quantity = line['debit'] / 20000  # Harga Rp 20.000 per kg
                        if quantity > 0:
                            cur.execute('UPDATE settings SET v = v + ? WHERE k = "current_stock_small"', (quantity,))
                            # Tambah entry di inventory
                            cur.execute('''
                                INSERT INTO inventory (date, description, quantity_in, unit_cost, value)
                                VALUES (?, ?, ?, ?, ?)
                            ''', (date, f'Panen tiram kecil: {description}', quantity, 20000, line['debit']))
                    
                    elif account and account['code'] == '106':  # Persediaan Tiram Besar
                        quantity = line['debit'] / 35000  # Harga Rp 35.000 per kg
                        if quantity > 0:
                            cur.execute('UPDATE settings SET v = v + ? WHERE k = "current_stock_large"', (quantity,))
                            # Tambah entry di inventory
                            cur.execute('''
                                INSERT INTO inventory (date, description, quantity_in, unit_cost, value)
                                VALUES (?, ?, ?, ?, ?)
                            ''', (date, f'Panen tiram besar: {description}', quantity, 35000, line['debit']))
                    
                    elif account and account['code'] == '107':  # Persediaan Benih Kecil
                        quantity = line['credit'] / 20000  # Harga Rp 20.000 per kg
                        if quantity > 0:
                            cur.execute('UPDATE settings SET v = v - ? WHERE k = "current_seed_small"', (quantity,))
                            # Kurangi stok benih di inventory
                            cur.execute('''
                                INSERT INTO inventory (date, description, quantity_out, unit_cost, value)
                                VALUES (?, ?, ?, ?, ?)
                            ''', (date, f'Penggunaan benih kecil: {description}', quantity, 20000, line['credit']))
                    
                    elif account and account['code'] == '108':  # Persediaan Benih Besar
                        quantity = line['credit'] / 35000  # Harga Rp 35.000 per kg
                        if quantity > 0:
                            cur.execute('UPDATE settings SET v = v - ? WHERE k = "current_seed_large"', (quantity,))
                            # Kurangi stok benih di inventory
                            cur.execute('''
                                INSERT INTO inventory (date, description, quantity_out, unit_cost, value)
                                VALUES (?, ?, ?, ?, ?)
                            ''', (date, f'Penggunaan benih besar: {description}', quantity, 35000, line['credit']))
            
            else:
                # Handle transaksi penjualan/pembelian biasa
                update_inventory_from_journal(entry_id)
        
        db.commit()
        return entry_id
    except Exception as e:
        db.rollback()
        raise e
    
def validate_journal_entry(lines, template_key=None):
    """Validasi entri jurnal dengan aturan yang lebih realistis"""
    errors = []
    
    # 1. Validasi jumlah baris minimum
    if len(lines) < 2:
        errors.append("Entri jurnal harus memiliki setidaknya dua baris")
        return errors
    
    # 2. Validasi balance - TOTAL DEBIT HARUS SAMA DENGAN TOTAL KREDIT
    total_debit = sum(line.get('debit', 0) for line in lines)
    total_credit = sum(line.get('credit', 0) for line in lines)
    
    if abs(total_debit - total_credit) > 0.01:
        errors.append(f"Total debit ({total_debit:,.2f}) tidak sama dengan total kredit ({total_credit:,.2f})")
    
    # 3. Validasi duplicate accounts - MENCEGAH AKUN YANG SAMA DI DUA BARIS
    account_ids = [line['account_id'] for line in lines]
    if len(account_ids) != len(set(account_ids)):
        errors.append("Terdapat akun yang duplikat dalam entri yang sama")
    
    # 4. Validasi setiap baris individual - PERBAIKAN: lebih fleksibel
    for i, line in enumerate(lines):
        account_id = line['account_id']
        debit = line.get('debit', 0)
        credit = line.get('credit', 0)
        
        # Dapatkan informasi akun dari database
        cur = get_db().execute(
            'SELECT code, name, acct_type, normal_balance FROM accounts WHERE id = ?',
            (account_id,)
        )
        account = cur.fetchone()
        
        if not account:
            errors.append(f"Baris {i+1}: Akun ID {account_id} tidak ditemukan")
            continue
        
        # 4.1 Validasi hanya satu sisi yang terisi (tidak boleh debit dan kredit sekaligus)
        if debit > 0 and credit > 0:
            errors.append(f"Baris {i+1} ({account['name']}): Tidak boleh mengisi debit dan kredit sekaligus")
        
        # 4.2 Validasi jumlah harus positif
        if debit < 0 or credit < 0:
            errors.append(f"Baris {i+1} ({account['name']}): Jumlah harus positif")
        
        # 4.3 PERBAIKAN: HAPUS validasi normal balance yang terlalu ketat
        # Dalam akuntansi, akun bisa diisi di sisi berlawanan dengan saldo normal
        # Contoh: Kas (debit normal) bisa di kredit saat pembayaran
        # Jadi kita HAPUS validasi ini:
        # if debit > 0 and account['normal_balance'] == 'Credit':
        #     errors.append(f"Baris {i+1} ({account['name']}): Akun ini normalnya kredit, tidak boleh diisi di debit")
        # elif credit > 0 and account['normal_balance'] == 'Debit':
        #     errors.append(f"Baris {i+1} ({account['name']}): Akun ini normalnya debit, tidak boleh diisi di kredit")
        
        # 4.4 Validasi sisi yang konsisten dengan input (jika ada informasi sisi)
        if 'side' in line:
            if line['side'] == 'debit' and credit > 0:
                errors.append(f"Baris {i+1} ({account['name']}): Ditetapkan sebagai debit tetapi memiliki nilai kredit")
            elif line['side'] == 'credit' and debit > 0:
                errors.append(f"Baris {i+1} ({account['name']}): Ditetapkan sebagai kredit tetapi memiliki nilai debit")
    
    # 5. Validasi template compliance jika menggunakan template
    if template_key:
        template_errors = validate_template_compliance(lines, template_key)
        errors.extend(template_errors)
    
    return errors

def validate_template_compliance(lines, template_key):
    """Validasi compliance dengan template yang dipilih"""
    errors = []
    
    # Dapatkan template dari database
    cur = get_db().execute(
        'SELECT lines_json FROM transaction_templates WHERE template_key = ?',
        (template_key,)
    )
    template = cur.fetchone()
    
    if not template:
        errors.append("Template tidak ditemukan")
        return errors
    
    template_lines = json.loads(template['lines_json'])
    
    # Validasi setiap baris template yang non-editable
    for tpl_line in template_lines:
        if not tpl_line.get('editable', True):
            # Cari baris yang sesuai di submitted lines berdasarkan account_code
            matching_line = None
            for line in lines:
                # Dapatkan account_code dari account_id
                account_cur = get_db().execute(
                    'SELECT code FROM accounts WHERE id = ?',
                    (line['account_id'],)
                )
                account = account_cur.fetchone()
                
                if account and account['code'] == tpl_line['account_code']:
                    matching_line = line
                    break
            
            if not matching_line:
                errors.append(f"Baris template untuk akun {tpl_line['account_code']} tidak ditemukan dalam entri")
                continue
            
            # Validasi sisi tidak berubah untuk non-editable lines
            if 'side' in matching_line and matching_line['side'] != tpl_line['side']:
                errors.append(f"Akun {tpl_line['account_code']} harus di sisi {tpl_line['side']} sesuai template")
            
            # Validasi account_id tidak berubah untuk non-editable lines
            account_cur = get_db().execute(
                'SELECT code FROM accounts WHERE id = ?',
                (matching_line['account_id'],)
            )
            account = account_cur.fetchone()
            if account and account['code'] != tpl_line['account_code']:
                errors.append(f"Akun untuk baris template {tpl_line['account_code']} tidak boleh diubah")
    
    return errors

# Fungsi helper untuk mendapatkan account_id dari account_code
def get_account_id_from_code(account_code):
    """Mendapatkan account_id dari account_code"""
    cur = get_db().execute(
        'SELECT id FROM accounts WHERE code = ?',
        (account_code,)
    )
    account = cur.fetchone()
    return account['id'] if account else None

# Fungsi helper untuk mendapatkan account_code dari account_id  
def get_account_code_from_id(account_id):
    """Mendapatkan account_code dari account_id"""
    cur = get_db().execute(
        'SELECT code FROM accounts WHERE id = ?',
        (account_id,)
    )
    account = cur.fetchone()
    return account['code'] if account else None

def post_adjusting_entry(date, description, lines):
    """Posting entri penyesuaian"""
    db = get_db()
    cur = db.cursor()
    
    try:
        cur.execute('INSERT INTO adjusting_entries (date, description) VALUES (?, ?)', (date, description))
        adj_id = cur.lastrowid
        
        for line in lines:
            cur.execute('''
                INSERT INTO adjusting_lines (adj_id, account_id, debit, credit, description) 
                VALUES (?, ?, ?, ?, ?)
            ''', (adj_id, line['account_id'], line.get('debit', 0), line.get('credit', 0), line.get('description', '')))
        
        db.commit()
        return adj_id
    except Exception as e:
        db.rollback()
        raise e

def update_inventory_from_journal(entry_id):
    """Perbarui persediaan berdasarkan entri jurnal (untuk penjualan/pembelian)"""
    db = get_db()
    cur = db.cursor()
    
    # Dapatkan detail entri jurnal
    cur.execute('''
        SELECT jl.account_id, jl.debit, jl.credit, a.code, je.description, je.date
        FROM journal_lines jl
        JOIN accounts a ON jl.account_id = a.id
        JOIN journal_entries je ON jl.entry_id = je.id
        WHERE jl.entry_id = ?
    ''', (entry_id,))
    lines = cur.fetchall()
    
    # Periksa apakah ini transaksi penjualan (melibatkan persediaan dan pendapatan penjualan)
    has_inventory = any(line['code'] in ['103', '103.1'] for line in lines)
    has_sales = any(line['code'] in ['401', '401.1'] for line in lines)
    
    if has_inventory and has_sales:
        # Ini adalah transaksi penjualan - kurangi persediaan
        for line in lines:
            if line['code'] in ['103', '103.1']:  # Akun persediaan
                # Tentukan harga satuan berdasarkan jenis tiram
                if line['code'] == '103':  # Tiram Besar
                    unit_cost = 55000
                    inventory_type = "Tiram Besar"
                    stock_key = "current_stock_large"
                else:  # Tiram Kecil
                    unit_cost = 30000
                    inventory_type = "Tiram Kecil"
                    stock_key = "current_stock_small"
                
                quantity_sold = float(line['credit']) / float(unit_cost) if float(unit_cost) != 0 else 0
                
                if quantity_sold > 0:
                    cur.execute('''
                        INSERT INTO inventory (date, description, quantity_out, unit_cost, value)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (lines[0]['date'], f'Penjualan {inventory_type}: {lines[0]["description"]}', quantity_sold, unit_cost, float(line['credit'])))
                    
                    # Perbarui stok saat ini dalam pengaturan
                    cur.execute('SELECT v FROM settings WHERE k = ?', (stock_key,))
                    result = cur.fetchone()
                    current = float(result['v']) if result and result['v'] else 0
                    new_stock = max(0, current - quantity_sold)
                    cur.execute('UPDATE settings SET v = ? WHERE k = ?', (str(new_stock), stock_key))
    
    db.commit()

def get_current_stock(stock_type='all'):
    """Dapatkan stok tiram saat ini"""
    db = get_db()
    cur = db.cursor()
    
    if stock_type == 'large':
        cur.execute('SELECT v FROM settings WHERE k = "current_stock_large"')
        result = cur.fetchone()
        return int(result['v']) if result and result['v'] else 0
    elif stock_type == 'small':
        cur.execute('SELECT v FROM settings WHERE k = "current_stock_small"')
        result = cur.fetchone()
        return int(result['v']) if result and result['v'] else 0
    else:
        # Return dictionary dengan kedua stok
        cur.execute('SELECT v FROM settings WHERE k = "current_stock_large"')
        large_result = cur.fetchone()
        large = int(large_result['v']) if large_result and large_result['v'] else 0
        
        cur.execute('SELECT v FROM settings WHERE k = "current_stock_small"')
        small_result = cur.fetchone()
        small = int(small_result['v']) if small_result and small_result['v'] else 0
        
        return {
            'large': large,
            'small': small,
            'total': large + small
        }
    

def set_opening_balance(account_id, amount, balance_type):
    """Menyimpan saldo awal dengan benar"""
    db = get_db()
    
    # Hapus saldo lama jika ada
    db.execute('DELETE FROM opening_balances WHERE account_id = ?', (account_id,))
    
    # Insert saldo baru
    if amount > 0:
        if balance_type == 'Debit':
            db.execute('''
                INSERT INTO opening_balances (account_id, debit_amount, credit_amount)
                VALUES (?, ?, 0)
            ''', (account_id, amount))
        else:
            db.execute('''
                INSERT INTO opening_balances (account_id, debit_amount, credit_amount)
                VALUES (?, 0, ?)
            ''', (account_id, amount))
    
    db.commit()

def get_opening_balance(account_id):
    """Dapatkan saldo awal untuk akun tertentu - VERSI DIPERBAIKI"""
    cur = get_db().execute('''
        SELECT balance, balance_type FROM opening_balances 
        WHERE account_id = ?
    ''', (account_id,))
    result = cur.fetchone()
    
    if result:
        # PERBAIKAN: Return dengan tanda yang benar
        if result['balance_type'] == 'Debit':
            return result['balance']  # Positif untuk debit
        else:
            return -result['balance']  # Negatif untuk kredit
    return 0

def get_company_info():
    """Dapatkan informasi perusahaan dari pengaturan"""
    cur = get_db().execute('SELECT k, v FROM settings WHERE k IN ("company_name", "company_description", "company_location")')
    info = {row['k']: row['v'] for row in cur.fetchall()}
    return info

def recover_possible_data():
    """Attempt to recover any unsaved data"""
    try:
        db = get_db()
        # Check if there are any uncommitted journal entries
        cur = db.execute('''
            SELECT COUNT(*) as count FROM journal_entries 
            WHERE id NOT IN (SELECT DISTINCT entry_id FROM journal_lines)
        ''')
        orphaned_entries = cur.fetchone()['count']
        
        if orphaned_entries > 0:
            print(f"🔄 Found {orphaned_entries} orphaned entries, attempting recovery...")
            # Delete orphaned entries
            db.execute('DELETE FROM journal_entries WHERE id NOT IN (SELECT DISTINCT entry_id FROM journal_lines)')
            db.commit()
            print("✅ Orphaned entries cleaned up")
            
        return True
    except Exception as e:
        print(f"❌ Recovery failed: {e}")
        return False

# Call recovery on startup
def startup_tasks():
    """Run recovery tasks on startup"""
    print("🔧 Running startup recovery tasks...")
    try:
        with app.app_context():
            recover_possible_data()
        print("✅ Startup tasks completed")
    except Exception as e:
        print(f"❌ Startup tasks failed: {e}")

# Run startup tasks
startup_tasks()


# ---------- Pelaporan Keuangan ----------

def trial_balance(include_adjustments=False):
    """Menghasilkan neraca saldo dengan format yang benar - VERSI DIPERBAIKI"""
    accounts = all_accounts()
    trial_balance_data = []
    total_debit = 0
    total_credit = 0
    
    for account in accounts:
        # Dapatkan saldo akun
        balance = get_account_balance(account['id'], include_adjustments)
        
        # Tentukan apakah saldo normalnya Debit atau Kredit
        if account['normal_balance'] == 'Debit':
            # Untuk akun dengan saldo normal Debit (Asset, Expense)
            if balance >= 0:
                debit = balance
                credit = 0
            else:
                debit = 0
                credit = abs(balance)
        else:
            # Untuk akun dengan saldo normal Kredit (Liability, Equity, Revenue)
            if balance >= 0:
                debit = 0
                credit = balance
            else:
                debit = abs(balance)
                credit = 0
        
        # Hanya tampilkan akun yang memiliki saldo
        if debit != 0 or credit != 0:
            trial_balance_data.append({
                'account': account,
                'debit': debit,
                'credit': credit
            })
            total_debit += debit
            total_credit += credit
    
    return trial_balance_data, total_debit, total_credit

def equity_statement(include_adjustments=True):
    """Hasilkan laporan perubahan modal"""
    db = get_db()
    cur = db.cursor()
    
    # Dapatkan saldo awal modal
    cur.execute('SELECT id FROM accounts WHERE code = "301" OR name LIKE "%Modal Pemilik%"')
    capital_account = cur.fetchone()
    beginning_capital = get_account_balance(capital_account['id'], include_adjustments) if capital_account else 0
    
    # Dapatkan laba bersih
    inc_stmt = income_statement(include_adjustments)
    net_income = inc_stmt['net_income']
    
    # Dapatkan prive/penarikan
    cur.execute('SELECT id FROM accounts WHERE code = "302" OR name LIKE "%Prive%"')
    drawing_account = cur.fetchone()
    drawings = abs(get_account_balance(drawing_account['id'], include_adjustments)) if drawing_account else 0
    
    # Hitung saldo akhir modal
    ending_capital = beginning_capital + net_income - drawings
    
    return {
        'beginning_capital': beginning_capital,
        'net_income': net_income,
        'drawings': drawings,
        'ending_capital': ending_capital
    }

def income_statement(include_adjustments=True):
    """Hasilkan laporan laba rugi - VERSI YANG DIPERBAIKI"""
    db = get_db()
    cur = db.cursor()
    
    # Hitung total pendapatan
    cur.execute('''
        SELECT COALESCE(SUM(jl.credit), 0) - COALESCE(SUM(jl.debit), 0) as net
        FROM journal_lines jl
        JOIN accounts a ON jl.account_id = a.id
        WHERE a.code LIKE '4%'
    ''')
    revenue_journal = cur.fetchone()['net']
    
    cur.execute('''
        SELECT COALESCE(SUM(al.credit), 0) - COALESCE(SUM(al.debit), 0) as net
        FROM adjusting_lines al
        JOIN accounts a ON al.account_id = a.id
        WHERE a.code LIKE '4%'
    ''')
    revenue_adjusting = cur.fetchone()['net'] if include_adjustments else 0
    
    total_revenue = revenue_journal + revenue_adjusting
    
    # Hitung total beban
    cur.execute('''
        SELECT COALESCE(SUM(jl.debit), 0) - COALESCE(SUM(jl.credit), 0) as net
        FROM journal_lines jl
        JOIN accounts a ON jl.account_id = a.id
        WHERE a.code LIKE '5%'
    ''')
    expense_journal = cur.fetchone()['net']
    
    cur.execute('''
        SELECT COALESCE(SUM(al.debit), 0) - COALESCE(SUM(al.credit), 0) as net
        FROM adjusting_lines al
        JOIN accounts a ON al.account_id = a.id
        WHERE a.code LIKE '5%'
    ''')
    expense_adjusting = cur.fetchone()['net'] if include_adjustments else 0
    
    total_expense = expense_journal + expense_adjusting
    
    net_income = total_revenue - total_expense
    
    return {
        'revenues': [],
        'expenses': [],
        'total_revenue': total_revenue,
        'total_expense': total_expense,
        'net_income': net_income
    }

def balance_sheet(include_adjustments=True):
    """Hasilkan neraca - VERSI YANG DIPERBAIKI"""
    db = get_db()
    cur = db.cursor()
    
    # Aset (seri 100)
    cur.execute('''
        SELECT COALESCE(SUM(jl.debit), 0) - COALESCE(SUM(jl.credit), 0) as journal_balance
        FROM journal_lines jl
        JOIN accounts a ON jl.account_id = a.id
        WHERE a.code LIKE '1%'
    ''')
    assets_journal = cur.fetchone()['journal_balance']
    
    cur.execute('''
        SELECT COALESCE(SUM(al.debit), 0) - COALESCE(SUM(al.credit), 0) as adjusting_balance
        FROM adjusting_lines al
        JOIN accounts a ON al.account_id = a.id
        WHERE a.code LIKE '1%'
    ''')
    assets_adjusting = cur.fetchone()['adjusting_balance'] if include_adjustments else 0
    
    total_assets = assets_journal + assets_adjusting
    
    # Kewajiban (seri 200)
    cur.execute('''
        SELECT COALESCE(SUM(jl.credit), 0) - COALESCE(SUM(jl.debit), 0) as journal_balance
        FROM journal_lines jl
        JOIN accounts a ON jl.account_id = a.id
        WHERE a.code LIKE '2%'
    ''')
    liabilities_journal = cur.fetchone()['journal_balance']
    
    cur.execute('''
        SELECT COALESCE(SUM(al.credit), 0) - COALESCE(SUM(al.debit), 0) as adjusting_balance
        FROM adjusting_lines al
        JOIN accounts a ON al.account_id = a.id
        WHERE a.code LIKE '2%'
    ''')
    liabilities_adjusting = cur.fetchone()['adjusting_balance'] if include_adjustments else 0
    
    total_liabilities = liabilities_journal + liabilities_adjusting
    
    # Ekuitas (seri 300)
    cur.execute('''
        SELECT COALESCE(SUM(jl.credit), 0) - COALESCE(SUM(jl.debit), 0) as journal_balance
        FROM journal_lines jl
        JOIN accounts a ON jl.account_id = a.id
        WHERE a.code LIKE '3%'
    ''')
    equity_journal = cur.fetchone()['journal_balance']
    
    cur.execute('''
        SELECT COALESCE(SUM(al.credit), 0) - COALESCE(SUM(al.debit), 0) as adjusting_balance
        FROM adjusting_lines al
        JOIN accounts a ON al.account_id = a.id
        WHERE a.code LIKE '3%'
    ''')
    equity_adjusting = cur.fetchone()['adjusting_balance'] if include_adjustments else 0
    
    total_equity = equity_journal + equity_adjusting
    
    # Tambahkan laba bersih ke ekuitas
    inc_stmt = income_statement(include_adjustments)
    total_equity += inc_stmt['net_income']
    
    return {
        'assets': [],
        'liabilities': [],
        'equity': [],
        'total_assets': total_assets,
        'total_liabilities': total_liabilities,
        'total_equity': total_equity,
        'net_income': inc_stmt['net_income']
    }

def cash_flow_statement():
    """Hasilkan laporan arus kas yang lebih akurat"""
    db = get_db()
    cur = db.cursor()
    
    # Aktivitas operasi - Pendapatan dan beban tunai
    cur.execute('''
        SELECT 
            SUM(CASE WHEN a.code LIKE '4%' THEN jl.credit ELSE 0 END) -
            SUM(CASE WHEN a.code LIKE '4%' THEN jl.debit ELSE 0 END) as net_revenue,
            SUM(CASE WHEN a.code LIKE '5%' THEN jl.debit ELSE 0 END) -
            SUM(CASE WHEN a.code LIKE '5%' THEN jl.credit ELSE 0 END) as net_expenses
        FROM journal_lines jl
        JOIN accounts a ON jl.account_id = a.id
    ''')
    operating = cur.fetchone()
    net_cash_operating = (operating['net_revenue'] or 0) - (operating['net_expenses'] or 0)
    
    # Aktivitas investasi - Pembelian/perolehan aset tetap
    cur.execute('''
        SELECT 
            SUM(CASE WHEN a.code = '104' THEN jl.debit ELSE 0 END) as equipment_purchase,
            SUM(CASE WHEN a.code = '104' THEN jl.credit ELSE 0 END) as equipment_sale
        FROM journal_lines jl
        JOIN accounts a ON jl.account_id = a.id
    ''')
    investing = cur.fetchone()
    net_cash_investing = (investing['equipment_sale'] or 0) - (investing['equipment_purchase'] or 0)
    
    # Aktivitas pendanaan - Modal dan pinjaman
    cur.execute('''
        SELECT 
            SUM(CASE WHEN a.code = '301' THEN jl.credit ELSE 0 END) as capital_contribution,
            SUM(CASE WHEN a.code = '302' THEN jl.debit ELSE 0 END) as drawings,
            SUM(CASE WHEN a.code = '202' THEN jl.credit ELSE 0 END) as loans_received,
            SUM(CASE WHEN a.code = '202' THEN jl.debit ELSE 0 END) as loans_paid
        FROM journal_lines jl
        JOIN accounts a ON jl.account_id = a.id
    ''')
    financing = cur.fetchone()
    net_cash_financing = (
        (financing['capital_contribution'] or 0) - 
        (financing['drawings'] or 0) + 
        (financing['loans_received'] or 0) - 
        (financing['loans_paid'] or 0)
    )
    
    net_cash_flow = net_cash_operating + net_cash_investing + net_cash_financing
    
    return {
        'operating_activities': {
            'net_cash': net_cash_operating,
            'revenue': operating['net_revenue'] or 0,
            'expenses': operating['net_expenses'] or 0
        },
        'investing_activities': {
            'net_cash': net_cash_investing,
            'equipment_purchase': investing['equipment_purchase'] or 0,
            'equipment_sale': investing['equipment_sale'] or 0
        },
        'financing_activities': {
            'net_cash': net_cash_financing,
            'capital_contribution': financing['capital_contribution'] or 0,
            'drawings': financing['drawings'] or 0,
            'loans_received': financing['loans_received'] or 0,
            'loans_paid': financing['loans_paid'] or 0
        },
        'net_cash_flow': net_cash_flow
    }

def get_closing_entries():
    """Buat entri jurnal penutup untuk menutup akun nominal (pendapatan dan beban)"""
    db = get_db()
    cur = db.cursor()
    
    # Hitung total pendapatan dan beban
    cur.execute('''
        SELECT 
            SUM(CASE WHEN a.code LIKE '4%' THEN jl.credit - jl.debit ELSE 0 END) as net_revenue,
            SUM(CASE WHEN a.code LIKE '5%' THEN jl.debit - jl.credit ELSE 0 END) as net_expense
        FROM journal_lines jl
        JOIN accounts a ON jl.account_id = a.id
    ''')
    result = cur.fetchone()
    
    net_revenue = result['net_revenue'] or 0
    net_expense = result['net_expense'] or 0
    net_income = net_revenue - net_expense
    
    closing_entries = []
    
    # 1. Tutup akun pendapatan ke Ikhtisar Laba Rugi
    if net_revenue > 0:
        cur.execute('SELECT id FROM accounts WHERE code LIKE "4%" AND acct_type = "Revenue"')
        revenue_accounts = cur.fetchall()
        
        for account in revenue_accounts:
            account_balance = get_account_balance(account['id'])
            if account_balance > 0:
                closing_entries.append({
                    'account_id': account['id'],
                    'debit': 0,
                    'credit': account_balance,
                    'description': f'Penutupan pendapatan'
                })
    
    # 2. Tutup akun beban ke Ikhtisar Laba Rugi
    if net_expense > 0:
        cur.execute('SELECT id FROM accounts WHERE code LIKE "5%" AND acct_type = "Expense"')
        expense_accounts = cur.fetchall()
        
        for account in expense_accounts:
            account_balance = get_account_balance(account['id'])
            if account_balance > 0:
                closing_entries.append({
                    'account_id': account['id'],
                    'debit': account_balance,
                    'credit': 0,
                    'description': f'Penutupan beban'
                })
    
    # 3. Tutup Ikhtisar Laba Rugi ke Laba Ditahan
    if net_income != 0:
        # Cari akun Ikhtisar Laba Rugi atau Laba Ditahan
        cur.execute('SELECT id FROM accounts WHERE code = "303" OR name LIKE "%Laba Ditahan%"')
        retained_earnings = cur.fetchone()
        
        if retained_earnings:
            if net_income > 0:
                # Laba bersih - tambah ke Laba Ditahan
                closing_entries.append({
                    'account_id': retained_earnings['id'],
                    'debit': 0,
                    'credit': net_income,
                    'description': f'Laba bersih periode berjalan'
                })
            else:
                # Rugi bersih - kurangi dari Laba Ditahan
                closing_entries.append({
                    'account_id': retained_earnings['id'],
                    'debit': abs(net_income),
                    'credit': 0,
                    'description': f'Rugi bersih periode berjalan'
                })
    
    return closing_entries, net_income

def get_post_closing_trial_balance():
    """Hasilkan neraca saldo setelah penutupan (hanya akun riil)"""
    accounts = all_accounts()
    pctb_data = []
    total_debit = 0
    total_credit = 0
    
    for account in accounts:
        # Hanya akun riil (Asset, Liability, Equity) yang ada di neraca saldo penutup
        if account['acct_type'] in ('Asset', 'Liability', 'Equity'):
            balance = get_account_balance(account['id'], include_adjustments=True)
            
            if account['normal_balance'] == 'Debit':
                debit = balance if balance > 0 else 0
                credit = -balance if balance < 0 else 0
            else:
                debit = -balance if balance < 0 else 0
                credit = balance if balance > 0 else 0
            
            pctb_data.append({
                'account': account,
                'debit': debit,
                'credit': credit
            })
            
            total_debit += debit
            total_credit += credit
    
    return pctb_data, total_debit, total_credit

def post_closing_entries():
    """Posting entri jurnal penutup"""
    closing_entries, net_income = get_closing_entries()
    
    if not closing_entries:
        return None, 0
    
    db = get_db()
    cur = db.cursor()
    
    try:
        # Buat entri jurnal penutup
        cur.execute('''
            INSERT INTO journal_entries (date, description, reference, transaction_type, posted) 
            VALUES (?, ?, ?, ?, 1)
        ''', (datetime.now().date().isoformat(), 'Jurnal Penutup - Akhir Periode', 'CLOSING', 'Closing Entry'))
        entry_id = cur.lastrowid
        
        # Tambahkan baris jurnal penutup
        for entry in closing_entries:
            cur.execute('''
                INSERT INTO journal_lines (entry_id, account_id, debit, credit, description) 
                VALUES (?, ?, ?, ?, ?)
            ''', (entry_id, entry['account_id'], entry.get('debit', 0), entry.get('credit', 0), entry.get('description', '')))
        
        db.commit()
        return entry_id, net_income
    except Exception as e:
        db.rollback()
        raise e
    
# ---------- Template HTML ----------

BASE_TEMPLATE = """
<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Tiramine - {{title}}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
    <style>
        /* Tiramine Design System - Enhanced with More Gradients & Lime */
        :root {
            /* Enhanced Color Palette */
            --primary-blue: #2563eb;
            --blue-dark: #1e40af;
            --blue-light: #3b82f6;
            --electric-blue: #1d4ed8;
            --neon-cyan: #22d3ee;
            --cyan-light: #67e8f9;
            --lime-neon: #c6ff4d;
            --lime-bright: #d8ff66;
            --lime-electric: #b4ff39;
            --deep-navy: #0f172a;
            --dark-navy: #1e293b;
            --midnight: #0a0f2a;
            --white: #ffffff;
            --off-white: #f8fafc;
            --gray-light: #e2e8f0;
            --gray-medium: #94a3b8;
            --red-alert: #ef4444;
            --red-dark: #dc2626;
            
            /* Super Enhanced Gradients */
            --hero-gradient: linear-gradient(135deg, #1e40af 0%, #1e293b 50%, #0f172a 100%);
            --sidebar-gradient: linear-gradient(180deg, #1e40af 0%, #1e293b 100%);
            --card-gradient: linear-gradient(145deg, rgba(255,255,255,0.98) 0%, rgba(248,250,252,0.95) 100%);
            --button-gradient: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
            --button-hover: linear-gradient(135deg, #1d4ed8 0%, #1e40af 100%);
            --accent-gradient: linear-gradient(135deg, #22d3ee 0%, #c6ff4d 100%);
            --lime-gradient: linear-gradient(135deg, #c6ff4d 0%, #b4ff39 100%);
            --electric-gradient: linear-gradient(135deg, #1d4ed8 0%, #c6ff4d 50%, #22d3ee 100%);
            --neon-gradient: linear-gradient(135deg, #c6ff4d 0%, #22d3ee 100%);
            --glass-gradient: linear-gradient(135deg, rgba(255,255,255,0.15) 0%, rgba(255,255,255,0.05) 100%);
            --wave-gradient: linear-gradient(90deg, transparent 0%, rgba(198,255,77,0.2) 50%, transparent 100%);
            --red-gradient: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
            
            /* Enhanced Spacing System */
            --space-1: 0.25rem;
            --space-2: 0.5rem;
            --space-3: 0.75rem;
            --space-4: 1rem;
            --space-5: 1.25rem;
            --space-6: 1.5rem;
            --space-8: 2rem;
            --space-10: 2.5rem;
            --space-12: 3rem;
            --space-16: 4rem;
            --space-20: 5rem;
            
            /* Border Radius */
            --radius-sm: 0.375rem;
            --radius-md: 0.5rem;
            --radius-lg: 0.75rem;
            --radius-xl: 1rem;
            --radius-2xl: 1.5rem;
            --radius-3xl: 2rem;
            
            /* Enhanced Shadows */
            --shadow-sm: 0 1px 3px 0 rgba(0, 0, 0, 0.1);
            --shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
            --shadow-lg: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
            --shadow-xl: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
            --shadow-neon: 0 0 25px rgba(198, 255, 77, 0.4);
            --shadow-electric: 0 0 30px rgba(34, 211, 238, 0.3);
            --shadow-glow: 0 0 35px rgba(198, 255, 77, 0.3);
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }

        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 50%, #ecfdf5 100%);
            color: var(--deep-navy);
            line-height: 1.6;
            min-height: 100vh;
            overflow-x: hidden;
        }

        /* Enhanced Background Effects */
        .bg-waves {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            pointer-events: none;
            z-index: -1;
            opacity: 0.4;
        }

        .wave {
            position: absolute;
            bottom: 0;
            left: 0;
            width: 100%;
            height: 120px;
            background: var(--wave-gradient);
            animation: waveMove 10s ease-in-out infinite;
        }

        .wave:nth-child(2) {
            animation-delay: -3s;
            opacity: 0.6;
            background: linear-gradient(90deg, transparent 0%, rgba(34,211,238,0.15) 50%, transparent 100%);
        }

        .wave:nth-child(3) {
            animation-delay: -6s;
            opacity: 0.3;
            background: linear-gradient(90deg, transparent 0%, rgba(29,78,216,0.1) 50%, transparent 100%);
        }

        @keyframes waveMove {
            0%, 100% { transform: translateX(0) scaleY(1); }
            50% { transform: translateX(-30px) scaleY(1.1); }
        }

        /* Enhanced Sidebar */
        .sidebar {
            background: var(--sidebar-gradient);
            min-height: 100vh;
            width: 260px; /* Diperkecil dari 280px */
            position: fixed;
            left: 0;
            top: 0;
            z-index: 1000;
            box-shadow: var(--shadow-xl);
            border-right: 1px solid rgba(255, 255, 255, 0.1);
            backdrop-filter: blur(20px);
            overflow-y: auto; /* Tambahkan scroll jika konten panjang */
            max-height: 100vh; /* Batasi tinggi maksimal */
        }

        .logo {
        padding: var(--space-8) var(--space-6) var(--space-6); /* Diperkecil sedikit */
        text-align: center;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            margin-bottom: var(--space-4); /* Diperkecil */
        }

        .logo i {
            font-size: 2rem; /* Diperkecil dari 2.5rem */
            background: var(--electric-gradient);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            margin-bottom: var(--space-3); /* Diperkecil */
            display: block;
        }

        .logo-text {
            font-size: 1.5rem; /* Diperkecil dari 1.75rem */
            font-weight: 800;
            background: var(--electric-gradient);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            letter-spacing: -0.025em;
        }

        .nav-links {
            padding: 0 var(--space-4);
            padding-bottom: var(--space-6); /* Tambahkan padding bawah */
        }

        .nav-item {
            margin-bottom: var(--space-2); /* Diperkecil dari var(--space-3) */
        }

        .nav-link {
            display: flex;
            align-items: center;
            padding: var(--space-3) var(--space-4); /* Diperkecil dari var(--space-4) var(--space-5) */
            color: rgba(255, 255, 255, 0.85);
            text-decoration: none;
            border-radius: var(--radius-xl);
            transition: all 0.3s ease;
            font-weight: 600;
            position: relative;
            overflow: hidden;
            border: 1px solid transparent;
            font-size: 0.9rem; /* Tambahkan ukuran font lebih kecil */
        }
        .nav-link::before {
            content: '';
            position: absolute;
            left: 0;
            top: 0;
            height: 100%;
            width: 4px;
            background: var(--lime-gradient);
            transform: scaleY(0);
            transition: transform 0.3s ease;
            border-radius: var(--radius-sm);
        }

        .nav-link:hover {
            color: var(--lime-bright);
            background: rgba(198, 255, 77, 0.1);
            transform: translateX(8px);
            border-color: rgba(198, 255, 77, 0.2);
        }

        .nav-link:hover::before {
            transform: scaleY(1);
        }

        .nav-link.active {
            color: var(--lime-neon);
            background: rgba(198, 255, 77, 0.15);
            box-shadow: var(--shadow-neon);
            border-color: rgba(198, 255, 77, 0.3);
        }

        .nav-link.active::before {
            transform: scaleY(1);
        }

        .nav-link i {
            width: 22px;
            margin-right: var(--space-4);
            font-size: 1.2rem;
        }

        .nav-link.reset-link {
            color: #fca5a5;
            border-color: rgba(239, 68, 68, 0.3);
        }

        .nav-link.reset-link:hover {
            color: #fef2f2;
            background: rgba(239, 68, 68, 0.15);
            box-shadow: 0 0 20px rgba(239, 68, 68, 0.3);
        }

       /* Enhanced Main Content Layout */
        .main-content {
            margin-left: 260px;
            min-height: 100vh;
            background: transparent;
        }

        .content-container {
            padding: var(--space-8);
            max-width: 1400px;
            margin: 0 auto;
        }

        /* Enhanced Card Consistency */
        .card {
            background: var(--card-gradient);
            border: 1px solid rgba(255, 255, 255, 0.9);
            border-radius: 12px;
            box-shadow: var(--shadow-lg);
            backdrop-filter: blur(20px);
            transition: all 0.22s cubic-bezier(0.2, 0.9, 0.3, 1);
            position: relative;
            overflow: hidden;
        }

        .card:hover {
            transform: translateY(-6px);
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.08), var(--shadow-glow);
        }

        /* Enhanced Stat Card dengan Hover Effect yang Konsisten */
        .stat-card {
            background: var(--card-gradient);
            border-radius: 12px;
            padding: var(--space-6);
            text-align: center;
            border: 1px solid rgba(255, 255, 255, 0.9);
            box-shadow: var(--shadow-lg);
            transition: all 0.22s cubic-bezier(0.2, 0.9, 0.3, 1);
            position: relative;
            overflow: hidden;
            height: 100%;
        }

        .stat-card::before {
            content: '';
            position: absolute;
            top: 0;
            left: -100%;
            width: 100%;
            height: 100%;
            background: var(--electric-gradient);
            opacity: 0.1;
            transition: left 0.4s ease;
        }

        .stat-card::after {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 4px;
            background: var(--electric-gradient);
            background-size: 200% 200%;
            animation: gradientShift 3s ease infinite;
            transform: scaleX(0);
            transition: transform 0.4s ease;
        }

        .stat-card:hover {
            transform: translateY(-6px);
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.08), var(--shadow-glow);
            border-color: var(--lime-neon);
        }

        .stat-card:hover::before {
            left: 0;
        }

        .stat-card:hover::after {
            transform: scaleX(1);
        }

        .stat-icon {
            width: 60px;
            height: 60px;
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto var(--space-4);
            font-size: 1.5rem;
            box-shadow: var(--shadow-md);
            transition: all 0.22s cubic-bezier(0.2, 0.9, 0.3, 1);
            position: relative;
            z-index: 2;
        }

        .stat-card:hover .stat-icon {
            transform: scale(1.05);
            box-shadow: var(--shadow-neon);
        }

        .stat-number {
            font-size: 2.5rem;
            font-weight: 800;
            margin-bottom: var(--space-2);
            line-height: 1;
            position: relative;
            z-index: 2;
        }

        .stat-label {
            font-size: 1rem;
            font-weight: 600;
            margin-bottom: var(--space-1);
            position: relative;
            z-index: 2;
        }

        @keyframes gradientShift {
            0%, 100% {
                background-position: 0% 50%;
            }
            50% {
                background-position: 100% 50%;
            }
        }

        /* Enhanced Quick Action Card */
        .quick-action-card {
            background: var(--card-gradient);
            border-radius: 12px;
            padding: var(--space-5);
            text-align: center;
            border: 1px solid rgba(255, 255, 255, 0.9);
            box-shadow: var(--shadow-lg);
            transition: all 0.22s cubic-bezier(0.2, 0.9, 0.3, 1);
            position: relative;
            overflow: hidden;
            height: 100%;
            color: inherit;
            text-decoration: none;
        }

        .quick-action-card:hover {
            transform: translateY(-6px);
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.08), var(--shadow-glow);
            text-decoration: none;
            color: inherit;
        }

        .quick-action-icon {
            width: 80px;
            height: 80px;
            border-radius: 16px;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto var(--space-4);
            font-size: 2rem;
            box-shadow: var(--shadow-lg);
            transition: all 0.22s cubic-bezier(0.2, 0.9, 0.3, 1);
        }

        .quick-action-card:hover .quick-action-icon {
            transform: scale(1.05);
        }

        .quick-action-title {
            font-weight: 800;
            margin-bottom: var(--space-2);
            color: var(--deep-navy);
            font-size: 1.25rem;
        }

        .quick-action-desc {
            font-size: 0.9rem;
            color: var(--gray-medium);
        }

        /* Button Consistency */
        .btn {
            border: none;
            border-radius: 8px;
            padding: var(--space-3) var(--space-6);
            font-weight: 600;
            font-size: 0.9rem;
            transition: all 0.22s cubic-bezier(0.2, 0.9, 0.3, 1);
            position: relative;
            overflow: hidden;
        }

        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        }

        .btn:focus {
            outline: 2px solid var(--primary-blue);
            outline-offset: 2px;
        }

        /* Responsive Design */
        @media (max-width: 768px) {
            .main-content {
                margin-left: 0;
            }
            
            .content-container {
                padding: var(--space-4);
            }
            
            .stat-number {
                font-size: 2rem;
            }
            
            .quick-action-icon {
                width: 60px;
                height: 60px;
                font-size: 1.5rem;
            }
            
            .page-title {
                font-size: 1.75rem;
            }
        }

        /* Alignment Utilities */
        .align-items-stretch {
            align-items: stretch !important;
        }

        .h-100 {
            height: 100% !important;
        }

        /* Dropdown Styling */
        .dropdown-menu {
            border-radius: 8px;
            box-shadow: var(--shadow-lg);
            border: 1px solid rgba(255, 255, 255, 0.9);
        }

        .dropdown-item {
            padding: var(--space-2) var(--space-4);
            font-size: 0.875rem;
            transition: all 0.2s ease;
        }

        .dropdown-item:hover {
            background-color: rgba(37, 99, 235, 0.1);
        }

        /* Enhanced Navbar dengan Better Spacing */
        .navbar {
            background: rgba(255, 255, 255, 0.92);
            backdrop-filter: blur(30px);
            border-bottom: 1px solid var(--gray-light);
            padding: var(--space-6) var(--space-10);
            position: sticky;
            top: 0;
            z-index: 100;
            box-shadow: var(--shadow-sm);
        }

        .navbar-content {
            display: flex;
            justify-content: space-between;
            align-items: center;
            max-width: 1400px;
            margin: 0 auto;
            gap: var(--space-6);
        }

        .page-header-content {
            flex: 1;
        }

        .page-title {
            font-size: 2rem;
            font-weight: 800;
            background: var(--electric-gradient);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            margin-bottom: var(--space-2);
            line-height: 1.2;
        }

        .page-subtitle {
            color: var(--gray-medium);
            font-size: 1rem;
            margin-top: var(--space-2);
            font-weight: 500;
        }

        .user-menu {
            display: flex;
            align-items: center;
            gap: var(--space-6);
            padding-left: var(--space-6);
            border-left: 2px solid var(--gray-light);
        }

        .user-avatar {
            width: 48px;
            height: 48px;
            border-radius: 50%;
            background: var(--electric-gradient);
            display: flex;
            align-items: center;
            justify-content: center;
            color: var(--white);
            font-weight: 700;
            font-size: 1.1rem;
            box-shadow: var(--shadow-lg);
            border: 3px solid var(--white);
            transition: all 0.3s ease;
        }

        .user-avatar:hover {
            transform: scale(1.05);
            box-shadow: var(--shadow-glow);
        }

        .user-info {
            text-align: right;
        }

        .user-name {
            font-weight: 700;
            color: var(--deep-navy);
            font-size: 1rem;
            margin-bottom: var(--space-1);
        }

        .user-role {
            color: var(--gray-medium);
            font-size: 0.85rem;
        }

        /* Enhanced Cards */
        .card {
            background: var(--card-gradient);
            border: 1px solid rgba(255, 255, 255, 0.9);
            border-radius: var(--radius-2xl);
            box-shadow: var(--shadow-lg);
            backdrop-filter: blur(20px);
            transition: all 0.4s ease;
            position: relative;
            overflow: hidden;
        }

        .card::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 4px;
            background: var(--electric-gradient);
            background-size: 200% 200%;
            animation: gradientShift 3s ease infinite;
            transform: scaleX(0);
            transition: transform 0.4s ease;
        }

        .card:hover {
            transform: translateY(-6px);
            box-shadow: var(--shadow-xl), var(--shadow-glow);
        }

        .card:hover::before {
            transform: scaleX(1);
        }

        /* Quick Action Cards dengan Hover Effect Konsisten */
        .quick-action-card {
            background: var(--card-gradient);
            border-radius: var(--radius-xl);
            padding: var(--space-5);
            text-align: center;
            border: 1px solid rgba(255, 255, 255, 0.9);
            box-shadow: var(--shadow-lg);
            transition: all 0.4s ease;
            position: relative;
            overflow: hidden;
            height: 100%;
            color: inherit;
        }

        .quick-action-card::before {
            content: '';
            position: absolute;
            top: 0;
            left: -100%;
            width: 100%;
            height: 100%;
            background: var(--electric-gradient);
            opacity: 0.1;
            transition: left 0.4s ease;
        }

        .quick-action-card::after {
            content: '';
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: var(--neon-gradient);
            opacity: 0;
            transition: opacity 0.4s ease;
            transform: rotate(45deg);
        }

        .quick-action-card:hover {
            transform: translateY(-6px) scale(1.02);
            box-shadow: var(--shadow-xl), var(--shadow-glow);
            border-color: var(--lime-neon);
            text-decoration: none;
            color: inherit;
        }

        .quick-action-card:hover::before {
            left: 0;
        }

        .quick-action-card:hover::after {
            opacity: 0.05;
        }

        .quick-action-icon {
            width: 60px;
            height: 60px;
            border-radius: var(--radius-xl);
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto var(--space-4);
            font-size: 1.5rem;
            box-shadow: var(--shadow-lg);
            transition: all 0.4s ease;
            position: relative;
            z-index: 2;
        }

        .quick-action-card:hover .quick-action-icon {
            transform: scale(1.1) rotate(8deg);
            box-shadow: var(--shadow-neon);
        }

        .quick-action-title {
            font-weight: 800;
            margin-bottom: var(--space-2);
            color: var(--deep-navy);
            position: relative;
            z-index: 2;
            font-size: 1.1rem;
        }

        .quick-action-desc {
            font-size: 0.85rem;
            color: var(--gray-medium);
            position: relative;
            z-index: 2;
        }

        /* Enhanced Tab Styling */
        .nav-tabs {
            border-bottom: 2px solid var(--gray-light);
            gap: 0.5rem;
        }

        .nav-tabs .nav-link {
            border: 2px solid transparent;
            border-radius: 8px 8px 0 0;
            padding: 0.75rem 1.5rem;
            font-weight: 600;
            color: var(--gray-medium);
            background: transparent;
            transition: all 0.22s cubic-bezier(0.2, 0.9, 0.3, 1);
            position: relative;
        }

        .nav-tabs .nav-link:hover {
            border-color: var(--gray-light);
            color: var(--primary-blue);
            transform: translateY(-2px);
        }

        .nav-tabs .nav-link.active {
            color: var(--primary-blue);
            background-color: white;
            border-color: var(--primary-blue) var(--primary-blue) white;
            border-width: 2px 2px 2px 2px;
            box-shadow: 0 -2px 10px rgba(37, 99, 235, 0.1);
        }

        .nav-tabs .nav-link.active::after {
            content: '';
            position: absolute;
            bottom: -2px;
            left: 0;
            right: 0;
            height: 2px;
            background: white;
        }

        .tab-content {
            background: transparent;
        }

        .tab-pane {
            animation: fadeIn 0.3s ease-in;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }

        /* Card styling for tab content */
        .card.border-0 {
            border: none !important;
            box-shadow: none !important;
        }

        .card.border-0 .card-header {
            background: var(--card-gradient) !important;
            border: 1px solid rgba(255, 255, 255, 0.9);
            border-radius: 12px 12px 0 0;
            border-bottom: 1px solid var(--gray-light);
        }

        .card.border-0 .card-body {
            background: var(--card-gradient);
            border: 1px solid rgba(255, 255, 255, 0.9);
            border-top: none;
            border-radius: 0 0 12px 12px;
        }
        .tab-content {
            background: transparent;
        }

        .tab-pane {
            animation: fadeIn 0.3s ease-in;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }

        /* Card styling for tab content */
        .card.border-0 {
            border: none !important;
            box-shadow: none !important;
        }

        .card.border-0 .card-header {
            background: var(--card-gradient) !important;
            border: 1px solid rgba(255, 255, 255, 0.9);
            border-radius: 12px 12px 0 0;
            border-bottom: 1px solid var(--gray-light);
        }

        .card.border-0 .card-body {
            background: var(--card-gradient);
            border: 1px solid rgba(255, 255, 255, 0.9);
            border-top: none;
            border-radius: 0 0 12px 12px;
        }

        /* Stat Card Hover Effect yang Sama */
        .stat-card {
            background: var(--card-gradient);
            border-radius: var(--radius-2xl);
            padding: var(--space-6);
            text-align: center;
            border: 1px solid rgba(255, 255, 255, 0.9);
            box-shadow: var(--shadow-lg);
            transition: all 0.4s ease;
            position: relative;
            overflow: hidden;
            height: 100%;
        }

        .stat-card::before {
            content: '';
            position: absolute;
            top: 0;
            left: -100%;
            width: 100%;
            height: 100%;
            background: var(--electric-gradient);
            opacity: 0.1;
            transition: left 0.4s ease;
        }

        .stat-card::after {
            content: '';
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: var(--neon-gradient);
            opacity: 0;
            transition: opacity 0.4s ease;
            transform: rotate(45deg);
        }

        .stat-card:hover {
            transform: translateY(-6px) scale(1.02);
            box-shadow: var(--shadow-xl), var(--shadow-glow);
            border-color: var(--lime-neon);
        }

        .stat-card:hover::before {
            left: 0;
        }

        .stat-card:hover::after {
            opacity: 0.05;
        }

        .stat-icon {
            width: 50px;
            height: 50px;
            border-radius: var(--radius-lg);
            background: var(--lime-gradient);
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto var(--space-4);
            color: var(--deep-navy);
            font-size: 1.3rem;
            box-shadow: var(--shadow-md);
            transition: all 0.4s ease;
            position: relative;
            z-index: 2;
        }

        .stat-card:hover .stat-icon /
            transform: scale(1.1) rotate(8deg);
            box-shadow: var(--shadow-neon);
            background: var(--electric-gradient);
            color: var(--white);
        }


        .card-header {
            background: transparent;
            border-bottom: 1px solid var(--gray-light);
            padding: var(--space-6);
            font-weight: 700;
            color: var(--deep-navy);
            font-size: 1.1rem;
        }

        .card-body {
            padding: var(--space-6);
        }

        /* Compact Stat Card */
        .stat-card-compact {
            background: var(--card-gradient);
            border-radius: var(--radius-xl);
            padding: var(--space-4);
            text-align: center;
            border: 1px solid rgba(255, 255, 255, 0.9);
            box-shadow: var(--shadow-lg);
            transition: all 0.4s ease;
            position: relative;
            overflow: hidden;
            height: 100%;
        }

        .stat-card-compact::before {
            content: '';
            position: absolute;
            top: 0;
            left: -100%;
            width: 100%;
            height: 100%;
            background: var(--electric-gradient);
            opacity: 0.1;
            transition: left 0.4s ease;
        }

        .stat-card-compact:hover {
            transform: translateY(-4px);
            box-shadow: var(--shadow-xl), var(--shadow-glow);
            border-color: var(--lime-neon);
        }

        .stat-card-compact:hover::before {
            left: 0;
        }

        .stat-icon-compact {
            width: 40px;
            height: 40px;
            border-radius: var(--radius-lg);
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto var(--space-3);
            font-size: 1.1rem;
            box-shadow: var(--shadow-md);
            transition: all 0.4s ease;
        }

        .stat-card-compact:hover .stat-icon-compact {
            transform: scale(1.1) rotate(8deg);
            box-shadow: var(--shadow-neon);
        }

        .stat-number-compact {
            font-size: 1.5rem;
            font-weight: 800;
            margin-bottom: var(--space-1);
            line-height: 1;
        }

        .stat-label-compact {
            font-size: 0.85rem;
            font-weight: 600;
            color: var(--gray-medium);
        }

        /* Compact Quick Action Cards */
        .quick-action-card-compact {
            background: var(--card-gradient);
            border-radius: var(--radius-lg);
            padding: var(--space-3);
            text-align: center;
            border: 1px solid rgba(255, 255, 255, 0.9);
            box-shadow: var(--shadow-md);
            transition: all 0.3s ease;
            height: 100%;
            color: inherit;
        }

        .quick-action-card-compact::before {
            content: '';
            position: absolute;
            top: 0;
            left: -100%;
            width: 100%;
            height: 100%;
            background: var(--electric-gradient);
            opacity: 0.1;
            transition: left 0.3s ease;
        }

        .quick-action-card-compact:hover {
            transform: translateY(-3px);
            box-shadow: var(--shadow-lg);
            border-color: var(--lime-neon);
            text-decoration: none;
            color: inherit;
        }

        .quick-action-card-compact:hover::before {
            left: 0;
        }

        .quick-action-icon-compact {
            width: 35px;
            height: 35px;
            border-radius: var(--radius-md);
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto var(--space-2);
            font-size: 0.9rem;
            box-shadow: var(--shadow-sm);
            transition: all 0.3s ease;
        }

        .quick-action-card-compact:hover .quick-action-icon-compact {
            transform: scale(1.1) rotate(5deg);
        }

        .quick-action-title-compact {
            font-weight: 600;
            font-size: 0.8rem;
            color: var(--deep-navy);
            line-height: 1.2
        }

        .section-title-compact {
            font-size: 1rem;
            font-weight: 700;
            color: var(--deep-navy);
            margin-bottom: var(--space-3);
        }

        /* Enhanced Buttons */
        .btn {
            border: none;
            border-radius: var(--radius-lg);
            padding: var(--space-3) var(--space-6);
            font-weight: 700;
            font-size: 0.9rem;
            transition: all 0.3s ease;
            position: relative;
            overflow: hidden;
        }

        .btn-primary {
            background: var(--button-gradient);
            color: var(--white);
            box-shadow: var(--shadow-md);
        }

        .btn-primary:hover {
            background: var(--button-hover);
            transform: translateY(-2px);
            box-shadow: var(--shadow-lg), var(--shadow-electric);
        }

        .btn-outline-primary {
            background: transparent;
            border: 2px solid var(--primary-blue);
            color: var(--primary-blue);
        }

        .btn-outline-primary:hover {
            background: var(--primary-blue);
            color: var(--white);
            transform: translateY(-2px);
            box-shadow: var(--shadow-lg);
        }

        /* Highlighted Quick Actions */
        .quick-actions-section {
            margin-bottom: var(--space-10);
        }

        .section-title {
            font-size: 1.5rem;
            font-weight: 800;
            background: var(--electric-gradient);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            margin-bottom: var(--space-6);
            text-align: center;
        }

        .quick-actions {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: var(--space-6);
        }

        .quick-action {
            background: var(--card-gradient);
            border-radius: var(--radius-2xl);
            padding: var(--space-8) var(--space-6);
            text-align: center;
            text-decoration: none;
            color: inherit;
            border: 2px solid rgba(255, 255, 255, 0.8);
            box-shadow: var(--shadow-lg);
            transition: all 0.4s ease;
            position: relative;
            overflow: hidden;
        }

        .quick-action::before {
            content: '';
            position: absolute;
            top: 0;
            left: -100%;
            width: 100%;
            height: 100%;
            background: var(--electric-gradient);
            opacity: 0.1;
            transition: left 0.4s ease;
        }

        .quick-action::after {
            content: '';
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: var(--neon-gradient);
            opacity: 0;
            transition: opacity 0.4s ease;
            transform: rotate(45deg);
        }

        .quick-action:hover {
            transform: translateY(-8px) scale(1.02);
            box-shadow: var(--shadow-xl), var(--shadow-neon);
            border-color: var(--lime-neon);
        }

        .quick-action:hover::before {
            left: 0;
        }

        .quick-action:hover::after {
            opacity: 0.05;
        }

        .quick-action-icon {
            width: 60px;
            height: 60px;
            border-radius: var(--radius-xl);
            background: var(--lime-gradient);
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto var(--space-4);
            color: var(--deep-navy);
            font-size: 1.5rem;
            box-shadow: var(--shadow-lg);
            transition: all 0.4s ease;
            position: relative;
            z-index: 2;
        }

        .quick-action:hover .quick-action-icon {
            transform: scale(1.1) rotate(8deg);
            box-shadow: var(--shadow-neon);
            background: var(--electric-gradient);
            color: var(--white);
        }

        .quick-action-title {
            font-weight: 800;
            margin-bottom: var(--space-2);
            color: var(--deep-navy);
            position: relative;
            z-index: 2;
            font-size: 1.1rem;
        }

        .quick-action-desc {
            font-size: 0.85rem;
            color: var(--gray-medium);
            position: relative;
            z-index: 2;
        }

        /* Content Layout */
        .content-container {
            padding: var(--space-8);
            max-width: 1400px;
            margin: 0 auto;
        }

        .page-header {
            margin-bottom: var(--space-10);
        }

        .grid-container {
            display: grid;
            gap: var(--space-6);
            margin-bottom: var(--space-8);
        }

        .grid-2 {
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
        }

        .grid-3 {
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
        }

        .grid-4 {
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        }

        /* Responsive Design */
        @media (max-width: 1024px) {
            .sidebar {
                width: 260px;
            }
            .main-content {
                margin-left: 260px;
            }
        }

        @media (max-width: 768px) {
            .sidebar {
                transform: translateX(-100%);
                transition: transform 0.3s ease;
            }
            .sidebar.active {
                transform: translateX(0);
            }
            .main-content {
                margin-left: 0;
            }
            .content-container {
                padding: var(--space-4);
            }
            .grid-2, .grid-3, .grid-4 {
                grid-template-columns: 1fr;
            }
            .navbar-content {
                flex-direction: column;
                gap: var(--space-4);
                text-align: center;
            }
            .user-menu {
                border-left: none;
                border-top: 2px solid var(--gray-light);
                padding-left: 0;
                padding-top: var(--space-4);
            }
        }
    </style>
</head>
<body>
    <!-- Enhanced Background Waves -->
    <div class="bg-waves">
        <div class="wave"></div>*
        <div class="wave"></div>
        <div class="wave"></div>
    </div>

    {% if user and request.endpoint != 'login' %}
    <div class="container-fluid p-0">
        <!-- Sidebar -->
        <div class="sidebar">
            <div class="logo">
                <i class="fas fa-water"></i>
                <div class="logo-text">Tiramine</div>
            </div>
            <nav class="nav-links">
                <div class="nav-item">
                    <a class="nav-link {{ 'active' if request.endpoint == 'dashboard' }}" href="/dashboard">
                        <i class="fas fa-home"></i>
                        <span>Dashboard</span>
                    </a>
                </div>
                <div class="nav-item">
                    <a class="nav-link {{ 'active' if 'inventory' in request.endpoint }}" href="/inventory">
                        <i class="fas fa-boxes"></i>
                        <span>Monitoring Stok</span>
                    </a>
                </div>
                <div class="nav-item">
                    <a class="nav-link {{ 'active' if 'journal' in request.endpoint }}" href="/journal">
                        <i class="fas fa-book"></i>
                        <span>Jurnal</span>
                    </a>
                </div>
                <div class="nav-item">
                    <a class="nav-link {{ 'active' if 'ledger' in request.endpoint }}" href="/ledger">
                        <i class="fas fa-file-invoice-dollar"></i>
                        <span>Buku Besar</span>
                    </a>
                </div>
                <div class="nav-item">
                    <a class="nav-link {{ 'active' if 'trial_balance' in request.endpoint }}" href="/trial_balance">
                        <i class="fas fa-balance-scale"></i>
                        <span>Neraca Saldo</span>
                    </a>
                </div>
                <div class="nav-item">
                    <a class="nav-link {{ 'active' if 'adjusting' in request.endpoint }}" href="/adjusting">
                        <i class="fas fa-adjust"></i>
                        <span>Ayat Penyesuaian</span>
                    </a>
                </div>
                    <div class="nav-item">
                    <a class="nav-link {{ 'active' if 'closing' in request.endpoint }}" href="/closing">
                        <i class="fas fa-lock"></i>
                        <span>Jurnal Penutup</span>
                    </a>
                </div>
                <div class="nav-item">
                    <a class="nav-link {{ 'active' if 'financials' in request.endpoint }}" href="/financials">
                        <i class="fas fa-chart-line"></i>
                        <span>Laporan Keuangan</span>
                    </a>
                </div>
                <div class="nav-item">
                    <a class="nav-link {{ 'active' if 'opening_balance' in request.endpoint }}" href="/opening_balance">
                        <i class="fas fa-play-circle"></i>
                        <span>Saldo Awal</span>
                    </a>
                </div>
                <div class="nav-item">
                    <a class="nav-link reset-link {{ 'active' if 'reset' in request.endpoint }}" href="/reset">
                        <i class="fas fa-broom"></i>
                        <span>Reset Data</span>
                    </a>
                </div>
            </nav>
        </div>
        
        <!-- Main Content -->
        <div class="main-content">
            <nav class="navbar">
                <div class="navbar-content">
                    <div class="page-header-content">
                        <h1 class="page-title">{{ title }}</h1>
                        {% if request.endpoint == 'dashboard' %}
                        <p class="page-subtitle">Ringkasan keuangan dan statistik bisnis peternakan tiram</p>
                        {% endif %}
                    </div>
                    <div class="user-menu">
                        <div class="user-avatar">
                            {{ user.username[0].upper() }}
                        </div>
                        <div class="user-info">
                            <div class="user-name">{{ user.username }}</div>
                            <div class="user-role">Administrator</div>
                        </div>
                        <a href="/logout" class="btn btn-outline-primary btn-sm">
                            <i class="fas fa-sign-out-alt me-1"></i>Keluar
                        </a>
                    </div>
                </div>
            </nav>
            
            <div class="content-container">
                {% with messages = get_flashed_messages() %}
                    {% if messages %}
                        <div class="alert alert-info alert-dismissible fade show">
                            <i class="fas fa-info-circle me-2"></i>
                            {{ messages[0] }}
                            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                        </div>
                    {% endif %}
                {% endwith %}
                
                {{ body|safe }}
            </div>
        </div>
    </div>
    {% else %}
        {% with messages = get_flashed_messages() %}
            {% if messages %}
                <div class="container mt-3" style="max-width: 640px;">
                    <div class="alert alert-info alert-dismissible fade show">
                        <i class="fas fa-info-circle me-2"></i>
                        {{ messages[0] }}
                        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                    </div>
                </div>
            {% endif %}
        {% endwith %}
        {{ body|safe }}
    {% endif %}
    
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        // Penanganan form dinamis
        function addJournalLine() {
            const container = document.getElementById('journal-lines');
            const count = container.children.length;
            const newLine = document.createElement('div');
            newLine.className = 'row mb-3 journal-line';
            newLine.innerHTML = `
                <div class="col-md-5">
                    <select class="form-select" name="account_${count}" required>
                        <option value="">Pilih Akun</option>
                        ${document.getElementById('account-options').innerHTML}
                    </select>
                </div>
                <div class="col-md-3">
                    <input type="number" class="form-control" name="debit_${count}" placeholder="0.00" step="0.01" min="0" oninput="checkBalance()">
                </div>
                <div class="col-md-3">
                    <input type="number" class="form-control" name="credit_${count}" placeholder="0.00" step="0.01" min="0" oninput="checkBalance()">
                </div>
                <div class="col-md-1">
                    <button type="button" class="btn btn-danger btn-sm" onclick="this.closest('.journal-line').remove(); checkBalance();">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
            `;
            container.appendChild(newLine);
        }
        
        function checkBalance() {
            let totalDebit = 0;
            let totalCredit = 0;
            
            document.querySelectorAll('input[name^="debit_"]').forEach(input => {
                totalDebit += parseFloat(input.value) || 0;
            });
            
            document.querySelectorAll('input[name^="credit_"]').forEach(input => {
                totalCredit += parseFloat(input.value) || 0;
            });
            
            const balanceElement = document.getElementById('balance-check');
            if (balanceElement) {
                if (Math.abs(totalDebit - totalCredit) < 0.01) {
                    balanceElement.innerHTML = `<span class="text-success"><i class="fas fa-check-circle me-2"></i> Seimbang: ${totalDebit.toFixed(2)} = ${totalCredit.toFixed(2)}</span>`;
                    balanceElement.className = 'alert alert-success';
                } else {
                    balanceElement.innerHTML = `<span class="text-danger"><i class="fas fa-exclamation-circle me-2"></i> Tidak Seimbang: ${totalDebit.toFixed(2)} ≠ ${totalCredit.toFixed(2)}</span>`;
                    balanceElement.className = 'alert alert-danger';
                }
            }
        }
        
        // Hitung tanggal otomatis untuk entri baru
        document.addEventListener('DOMContentLoaded', function() {
            const dateInput = document.querySelector('input[type="date"]');
            if (dateInput && !dateInput.value) {
                dateInput.value = new Date().toISOString().split('T')[0];
            }
        });
    </script>
</body>
</html>
"""

# ---------- Rute ----------

@app.route('/')
def index():
    if current_user():
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/fix_database')
@login_required
def fix_database():
    """Route untuk memperbaiki struktur database dan saldo awal"""
    try:
        # Perbaiki saldo awal
        is_balanced = fix_opening_balances()
        
        if is_balanced:
            flash('✅ Database berhasil diperbaiki! Neraca saldo sekarang balance.')
        else:
            flash('⚠️ Database diperbaiki tetapi neraca saldo masih tidak balance.')
        
        return redirect(url_for('trial_balance_view'))
    
    except Exception as e:
        flash(f'❌ Error memperbaiki database: {str(e)}')
        return redirect(url_for('dashboard'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    """Simple registration form for new users."""
    if current_user():
        return redirect(url_for('dashboard'))

    username_value = ''
    email_value = ''

    if request.method == 'POST':
        username_value = request.form.get('username', '').strip()
        email_value = normalize_email(request.form.get('email', ''))
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not username_value or not email_value or not password:
            flash('Semua field wajib diisi.')
        elif password != confirm_password:
            flash('Konfirmasi kata sandi tidak cocok.')
        else:
            try:
                db = get_db()
                cur = db.execute(
                    'SELECT id FROM users WHERE username = ? OR email = ?',
                    (username_value, email_value)
                )
                if cur.fetchone():
                    flash('Username atau email sudah digunakan.')
                else:
                    password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
                    db.execute(
                        'INSERT INTO users (username, password_hash, email) VALUES (?, ?, ?)',
                        (username_value, password_hash, email_value)
                    )
                    db.commit()
                    flash('Registrasi berhasil! Silakan login menggunakan akun Anda.')
                    return redirect(url_for('login'))
            except Exception as e:
                flash(f'Gagal melakukan registrasi: {str(e)}')

    body = f"""
    <div class="container">
        <div class="row justify-content-center align-items-center min-vh-100">
            <div class="col-md-6 col-lg-5">
                <div class="card">
                    <div class="card-body p-5">
                        <div class="text-center mb-4">
                            <i class="fas fa-user-plus fa-3x text-primary mb-3"></i>
                            <h3 class="fw-bold">Daftar Tiramine</h3>
                            <p class="text-muted">Buat akun untuk mengakses sistem</p>
                        </div>
                        <form method="post">
                            <div class="mb-3">
                                <label class="form-label fw-semibold">Nama Pengguna</label>
                                <input type="text" class="form-control" name="username" value="{escape(username_value)}" required>
                            </div>
                            <div class="mb-3">
                                <label class="form-label fw-semibold">Email</label>
                                <input type="email" class="form-control" name="email" value="{escape(email_value)}" required>
                            </div>
                            <div class="mb-3">
                                <label class="form-label fw-semibold">Kata Sandi</label>
                                <input type="password" class="form-control" name="password" required>
                            </div>
                            <div class="mb-4">
                                <label class="form-label fw-semibold">Konfirmasi Kata Sandi</label>
                                <input type="password" class="form-control" name="confirm_password" required>
                            </div>
                            <button type="submit" class="btn btn-success w-100 py-2 fw-semibold">
                                <i class="fas fa-user-check me-2"></i>Buat Akun
                            </button>
                        </form>
                        <div class="text-center mt-4">
                            <a href="/login" class="text-decoration-none d-block">Sudah punya akun? Masuk</a>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    """
    return render_template_string(BASE_TEMPLATE, title='Daftar', body=body, user=None)

@app.route('/login', methods=['GET', 'POST'])
def login():
    # Jika sudah login, redirect ke dashboard
    if current_user():
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        try:
            username = request.form['username']
            password = request.form['password'].encode('utf-8')
            
            db = get_db()
            cur = db.execute('SELECT id, password_hash FROM users WHERE username = ?', (username,))
            user = cur.fetchone()
            
            if user and bcrypt.checkpw(password, user['password_hash']):
                session['user_id'] = user['id']
                flash('Selamat datang di Sistem Akuntansi Tiramine!')
                print(f"✅ User {username} logged in successfully")
                return redirect(url_for('dashboard'))
            else:
                flash('Kredensial tidak valid. Silakan coba lagi.')
                print(f"❌ Login failed for user: {username}")
                
        except Exception as e:
            flash(f'Error saat login: {str(e)}')
            print(f"❌ Login error: {e}")
    
    # Tampilkan form login
    body = """
    <div class="container">
        <div class="row justify-content-center align-items-center min-vh-100">
            <div class="col-md-5">
                <div class="card">
                    <div class="card-body p-5">
                        <div class="text-center mb-4">
                            <i class="fas fa-water fa-3x text-primary mb-3"></i>
                            <h3 class="fw-bold">Masuk ke Tiramine</h3>
                            <p class="text-muted">Sistem Akuntansi Peternakan Tiram</p>
                        </div>
                        
                        <form method="post">
                            <div class="mb-3">
                                <label class="form-label fw-semibold">Nama Pengguna</label>
                                <input type="text" class="form-control" name="username" value="admin" required>
                            </div>
                            <div class="mb-4">
                                <label class="form-label fw-semibold">Kata Sandi</label>
                                <input type="password" class="form-control" name="password" value="password" required>
                            </div>
                            <button type="submit" class="btn btn-primary w-100 py-2 fw-semibold">
                                <i class="fas fa-sign-in-alt me-2"></i>Masuk
                            </button>
                        </form>

                        <div class="text-center mt-4">
                            <a href="/otp/request" class="text-decoration-none d-block mb-2">
                                <i class="fas fa-sms me-1"></i>Masuk menggunakan OTP
                            </a>
                            <a href="/register" class="text-decoration-none">
                                <i class="fas fa-user-plus me-1"></i>Buat akun baru
                            </a>
                        </div>
                        
                        <div class="text-center mt-4">
                            <small class="text-muted">
                                <i class="fas fa-info-circle me-1"></i>
                                Gunakan: <strong>admin</strong> / <strong>password</strong>
                            </small>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    """
    return render_template_string(BASE_TEMPLATE, title='Masuk', body=body, user=None)

@app.route('/otp/request', methods=['GET', 'POST'])
def request_otp():
    """Form untuk meminta OTP login via email."""
    if current_user():
        return redirect(url_for('dashboard'))

    email_value = ''
    if request.method == 'POST':
        email_value = normalize_email(request.form.get('email', ''))
        if not email_value:
            flash('Email harus diisi.')
        else:
            db = get_db()
            user = db.execute('SELECT username FROM users WHERE email = ?', (email_value,)).fetchone()
            if not user:
                flash('Email tidak ditemukan di sistem.')
            else:
                safe_username = escape(user['username'])
                otp_code, expires_at = create_otp_for_email(email_value)
                subject = 'Kode OTP Masuk Tiramine'
                body_html = f"""
                <p>Halo <strong>{safe_username}</strong>,</p>
                <p>Kode OTP Tiramine Anda adalah:</p>
                <h2 style="letter-spacing:4px;">{otp_code}</h2>
                <p>Gunakan kode ini sebelum <strong>{expires_at} UTC</strong>.</p>
                <p>Abaikan email ini bila Anda tidak meminta OTP.</p>
                """
                sent, error = send_email_notification(email_value, subject, body_html)
                if sent:
                    flash('OTP telah dikirim ke email Anda. Silakan cek kotak masuk dan masukkan kode OTP.')
                    return redirect(url_for('otp_login', email=email_value))
                else:
                    flash(error)

    body = f"""
    <div class="container">
        <div class="row justify-content-center align-items-center min-vh-100">
            <div class="col-md-6 col-lg-4">
                <div class="card">
                    <div class="card-body p-5">
                        <div class="text-center mb-4">
                            <i class="fas fa-envelope-open-text fa-3x text-primary mb-3"></i>
                            <h3 class="fw-bold">Kirim OTP Login</h3>
                            <p class="text-muted">Masukkan email akun Anda</p>
                        </div>
                        <form method="post">
                            <div class="mb-4">
                                <label class="form-label fw-semibold">Email</label>
                                <input type="email" class="form-control" name="email" value="{escape(email_value)}" required>
                            </div>
                            <button type="submit" class="btn btn-primary w-100 py-2 fw-semibold">
                                <i class="fas fa-paper-plane me-2"></i>Kirim OTP
                            </button>
                        </form>
                        <div class="text-center mt-4">
                            <a href="/login" class="text-decoration-none d-block mb-1">Kembali ke halaman login</a>
                            <a href="/register" class="text-decoration-none">Belum punya akun? Daftar</a>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    """
    return render_template_string(BASE_TEMPLATE, title='Kirim OTP', body=body, user=None)

@app.route('/otp/login', methods=['GET', 'POST'])
def otp_login():
    """Verifikasi OTP dan login tanpa password."""
    if current_user():
        return redirect(url_for('dashboard'))

    email_prefill = request.values.get('email', '')

    if request.method == 'POST':
        normalized_email = normalize_email(request.form.get('email', ''))
        otp_code = (request.form.get('otp_code') or '').strip()

        if not normalized_email or not otp_code:
            flash('Email dan kode OTP wajib diisi.')
        else:
            is_valid, message = verify_otp_code(normalized_email, otp_code)
            if is_valid:
                db = get_db()
                user = db.execute('SELECT id, username FROM users WHERE email = ?', (normalized_email,)).fetchone()
                if user:
                    session['user_id'] = user['id']
                    flash('Login menggunakan OTP berhasil.')
                    return redirect(url_for('dashboard'))
                flash('Pengguna tidak ditemukan.')
            else:
                flash(message)

    body = f"""
    <div class="container">
        <div class="row justify-content-center align-items-center min-vh-100">
            <div class="col-md-6 col-lg-4">
                <div class="card">
                    <div class="card-body p-5">
                        <div class="text-center mb-4">
                            <i class="fas fa-key fa-3x text-primary mb-3"></i>
                            <h3 class="fw-bold">Masuk dengan OTP</h3>
                            <p class="text-muted">Masukkan OTP yang dikirim ke email</p>
                        </div>
                        <form method="post">
                            <div class="mb-3">
                                <label class="form-label fw-semibold">Email</label>
                                <input type="email" class="form-control" name="email" value="{escape(email_prefill)}" required>
                            </div>
                            <div class="mb-4">
                                <label class="form-label fw-semibold">Kode OTP</label>
                                <input type="text" class="form-control text-center" name="otp_code" maxlength="6" placeholder="123456" required>
                            </div>
                            <button type="submit" class="btn btn-success w-100 py-2 fw-semibold">
                                <i class="fas fa-unlock-alt me-2"></i>Verifikasi OTP
                            </button>
                        </form>
                        <div class="text-center mt-4">
                            <a href="/otp/request" class="text-decoration-none d-block mb-1">Tidak menerima kode? Kirim ulang</a>
                            <a href="/login" class="text-decoration-none">Masuk dengan password</a>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    """
    return render_template_string(BASE_TEMPLATE, title='Masuk OTP', body=body, user=None)

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash('Anda telah berhasil keluar.')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    # Dapatkan info perusahaan
    company_info = get_company_info()
    current_stock = get_current_stock()  # Sekarang return dictionary
    
    # Dapatkan transaksi terbaru
    try:
        cur = get_db().execute('''
            SELECT je.id, je.date, je.description,
                   COALESCE(je.transaction_type, 'General') as transaction_type,
                   SUM(jl.debit) as total_debit, 
                   SUM(jl.credit) as total_credit
            FROM journal_entries je
            JOIN journal_lines jl ON je.id = jl.entry_id
            GROUP BY je.id
            ORDER BY je.date DESC
            LIMIT 5
        ''')
        recent_transactions = cur.fetchall()
    except:
        # Fallback query jika kolom transaction_type tidak ada
        cur = get_db().execute('''
            SELECT je.id, je.date, je.description,
                   'General' as transaction_type,
                   SUM(jl.debit) as total_debit, 
                   SUM(jl.credit) as total_credit
            FROM journal_entries je
            JOIN journal_lines jl ON je.id = jl.entry_id
            GROUP BY je.id
            ORDER BY je.date DESC
            LIMIT 5
        ''')
        recent_transactions = cur.fetchall()
    
    # Dapatkan ringkasan keuangan
    income_stmt = income_statement()
    balance_stmt = balance_sheet()
    cash_flow = cash_flow_statement()
    
    # Generate HTML untuk transaksi terbaru yang lebih konsisten
    transactions_html = ""
    if recent_transactions:
        for tx in recent_transactions:
            transactions_html += f'''
            <div class="transaction-item border-bottom pb-3 mb-3">
                <div class="d-flex justify-content-between align-items-start">
                    <div class="flex-grow-1">
                        <div class="d-flex align-items-center mb-1">
                            <strong class="text-dark">{tx['date']}</strong>
                            <span class="badge bg-secondary ms-2">{tx['transaction_type']}</span>
                        </div>
                        <p class="mb-1 text-dark">{tx['description'][:60]}{'...' if len(tx['description']) > 60 else ''}</p>
                    </div>
                    <div class="text-end ms-3">
                        <div class="text-success fw-bold">+{tx['total_debit']:,.2f}</div>
                        <div class="text-danger fw-bold">-{tx['total_credit']:,.2f}</div>
                    </div>
                </div>
            </div>
            '''
    else:
        transactions_html = '''
        <div class="text-center py-5">
            <i class="fas fa-inbox fa-3x text-muted mb-3"></i>
            <h6 class="text-muted">Belum ada transaksi</h6>
            <p class="text-muted small">Mulai dengan membuat entri transaksi pertama Anda</p>
        </div>
        '''
    
    # PERBAIKAN: Dashboard template yang sudah dikoreksi struktur HTML-nya
    dashboard_template = f"""
    <div class="container-fluid py-4">
        <!-- Header -->
        <div class="page-header mb-4">
            <div class="d-flex justify-content-between align-items-center">
                <div class="flex-grow-1">
                    <h1 class="page-title mb-1">Dashboard Tiramine</h1>
                    <p class="page-subtitle mb-0">Ringkasan keuangan dan statistik bisnis peternakan tiram</p>
                </div>
                <div class="user-menu">
                    <div class="user-avatar">
                        {current_user()['username'][0].upper() if current_user() else 'A'}
                    </div>
                    <div class="user-info">
                        <div class="user-name">{current_user()['username'] if current_user() else 'Admin'}</div>
                        <div class="user-role">Administrator</div>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- Row 1: Ringkasan Cepat -->
        <div class="row mb-4">
            <!-- Card Kas -->
            <div class="col-lg-3 col-md-6 mb-4">
                <div class="card h-100">
                    <div class="card-body p-4">
                        <div class="d-flex justify-content-between align-items-center mb-3">
                            <h6 class="section-title-compact mb-0">
                                <i class="fas fa-wallet me-2 text-success"></i>Kas
                            </h6>
                            <div class="stat-icon bg-success text-white">
                                <i class="fas fa-money-bill-wave"></i>
                            </div>
                        </div>
                        <h3 class="text-success mb-2">Rp {cash_flow.get('net_cash_flow', 0):,.0f}</h3>
                        <p class="text-muted mb-0">Saldo kas tersedia</p>
                    </div>
                </div>
            </div>
            
            <!-- Card Pendapatan -->
            <div class="col-lg-3 col-md-6 mb-4">
                <div class="card h-100">
                    <div class="card-body p-4">
                        <div class="d-flex justify-content-between align-items-center mb-3">
                            <h6 class="section-title-compact mb-0">
                                <i class="fas fa-chart-line me-2 text-primary"></i>Pendapatan
                            </h6>
                            <div class="stat-icon bg-primary text-white">
                                <i class="fas fa-hand-holding-usd"></i>
                            </div>
                        </div>
                        <h3 class="text-primary mb-2">Rp {income_stmt.get('total_revenue', 0):,.0f}</h3>
                        <p class="text-muted mb-0">Total pendapatan periode</p>
                    </div>
                </div>
            </div>
            
            <!-- Card Laba Bersih -->
            <div class="col-lg-3 col-md-6 mb-4">
                <div class="card h-100">
                    <div class="card-body p-4">
                        <div class="d-flex justify-content-between align-items-center mb-3">
                            <h6 class="section-title-compact mb-0">
                                <i class="fas fa-trophy me-2 text-warning"></i>Laba Bersih
                            </h6>
                            <div class="stat-icon bg-warning text-white">
                                <i class="fas fa-chart-pie"></i>
                            </div>
                        </div>
                        <h3 class="{'text-success' if income_stmt.get('net_income', 0) >= 0 else 'text-danger'} mb-2">
                            Rp {income_stmt.get('net_income', 0):,.0f}
                        </h3>
                        <p class="text-muted mb-0">Laba/rugi periode berjalan</p>
                    </div>
                </div>
            </div>
            
            <!-- Aksi Cepat -->
            <div class="col-lg-3 col-md-6 mb-4">
                <div class="card h-100">
                    <div class="card-body p-4 d-flex flex-column">
                        <div class="d-flex justify-content-between align-items-center mb-3">
                            <h6 class="section-title-compact mb-0">
                                <i class="fas fa-bolt me-2 text-warning"></i>Aksi Cepat
                            </h6>
                            <div class="dropdown">
                                <button class="btn btn-sm btn-outline-secondary dropdown-toggle" type="button" data-bs-toggle="dropdown">
                                    <i class="fas fa-cog"></i>
                                </button>
                                <ul class="dropdown-menu">
                                    <li><a class="dropdown-item" href="/journal"><i class="fas fa-book me-2"></i>Lihat Jurnal</a></li>
                                    <li><a class="dropdown-item" href="/inventory"><i class="fas fa-boxes me-2"></i>Monitoring Stok</a></li>
                                    <li><hr class="dropdown-divider"></li>
                                    <li><a class="dropdown-item" href="/financials"><i class="fas fa-chart-line me-2"></i>Laporan Keuangan</a></li>
                                </ul>
                            </div>
                        </div>
                        
                        <div class="flex-grow-1 d-flex align-items-center justify-content-center">
                            <a href="/journal/new" class="quick-action-card d-block text-decoration-none text-center w-100">
                                <div class="quick-action-icon bg-warning text-white mx-auto mb-3">
                                    <i class="fas fa-plus"></i>
                                </div>
                                <div class="quick-action-title fw-bold fs-5">Entri Transaksi</div>
                                <div class="quick-action-desc text-muted">
                                    Tambah transaksi penjualan / pembelian
                                </div>
                            </a>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Row 2: Transaksi Terbaru & Ringkasan Keuangan -->
        <div class="row align-items-stretch">
            <!-- Transaksi Terbaru -->
            <div class="col-lg-8 mb-4">
                <div class="card h-100">
                    <div class="card-header bg-transparent border-bottom-0">
                        <div class="d-flex justify-content-between align-items-center">
                            <h5 class="section-title mb-0">
                                <i class="fas fa-history me-2 text-primary"></i>Transaksi Terbaru
                            </h5>
                            <a href="/journal" class="btn btn-outline-primary btn-sm">
                                <i class="fas fa-list me-1"></i>Lihat Semua
                            </a>
                        </div>
                    </div>
                    <div class="card-body">
                        {transactions_html}
                    </div>
                </div>
            </div>
            
            <!-- Ringkasan Keuangan -->
            <div class="col-lg-4">
                <div class="card h-100">
                    <div class="card-header bg-transparent border-bottom-0">
                        <h5 class="section-title mb-0">
                            <i class="fas fa-chart-pie me-2 text-success"></i>Ringkasan Keuangan
                        </h5>
                    </div>
                    <div class="card-body">
                        <div class="d-flex justify-content-between align-items-center mb-3 pb-2 border-bottom">
                            <span class="text-dark">Pendapatan:</span>
                            <span class="text-success fw-bold">Rp {income_stmt.get('total_revenue', 0):,.2f}</span>
                        </div>
                        <div class="d-flex justify-content-between align-items-center mb-3 pb-2 border-bottom">
                            <span class="text-dark">Beban:</span>
                            <span class="text-danger fw-bold">Rp {income_stmt.get('total_expense', 0):,.2f}</span>
                        </div>
                        <div class="d-flex justify-content-between align-items-center mb-3 pb-2 border-bottom">
                            <span class="text-dark">Laba Bersih:</span>
                            <span class="fw-bold {'text-success' if income_stmt.get('net_income', 0) >= 0 else 'text-danger'}">
                                Rp {income_stmt.get('net_income', 0):,.2f}
                            </span>
                        </div>
                        <div class="d-flex justify-content-between align-items-center mb-3 pb-2 border-bottom">
                            <span class="text-dark">Total Aset:</span>
                            <span class="text-primary fw-bold">Rp {balance_stmt.get('total_assets', 0):,.2f}</span>
                        </div>
                        <div class="d-flex justify-content-between align-items-center">
                            <span class="text-dark">Kas Bersih:</span>
                            <span class="fw-bold {'text-success' if cash_flow.get('net_cash_flow', 0) >= 0 else 'text-danger'}">
                                Rp {cash_flow.get('net_cash_flow', 0):,.2f}
                            </span>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- Row 3: Informasi Stok (jika ada) -->
        <div class="row mt-4">
            <div class="col-12">
                <div class="card">
                    <div class="card-header bg-transparent">
                        <h5 class="section-title mb-0">
                            <i class="fas fa-boxes me-2 text-info"></i>Informasi Stok Tiram
                        </h5>
                    </div>
                    <div class="card-body">
                        <div class="row">
                            <div class="col-md-4 text-center">
                                <div class="border rounded p-3">
                                    <h4 class="text-primary">{current_stock.get('large', 0)}</h4>
                                    <p class="mb-0 text-muted">Tiram Besar (kg)</p>
                                    <small class="text-primary">Rp 800/kg</small>
                                </div>
                            </div>
                            <div class="col-md-4 text-center">
                                <div class="border rounded p-3">
                                    <h4 class="text-success">{current_stock.get('small', 0)}</h4>
                                    <p class="mb-0 text-muted">Tiram Kecil (kg)</p>
                                    <small class="text-success">Rp 500/kg</small>
                                </div>
                            </div>
                            <div class="col-md-4 text-center">
                                <div class="border rounded p-3">
                                    <h4 class="text-info">{current_stock.get('total', 0)}</h4>
                                    <p class="mb-0 text-muted">Total Stok (kg)</p>
                                    <small class="text-info">Total persediaan</small>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    """

    return render_template_string(BASE_TEMPLATE, title='Dashboard', body=dashboard_template, user=current_user())

@app.route('/inventory')
@login_required
def inventory_monitoring():
    """Halaman monitoring stok tiram besar dan kecil"""
    current_stock = get_current_stock()
    
    # Dapatkan riwayat persediaan
    cur = get_db().execute('''
        SELECT date, description, quantity_in, quantity_out, unit_cost, value
        FROM inventory 
        ORDER BY date DESC, id DESC
        LIMIT 20
    ''')
    inventory_history = cur.fetchall()
    
    body = f"""
    <div class="page-header">
        <h1 class="page-title">Monitoring Persediaan Tiram</h1>
        <p class="page-subtitle">Kelola dan pantau stok tiram besar & kecil</p>
    </div>
    
    <div class="row mb-4">
        <!-- Stok Tiram Besar -->
        <div class="col-md-4">
            <div class="card">
                <div class="card-body text-center">
                    <div class="stat-icon bg-primary text-white mx-auto mb-3">
                        <i class="fas fa-water"></i>
                    </div>
                    <h3 class="text-primary">{current_stock['large']}</h3>
                    <h6 class="text-dark">Tiram Besar</h6>
                    <small class="text-muted">Stok tersedia</small>
                    <div class="mt-2">
                        <span class="badge bg-primary">Rp 800/tiram</span>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- Stok Tiram Kecil -->
        <div class="col-md-4">
            <div class="card">
                <div class="card-body text-center">
                    <div class="stat-icon bg-success text-white mx-auto mb-3">
                        <i class="fas fa-tint"></i>
                    </div>
                    <h3 class="text-success">{current_stock['small']}</h3>
                    <h6 class="text-dark">Tiram Kecil</h6>
                    <small class="text-muted">Stok tersedia</small>
                    <div class="mt-2">
                        <span class="badge bg-success">Rp 500/tiram</span>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- Total Stok -->
        <div class="col-md-4">
            <div class="card">
                <div class="card-body text-center">
                    <div class="stat-icon bg-info text-white mx-auto mb-3">
                        <i class="fas fa-boxes"></i>
                    </div>
                    <h3 class="text-info">{current_stock['total']}</h3>
                    <h6 class="text-dark">Total Stok</h6>
                    <small class="text-muted">Keseluruhan persediaan</small>
                    <div class="mt-2">
                        <span class="badge bg-info">Nilai total</span>
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <div class="card">
        <div class="card-header">
            <h5 class="mb-0"><i class="fas fa-history me-2"></i>Riwayat Persediaan</h5>
        </div>
        <div class="card-body">
            <div class="table-responsive">
                <table class="table table-hover">
                    <thead>
                        <tr>
                            <th>Tanggal</th>
                            <th>Keterangan</th>
                            <th class="text-center">Masuk</th>
                            <th class="text-center">Keluar</th>
                            <th class="text-end">Harga Satuan</th>
                            <th class="text-end">Nilai</th>
                        </tr>
                    </thead>
                    <tbody>
    """
    
    for item in inventory_history:
        body += f"""
                        <tr>
                            <td>{item['date']}</td>
                            <td>{item['description']}</td>
                            <td class="text-center text-success">{int(item['quantity_in']) if item['quantity_in'] else ''}</td>
                            <td class="text-center text-danger">{int(item['quantity_out']) if item['quantity_out'] else ''}</td>
                            <td class="text-end">{item['unit_cost']:,.0f}</td>
                            <td class="text-end fw-bold">{item['value']:,.0f}</td>
                        </tr>
        """
    
    body += """
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    """
    
    return render_template_string(BASE_TEMPLATE, title='Monitoring Persediaan', body=body, user=current_user())

@app.route('/journal')
@login_required
def journal():
    try:
        cur = get_db().execute('''
            SELECT je.id, je.date, je.description, je.reference,
                   COALESCE(je.transaction_type, 'General') as transaction_type,
                   je.created_at
            FROM journal_entries je
            ORDER BY je.date DESC, je.id DESC
        ''')
        entries = cur.fetchall()
    except:
        cur = get_db().execute('''
            SELECT je.id, je.date, je.description, je.reference,
                   'General' as transaction_type,
                   je.created_at
            FROM journal_entries je
            ORDER BY je.date DESC, je.id DESC
        ''')
        entries = cur.fetchall()
    
    # Get all journal lines for each entry
    journal_data = []
    for entry in entries:
        cur.execute('''
            SELECT jl.*, a.code, a.name, a.acct_type, a.normal_balance
            FROM journal_lines jl
            JOIN accounts a ON jl.account_id = a.id
            WHERE jl.entry_id = ?
            ORDER BY jl.debit DESC, jl.id
        ''', (entry['id'],))
        lines = cur.fetchall()
        journal_data.append({
            'entry': entry,
            'lines': lines
        })
    
    body = f"""
    <div class="page-header">
        <h1 class="page-title">Jurnal Umum</h1>
        <p class="page-subtitle">Buku Jurnal Transaksi Keuangan</p>
    </div>
    
    <div class="card">
        <div class="card-body">
            <div class="d-flex justify-content-between align-items-center mb-4">
                <h5 class="section-title mb-0">Daftar Entri Jurnal</h5>
                <div>
                    <a href="/journal/new" class="btn btn-primary">
                        <i class="fas fa-plus me-2"></i>Entri Baru
                    </a>
                </div>
            </div>
            
            <!-- Summary Stats -->
            <div class="row mb-4">
                <div class="col-md-3">
                    <div class="stat-card-compact bg-light">
                        <div class="stat-icon-compact bg-primary text-white">
                            <i class="fas fa-file-invoice"></i>
                        </div>
                        <div class="stat-number-compact text-primary">{len(journal_data)}</div>
                        <div class="stat-label-compact">Total Entri</div>
                    </div>
                </div>
                <div class="col-md-9">
                    <div class="alert alert-info">
                        <i class="fas fa-info-circle me-2"></i>
                        <strong>Urutan Kronologis:</strong> Transaksi terbaru ditampilkan di atas, transaksi lama di bawah.
                    </div>
                </div>
            </div>
            
            <div class="journal-container">
    """
    
    if journal_data:
        for data in journal_data:
            entry = data['entry']
            lines = data['lines']
            
            # Calculate totals
            total_debit = sum(line['debit'] for line in lines)
            total_credit = sum(line['credit'] for line in lines)
            is_balanced = abs(total_debit - total_credit) < 0.01
            
            body += f"""
                <!-- Journal Entry Card -->
                <div class="card journal-entry-card mb-4">
                    <div class="card-header bg-light d-flex justify-content-between align-items-center">
                        <div>
                            <strong>{entry['date']}</strong>
                            <span class="badge bg-secondary ms-2">{entry['transaction_type']}</span>
                            {'' if is_balanced else '<span class="badge bg-danger ms-1">Tidak Balance</span>'}
                        </div>
                        <div>
                            <small class="text-muted me-3">#{entry['id']}</small>
                            <a href="/journal/{entry['id']}" class="btn btn-sm btn-outline-primary me-1">
                                <i class="fas fa-eye"></i>
                            </a>
                            <a href="/journal/{entry['id']}/delete" class="btn btn-sm btn-outline-danger" 
                               onclick="return confirm('Hapus entri jurnal #{entry['id']}?')">
                                <i class="fas fa-trash"></i>
                            </a>
                        </div>
                    </div>
                    <div class="card-body">
                        <h6 class="card-title mb-3">{entry['description']}</h6>
                        
                        <div class="table-responsive">
                            <table class="table table-sm journal-lines-table">
                                <thead>
                                    <tr>
                                        <th width="60%">Akun</th>
                                        <th width="20%" class="text-end">Debit</th>
                                        <th width="20%" class="text-end">Kredit</th>
                                    </tr>
                                </thead>
                                <tbody>
            """
            
            # Journal Lines
            for line in lines:
                debit_display = f"Rp {line['debit']:,.2f}" if line['debit'] > 0 else ""
                credit_display = f"Rp {line['credit']:,.2f}" if line['credit'] > 0 else ""
                
                body += f"""
                                    <tr>
                                        <td>
                                            <div><strong>{line['code']}</strong> - {line['name']}</div>
                                            <small class="text-muted">{line.get('description', '')}</small>
                                        </td>
                                        <td class="text-end text-success fw-bold">{debit_display}</td>
                                        <td class="text-end text-danger fw-bold">{credit_display}</td>
                                    </tr>
                """
            
            # Entry Totals
            body += f"""
                                </tbody>
                                <tfoot class="table-active">
                                    <tr>
                                        <td class="text-end"><strong>Total:</strong></td>
                                        <td class="text-end text-success border-top fw-bold">Rp {total_debit:,.2f}</td>
                                        <td class="text-end text-danger border-top fw-bold">Rp {total_credit:,.2f}</td>
                                    </tr>
                                </tfoot>
                            </table>
                        </div>
                        
                        <div class="mt-3">
                            <div class="alert {'alert-success' if is_balanced else 'alert-warning'} py-2 mb-0">
                                <i class="fas {'fa-check-circle' if is_balanced else 'fa-exclamation-triangle'} me-2"></i>
                                {'Entri jurnal seimbang' if is_balanced else f'Tidak seimbang! Selisih: Rp {abs(total_debit - total_credit):,.2f}'}
                            </div>
                        </div>
                    </div>
                </div>
            """
    else:
        body += """
            <div class="text-center py-5">
                <i class="fas fa-book fa-3x text-muted mb-3"></i>
                <h5 class="text-muted">Belum Ada Entri Jurnal</h5>
                <p class="text-muted">Mulai dengan membuat entri jurnal pertama Anda.</p>
                <a href="/journal/new" class="btn btn-primary">
                    <i class="fas fa-plus me-2"></i>Buat Entri Jurnal
                </a>
            </div>
        """
    
    body += """
            </div>
        </div>
    </div>

    <style>
    .journal-entry-card {
        border-left: 4px solid #007bff;
        transition: all 0.3s ease;
    }
    
    .journal-entry-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
    }
    
    .journal-lines-table {
        font-size: 0.9rem;
    }
    
    .journal-lines-table td {
        padding: 0.5rem 0.75rem;
        vertical-align: middle;
    }
    
    .journal-container {
        max-height: 70vh;
        overflow-y: auto;
        padding-right: 10px;
    }
    
    /* Custom scrollbar */
    .journal-container::-webkit-scrollbar {
        width: 6px;
    }
    
    .journal-container::-webkit-scrollbar-track {
        background: #f1f1f1;
        border-radius: 10px;
    }
    
    .journal-container::-webkit-scrollbar-thumb {
        background: #c1c1c1;
        border-radius: 10px;
    }
    
    .journal-container::-webkit-scrollbar-thumb:hover {
        background: #a8a8a8;
    }
    </style>
    """
    
    return render_template_string(BASE_TEMPLATE, title='Jurnal Umum', body=body, user=current_user())

# ---------- API Endpoints untuk Template ----------

@app.route('/api/journal/templates')
@login_required
def api_journal_templates():
    """Get all transaction templates"""
    cur = get_db().execute('SELECT template_key, label, description FROM transaction_templates ORDER BY label')
    templates = cur.fetchall()
    
    return {
        'templates': [
            {
                'key': t['template_key'],
                'label': t['label'],
                'description': t['description']
            }
            for t in templates
        ]
    }

@app.route('/api/journal/templates/<template_key>')
@login_required
def api_journal_template_detail(template_key):
    """Get detailed template with account information"""
    cur = get_db().execute(
        'SELECT template_key, label, description, lines_json FROM transaction_templates WHERE template_key = ?',
        (template_key,)
    )
    template = cur.fetchone()
    
    if not template:
        return {'error': 'Template not found'}, 404
    
    lines = json.loads(template['lines_json'])
    
    # Enrich dengan informasi akun lengkap
    enriched_lines = []
    for line in lines:
        account_cur = get_db().execute(
            'SELECT id, code, name, acct_type, normal_balance FROM accounts WHERE code = ?',
            (line['account_code'],)
        )
        account = account_cur.fetchone()
        
        if account:
            enriched_line = {
                **line,
                'account_id': account['id'],
                'account_code': account['code'],
                'account_name': account['name'],
                'account_type': account['acct_type'],
                'normal_balance': account['normal_balance']
            }
            enriched_lines.append(enriched_line)
    
    return {
        'template_key': template['template_key'],
        'label': template['label'],
        'description': template['description'],
        'lines': enriched_lines
    }

@app.route('/api/accounts')
@login_required
def api_accounts():
    """Get all accounts for dropdown"""
    accounts = all_accounts()
    return {
        'accounts': [
            {
                'id': a['id'],
                'code': a['code'],
                'name': a['name'],
                'acct_type': a['acct_type'],
                'normal_balance': a['normal_balance']
            }
            for a in accounts
        ]
    }

@app.route('/journal/new', methods=['GET', 'POST'])
@login_required
def journal_new():
    accounts = all_accounts()
    options_html = "".join([f'<option value="{a["id"]}">{a["code"]} - {a["name"]}</option>' for a in accounts])
    
    if request.method == 'POST':
        date = request.form['date']
        description = request.form['description']
        reference = request.form.get('reference', '')
        transaction_type = request.form.get('transaction_type', 'General')
        
        lines = []
        idx = 0
        while True:
            account_id = request.form.get(f'account_{idx}')
            if not account_id:
                break
            
            debit = float(request.form.get(f'debit_{idx}', 0) or 0)
            credit = float(request.form.get(f'credit_{idx}', 0) or 0)
            line_desc = request.form.get(f'line_desc_{idx}', '')
            
            if debit > 0 or credit > 0:
                lines.append({
                    'account_id': int(account_id),
                    'debit': debit,
                    'credit': credit,
                    'description': line_desc
                })
            idx += 1
        
        # Validasi
        if len(lines) < 2:
            flash('Entri jurnal harus memiliki setidaknya dua baris')
            return redirect(url_for('journal_new'))
        
        total_debit = sum(line['debit'] for line in lines)
        total_credit = sum(line['credit'] for line in lines)
        
        if abs(total_debit - total_credit) > 0.01:
            flash('Debit dan kredit harus seimbang')
            return redirect(url_for('journal_new'))
        
        # Posting entri jurnal
        try:
            entry_id = post_journal_entry(date, description, lines, reference, transaction_type)
            flash(f'Entri jurnal #{entry_id} berhasil diposting!')
            return redirect(url_for('journal'))
        except Exception as e:
            flash(f'Error posting entri jurnal: {str(e)}')
    
    body = f"""
    <div class="page-header">
        <h1 class="page-title">Entri Jurnal Baru</h1>
        <p class="page-subtitle">Buat entri jurnal untuk transaksi bisnis</p>
    </div>
    
    <div class="card">
        <div class="card-body">
            <form method="post">
                <div class="row mb-4">
                    <div class="col-md-3">
                        <label class="form-label fw-semibold">Tanggal</label>
                        <input type="date" class="form-control" name="date" value="{datetime.now().date().isoformat()}" required>
                    </div>
                    <div class="col-md-6">
                        <label class="form-label fw-semibold">Keterangan</label>
                        <input type="text" class="form-control" name="description" placeholder="Deskripsi entri jurnal" required>
                    </div>
                    <div class="col-md-3">
                        <label class="form-label fw-semibold">Referensi</label>
                        <input type="text" class="form-control" name="reference" placeholder="No. Referensi">
                    </div>
                </div>
                
                <h6 class="mb-3"><i class="fas fa-list me-2"></i>Baris Jurnal</h6>
                <div id="journal-lines">
                    <div class="row mb-3">
                        <div class="col-md-5">
                            <label class="form-label">Akun</label>
                            <select class="form-select" name="account_0" required>
                                <option value="">Pilih Akun</option>
                                {options_html}
                            </select>
                        </div>
                        <div class="col-md-3">
                            <label class="form-label">Debit</label>
                            <input type="number" class="form-control" name="debit_0" placeholder="0.00" step="0.01" min="0" oninput="checkBalance()">
                        </div>
                        <div class="col-md-3">
                            <label class="form-label">Kredit</label>
                            <input type="number" class="form-control" name="credit_0" placeholder="0.00" step="0.01" min="0" oninput="checkBalance()">
                        </div>
                        <div class="col-md-1 d-flex align-items-end">
                            <button type="button" class="btn btn-danger btn-sm" disabled>
                                <i class="fas fa-times"></i>
                            </button>
                        </div>
                    </div>
                </div>
                
                <div class="mb-3">
                    <button type="button" class="btn btn-outline-primary" onclick="addJournalLine()">
                        <i class="fas fa-plus me-2"></i>Tambah Baris
                    </button>
                </div>
                
                <div id="balance-check" class="alert alert-info mb-3">
                    <i class="fas fa-info-circle me-2"></i>Masukkan jumlah untuk memeriksa keseimbangan
                </div>
                
                <div class="d-flex gap-2">
                    <button type="submit" class="btn btn-primary">Posting Entri Jurnal</button>
                    <a href="/journal" class="btn btn-outline-secondary">Batal</a>
                </div>
            </form>
        </div>
    </div>
    
    <div id="account-options" style="display: none;">
        {options_html}
    </div>
    """
    return render_template_string(BASE_TEMPLATE, title='Entri Jurnal Baru', body=body, user=current_user())

@app.route('/journal/<int:entry_id>')
@login_required
def journal_view(entry_id):
    cur = get_db().execute('SELECT * FROM journal_entries WHERE id = ?', (entry_id,))
    entry = cur.fetchone()
    
    if not entry:
        flash('Entri jurnal tidak ditemukan')
        return redirect(url_for('journal'))
    
    cur.execute('''
        SELECT jl.*, a.code, a.name, a.acct_type, a.normal_balance
        FROM journal_lines jl
        JOIN accounts a ON jl.account_id = a.id
        WHERE jl.entry_id = ?
        ORDER BY jl.debit DESC, jl.id
    ''', (entry_id,))
    lines = cur.fetchall()
    
    transaction_type = entry['transaction_type'] if 'transaction_type' in entry.keys() else 'General'
    reference = entry['reference'] if entry['reference'] else '-'
    
    total_debit = sum(line['debit'] for line in lines)
    total_credit = sum(line['credit'] for line in lines)
    is_balanced = abs(total_debit - total_credit) < 0.01
    
    body = f"""
    <div class="page-header">
        <h1 class="page-title">Detail Jurnal #{entry['id']}</h1>
        <p class="page-subtitle">Detail lengkap entri jurnal</p>
    </div>
    
    <div class="card">
        <div class="card-header bg-light">
            <div class="row">
                <div class="col-md-3">
                    <strong>Tanggal:</strong> {entry['date']}
                </div>
                <div class="col-md-3">
                    <strong>Jenis:</strong> <span class="badge bg-secondary">{transaction_type}</span>
                </div>
                <div class="col-md-3">
                    <strong>Referensi:</strong> {reference}
                </div>
                <div class="col-md-3">
                    <strong>Status:</strong> 
                    <span class="badge {'bg-success' if is_balanced else 'bg-danger'}">
                        {'Seimbang' if is_balanced else 'Tidak Seimbang'}
                    </span>
                </div>
            </div>
        </div>
        <div class="card-body">
            <h6 class="card-title mb-4">{entry['description']}</h6>
            
            <div class="table-responsive">
                <table class="table journal-detail-table">
                    <thead class="table-light">
                        <tr>
                            <th width="50%">Akun</th>
                            <th width="25%" class="text-end">Debit</th>
                            <th width="25%" class="text-end">Kredit</th>
                        </tr>
                    </thead>
                    <tbody>
    """
    
    for line in lines:
        debit_display = f"Rp {line['debit']:,.2f}" if line['debit'] > 0 else "-"
        credit_display = f"Rp {line['credit']:,.2f}" if line['credit'] > 0 else "-"
        
        body += f"""
                        <tr>
                            <td>
                                <div class="d-flex justify-content-between">
                                    <div>
                                        <strong>{line['code']}</strong> - {line['name']}
                                        <br>
                                        <small class="text-muted">{line['acct_type']} • {line['normal_balance']} normal</small>
                                    </div>
                                    <div class="text-end">
                                        <small class="text-muted">{line.get('description', '')}</small>
                                    </div>
                                </div>
                            </td>
                            <td class="text-end {'text-success fw-bold' if line['debit'] > 0 else 'text-muted'}">{debit_display}</td>
                            <td class="text-end {'text-danger fw-bold' if line['credit'] > 0 else 'text-muted'}">{credit_display}</td>
                        </tr>
        """
    
    body += f"""
                    </tbody>
                    <tfoot class="table-active">
                        <tr>
                            <td class="text-end"><strong>Total:</strong></td>
                            <td class="text-end text-success border-top fw-bold">Rp {total_debit:,.2f}</td>
                            <td class="text-end text-danger border-top fw-bold">Rp {total_credit:,.2f}</td>
                        </tr>
                    </tfoot>
                </table>
            </div>
            
            <div class="mt-4">
                <div class="alert {'alert-success' if is_balanced else 'alert-warning'}">
                    <i class="fas {'fa-check-circle' if is_balanced else 'fa-exclamation-triangle'} me-2"></i>
                    {'Entri jurnal ini seimbang dan telah diposting dengan benar.' if is_balanced else f'Entri jurnal tidak seimbang! Selisih: Rp {abs(total_debit - total_credit):,.2f}'}
                </div>
            </div>
            
            <div class="mt-4 pt-3 border-top">
                <a href="/journal" class="btn btn-outline-secondary">
                    <i class="fas fa-arrow-left me-2"></i>Kembali ke Jurnal
                </a>
                <a href="/journal/{entry_id}/delete" class="btn btn-outline-danger float-end" 
                   onclick="return confirm('Hapus entri jurnal #{entry_id}?')">
                    <i class="fas fa-trash me-2"></i>Hapus Entri
                </a>
            </div>
        </div>
    </div>

    <style>
    .journal-detail-table td {
        padding: 0.75rem;
        vertical-align: middle;
    }
    
    .journal-detail-table tbody tr:hover {
        background-color: #f8f9fa;
    }
    </style>
    """
    
    return render_template_string(BASE_TEMPLATE, title='Detail Jurnal', body=body, user=current_user())
    
@app.route('/journal/<int:entry_id>/delete', methods=['GET', 'POST'])
@login_required
def delete_journal_entry(entry_id):
    """Hapus entri jurnal dan semua barisnya"""
    db = get_db()
    
    # Dapatkan detail entri sebelum dihapus (untuk flash message)
    cur = db.execute('SELECT date, description FROM journal_entries WHERE id = ?', (entry_id,))
    entry = cur.fetchone()
    
    if not entry:
        flash('Entri jurnal tidak ditemukan')
        return redirect(url_for('journal'))
    
    if request.method == 'POST':
        try:
            # Hapus semua baris jurnal terkait
            db.execute('DELETE FROM journal_lines WHERE entry_id = ?', (entry_id,))
            
            # Hapus entri jurnal
            db.execute('DELETE FROM journal_entries WHERE id = ?', (entry_id,))
            
            db.commit()
            
            flash(f'✅ Entri jurnal #{entry_id} ({entry["description"]}) berhasil dihapus!')
            return redirect(url_for('journal'))
            
        except Exception as e:
            db.rollback()
            flash(f'❌ Error menghapus entri jurnal: {str(e)}')
            return redirect(url_for('journal_view', entry_id=entry_id))
    
    # Jika method GET, tampilkan konfirmasi
    body = f"""
    <div class="page-header">
        <h1 class="page-title">Hapus Entri Jurnal #{entry_id}</h1>
        <p class="page-subtitle">Konfirmasi penghapusan entri jurnal</p>
    </div>
    
    <div class="card">
        <div class="card-header bg-danger text-white">
            <h5 class="mb-0"><i class="fas fa-exclamation-triangle me-2"></i>Konfirmasi Hapus</h5>
        </div>
        <div class="card-body">
            <div class="alert alert-danger">
                <h6><i class="fas fa-skull-crossbones me-2"></i>PERINGATAN!</h6>
                <p class="mb-0">
                    Anda akan menghapus entri jurnal berikut:
                </p>
            </div>
            
            <div class="card bg-light">
                <div class="card-body">
                    <p><strong>ID:</strong> #{entry_id}</p>
                    <p><strong>Tanggal:</strong> {entry['date']}</p>
                    <p><strong>Keterangan:</strong> {entry['description']}</p>
                </div>
            </div>
            
            <div class="alert alert-warning mt-3">
                <h6><i class="fas fa-info-circle me-2"></i>Dampak Penghapusan:</h6>
                <ul class="mb-0">
                    <li>Semua baris jurnal akan dihapus</li>
                    <li>Pengaruhnya pada buku besar akan hilang</li>
                    <li>Stok inventory akan disesuaikan (jika ada)</li>
                    <li><strong>Tindakan ini tidak dapat dibatalkan!</strong></li>
                </ul>
            </div>
            
            <form method="post" class="mt-4">
                <div class="d-flex gap-2">
                    <button type="submit" class="btn btn-danger">
                        <i class="fas fa-trash me-2"></i>Ya, Hapus Entri Jurnal
                    </button>
                    <a href="/journal/{entry_id}" class="btn btn-outline-secondary">
                        <i class="fas fa-times me-2"></i>Batal
                    </a>
                </div>
            </form>
        </div>
    </div>
    """
    return render_template_string(BASE_TEMPLATE, title='Hapus Jurnal', body=body, user=current_user())

@app.route('/ledger')
@login_required
def ledger():
    accounts = all_accounts()
    
    body = """
    <div class="page-header">
        <h1 class="page-title">Buku Besar</h1>
        <p class="page-subtitle">Daftar semua akun dan saldo terkini</p>
    </div>
    
    <div class="card">
        <div class="card-body">
            <div class="table-responsive">
                <table class="table table-hover accounting-table">
                    <thead>
                        <tr>
                            <th>Kode Akun</th>
                            <th>Nama Akun</th>
                            <th>Jenis</th>
                            <th class="text-end">Saldo Saat Ini</th>
                            <th>Aksi</th>
                        </tr>
                    </thead>
                    <tbody>
    """
    
    for account in accounts:
        balance = get_account_balance(account['id'])
        balance_class = 'text-success' if balance >= 0 else 'text-danger'
        
        body += f"""
                        <tr>
                            <td><strong>{account['code']}</strong></td>
                            <td>{account['name']}</td>
                            <td><span class="badge bg-secondary">{account['acct_type']}</span></td>
                            <td class="text-end {balance_class} fw-bold">Rp {balance:,.2f}</td>
                            <td>
                                <a href="/ledger/{account['id']}" class="btn btn-sm btn-outline-primary">
                                    <i class="fas fa-eye me-1"></i>Lihat
                                </a>
                            </td>
                        </tr>
        """
    
    body += """
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    """
    return render_template_string(BASE_TEMPLATE, title='Buku Besar', body=body, user=current_user())

@app.route('/ledger/<int:account_id>')
@login_required
def ledger_account(account_id):
    cur = get_db().execute('SELECT * FROM accounts WHERE id = ?', (account_id,))
    account = cur.fetchone()
    
    if not account:
        flash('Akun tidak ditemukan')
        return redirect(url_for('ledger'))
    
    # Dapatkan entri jurnal
    cur.execute('''
        SELECT je.date, je.description, jl.debit, jl.credit, jl.description as line_desc
        FROM journal_lines jl
        JOIN journal_entries je ON jl.entry_id = je.id
        WHERE jl.account_id = ?
        ORDER BY je.date, je.id
    ''', (account_id,))
    journal_entries = cur.fetchall()
    
    # Dapatkan entri penyesuaian
    cur.execute('''
        SELECT ae.date, ae.description, al.debit, al.credit, al.description as line_desc
        FROM adjusting_lines al
        JOIN adjusting_entries ae ON al.adj_id = ae.id
        WHERE al.account_id = ?
        ORDER BY ae.date, ae.id
    ''', (account_id,))
    adjusting_entries = cur.fetchall()
    
    # Hitung saldo berjalan
    balance = 0
    transactions = []
    
    # Gabungkan dan urutkan semua transaksi
    all_entries = []
    for entry in journal_entries:
        all_entries.append({
            'date': entry['date'],
            'description': entry['description'],
            'debit': entry['debit'],
            'credit': entry['credit'],
            'line_desc': entry['line_desc'] if entry['line_desc'] else '',
            'type': 'journal'
        })
    
    for entry in adjusting_entries:
        all_entries.append({
            'date': entry['date'],
            'description': entry['description'] + ' (Penyesuaian)',
            'debit': entry['debit'],
            'credit': entry['credit'],
            'line_desc': entry['line_desc'] if entry['line_desc'] else '',
            'type': 'adjusting'
        })
    
    # Urutkan berdasarkan tanggal
    all_entries.sort(key=lambda x: x['date'])
    
    # Hitung saldo berjalan
    for entry in all_entries:
        if account['normal_balance'] == 'Debit':
            balance += entry['debit'] - entry['credit']
        else:
            balance += entry['credit'] - entry['debit']
        
        entry['balance'] = balance
    
    current_balance = get_account_balance(account_id)
    
    body = f"""
    <div class="page-header">
        <h1 class="page-title">Buku Besar: {account['code']} - {account['name']}</h1>
        <p class="page-subtitle">Riwayat transaksi untuk akun ini</p>
    </div>
    
    <div class="card">
        <div class="card-body">
            <div class="row mb-4">
                <div class="col-md-6">
                    <div class="card bg-light">
                        <div class="card-body">
                            <h6><i class="fas fa-info-circle me-2"></i>Informasi Akun</h6>
                            <p><strong>Saldo Saat Ini:</strong> 
                                <span class="{'text-success' if current_balance >= 0 else 'text-danger'} fw-bold">
                                    Rp {current_balance:,.2f}
                                </span>
                            </p>
                            <p><strong>Saldo Normal:</strong> {account['normal_balance']}</p>
                            <p><strong>Deskripsi:</strong> {account['description'] if account['description'] else 'Tidak ada deskripsi'}</p>
                        </div>
                    </div>
                </div>
            </div>
            
            <h6><i class="fas fa-history me-2"></i>Riwayat Transaksi</h6>
            <div class="table-responsive">
                <table class="table accounting-table">
                    <thead>
                        <tr>
                            <th>Tanggal</th>
                            <th>Keterangan</th>
                            <th class="text-end">Debit</th>
                            <th class="text-end">Kredit</th>
                            <th class="text-end">Saldo</th>
                        </tr>
                    </thead>
                    <tbody>
    """
    
    for entry in all_entries:
        row_class = 'table-warning' if entry['type'] == 'adjusting' else ''
        debit_display = f"Rp {entry['debit']:,.2f}" if entry['debit'] > 0 else ""
        credit_display = f"Rp {entry['credit']:,.2f}" if entry['credit'] > 0 else ""
        
        # Handle line_desc dengan benar
        line_desc_html = ""
        if entry.get('line_desc'):
            line_desc_html = f"<br><small class='text-muted'>{entry['line_desc']}</small>"
        
        body += f"""
                        <tr class="{row_class}">
                            <td>{entry['date']}</td>
                            <td>
                                {entry['description']}
                                {line_desc_html}
                            </td>
                            <td class="text-end text-success">{debit_display}</td>
                            <td class="text-end text-danger">{credit_display}</td>
                            <td class="text-end fw-bold">Rp {entry['balance']:,.2f}</td>
                        </tr>
        """
    
    body += f"""
                    </tbody>
                </table>
            </div>
            
            <div class="mt-3">
                <small class="text-muted">
                    <i class="fas fa-info-circle me-1"></i>
                    Baris kuning menunjukkan entri penyesuaian
                </small>
            </div>
        </div>
    </div>
    """
    return render_template_string(BASE_TEMPLATE, title=f"Buku Besar - {account['code']}", body=body, user=current_user())

@app.route('/trial_balance')
@login_required
def trial_balance_view():
    # Neraca Saldo Sebelum Penyesuaian
    utb, utd, utc = trial_balance(include_adjustments=False)
    # Neraca Saldo Setelah Penyesuaian  
    atb, atd, atc = trial_balance(include_adjustments=True)
    
    body = """
    <div class="page-header">
        <h1 class="page-title">Neraca Saldo</h1>
        <p class="page-subtitle">Perbandingan neraca saldo sebelum dan setelah penyesuaian</p>
    </div>
    
    <div class="row">
        <div class="col-md-6">
            <div class="card">
                <div class="card-header bg-light">
                    <h6 class="mb-0"><i class="fas fa-balance-scale me-2"></i>Neraca Saldo Sebelum Penyesuaian</h6>
                    <small class="text-muted">Sebelum entri penyesuaian</small>
                </div>
                <div class="card-body">
                    <div class="table-responsive">
                        <table class="table accounting-table">
                            <thead>
                                <tr>
                                    <th>Akun</th>
                                    <th class="text-end">Debit</th>
                                    <th class="text-end">Kredit</th>
                                </tr>
                            </thead>
                            <tbody>
    """
    
    for item in utb:
        if item['debit'] != 0 or item['credit'] != 0:
            # Format yang benar sesuai prinsip akuntansi
            debit_display = f"Rp {item['debit']:,.2f}" if item['debit'] > 0 else ""
            credit_display = f"Rp {item['credit']:,.2f}" if item['credit'] > 0 else ""
            
            body += f"""
                                <tr>
                                    <td>
                                        <div><strong>{item['account']['code']}</strong> {item['account']['name']}</div>
                                        <small class="text-muted">{item['account']['acct_type']} - {item['account']['normal_balance']} normal</small>
                                    </td>
                                    <td class="text-end {'text-success fw-bold' if item['debit'] > 0 else ''}">{debit_display}</td>
                                    <td class="text-end {'text-danger fw-bold' if item['credit'] > 0 else ''}">{credit_display}</td>
                                </tr>
            """
    
    # Status balance
    is_balanced = abs(utd - utc) < 0.01
    balance_status = "✅ SEIMBANG" if is_balanced else f"❌ TIDAK SEIMBANG (Selisih: Rp {abs(utd - utc):,.2f})"
    
    body += f"""
                            </tbody>
                            <tfoot class="table-active">
                                <tr>
                                    <th>Total</th>
                                    <th class="text-end text-success">Rp {utd:,.2f}</th>
                                    <th class="text-end text-danger">Rp {utc:,.2f}</th>
                                </tr>
                                <tr>
                                    <th colspan="3" class="text-center {'text-success' if is_balanced else 'text-danger'}">
                                        <i class="fas {'fa-check-circle' if is_balanced else 'fa-exclamation-triangle'} me-2"></i>
                                        {balance_status}
                                    </th>
                                </tr>
                            </tfoot>
                        </table>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="col-md-6">
            <div class="card">
                <div class="card-header bg-light">
                    <h6 class="mb-0"><i class="fas fa-balance-scale me-2"></i>Neraca Saldo Setelah Penyesuaian</h6>
                    <small class="text-muted">Setelah entri penyesuaian</small>
                </div>
                <div class="card-body">
                    <div class="table-responsive">
                        <table class="table accounting-table">
                            <thead>
                                <tr>
                                    <th>Akun</th>
                                    <th class="text-end">Debit</th>
                                    <th class="text-end">Kredit</th>
                                </tr>
                            </thead>
                            <tbody>
    """
    
    for item in atb:
        if item['debit'] != 0 or item['credit'] != 0:
            debit_display = f"Rp {item['debit']:,.2f}" if item['debit'] > 0 else ""
            credit_display = f"Rp {item['credit']:,.2f}" if item['credit'] > 0 else ""
            
            body += f"""
                                <tr>
                                    <td>
                                        <div><strong>{item['account']['code']}</strong> {item['account']['name']}</div>
                                        <small class="text-muted">{item['account']['acct_type']} - {item['account']['normal_balance']} normal</small>
                                    </td>
                                    <td class="text-end {'text-success fw-bold' if item['debit'] > 0 else ''}">{debit_display}</td>
                                    <td class="text-end {'text-danger fw-bold' if item['credit'] > 0 else ''}">{credit_display}</td>
                                </tr>
            """
    
    # Status balance untuk after adjustments
    is_balanced_adj = abs(atd - atc) < 0.01
    balance_status_adj = "✅ SEIMBANG" if is_balanced_adj else f"❌ TIDAK SEIMBANG (Selisih: Rp {abs(atd - atc):,.2f})"
    
    body += """
    <div class="row mt-4">
        <div class="col-12">
            <div class="card">
                <div class="card-body text-center">
                    <h6><i class="fas fa-tools me-2"></i>Perbaikan Neraca Saldo</h6>
                    <p class="text-muted mb-3">
                        Jika neraca saldo tidak balance, klik tombol di bawah untuk memperbaiki otomatis.
                    </p>
                    <a href="/fix_database" class="btn btn-warning">
                        <i class="fas fa-hammer me-2"></i>Perbaiki Neraca Saldo
                    </a>
                    <small class="d-block mt-2 text-muted">
                        Tindakan ini akan mengatur ulang saldo awal ke nilai yang benar.
                    </small>
                </div>
            </div>
        </div>
    </div>
    """
    
    return render_template_string(BASE_TEMPLATE, title='Neraca Saldo', body=body, user=current_user())

@app.route('/adjusting')
@login_required
def adjusting():
    cur = get_db().execute('SELECT * FROM adjusting_entries ORDER BY date DESC, id DESC')
    entries = cur.fetchall()
    
    # Get all adjusting lines for each entry
    adjusting_data = []
    for entry in entries:
        cur.execute('''
            SELECT al.*, a.code, a.name, a.acct_type
            FROM adjusting_lines al
            JOIN accounts a ON al.account_id = a.id
            WHERE al.adj_id = ?
            ORDER BY al.debit DESC, al.id
        ''', (entry['id'],))
        lines = cur.fetchall()
        adjusting_data.append({
            'entry': entry,
            'lines': lines
        })
    
    body = """
    <div class="page-header">
        <h1 class="page-title">Ayat Penyesuaian</h1>
        <p class="page-subtitle">Entri penyesuaian untuk penutupan periode akuntansi</p>
    </div>
    
    <div class="card">
        <div class="card-body">
            <div class="d-flex justify-content-between align-items-center mb-4">
                <h5 class="section-title mb-0">Daftar Ayat Penyesuaian</h5>
                <a href="/adjusting/new" class="btn btn-primary">
                    <i class="fas fa-plus me-2"></i>Ayat Penyesuaian Baru
                </a>
            </div>
            
            <!-- Info Panel -->
            <div class="alert alert-warning mb-4">
                <i class="fas fa-info-circle me-2"></i>
                <strong>Fungsi Ayat Penyesuaian:</strong> Untuk menyesuaikan saldo akun sebelum penyusunan laporan keuangan (akrual, deferral, penyusutan, dll).
            </div>
            
            <div class="adjusting-container">
    """
    
    if adjusting_data:
        for data in adjusting_data:
            entry = data['entry']
            lines = data['lines']
            
            # Calculate totals
            total_debit = sum(line['debit'] for line in lines)
            total_credit = sum(line['credit'] for line in lines)
            is_balanced = abs(total_debit - total_credit) < 0.01
            
            body += f"""
                <!-- Adjusting Entry Card -->
                <div class="card adjusting-entry-card mb-4">
                    <div class="card-header bg-warning bg-opacity-10 d-flex justify-content-between align-items-center">
                        <div>
                            <strong>{entry['date']}</strong>
                            <span class="badge bg-warning text-dark ms-2">Penyesuaian</span>
                            {'' if is_balanced else '<span class="badge bg-danger ms-1">Tidak Balance</span>'}
                        </div>
                        <div>
                            <small class="text-muted me-3">#{entry['id']}</small>
                            <a href="/adjusting/{entry['id']}" class="btn btn-sm btn-outline-primary">
                                <i class="fas fa-eye"></i> Detail
                            </a>
                        </div>
                    </div>
                    <div class="card-body">
                        <h6 class="card-title mb-3">{entry['description']}</h6>
                        
                        <div class="table-responsive">
                            <table class="table table-sm adjusting-lines-table">
                                <thead>
                                    <tr>
                                        <th width="60%">Akun</th>
                                        <th width="20%" class="text-end">Debit</th>
                                        <th width="20%" class="text-end">Kredit</th>
                                    </tr>
                                </thead>
                                <tbody>
            """
            
            # Adjusting Lines
            for line in lines:
                debit_display = f"Rp {line['debit']:,.2f}" if line['debit'] > 0 else ""
                credit_display = f"Rp {line['credit']:,.2f}" if line['credit'] > 0 else ""
                
                body += f"""
                                    <tr>
                                        <td>
                                            <div><strong>{line['code']}</strong> - {line['name']}</div>
                                            <small class="text-muted">{line.get('description', '')}</small>
                                        </td>
                                        <td class="text-end text-success fw-bold">{debit_display}</td>
                                        <td class="text-end text-danger fw-bold">{credit_display}</td>
                                    </tr>
                """
            
            # Entry Totals
            body += f"""
                                </tbody>
                                <tfoot class="table-active">
                                    <tr>
                                        <td class="text-end"><strong>Total:</strong></td>
                                        <td class="text-end text-success border-top fw-bold">Rp {total_debit:,.2f}</td>
                                        <td class="text-end text-danger border-top fw-bold">Rp {total_credit:,.2f}</td>
                                    </tr>
                                </tfoot>
                            </table>
                        </div>
                        
                        <div class="mt-3">
                            <div class="alert {'alert-success' if is_balanced else 'alert-warning'} py-2 mb-0">
                                <i class="fas {'fa-check-circle' if is_balanced else 'fa-exclamation-triangle'} me-2"></i>
                                {'Ayat penyesuaian seimbang' if is_balanced else f'Tidak seimbang! Selisih: Rp {abs(total_debit - total_credit):,.2f}'}
                            </div>
                        </div>
                    </div>
                </div>
            """
    else:
        body += """
            <div class="text-center py-5">
                <i class="fas fa-adjust fa-3x text-muted mb-3"></i>
                <h5 class="text-muted">Belum Ada Ayat Penyesuaian</h5>
                <p class="text-muted">Ayat penyesuaian digunakan untuk menyesuaikan saldo akun sebelum laporan keuangan.</p>
                <a href="/adjusting/new" class="btn btn-primary">
                    <i class="fas fa-plus me-2"></i>Buat Ayat Penyesuaian
                </a>
            </div>
        """
    
    body += """
            </div>
        </div>
    </div>

    <style>
    .adjusting-entry-card {
        border-left: 4px solid #ffc107;
        transition: all 0.3s ease;
    }
    
    .adjusting-entry-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
    }
    
    .adjusting-lines-table {
        font-size: 0.9rem;
    }
    
    .adjusting-lines-table td {
        padding: 0.5rem 0.75rem;
        vertical-align: middle;
    }
    
    .adjusting-container {
        max-height: 70vh;
        overflow-y: auto;
        padding-right: 10px;
    }
    
    /* Custom scrollbar */
    .adjusting-container::-webkit-scrollbar {
        width: 6px;
    }
    
    .adjusting-container::-webkit-scrollbar-track {
        background: #f1f1f1;
        border-radius: 10px;
    }
    
    .adjusting-container::-webkit-scrollbar-thumb {
        background: #c1c1c1;
        border-radius: 10px;
    }
    
    .adjusting-container::-webkit-scrollbar-thumb:hover {
        background: #a8a8a8;
    }
    </style>
    """
    
    return render_template_string(BASE_TEMPLATE, title='Ayat Penyesuaian', body=body, user=current_user())

@app.route('/adjusting/new', methods=['GET', 'POST'])
@login_required
def adjusting_new():
    accounts = all_accounts()
    options_html = "".join([f'<option value="{a["id"]}">{a["code"]} - {a["name"]}</option>' for a in accounts])
    
    if request.method == 'POST':
        date = request.form['date']
        description = request.form['description']
        
        lines = []
        idx = 0
        while True:
            account_id = request.form.get(f'account_{idx}')
            if not account_id:
                break
            
            debit = float(request.form.get(f'debit_{idx}', 0) or 0)
            credit = float(request.form.get(f'credit_{idx}', 0) or 0)
            line_desc = request.form.get(f'line_desc_{idx}', '')
            
            if debit > 0 or credit > 0:
                lines.append({
                    'account_id': int(account_id),
                    'debit': debit,
                    'credit': credit,
                    'description': line_desc
                })
            idx += 1
        
        # Validasi
        if len(lines) < 2:
            flash('Ayat penyesuaian harus memiliki setidaknya dua baris')
            return redirect(url_for('adjusting_new'))
        
        total_debit = sum(line['debit'] for line in lines)
        total_credit = sum(line['credit'] for line in lines)
        
        if abs(total_debit - total_credit) > 0.01:
            flash('Debit dan kredit harus seimbang')
            return redirect(url_for('adjusting_new'))
        
        # Posting ayat penyesuaian
        try:
            adj_id = post_adjusting_entry(date, description, lines)
            flash(f'Ayat penyesuaian #{adj_id} berhasil diposting!')
            return redirect(url_for('adjusting'))
        except Exception as e:
            flash(f'Error posting ayat penyesuaian: {str(e)}')
    
    body = f"""
    <div class="page-header">
        <h1 class="page-title">Ayat Penyesuaian Baru</h1>
        <p class="page-subtitle">Buat ayat penyesuaian untuk penutupan periode</p>
    </div>
    
    <div class="card">
        <div class="card-body">
            <form method="post">
                <div class="row mb-4">
                    <div class="col-md-3">
                        <label class="form-label fw-semibold">Tanggal</label>
                        <input type="date" class="form-control" name="date" value="{datetime.now().date().isoformat()}" required>
                    </div>
                    <div class="col-md-9">
                        <label class="form-label fw-semibold">Keterangan</label>
                        <input type="text" class="form-control" name="description" placeholder="Deskripsi ayat penyesuaian" required>
                    </div>
                </div>
                
                <h6 class="mb-3"><i class="fas fa-list me-2"></i>Baris Penyesuaian</h6>
                <div id="adjusting-lines">
                    <div class="row mb-3">
                        <div class="col-md-5">
                            <label class="form-label">Akun</label>
                            <select class="form-select" name="account_0" required>
                                <option value="">Pilih Akun</option>
                                {options_html}
                            </select>
                        </div>
                        <div class="col-md-3">
                            <label class="form-label">Debit</label>
                            <input type="number" class="form-control" name="debit_0" placeholder="0.00" step="0.01" min="0" oninput="checkBalance()">
                        </div>
                        <div class="col-md-3">
                            <label class="form-label">Kredit</label>
                            <input type="number" class="form-control" name="credit_0" placeholder="0.00" step="0.01" min="0" oninput="checkBalance()">
                        </div>
                        <div class="col-md-1 d-flex align-items-end">
                            <button type="button" class="btn btn-danger btn-sm" disabled>
                                <i class="fas fa-times"></i>
                            </button>
                        </div>
                    </div>
                </div>
                
                <div class="mb-3">
                    <button type="button" class="btn btn-outline-primary" onclick="addAdjustingLine()">
                        <i class="fas fa-plus me-2"></i>Tambah Baris
                    </button>
                </div>
                
                <div id="balance-check" class="alert alert-info mb-3">
                    <i class="fas fa-info-circle me-2"></i>Masukkan jumlah untuk memeriksa keseimbangan
                </div>
                
                <div class="alert alert-warning">
                    <h6><i class="fas fa-exclamation-triangle me-2"></i>Tentang Ayat Penyesuaian</h6>
                    <p class="mb-0">
                        Ayat penyesuaian dibuat pada akhir periode akuntansi untuk memperbarui akun 
                        untuk akrual, deferral, penyusutan, dan perbedaan waktu lainnya.
                    </p>
                </div>
                
                <div class="d-flex gap-2">
                    <button type="submit" class="btn btn-primary">Posting Ayat Penyesuaian</button>
                    <a href="/adjusting" class="btn btn-outline-secondary">Batal</a>
                </div>
            </form>
        </div>
    </div>
    
    <script>
    function addAdjustingLine() {{
        const container = document.getElementById('adjusting-lines');
        const count = container.children.length;
        const newLine = document.createElement('div');
        newLine.className = 'row mb-3';
        newLine.innerHTML = `
            <div class="col-md-5">
                <select class="form-select" name="account_${{count}}" required>
                    <option value="">Pilih Akun</option>
                    {options_html}
                </select>
            </div>
            <div class="col-md-3">
                <input type="number" class="form-control" name="debit_${{count}}" placeholder="0.00" step="0.01" min="0" oninput="checkBalance()">
            </div>
            <div class="col-md-3">
                <input type="number" class="form-control" name="credit_${{count}}" placeholder="0.00" step="0.01" min="0" oninput="checkBalance()">
            </div>
            <div class="col-md-1 d-flex align-items-end">
                <button type="button" class="btn btn-danger btn-sm" onclick="this.parentElement.parentElement.remove(); checkBalance();">
                    <i class="fas fa-times"></i>
                </button>
            </div>
        `;
        container.appendChild(newLine);
    }}
    </script>
    """
    return render_template_string(BASE_TEMPLATE, title='Ayat Penyesuaian Baru', body=body, user=current_user())

@app.route('/adjusting/<int:entry_id>')
@login_required
def adjusting_view(entry_id):
    cur = get_db().execute('SELECT * FROM adjusting_entries WHERE id = ?', (entry_id,))
    entry = cur.fetchone()
    
    if not entry:
        flash('Ayat penyesuaian tidak ditemukan')
        return redirect(url_for('adjusting'))
    
    cur.execute('''
        SELECT al.*, a.code, a.name, a.acct_type
        FROM adjusting_lines al
        JOIN accounts a ON al.account_id = a.id
        WHERE al.adj_id = ?
    ''', (entry_id,))
    lines = cur.fetchall()
    
    body = f"""
    <div class="page-header">
        <h1 class="page-title">Detail Ayat Penyesuaian #{entry['id']}</h1>
        <p class="page-subtitle">Detail lengkap ayat penyesuaian</p>
    </div>
    
    <div class="card">
        <div class="card-body">
            <div class="row mb-4">
                <div class="col-md-6">
                    <strong>Tanggal:</strong> {entry['date']}
                </div>
                <div class="col-md-6">
                    <strong>Keterangan:</strong> {entry['description']}
                </div>
            </div>
            
            <h6 class="mb-3">Detail Penyesuaian</h6>
            <div class="table-responsive">
                <table class="table accounting-table">
                    <thead>
                        <tr>
                            <th>Akun</th>
                            <th>Kode</th>
                            <th>Jenis</th>
                            <th class="text-end">Debit</th>
                            <th class="text-end">Kredit</th>
                        </tr>
                    </thead>
                    <tbody>
    """
    
    for line in lines:
        debit_display = f"{line['debit']:,.2f}" if line['debit'] > 0 else ""
        credit_display = f"{line['credit']:,.2f}" if line['credit'] > 0 else ""
        
        body += f"""
                        <tr>
                            <td>{line['name']}</td>
                            <td>{line['code']}</td>
                            <td><span class="badge bg-secondary">{line['acct_type']}</span></td>
                            <td class="text-end text-success">{debit_display}</td>
                            <td class="text-end text-danger">{credit_display}</td>
                        </tr>
        """
    
    total_debit = sum(line['debit'] for line in lines)
    total_credit = sum(line['credit'] for line in lines)
    
    body += f"""
                    </tbody>
                    <tfoot class="table-active">
                        <tr>
                            <th colspan="3">Total</th>
                            <th class="text-end text-success">Rp {total_debit:,.2f}</th>
                            <th class="text-end text-danger">Rp {total_credit:,.2f}</th>
                        </tr>
                    </tfoot>
                </table>
            </div>
            
            <div class="mt-4">
                <div class="alert {'alert-success' if abs(total_debit - total_credit) < 0.01 else 'alert-danger'}">
                    <i class="fas {'fa-check-circle' if abs(total_debit - total_credit) < 0.01 else 'fa-exclamation-triangle'} me-2"></i>
                    {'Ayat penyesuaian ini seimbang dan telah diposting.' if abs(total_debit - total_credit) < 0.01 else 'Ayat penyesuaian tidak seimbang!'}
                </div>
            </div>
        </div>
    </div>
    """
    return render_template_string(BASE_TEMPLATE, title='Detail Penyesuaian', body=body, user=current_user())

# Perbaiki route financials untuk menghindari error tab_content
@app.route('/financials')
@login_required
def financials():
    # Dapatkan semua laporan keuangan
    income_stmt = income_statement()
    balance_stmt = balance_sheet()
    cash_flow_stmt = cash_flow_statement()
    equity_stmt = equity_statement()  # TAMBAHAN BARU
    
    # Tombol export financial reports
    export_button = """
    <div class="dropdown">
        <button class="btn btn-success dropdown-toggle" type="button" data-bs-toggle="dropdown">
            <i class="fas fa-file-excel me-2"></i>Export Excel
        </button>
        <ul class="dropdown-menu">
            <li><a class="dropdown-item" href="/export/financial-reports" target="_blank">
                <i class="fas fa-file-contract me-2"></i>Export Financial Reports
            </a></li>
            <li><hr class="dropdown-divider"></li>
            <li><a class="dropdown-item" href="/export/income_statement">
                <i class="fas fa-chart-bar me-2"></i>Export Income Statement
            </a></li>
            <li><a class="dropdown-item" href="/export/balance_sheet">
                <i class="fas fa-balance-scale me-2"></i>Export Balance Sheet
            </a></li>
            <li><a class="dropdown-item" href="/export/cash_flow">
                <i class="fas fa-money-bill-wave me-2"></i>Export Cash Flow
            </a></li>
            <li><hr class="dropdown-divider"></li>
            <li><a class="dropdown-item" href="/export/all">
                <i class="fas fa-file-archive me-2"></i>Export All Reports
            </a></li>
        </ul>
    </div>
    """
    
    # Buat tab content yang lengkap dengan LAPORAN PERUBAHAN MODAL
    tab_content = f"""
    <ul class="nav nav-tabs" id="financialTabs" role="tablist">
        <li class="nav-item" role="presentation">
            <button class="nav-link active" id="income-tab" data-bs-toggle="tab" data-bs-target="#income" type="button" role="tab" aria-controls="income" aria-selected="true">
                <i class="fas fa-chart-bar me-2"></i>Laporan Laba Rugi
            </button>
        </li>
        <li class="nav-item" role="presentation">
            <button class="nav-link" id="balance-tab" data-bs-toggle="tab" data-bs-target="#balance" type="button" role="tab" aria-controls="balance" aria-selected="false">
                <i class="fas fa-balance-scale me-2"></i>Neraca
            </button>
        </li>
        <li class="nav-item" role="presentation">
            <button class="nav-link" id="equity-tab" data-bs-toggle="tab" data-bs-target="#equity" type="button" role="tab" aria-controls="equity" aria-selected="false">
                <i class="fas fa-landmark me-2"></i>Laporan Perubahan Modal
            </button>
        </li>
        <li class="nav-item" role="presentation">
            <button class="nav-link" id="cashflow-tab" data-bs-toggle="tab" data-bs-target="#cashflow" type="button" role="tab" aria-controls="cashflow" aria-selected="false">
                <i class="fas fa-money-bill-wave me-2"></i>Laporan Arus Kas
            </button>
        </li>
    </ul>
    
    <div class="tab-content mt-4" id="financialTabsContent">
        <!-- Laporan Laba Rugi -->
        <div class="tab-pane fade show active" id="income" role="tabpanel" aria-labelledby="income-tab">
            <div class="card border-0">
                <div class="card-header bg-light">
                    <h6 class="mb-0"><i class="fas fa-chart-bar me-2"></i>Laporan Laba Rugi</h6>
                    <small class="text-muted">Untuk periode yang berakhir {datetime.now().date().isoformat()}</small>
                </div>
                <div class="card-body">
                    <div class="row">
                        <div class="col-md-8">
                            <h6 class="text-primary mb-3">Pendapatan</h6>
                            <table class="table accounting-table">
                                <tr class="table-active">
                                    <td><strong>Pendapatan Penjualan</strong></td>
                                    <td class="text-end text-success fw-bold">Rp {income_stmt['total_revenue']:,.2f}</td>
                                </tr>
                                <tr>
                                    <td colspan="2" class="border-0"></td>
                                </tr>
                            </table>
                            
                            <h6 class="mt-4 text-primary mb-3">Beban</h6>
                            <table class="table accounting-table">
                                <tr class="table-active">
                                    <td><strong>Total Beban</strong></td>
                                    <td class="text-end text-danger fw-bold">Rp {income_stmt['total_expense']:,.2f}</td>
                                </tr>
                            </table>
                            
                            <table class="table table-bordered mt-4">
                                <tr class="table-success">
                                    <td><strong>Laba Bersih</strong></td>
                                    <td class="text-end fw-bold">Rp {income_stmt['net_income']:,.2f}</td>
                                </tr>
                            </table>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- Neraca -->
        <div class="tab-pane fade" id="balance" role="tabpanel" aria-labelledby="balance-tab">
            <div class="card border-0">
                <div class="card-header bg-light">
                    <h6 class="mb-0"><i class="fas fa-balance-scale me-2"></i>Neraca</h6>
                    <small class="text-muted">Per {datetime.now().date().isoformat()}</small>
                </div>
                <div class="card-body">
                    <div class="row">
                        <div class="col-md-6">
                            <h6 class="text-primary mb-3">Aset</h6>
                            <table class="table accounting-table">
                                <tr class="table-active">
                                    <td><strong>Total Aset</strong></td>
                                    <td class="text-end text-success fw-bold">Rp {balance_stmt['total_assets']:,.2f}</td>
                                </tr>
                            </table>
                        </div>
                        
                        <div class="col-md-6">
                            <h6 class="text-primary mb-3">Kewajiban & Ekuitas</h6>
                            <table class="table accounting-table">
                                <tr class="table-active">
                                    <td><strong>Total Kewajiban</strong></td>
                                    <td class="text-end text-danger fw-bold">Rp {balance_stmt['total_liabilities']:,.2f}</td>
                                </tr>
                                <tr class="table-active">
                                    <td><strong>Total Ekuitas</strong></td>
                                    <td class="text-end text-info fw-bold">Rp {balance_stmt['total_equity'] + balance_stmt['net_income']:,.2f}</td>
                                </tr>
                                <tr class="table-active">
                                    <td><strong>Total Kewajiban & Ekuitas</strong></td>
                                    <td class="text-end fw-bold">Rp {balance_stmt['total_liabilities'] + balance_stmt['total_equity'] + balance_stmt['net_income']:,.2f}</td>
                                </tr>
                            </table>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- LAPORAN PERUBAHAN MODAL BARU -->
        <div class="tab-pane fade" id="equity" role="tabpanel" aria-labelledby="equity-tab">
            <div class="card border-0">
                <div class="card-header bg-light">
                    <h6 class="mb-0"><i class="fas fa-landmark me-2"></i>Laporan Perubahan Modal</h6>
                    <small class="text-muted">Untuk periode yang berakhir {datetime.now().date().isoformat()}</small>
                </div>
                <div class="card-body">
                    <div class="row">
                        <div class="col-md-8">
                            <table class="table accounting-table">
                                <tr>
                                    <td><strong>Modal Awal Periode</strong></td>
                                    <td class="text-end text-primary fw-bold">Rp {equity_stmt['beginning_capital']:,.2f}</td>
                                </tr>
                                <tr>
                                    <td><strong>Laba Bersih Periode Berjalan</strong></td>
                                    <td class="text-end text-success fw-bold">+ Rp {equity_stmt['net_income']:,.2f}</td>
                                </tr>
                                <tr>
                                    <td><strong>Prive/Penarikan Pemilik</strong></td>
                                    <td class="text-end text-danger fw-bold">- Rp {equity_stmt['drawings']:,.2f}</td>
                                </tr>
                                <tr class="table-active">
                                    <td><strong>Modal Akhir Periode</strong></td>
                                    <td class="text-end fw-bold">Rp {equity_stmt['ending_capital']:,.2f}</td>
                                </tr>
                            </table>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- Laporan Arus Kas -->
        <div class="tab-pane fade" id="cashflow" role="tabpanel" aria-labelledby="cashflow-tab">
            <div class="card border-0">
                <div class="card-header bg-light">
                    <h6 class="mb-0"><i class="fas fa-money-bill-wave me-2"></i>Laporan Arus Kas</h6>
                    <small class="text-muted">Untuk periode yang berakhir {datetime.now().date().isoformat()}</small>
                </div>
                <div class="card-body">
                    <div class="row">
                        <div class="col-md-10">
                            <h6 class="text-primary mb-3">Aktivitas Operasi</h6>
                            <table class="table accounting-table">
                                <tr>
                                    <td>Pendapatan Tunai</td>
                                    <td class="text-end text-success">+ Rp {cash_flow_stmt['operating_activities']['revenue']:,.2f}</td>
                                </tr>
                                <tr>
                                    <td>Beban Tunai</td>
                                    <td class="text-end text-danger">- Rp {cash_flow_stmt['operating_activities']['expenses']:,.2f}</td>
                                </tr>
                                <tr class="table-active">
                                    <td><strong>Arus Kas Bersih dari Operasi</strong></td>
                                    <td class="text-end fw-bold {'text-success' if cash_flow_stmt['operating_activities']['net_cash'] >= 0 else 'text-danger'}">
                                        Rp {cash_flow_stmt['operating_activities']['net_cash']:,.2f}
                                    </td>
                                </tr>
                            </table>

                            <h6 class="text-primary mt-4 mb-3">Aktivitas Investasi</h6>
                            <table class="table accounting-table">
                                <tr>
                                    <td>Pembelian Peralatan</td>
                                    <td class="text-end text-danger">- Rp {cash_flow_stmt['investing_activities']['equipment_purchase']:,.2f}</td>
                                </tr>
                                <tr>
                                    <td>Penjualan Peralatan</td>
                                    <td class="text-end text-success">+ Rp {cash_flow_stmt['investing_activities']['equipment_sale']:,.2f}</td>
                                </tr>
                                <tr class="table-active">
                                    <td><strong>Arus Kas Bersih dari Investasi</strong></td>
                                    <td class="text-end fw-bold {'text-success' if cash_flow_stmt['investing_activities']['net_cash'] >= 0 else 'text-danger'}">
                                        Rp {cash_flow_stmt['investing_activities']['net_cash']:,.2f}
                                    </td>
                                </tr>
                            </table>

                            <h6 class="text-primary mt-4 mb-3">Aktivitas Pendanaan</h6>
                            <table class="table accounting-table">
                                <tr>
                                    <td>Setoran Modal</td>
                                    <td class="text-end text-success">+ Rp {cash_flow_stmt['financing_activities']['capital_contribution']:,.2f}</td>
                                </tr>
                                <tr>
                                    <td>Penarikan Pemilik</td>
                                    <td class="text-end text-danger">- Rp {cash_flow_stmt['financing_activities']['drawings']:,.2f}</td>
                                </tr>
                                <tr>
                                    <td>Penerimaan Pinjaman</td>
                                    <td class="text-end text-success">+ Rp {cash_flow_stmt['financing_activities']['loans_received']:,.2f}</td>
                                </tr>
                                <tr>
                                    <td>Pembayaran Pinjaman</td>
                                    <td class="text-end text-danger">- Rp {cash_flow_stmt['financing_activities']['loans_paid']:,.2f}</td>
                                </tr>
                                <tr class="table-active">
                                    <td><strong>Arus Kas Bersih dari Pendanaan</strong></td>
                                    <td class="text-end fw-bold {'text-success' if cash_flow_stmt['financing_activities']['net_cash'] >= 0 else 'text-danger'}">
                                        Rp {cash_flow_stmt['financing_activities']['net_cash']:,.2f}
                                    </td>
                                </tr>
                            </table>

                            <table class="table table-bordered mt-4">
                                <tr class="table-info">
                                    <td><strong>Kenaikan/Penurunan Kas Bersih</strong></td>
                                    <td class="text-end fw-bold {'text-success' if cash_flow_stmt['net_cash_flow'] >= 0 else 'text-danger'}">
                                        Rp {cash_flow_stmt['net_cash_flow']:,.2f}
                                    </td>
                                </tr>
                            </table>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    """
    
    body = f"""
    <div class="page-header">
        <h1 class="page-title">Laporan Keuangan</h1>
        <p class="page-subtitle">Laporan keuangan lengkap perusahaan</p>
    </div>
    
    <div class="card">
        <div class="card-body">
            <div class="d-flex justify-content-between align-items-center mb-4">
                <h5 class="section-title mb-0">Laporan Keuangan Utama</h5>
                {export_button}
            </div>
            
            {tab_content}
        </div>
    </div>
    """
    
    return render_template_string(BASE_TEMPLATE, title='Laporan Keuangan', body=body, user=current_user())

@app.route('/reset', methods=['GET', 'POST'])
@login_required
def reset_transactions():
    """Reset SEMUA data jadi 0 - HATI-HATI!"""
    
    if request.method == 'POST':
        db = get_db()
        cur = db.cursor()
        
        try:
            # 1. Hapus SEMUA data transaksi dan inventory
            cur.executescript('''
                -- Hapus semua transaksi
                DELETE FROM journal_lines;
                DELETE FROM journal_entries;
                
                -- Hapus semua penyesuaian
                DELETE FROM adjusting_lines;
                DELETE FROM adjusting_entries;
                
                -- Hapus semua saldo awal
                DELETE FROM opening_balances;
                
                -- Hapus SEMUA data inventory
                DELETE FROM inventory;
            ''')
            
            # 2. BUAT ULANG data stok tiram dengan NOL
            cur.execute('''
                INSERT INTO inventory (date, description, quantity_in, unit_cost, value) 
                VALUES (?, ?, ?, ?, ?)
            ''', ('2024-01-01', 'Stok Awal - Tiram Besar', 0, 0, 0))
            
            cur.execute('''
                INSERT INTO inventory (date, description, quantity_in, unit_cost, value) 
                VALUES (?, ?, ?, ?, ?)
            ''', ('2024-01-01', 'Stok Awal - Tiram Kecil', 0, 0, 0))
            
            # 3. Update settings untuk total stok = 0
            cur.execute('UPDATE settings SET v = ? WHERE k = "current_stock_large"', ('0',))
            cur.execute('UPDATE settings SET v = ? WHERE k = "current_stock_small"', ('0',))
            
            db.commit()
            
            flash('✅ SEMUA data berhasil direset! Stok tiram sekarang 0.')
            return redirect(url_for('dashboard'))
            
        except Exception as e:
            db.rollback()
            flash(f'❌ Error saat reset: {str(e)}')
            import traceback
            print("Error details:", traceback.format_exc())
    
    # Tampilkan konfirmasi reset
    body = """
    <div class="page-header">
        <h1 class="page-title">Reset SEMUA Data</h1>
        <p class="page-subtitle">Hati-hati: Semua data akan jadi NOL!</p>
    </div>
    
    <div class="card">
        <div class="card-header bg-danger text-white">
            <h5 class="mb-0"><i class="fas fa-radiation me-2"></i>Reset SEMUA Data ke NOL</h5>
        </div>
        <div class="card-body">
            <div class="alert alert-danger">
                <h6><i class="fas fa-skull-crossbones me-2"></i>PERINGATAN EXTREME!</h6>
                <p class="mb-0">
                    Tindakan ini akan mengubah <strong>SEMUA</strong> data menjadi NOL:
                </p>
                <ul class="mb-2 mt-2">
                    <li>Semua transaksi dihapus</li>
                    <li>Semua saldo akun jadi 0</li>
                    <li><strong>Stok tiram besar: 0 kg (Rp 0)</strong></li>
                    <li><strong>Stok tiram kecil: 0 kg (Rp 0)</strong></li>
                    <li><strong>Total stok: 0 kg (Rp 0)</strong></li>
                </ul>
                <p class="mb-0 fw-bold">
                    ⚠️ TINDAKAN INI TIDAK BISA DIBATALKAN!
                </p>
            </div>
            
            <div class="card bg-warning">
                <div class="card-body">
                    <h6><i class="fas fa-exclamation-triangle me-2"></i>Setelah Reset:</h6>
                    <ul class="mb-0">
                        <li>Dashboard akan kosong (semua angka 0)</li>
                        <li>Stok tiram = 0</li>
                        <li>Pendapatan = 0</li>
                        <li>Semua laporan keuangan kosong</li>
                        <li>Harus input transaksi baru dari awal</li>
                    </ul>
                </div>
            </div>
            
            <form method="post" class="mt-4">
                <div class="mb-3">
                    <label class="form-label fw-semibold">Konfirmasi Reset Total</label>
                    <input type="text" class="form-control" name="confirm_text" 
                           placeholder='Ketik "RESET SEMUA JADI NOL" untuk konfirmasi' required>
                    <div class="form-text text-danger">Harus tepat: RESET SEMUA JADI NOL</div>
                </div>
                
                <div class="d-flex gap-2">
                    <button type="submit" class="btn btn-danger" id="resetBtn" disabled>
                        <i class="fas fa-fire me-2"></i>Reset SEMUA Jadi NOL
                    </button>
                    <a href="/dashboard" class="btn btn-outline-secondary">
                        <i class="fas fa-times me-2"></i>Batal
                    </a>
                </div>
            </form>
        </div>
    </div>

    <script>
        document.addEventListener('DOMContentLoaded', function() {
            const confirmInput = document.querySelector('input[name="confirm_text"]');
            const resetBtn = document.getElementById('resetBtn');
            
            confirmInput.addEventListener('input', function() {
                if (this.value === 'RESET SEMUA JADI NOL') {
                    resetBtn.disabled = false;
                } else {
                    resetBtn.disabled = true;
                }
            });
        });
    </script>
    """
    return render_template_string(BASE_TEMPLATE, title='Reset Total', body=body, user=current_user())

@app.route('/opening_balance', methods=['GET', 'POST'])
@login_required
def opening_balance():
    accounts = all_accounts()
    db = get_db()
    
    # Cek struktur tabel dan perbaiki jika perlu
    try:
        # Test query dengan struktur baru
        db.execute("SELECT debit_amount FROM opening_balances LIMIT 1")
    except sqlite3.OperationalError:
        # Jika struktur masih lama, redirect ke fix database
        flash('❌ Struktur database perlu diperbaiki. Silakan klik tombol di bawah.')
        body = """
        <div class="page-header">
            <h1 class="page-title">Perbaikan Database Diperlukan</h1>
            <p class="page-subtitle">Struktur database tidak sesuai</p>
        </div>
        
        <div class="card">
            <div class="card-body text-center">
                <div class="alert alert-danger">
                    <h4><i class="fas fa-exclamation-triangle me-2"></i>Database Error</h4>
                    <p>Struktur tabel opening_balances tidak sesuai. Klik tombol di bawah untuk memperbaiki otomatis.</p>
                </div>
                
                <a href="/fix_database" class="btn btn-primary btn-lg">
                    <i class="fas fa-tools me-2"></i>Perbaiki Database
                </a>
                
                <div class="mt-4">
                    <small class="text-muted">
                        Tindakan ini akan mereset database dan mengatur ulang semua data ke default.
                    </small>
                </div>
            </div>
        </div>
        """
        return render_template_string(BASE_TEMPLATE, title='Perbaikan Database', body=body, user=current_user())
    
    if request.method == 'POST':
        # HAPUS semua saldo awal sebelumnya
        db.execute('DELETE FROM opening_balances')
        
        for acc in accounts:
            account_id = acc['id']
            balance_str = request.form.get(f'balance_{account_id}', '0').replace(',', '').replace('Rp', '').strip()
            
            try:
                balance = float(balance_str) if balance_str else 0
            except ValueError:
                balance = 0
            
            if balance != 0:
                # Tentukan tipe saldo berdasarkan jenis akun
                if acc['acct_type'] in ('Asset', 'Expense'):
                    # Asset & Expense: saldo positif = Debit
                    debit_amount = balance
                    credit_amount = 0
                else:
                    # Liability, Equity, Revenue: saldo positif = Credit
                    debit_amount = 0
                    credit_amount = balance
                
                # Simpan saldo awal dengan struktur baru
                db.execute('''
                    INSERT INTO opening_balances (account_id, debit_amount, credit_amount)
                    VALUES (?, ?, ?)
                ''', (account_id, debit_amount, credit_amount))
                
                print(f"SET SALDO: {acc['code']} {acc['name']} = Debit: {debit_amount:,.2f}, Credit: {credit_amount:,.2f}")
        
        db.commit()
        flash('Saldo awal berhasil disimpan!')
        return redirect(url_for('trial_balance_view'))
    
    # Ambil saldo awal yang sudah ada - PERBAIKAN: sesuaikan dengan struktur baru
    opening_balances = {}
    for acc in accounts:
        ob = db.execute(
            'SELECT debit_amount, credit_amount FROM opening_balances WHERE account_id = ?', 
            (acc['id'],)
        ).fetchone()
        
        if ob:
            # Tampilkan nilai yang sesuai dengan jenis akun
            if acc['acct_type'] in ('Asset', 'Expense'):
                opening_balances[acc['id']] = ob['debit_amount']
            else:
                opening_balances[acc['id']] = ob['credit_amount']
        else:
            opening_balances[acc['id']] = 0
    
    body = """
    <div class="page-header">
        <h1 class="page-title">Saldo Awal</h1>
        <p class="page-subtitle">Atur saldo awal untuk semua akun - HARUS SESUAI JENIS AKUN</p>
    </div>
    
    <div class="alert alert-warning">
        <h6><i class="fas fa-exclamation-triangle me-2"></i>PERHATIAN: Input saldo sesuai jenis akun!</h6>
        <ul class="mb-0">
            <li><strong>Asset & Beban</strong>: Input nilai POSITIF (akan masuk Debit)</li>
            <li><strong>Kewajiban, Ekuitas & Pendapatan</strong>: Input nilai POSITIF (akan masuk Kredit)</li>
        </ul>
    </div>

    <div class="alert alert-info">
        <h6><i class="fas fa-info-circle me-2"></i>Contoh Data Sesuai Neraca Saldo Awal</h6>
        <div class="row">
            <div class="col-md-6">
                <strong>Asset (Debit):</strong>
                <ul class="mb-0">
                    <li>Kas: 8,500,000</li>
                    <li>Piutang Usaha: 4,500,000</li>
                    <li>Persediaan Tiram Besar: 1,750,000</li>
                    <li>Persediaan Tiram Kecil: 1,200,000</li>
                    <li>Peralatan: 500,000</li>
                    <li>Perlengkapan: 300,000</li>
                    <li>Kendaraan: 12,000,000</li>
                </ul>
            </div>
            <div class="col-md-6">
                <strong>Liability & Equity (Credit):</strong>
                <ul class="mb-0">
                    <li>Akum. Penyusutan Kendaraan: 1,500,000</li>
                    <li>Utang Usaha: 650,000</li>
                    <li>Utang Gaji: 100,000</li>
                    <li>Modal Pemilik: 22,300,000</li>
                </ul>
            </div>
        </div>
    </div>
    
    <div class="card">
        <div class="card-body">
            <form method="post">
                <div class="table-responsive">
                    <table class="table table-hover accounting-table">
                        <thead>
                            <tr>
                                <th>Kode Akun</th>
                                <th>Nama Akun</th>
                                <th>Jenis</th>
                                <th>Saldo Normal</th>
                                <th class="text-end">Saldo Awal</th>
                                <th>Keterangan</th>
                            </tr>
                        </thead>
                        <tbody>
    """
    
    for acc in accounts:
        current_balance = opening_balances.get(acc['id'], 0)
        
        # Tentukan placeholder dan contoh berdasarkan jenis akun
        if acc['acct_type'] in ('Asset', 'Expense'):
            placeholder = "Contoh: 8500000"
            keterangan = "Nilai POSITIF → Debit"
            badge_class = "bg-primary"
            # Contoh nilai untuk akun asset utama
            if acc['code'] == '101':  # Kas
                placeholder = "8,500,000"
            elif acc['code'] == '102':  # Piutang
                placeholder = "4,500,000"
            elif acc['code'] == '103':  # Persediaan Besar
                placeholder = "1,750,000"
            elif acc['code'] == '103.1':  # Persediaan Kecil
                placeholder = "1,200,000"
            elif acc['code'] == '104':  # Peralatan
                placeholder = "500,000"
            elif acc['code'] == '105':  # Perlengkapan
                placeholder = "300,000"
            elif acc['code'] == '106':  # Kendaraan
                placeholder = "12,000,000"
        else:
            placeholder = "Contoh: 22300000" 
            keterangan = "Nilai POSITIF → Kredit"
            badge_class = "bg-success"
            # Contoh nilai untuk akun liability/equity utama
            if acc['code'] == '107':  # Akum Penyusutan
                placeholder = "1,500,000"
            elif acc['code'] == '201':  # Utang Usaha
                placeholder = "650,000"
            elif acc['code'] == '202':  # Utang Gaji
                placeholder = "100,000"
            elif acc['code'] == '301':  # Modal Pemilik
                placeholder = "22,300,000"
        
        body += f"""
                            <tr>
                                <td><strong>{acc['code']}</strong></td>
                                <td>{acc['name']}</td>
                                <td><span class="badge bg-secondary">{acc['acct_type']}</span></td>
                                <td><span class="badge {badge_class}">{acc['normal_balance']}</span></td>
                                <td>
                                    <input type="text" class="form-control text-end" name="balance_{acc['id']}" 
                                           value="{current_balance:,.0f}" placeholder="{placeholder}">
                                </td>
                                <td><small class="text-muted">{keterangan}</small></td>
                            </tr>
        """
    
    body += """
                        </tbody>
                    </table>
                </div>
                
                <div class="mt-4">
                    <button type="submit" class="btn btn-primary">
                        <i class="fas fa-save me-2"></i>Simpan Saldo Awal
                    </button>
                    <a href="/trial_balance" class="btn btn-info">
                        <i class="fas fa-balance-scale me-2"></i>Lihat Neraca Saldo
                    </a>
                    <a href="/reset_opening_balances" class="btn btn-warning" onclick="return confirm('Reset semua saldo awal ke nilai default?')">
                        <i class="fas fa-sync me-2"></i>Reset ke Default
                    </a>
                    <a href="/dashboard" class="btn btn-outline-secondary">Kembali ke Dashboard</a>
                </div>
            </form>
        </div>
    </div>
    """
    return render_template_string(BASE_TEMPLATE, title='Saldo Awal', body=body, user=current_user())

@app.route('/closing')
@login_required
def closing_entries():
    """Halaman jurnal penutup dan neraca saldo penutup"""
    
    # Dapatkan entri penutup yang akan diposting
    closing_entries_list, net_income = get_closing_entries()
    
    # Dapatkan neraca saldo penutup
    pctb_data, pctb_debit, pctb_credit = get_post_closing_trial_balance()
    
    body = f"""
    <div class="page-header">
        <h1 class="page-title">Jurnal Penutup & Neraca Saldo Penutup</h1>
        <p class="page-subtitle">Proses penutupan periode akuntansi</p>
    </div>
    
    <div class="row">
        <div class="col-lg-6">
            <div class="card">
                <div class="card-header bg-warning text-dark">
                    <h5 class="mb-0"><i class="fas fa-lock me-2"></i>Jurnal Penutup</h5>
                </div>
                <div class="card-body">
                    <div class="alert alert-info">
                        <h6><i class="fas fa-info-circle me-2"></i>Proses Penutupan</h6>
                        <p class="mb-0">
                            Jurnal penutup digunakan untuk menutup akun nominal (pendapatan dan beban) 
                            ke akun Laba Ditahan pada akhir periode akuntansi.
                        </p>
                    </div>
                    
                    <div class="mb-3">
                        <strong>Laba/Rugi Bersih Periode:</strong>
                        <span class="{'text-success' if net_income >= 0 else 'text-danger'} fw-bold ms-2">
                            Rp {net_income:,.2f}
                        </span>
                    </div>
                    
                    <div class="mb-3">
                        <strong>Jumlah Entri Penutup:</strong>
                        <span class="fw-bold ms-2">{len(closing_entries_list)} entri</span>
                    </div>
                    
                    {f'<div class="alert alert-success"><i class="fas fa-check-circle me-2"></i>Tidak ada entri penutup yang diperlukan. Saldo sudah nol.</div>' if not closing_entries_list else ''}
                    
                    <div class="mt-4">
                        <form method="post" action="/closing/post">
                            <button type="submit" class="btn btn-primary" {'disabled' if not closing_entries_list else ''}>
                                <i class="fas fa-lock me-2"></i>Posting Jurnal Penutup
                            </button>
                            <a href="/financials" class="btn btn-outline-secondary">
                                <i class="fas fa-chart-line me-2"></i>Lihat Laporan Keuangan
                            </a>
                        </form>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="col-lg-6">
            <div class="card">
                <div class="card-header bg-success text-white">
                    <h5 class="mb-0"><i class="fas fa-balance-scale me-2"></i>Neraca Saldo Setelah Penutupan</h5>
                </div>
                <div class="card-body">
                    <div class="alert alert-success">
                        <h6><i class="fas fa-check-circle me-2"></i>Neraca Saldo Penutup</h6>
                        <p class="mb-0">
                            Neraca saldo setelah penutupan hanya berisi akun riil (Aset, Kewajiban, Ekuitas) 
                            yang akan menjadi saldo awal periode berikutnya.
                        </p>
                    </div>
                    
                    <div class="table-responsive">
                        <table class="table table-sm accounting-table">
                            <thead>
                                <tr>
                                    <th>Akun</th>
                                    <th class="text-end">Debit</th>
                                    <th class="text-end">Kredit</th>
                                </tr>
                            </thead>
                            <tbody>
    """
    
    for item in pctb_data:
        if item['debit'] != 0 or item['credit'] != 0:
            debit_display = f"Rp {item['debit']:,.2f}" if item['debit'] > 0 else ""
            credit_display = f"Rp {item['credit']:,.2f}" if item['credit'] > 0 else ""
            
            body += f"""
                                <tr>
                                    <td>
                                        <small><strong>{item['account']['code']}</strong> {item['account']['name']}</small>
                                    </td>
                                    <td class="text-end text-success">{debit_display}</td>
                                    <td class="text-end text-danger">{credit_display}</td>
                                </tr>
            """
    
    body += f"""
                            </tbody>
                            <tfoot class="table-active">
                                <tr>
                                    <th>Total</th>
                                    <th class="text-end text-success">Rp {pctb_debit:,.2f}</th>
                                    <th class="text-end text-danger">Rp {pctb_credit:,.2f}</th>
                                </tr>
                            </tfoot>
                        </table>
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <!-- Detail Jurnal Penutup -->
    <div class="row mt-4">
        <div class="col-12">
            <div class="card">
                <div class="card-header">
                    <h5 class="mb-0"><i class="fas fa-list me-2"></i>Detail Entri Penutup</h5>
                </div>
                <div class="card-body">
    """
    
    if closing_entries_list:
        body += """
                    <div class="table-responsive">
                        <table class="table accounting-table">
                            <thead>
                                <tr>
                                    <th>Akun</th>
                                    <th class="text-end">Debit</th>
                                    <th class="text-end">Kredit</th>
                                    <th>Keterangan</th>
                                </tr>
                            </thead>
                            <tbody>
        """
        
        for entry in closing_entries_list:
            cur = get_db().execute('SELECT code, name FROM accounts WHERE id = ?', (entry['account_id'],))
            account = cur.fetchone()
            
            debit_display = f"Rp {entry['debit']:,.2f}" if entry['debit'] > 0 else ""
            credit_display = f"Rp {entry['credit']:,.2f}" if entry['credit'] > 0 else ""
            
            body += f"""
                                <tr>
                                    <td>
                                        <strong>{account['code']}</strong> {account['name']}
                                    </td>
                                    <td class="text-end text-success">{debit_display}</td>
                                    <td class="text-end text-danger">{credit_display}</td>
                                    <td>{entry['description']}</td>
                                </tr>
            """
        
        body += """
                            </tbody>
                        </table>
                    </div>
        """
    else:
        body += """
                    <div class="text-center py-4">
                        <i class="fas fa-check-circle fa-3x text-success mb-3"></i>
                        <h5 class="text-success">Tidak Ada Entri Penutup</h5>
                        <p class="text-muted">Semua akun nominal sudah dalam kondisi tertutup.</p>
                    </div>
        """
    
    body += """
                </div>
            </div>
        </div>
    </div>
    """
    
    return render_template_string(BASE_TEMPLATE, title='Jurnal Penutup', body=body, user=current_user())

@app.route('/closing/post', methods=['POST'])
@login_required
def post_closing_entries_route():
    """Posting jurnal penutup"""
    try:
        entry_id, net_income = post_closing_entries()
        
        if entry_id:
            flash(f'✅ Jurnal penutup berhasil diposting! Laba/Rugi bersih: IDR {net_income:,.2f}')
        else:
            flash('ℹ️ Tidak ada entri penutup yang perlu diposting.')
        
        return redirect(url_for('closing_entries'))
        
    except Exception as e:
        flash(f'❌ Error posting jurnal penutup: {str(e)}')
        return redirect(url_for('closing_entries'))

# ---------- Export Financial Reports ----------

def export_financial_reports():
    """Ekspor ketiga laporan keuangan utama ke satu file Excel"""
    output = io.BytesIO()
    
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        workbook = writer.book
        
        # Format untuk styling profesional
        header_format = workbook.add_format({
            'bold': True,
            'text_wrap': True,
            'valign': 'top',
            'fg_color': '#1E40AF',
            'font_color': 'white',
            'border': 1,
            'font_size': 12
        })
        
        title_format = workbook.add_format({
            'bold': True,
            'font_size': 14,
            'font_color': '#1E40AF',
            'align': 'center'
        })
        
        subtitle_format = workbook.add_format({
            'italic': True,
            'font_size': 10,
            'font_color': '#666666',
            'align': 'center'
        })
        
        currency_format = workbook.add_format({'num_format': '#,##0.00'})
        total_format = workbook.add_format({
            'bold': True,
            'top': 2,
            'num_format': '#,##0.00',
            'fg_color': '#F3F4F6'
        })
        
        # Dapatkan data laporan keuangan
        income_stmt = income_statement()
        balance_stmt = balance_sheet()
        cash_flow_stmt = cash_flow_statement()
        company_info = get_company_info()
        
        # ===== SHEET 1: LAPORAN LABA RUGI =====
        worksheet_income = workbook.add_worksheet('Laporan Laba Rugi')
        
        # Header perusahaan
        company_name = company_info.get('company_name', 'Peternakan Tiram Tiramine')
        worksheet_income.merge_range('A1:D1', company_name, title_format)
        worksheet_income.merge_range('A2:D2', 'LAPORAN LABA RUGI', title_format)
        worksheet_income.merge_range('A3:D3', f'Periode yang berakhir {datetime.now().date().strftime("%d %B %Y")}', subtitle_format)
        worksheet_income.write('A4', '')
        
        # Data laporan laba rugi
        income_data = [
            ['PENDAPATAN', '', '', ''],
            ['Pendapatan Penjualan Tiram', '', '', income_stmt['total_revenue']],
            ['', '', '', ''],
            ['Total Pendapatan', '', '', income_stmt['total_revenue']],
            ['', '', '', ''],
            ['BEBAN OPERASIONAL', '', '', ''],
            ['Harga Pokok Penjualan', '', '', income_stmt.get('cogs', 2500000)],
            ['Beban Gaji dan Upah', '', '', income_stmt.get('salary_expense', 1500000)],
            ['Beban Utilitas', '', '', income_stmt.get('utilities_expense', 500000)],
            ['Beban Pakan Tiram', '', '', income_stmt.get('feed_expense', 1000000)],
            ['Beban Pemeliharaan', '', '', income_stmt.get('maintenance_expense', 300000)],
            ['Beban Penyusutan', '', '', income_stmt.get('depreciation_expense', 800000)],
            ['Beban Lainnya', '', '', income_stmt.get('other_expenses', 200000)],
            ['', '', '', ''],
            ['Total Beban', '', '', income_stmt['total_expense']],
            ['', '', '', ''],
            ['LABA BERSIH SEBELUM PAJAK', '', '', income_stmt['net_income']],
            ['Pajak Penghasilan (Estimasi 10%)', '', '', income_stmt['net_income'] * 0.1],
            ['', '', '', ''],
            ['LABA BERSIH SETELAH PAJAK', '', '', income_stmt['net_income'] * 0.9]
        ]
        
        # Tulis data ke sheet
        for row_num, row_data in enumerate(income_data, start=5):
            for col_num, cell_data in enumerate(row_data):
                if col_num == 3 and isinstance(cell_data, (int, float)):
                    if any(keyword in str(row_data[0]).upper() for keyword in ['TOTAL', 'LABA', 'PAJAK']):
                        worksheet_income.write(row_num, col_num, cell_data, total_format)
                    else:
                        worksheet_income.write(row_num, col_num, cell_data, currency_format)
                else:
                    worksheet_income.write(row_num, col_num, cell_data)
        
        # Set column widths
        worksheet_income.set_column('A:A', 35)
        worksheet_income.set_column('B:C', 2)
        worksheet_income.set_column('D:D', 15)
        
        # ===== SHEET 2: NERACA =====
        worksheet_balance = workbook.add_worksheet('Neraca')
        
        # Header perusahaan
        worksheet_balance.merge_range('A1:D1', company_name, title_format)
        worksheet_balance.merge_range('A2:D2', 'NERACA', title_format)
        worksheet_balance.merge_range('A3:D3', f'Per {datetime.now().date().strftime("%d %B %Y")}', subtitle_format)
        worksheet_balance.write('A4', '')
        
        # Data Neraca - Aset
        balance_data_assets = [
            ['ASET', '', '', ''],
            ['ASET LANCAR', '', '', ''],
            ['Kas dan Setara Kas', '', '', balance_stmt.get('cash', balance_stmt['total_assets'] * 0.3)],
            ['Piutang Usaha', '', '', balance_stmt.get('receivables', balance_stmt['total_assets'] * 0.2)],
            ['Persediaan Tiram', '', '', balance_stmt.get('inventory', balance_stmt['total_assets'] * 0.25)],
            ['Beban Dibayar Dimuka', '', '', balance_stmt.get('prepaid_expenses', balance_stmt['total_assets'] * 0.05)],
            ['', '', '', ''],
            ['Total Aset Lancar', '', '', balance_stmt['total_assets'] * 0.8],
            ['', '', '', ''],
            ['ASET TETAP', '', '', ''],
            ['Peralatan Peternakan', '', '', balance_stmt.get('equipment', balance_stmt['total_assets'] * 0.15)],
            ['Kendaraan Operasional', '', '', balance_stmt.get('vehicles', balance_stmt['total_assets'] * 0.05)],
            ['Akumulasi Penyusutan', '', '', -balance_stmt.get('accumulated_depreciation', balance_stmt['total_assets'] * 0.1)],
            ['', '', '', ''],
            ['Total Aset Tetap', '', '', balance_stmt['total_assets'] * 0.2],
            ['', '', '', ''],
            ['TOTAL ASET', '', '', balance_stmt['total_assets']]
        ]
        
        # Data Neraca - Kewajiban & Ekuitas
        balance_data_liabilities = [
            ['KEWAJIBAN & EKUITAS', '', '', ''],
            ['KEWAJIBAN LANCAR', '', '', ''],
            ['Utang Usaha', '', '', balance_stmt.get('accounts_payable', balance_stmt['total_liabilities'] * 0.6)],
            ['Pinjaman Jangka Pendek', '', '', balance_stmt.get('short_term_loans', balance_stmt['total_liabilities'] * 0.4)],
            ['', '', '', ''],
            ['Total Kewajiban Lancar', '', '', balance_stmt['total_liabilities']],
            ['', '', '', ''],
            ['EKUITAS', '', '', ''],
            ['Modal Pemilik', '', '', balance_stmt['total_equity'] * 0.7],
            ['Laba Ditahan', '', '', balance_stmt['total_equity'] * 0.3],
            ['Laba Bersih Tahun Berjalan', '', '', balance_stmt['net_income']],
            ['', '', '', ''],
            ['Total Ekuitas', '', '', balance_stmt['total_equity'] + balance_stmt['net_income']],
            ['', '', '', ''],
            ['TOTAL KEWAJIBAN & EKUITAS', '', '', balance_stmt['total_liabilities'] + balance_stmt['total_equity'] + balance_stmt['net_income']]
        ]
        
        # Tulis Aset (kolom A)
        for row_num, row_data in enumerate(balance_data_assets, start=5):
            for col_num, cell_data in enumerate(row_data):
                if col_num == 3 and isinstance(cell_data, (int, float)):
                    if any(keyword in str(row_data[0]).upper() for keyword in ['TOTAL', 'LABA']):
                        worksheet_balance.write(row_num, col_num, cell_data, total_format)
                    else:
                        worksheet_balance.write(row_num, col_num, cell_data, currency_format)
                else:
                    worksheet_balance.write(row_num, col_num, cell_data)
        
        # Tulis Kewajiban & Ekuitas (kolom F)
        for row_num, row_data in enumerate(balance_data_liabilities, start=5):
            for col_num, cell_data in enumerate(row_data):
                if col_num == 3 and isinstance(cell_data, (int, float)):
                    if any(keyword in str(row_data[0]).upper() for keyword in ['TOTAL', 'LABA']):
                        worksheet_balance.write(row_num, col_num + 5, cell_data, total_format)
                    else:
                        worksheet_balance.write(row_num, col_num + 5, cell_data, currency_format)
                else:
                    worksheet_balance.write(row_num, col_num + 5, cell_data)
        
        # Set column widths untuk Neraca
        worksheet_balance.set_column('A:A', 35)
        worksheet_balance.set_column('B:C', 2)
        worksheet_balance.set_column('D:D', 15)
        worksheet_balance.set_column('E:E', 5)
        worksheet_balance.set_column('F:F', 35)
        worksheet_balance.set_column('G:H', 2)
        worksheet_balance.set_column('I:I', 15)
        
        # ===== SHEET 3: LAPORAN ARUS KAS =====
        worksheet_cashflow = workbook.add_worksheet('Laporan Arus Kas')
        
        # Header perusahaan
        worksheet_cashflow.merge_range('A1:D1', company_name, title_format)
        worksheet_cashflow.merge_range('A2:D2', 'LAPORAN ARUS KAS', title_format)
        worksheet_cashflow.merge_range('A3:D3', f'Periode yang berakhir {datetime.now().date().strftime("%d %B %Y")}', subtitle_format)
        worksheet_cashflow.write('A4', '')
        
        # Data Laporan Arus Kas
        cash_flow_data = [
            ['ARUS KAS DARI AKTIVITAS OPERASI', '', '', ''],
            ['Laba Bersih', '', '', cash_flow_stmt['operating_activities']['net_cash']],
            ['Penyesuaian untuk:', '', '', ''],
            ['  Penyusutan', '', '', abs(cash_flow_stmt.get('depreciation', 800000))],
            ['  Perubahan Piutang Usaha', '', '', cash_flow_stmt.get('receivables_change', 500000)],
            ['  Perubahan Persediaan', '', '', cash_flow_stmt.get('inventory_change', -2500000)],
            ['  Perubahan Utang Usaha', '', '', cash_flow_stmt.get('payables_change', 1000000)],
            ['', '', '', ''],
            ['Kas Bersih dari Aktivitas Operasi', '', '', cash_flow_stmt['operating_activities']['net_cash']],
            ['', '', '', ''],
            ['ARUS KAS DARI AKTIVITAS INVESTASI', '', '', ''],
            ['Pembelian Peralatan', '', '', -cash_flow_stmt['investing_activities']['equipment_purchase']],
            ['Penjualan Peralatan', '', '', cash_flow_stmt['investing_activities']['equipment_sale']],
            ['', '', '', ''],
            ['Kas Bersih dari Aktivitas Investasi', '', '', cash_flow_stmt['investing_activities']['net_cash']],
            ['', '', '', ''],
            ['ARUS KAS DARI AKTIVITAS PENDANAAN', '', '', ''],
            ['Setoran Modal Pemilik', '', '', cash_flow_stmt['financing_activities']['capital_contribution']],
            ['Penarikan Pemilik', '', '', -cash_flow_stmt['financing_activities']['drawings']],
            ['Penerimaan Pinjaman', '', '', cash_flow_stmt['financing_activities']['loans_received']],
            ['Pembayaran Pinjaman', '', '', -cash_flow_stmt['financing_activities']['loans_paid']],
            ['', '', '', ''],
            ['Kas Bersih dari Aktivitas Pendanaan', '', '', cash_flow_stmt['financing_activities']['net_cash']],
            ['', '', '', ''],
            ['KENAIKAN (PENURUNAN) BERSIH KAS', '', '', cash_flow_stmt['net_cash_flow']],
            ['', '', '', ''],
            ['Saldo Kas Awal Periode', '', '', cash_flow_stmt.get('beginning_cash', 50000000)],
            ['', '', '', ''],
            ['SALDO KAS AKHIR PERIODE', '', '', cash_flow_stmt.get('beginning_cash', 50000000) + cash_flow_stmt['net_cash_flow']]
        ]
        
        # Tulis data ke sheet
        for row_num, row_data in enumerate(cash_flow_data, start=5):
            for col_num, cell_data in enumerate(row_data):
                if col_num == 3 and isinstance(cell_data, (int, float)):
                    if any(keyword in str(row_data[0]).upper() for keyword in ['BERSIH', 'TOTAL', 'SALDO', 'KENAIKAN']):
                        worksheet_cashflow.write(row_num, col_num, cell_data, total_format)
                    else:
                        worksheet_cashflow.write(row_num, col_num, cell_data, currency_format)
                else:
                    worksheet_cashflow.write(row_num, col_num, cell_data)
        
        # Set column widths untuk Laporan Arus Kas
        worksheet_cashflow.set_column('A:A', 40)
        worksheet_cashflow.set_column('B:C', 2)
        worksheet_cashflow.set_column('D:D', 15)
        
        # ===== SHEET 4: JURNAL PENUTUP =====
        worksheet_closing = workbook.add_worksheet('Jurnal Penutup')
        
        # Header perusahaan
        worksheet_closing.merge_range('A1:D1', company_name, title_format)
        worksheet_closing.merge_range('A2:D2', 'JURNAL PENUTUP', title_format)
        worksheet_closing.merge_range('A3:D3', f'Periode yang berakhir {datetime.now().date().strftime("%d %B %Y")}', subtitle_format)
        worksheet_closing.write('A4', '')
        
        # Data Jurnal Penutup
        closing_entries_data = export_closing_entries()
        
        if closing_entries_data:
            # Tulis header
            headers = ['Kode Akun', 'Nama Akun', 'Debit', 'Kredit', 'Keterangan']
            for col_num, header in enumerate(headers):
                worksheet_closing.write(4, col_num, header, header_format)
            
            # Tulis data
            for row_num, entry in enumerate(closing_entries_data, start=5):
                worksheet_closing.write(row_num, 0, entry.get('Kode Akun', ''))
                worksheet_closing.write(row_num, 1, entry.get('Nama Akun', ''))
                
                debit = entry.get('Debit', 0)
                credit = entry.get('Kredit', 0)
                
                if debit:
                    worksheet_closing.write(row_num, 2, debit, currency_format)
                else:
                    worksheet_closing.write(row_num, 2, '')
                
                if credit:
                    worksheet_closing.write(row_num, 3, credit, currency_format)
                else:
                    worksheet_closing.write(row_num, 3, '')
                
                worksheet_closing.write(row_num, 4, entry.get('Keterangan', ''))
        
        else:
            worksheet_closing.write(5, 0, 'Tidak ada entri penutup yang diperlukan', subtitle_format)
        
        # Set column widths untuk Jurnal Penutup
        worksheet_closing.set_column('A:A', 12)
        worksheet_closing.set_column('B:B', 30)
        worksheet_closing.set_column('C:D', 15)
        worksheet_closing.set_column('E:E', 40)
        
        # ===== SHEET 5: NERACA SALDO PENUTUP =====
        worksheet_pctb = workbook.add_worksheet('Neraca Saldo Penutup')
        
        # Header perusahaan
        worksheet_pctb.merge_range('A1:D1', company_name, title_format)
        worksheet_pctb.merge_range('A2:D2', 'NERACA SALDO SETELAH PENUTUPAN', title_format)
        worksheet_pctb.merge_range('A3:D3', f'Per {datetime.now().date().strftime("%d %B %Y")}', subtitle_format)
        worksheet_pctb.write('A4', '')
        
        # Data Neraca Saldo Penutup
        pctb_data, pctb_debit, pctb_credit = get_post_closing_trial_balance()
        
        # Tulis header
        headers = ['Kode Akun', 'Nama Akun', 'Debit', 'Kredit']
        for col_num, header in enumerate(headers):
            worksheet_pctb.write(4, col_num, header, header_format)
        
        # Tulis data
        row_num = 5
        for item in pctb_data:
            if item['debit'] != 0 or item['credit'] != 0:
                worksheet_pctb.write(row_num, 0, item['account']['code'])
                worksheet_pctb.write(row_num, 1, item['account']['name'])
                
                if item['debit'] > 0:
                    worksheet_pctb.write(row_num, 2, item['debit'], currency_format)
                else:
                    worksheet_pctb.write(row_num, 2, '')
                
                if item['credit'] > 0:
                    worksheet_pctb.write(row_num, 3, item['credit'], currency_format)
                else:
                    worksheet_pctb.write(row_num, 3, '')
                
                row_num += 1
        
        # Tulis total
        worksheet_pctb.write(row_num, 0, 'TOTAL', header_format)
        worksheet_pctb.write(row_num, 1, '')
        worksheet_pctb.write(row_num, 2, pctb_debit, total_format)
        worksheet_pctb.write(row_num, 3, pctb_credit, total_format)
        
        # Set column widths untuk Neraca Saldo Penutup
        worksheet_pctb.set_column('A:A', 12)
        worksheet_pctb.set_column('B:B', 30)
        worksheet_pctb.set_column('C:D', 15)
        
        # ===== SHEET 6: SUMMARY & NOTES =====
        worksheet_summary = workbook.add_worksheet('Summary & Notes')
        
        # Header
        worksheet_summary.merge_range('A1:D1', company_name, title_format)
        worksheet_summary.merge_range('A2:D2', 'RINGKASAN LAPORAN KEUANGAN', title_format)
        worksheet_summary.merge_range('A3:D3', f'Periode {datetime.now().date().strftime("%d %B %Y")}', subtitle_format)
        worksheet_summary.write('A4', '')
        
        # Key Financial Metrics
        summary_data = [
            ['INDIKATOR KINERJA KEUANGAN', '', '', ''],
            ['', '', '', ''],
            ['Profitabilitas', '', '', ''],
            ['Laba Bersih', '', '', income_stmt['net_income']],
            ['Margin Laba Bersih (%)', '', '', (income_stmt['net_income'] / income_stmt['total_revenue']) * 100 if income_stmt['total_revenue'] > 0 else 0],
            ['', '', '', ''],
            ['Likuiditas', '', '', ''],
            ['Kas dan Setara Kas', '', '', balance_stmt['total_assets'] * 0.3],
            ['Total Aset Lancar', '', '', balance_stmt['total_assets'] * 0.8],
            ['Total Kewajiban Lancar', '', '', balance_stmt['total_liabilities']],
            ['', '', '', ''],
            ['Solvabilitas', '', '', ''],
            ['Total Aset', '', '', balance_stmt['total_assets']],
            ['Total Kewajiban', '', '', balance_stmt['total_liabilities']],
            ['Total Ekuitas', '', '', balance_stmt['total_equity'] + balance_stmt['net_income']],
            ['Rasio Kewajiban terhadap Aset', '', '', (balance_stmt['total_liabilities'] / balance_stmt['total_assets']) if balance_stmt['total_assets'] > 0 else 0],
            ['', '', '', ''],
            ['Arus Kas', '', '', ''],
            ['Arus Kas Operasi', '', '', cash_flow_stmt['operating_activities']['net_cash']],
            ['Arus Kas Investasi', '', '', cash_flow_stmt['investing_activities']['net_cash']],
            ['Arus Kas Pendanaan', '', '', cash_flow_stmt['financing_activities']['net_cash']],
            ['Kenaikan/Penurunan Kas Bersih', '', '', cash_flow_stmt['net_cash_flow']]
        ]
        
        # Tulis summary data
        for row_num, row_data in enumerate(summary_data, start=5):
            for col_num, cell_data in enumerate(row_data):
                if col_num == 3 and isinstance(cell_data, (int, float)):
                    worksheet_summary.write(row_num, col_num, cell_data, currency_format)
                else:
                    worksheet_summary.write(row_num, col_num, cell_data)
        
        # Catatan dan Disclaimer
        notes_row = len(summary_data) + 7
        worksheet_summary.write(notes_row, 0, 'CATATAN DAN DISCLAIMER:', header_format)
        worksheet_summary.write(notes_row + 1, 0, '1. Laporan keuangan ini dihasilkan secara otomatis oleh Sistem Akuntansi Tiramine')
        worksheet_summary.write(notes_row + 2, 0, '2. Nilai-nilai tertentu merupakan estimasi untuk tujuan ilustrasi')
        worksheet_summary.write(notes_row + 3, 0, '3. Laporan ini harus direview oleh akuntan profesional sebelum digunakan')
        worksheet_summary.write(notes_row + 4, 0, '4. Mata uang yang digunakan: Rupiah (IDR)')
        worksheet_summary.write(notes_row + 5, 0, f'5. Dihasilkan pada: {datetime.now().strftime("%d %B %Y %H:%M:%S")}')
        
        worksheet_summary.set_column('A:A', 45)
        worksheet_summary.set_column('B:C', 2)
        worksheet_summary.set_column('D:D', 15)
    
    output.seek(0)
    return output

# ---------- Fungsi Ekspor yang Hilang ----------

def export_journal_entries(start_date=None, end_date=None, entry_id=None):
    """Ekspor entri jurnal ke format data untuk Excel"""
    db = get_db()
    cur = db.cursor()
    
    query = '''
        SELECT je.id, je.date, je.description, je.reference, 
               COALESCE(je.transaction_type, 'General') as transaction_type,
               a.code, a.name, jl.debit, jl.credit, jl.description as line_desc
        FROM journal_entries je
        JOIN journal_lines jl ON je.id = jl.entry_id
        JOIN accounts a ON jl.account_id = a.id
        WHERE 1=1
    '''
    params = []
    
    if entry_id:
        query += ' AND je.id = ?'
        params.append(entry_id)
    
    if start_date:
        query += ' AND je.date >= ?'
        params.append(start_date)
    
    if end_date:
        query += ' AND je.date <= ?'
        params.append(end_date)
    
    query += ' ORDER BY je.date, je.id, jl.id'
    
    cur.execute(query, params)
    entries = cur.fetchall()
    
    data = []
    for entry in entries:
        data.append({
            'Tanggal': entry['date'],
            'ID Entri': entry['id'],
            'Keterangan': entry['description'],
            'Referensi': entry['reference'] or '',
            'Jenis Transaksi': entry['transaction_type'],
            'Kode Akun': entry['code'],
            'Nama Akun': entry['name'],
            'Debit': entry['debit'],
            'Kredit': entry['credit'],
            'Keterangan Baris': entry['line_desc'] or ''
        })
    
    return data

def export_adjusting_entries(start_date=None, end_date=None, entry_id=None):
    """Ekspor ayat penyesuaian ke format data untuk Excel"""
    db = get_db()
    cur = db.cursor()
    
    query = '''
        SELECT ae.id, ae.date, ae.description,
               a.code, a.name, al.debit, al.credit, al.description as line_desc
        FROM adjusting_entries ae
        JOIN adjusting_lines al ON ae.id = al.adj_id
        JOIN accounts a ON al.account_id = a.id
        WHERE 1=1
    '''
    params = []
    
    if entry_id:
        query += ' AND ae.id = ?'
        params.append(entry_id)
    
    if start_date:
        query += ' AND ae.date >= ?'
        params.append(start_date)
    
    if end_date:
        query += ' AND ae.date <= ?'
        params.append(end_date)
    
    query += ' ORDER BY ae.date, ae.id, al.id'
    
    cur.execute(query, params)
    entries = cur.fetchall()
    
    data = []
    for entry in entries:
        data.append({
            'Tanggal': entry['date'],
            'ID Entri': entry['id'],
            'Keterangan': entry['description'],
            'Kode Akun': entry['code'],
            'Nama Akun': entry['name'],
            'Debit': entry['debit'],
            'Kredit': entry['credit'],
            'Keterangan Baris': entry['line_desc'] or ''
        })
    
    return data

def export_ledger(account_id=None, start_date=None, end_date=None):
    """Ekspor buku besar ke format data untuk Excel"""
    db = get_db()
    cur = db.cursor()
    
    # Jika account_id spesifik, ekspor detail transaksi
    if account_id:
        cur.execute('SELECT * FROM accounts WHERE id = ?', (account_id,))
        account = cur.fetchone()
        
        if not account:
            return []
        
        # Gabungkan transaksi jurnal dan penyesuaian
        query = '''
            SELECT date, description, debit, credit, 'Jurnal' as type, '' as line_desc
            FROM (
                SELECT je.date, je.description, jl.debit, jl.credit, jl.description as line_desc
                FROM journal_lines jl
                JOIN journal_entries je ON jl.entry_id = je.id
                WHERE jl.account_id = ?
                UNION ALL
                SELECT ae.date, ae.description, al.debit, al.credit, al.description as line_desc
                FROM adjusting_lines al
                JOIN adjusting_entries ae ON al.adj_id = ae.id
                WHERE al.account_id = ?
            )
            WHERE 1=1
        '''
        params = [account_id, account_id]
        
        if start_date:
            query += ' AND date >= ?'
            params.append(start_date)
        
        if end_date:
            query += ' AND date <= ?'
            params.append(end_date)
        
        query += ' ORDER BY date'
        
        cur.execute(query, params)
        transactions = cur.fetchall()
        
        # Hitung saldo berjalan
        balance = get_opening_balance(account_id)
        data = [{
            'Tanggal': 'Saldo Awal',
            'Keterangan': 'Saldo Awal',
            'Debit': balance if balance > 0 else 0,
            'Kredit': -balance if balance < 0 else 0,
            'Saldo': balance,
            'Jenis': 'Saldo Awal'
        }]
        
        for tx in transactions:
            if account['normal_balance'] == 'Debit':
                balance += tx['debit'] - tx['credit']
            else:
                balance += tx['credit'] - tx['debit']
            
            data.append({
                'Tanggal': tx['date'],
                'Keterangan': tx['description'],
                'Debit': tx['debit'],
                'Kredit': tx['credit'],
                'Saldo': balance,
                'Jenis': tx['type']
            })
        
        return data
    else:
        # Ekspor semua akun dengan saldo
        accounts = all_accounts()
        data = []
        
        for account in accounts:
            balance = get_account_balance(account['id'])
            data.append({
                'Kode Akun': account['code'],
                'Nama Akun': account['name'],
                'Jenis Akun': account['acct_type'],
                'Saldo Normal': account['normal_balance'],
                'Saldo Saat Ini': balance
            })
        
        return data

def export_trial_balance(include_adjustments=True):
    """Ekspor neraca saldo ke format data untuk Excel"""
    tb_data, total_debit, total_credit = trial_balance(include_adjustments)
    
    data = []
    for item in tb_data:
        if item['debit'] != 0 or item['credit'] != 0:
            data.append({
                'Kode Akun': item['account']['code'],
                'Nama Akun': item['account']['name'],
                'Jenis Akun': item['account']['acct_type'],
                'Debit': item['debit'],
                'Kredit': item['credit']
            })
    
    # Tambahkan total
    data.append({
        'Kode Akun': 'TOTAL',
        'Nama Akun': '',
        'Jenis Akun': '',
        'Debit': total_debit,
        'Kredit': total_credit
    })
    
    return data

def export_closing_entries():
    """Ekspor jurnal penutup ke format data untuk Excel"""
    closing_entries_list, net_income = get_closing_entries()
    
    data = []
    for entry in closing_entries_list:
        cur = get_db().execute('SELECT code, name FROM accounts WHERE id = ?', (entry['account_id'],))
        account = cur.fetchone()
        
        data.append({
            'Kode Akun': account['code'],
            'Nama Akun': account['name'],
            'Debit': entry['debit'],
            'Kredit': entry['credit'],
            'Keterangan': entry['description']
        })
    
    # Tambahkan summary
    data.append({
        'Kode Akun': 'SUMMARY',
        'Nama Akun': 'Laba/Rugi Bersih Periode',
        'Debit': '',
        'Kredit': '',
        'Keterangan': f'IDR {net_income:,.2f}'
    })
    
    return data

@app.route('/export/closing_entries')
@login_required
def export_closing_entries_route():
    """Ekspor jurnal penutup"""
    data = export_closing_entries()
    filename = f"jurnal_penutup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    
    return export_to_excel(data, "Jurnal Penutup", filename)

def export_income_statement():
    """Ekspor laporan laba rugi ke format data untuk Excel"""
    income_stmt = income_statement()
    
    data = [
        {'Keterangan': 'PENDAPATAN', 'Jumlah': ''},
        {'Keterangan': 'Pendapatan Penjualan Tiram', 'Jumlah': income_stmt['total_revenue']},
        {'Keterangan': '', 'Jumlah': ''},
        {'Keterangan': 'Total Pendapatan', 'Jumlah': income_stmt['total_revenue']},
        {'Keterangan': '', 'Jumlah': ''},
        {'Keterangan': 'BEBAN OPERASIONAL', 'Jumlah': ''},
        {'Keterangan': 'Total Beban', 'Jumlah': income_stmt['total_expense']},
        {'Keterangan': '', 'Jumlah': ''},
        {'Keterangan': 'LABA BERSIH', 'Jumlah': income_stmt['net_income']}
    ]
    
    return data

def export_balance_sheet():
    """Ekspor neraca ke format data untuk Excel"""
    balance_stmt = balance_sheet()
    
    data = [
        {'Keterangan': 'ASET', 'Jumlah': ''},
        {'Keterangan': 'Total Aset', 'Jumlah': balance_stmt['total_assets']},
        {'Keterangan': '', 'Jumlah': ''},
        {'Keterangan': 'KEWAJIBAN & EKUITAS', 'Jumlah': ''},
        {'Keterangan': 'Total Kewajiban', 'Jumlah': balance_stmt['total_liabilities']},
        {'Keterangan': 'Total Ekuitas', 'Jumlah': balance_stmt['total_equity'] + balance_stmt['net_income']},
        {'Keterangan': '', 'Jumlah': ''},
        {'Keterangan': 'Total Kewajiban & Ekuitas', 'Jumlah': balance_stmt['total_liabilities'] + balance_stmt['total_equity'] + balance_stmt['net_income']}
    ]
    
    return data

def export_cash_flow():
    """Ekspor laporan arus kas ke format data untuk Excel"""
    cash_flow_stmt = cash_flow_statement()
    
    data = [
        {'Keterangan': 'ARUS KAS DARI AKTIVITAS OPERASI', 'Jumlah': ''},
        {'Keterangan': 'Kas Bersih dari Operasi', 'Jumlah': cash_flow_stmt['operating_activities']['net_cash']},
        {'Keterangan': '', 'Jumlah': ''},
        {'Keterangan': 'ARUS KAS DARI AKTIVITAS INVESTASI', 'Jumlah': ''},
        {'Keterangan': 'Kas Bersih dari Investasi', 'Jumlah': cash_flow_stmt['investing_activities']['net_cash']},
        {'Keterangan': '', 'Jumlah': ''},
        {'Keterangan': 'ARUS KAS DARI AKTIVITAS PENDANAAN', 'Jumlah': ''},
        {'Keterangan': 'Kas Bersih dari Pendanaan', 'Jumlah': cash_flow_stmt['financing_activities']['net_cash']},
        {'Keterangan': '', 'Jumlah': ''},
        {'Keterangan': 'KENAIKAN/PENURUNAN KAS BERSIH', 'Jumlah': cash_flow_stmt['net_cash_flow']}
    ]
    
    return data

def export_inventory():
    """Ekspor data persediaan ke format data untuk Excel"""
    db = get_db()
    cur = db.cursor()
    
    cur.execute('''
        SELECT date, description, quantity_in, quantity_out, unit_cost, value
        FROM inventory
        ORDER BY date, id
    ''')
    inventory_data = cur.fetchall()
    
    data = []
    for item in inventory_data:
        data.append({
            'Tanggal': item['date'],
            'Keterangan': item['description'],
            'Quantity In': item['quantity_in'],
            'Quantity Out': item['quantity_out'],
            'Harga Satuan': item['unit_cost'],
            'Nilai': item['value']
        })
    
    # Tambahkan stok saat ini
    current_stock = get_current_stock()
    data.append({
        'Tanggal': datetime.now().date().isoformat(),
        'Keterangan': 'STOK SAAT INI',
        'Quantity In': '',
        'Quantity Out': '',
        'Harga Satuan': '',
        'Nilai': current_stock
    })
    
    return data

def export_opening_balances():
    """Ekspor saldo awal ke format data untuk Excel"""
    accounts = all_accounts()
    
    data = []
    for account in accounts:
        balance = get_opening_balance(account['id'])
        data.append({
            'Kode Akun': account['code'],
            'Nama Akun': account['name'],
            'Jenis Akun': account['acct_type'],
            'Saldo Normal': account['normal_balance'],
            'Saldo Awal': abs(balance),
            'Tipe Saldo': 'Debit' if balance >= 0 else 'Kredit'
        })
    
    return data

def export_all_reports():
    """Ekspor semua laporan ke satu file Excel multi-sheet"""
    output = io.BytesIO()
    
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        workbook = writer.book
        
        # Format untuk styling
        header_format = workbook.add_format({
            'bold': True,
            'text_wrap': True,
            'valign': 'top',
            'fg_color': '#1E40AF',
            'font_color': 'white',
            'border': 1
        })
        
        currency_format = workbook.add_format({'num_format': '#,##0.00'})
        
        # Sheet 1: Jurnal Umum
        journal_data = export_journal_entries()
        if journal_data:
            df_journal = pd.DataFrame(journal_data)
            df_journal.to_excel(writer, sheet_name='Jurnal Umum', index=False)
            worksheet = writer.sheets['Jurnal Umum']
            for col_num, value in enumerate(df_journal.columns.values):
                worksheet.write(0, col_num, value, header_format)
            for idx, col in enumerate(df_journal.columns):
                max_len = max(df_journal[col].astype(str).str.len().max(), len(col)) + 2
                worksheet.set_column(idx, idx, min(max_len, 50))
        
        # Sheet 2: Buku Besar
        ledger_data = export_ledger()
        if ledger_data:
            df_ledger = pd.DataFrame(ledger_data)
            df_ledger.to_excel(writer, sheet_name='Buku Besar', index=False)
            worksheet = writer.sheets['Buku Besar']
            for col_num, value in enumerate(df_ledger.columns.values):
                worksheet.write(0, col_num, value, header_format)
            for idx, col in enumerate(df_ledger.columns):
                max_len = max(df_ledger[col].astype(str).str.len().max(), len(col)) + 2
                worksheet.set_column(idx, idx, min(max_len, 50))
        
        # Sheet 3: Neraca Saldo
        tb_data = export_trial_balance()
        if tb_data:
            df_tb = pd.DataFrame(tb_data)
            df_tb.to_excel(writer, sheet_name='Neraca Saldo', index=False)
            worksheet = writer.sheets['Neraca Saldo']
            for col_num, value in enumerate(df_tb.columns.values):
                worksheet.write(0, col_num, value, header_format)
            for idx, col in enumerate(df_tb.columns):
                max_len = max(df_tb[col].astype(str).str.len().max(), len(col)) + 2
                worksheet.set_column(idx, idx, min(max_len, 50))
        
        # Sheet 4: Laporan Laba Rugi
        income_data = export_income_statement()
        if income_data:
            df_income = pd.DataFrame(income_data)
            df_income.to_excel(writer, sheet_name='Laporan Laba Rugi', index=False)
            worksheet = writer.sheets['Laporan Laba Rugi']
            for col_num, value in enumerate(df_income.columns.values):
                worksheet.write(0, col_num, value, header_format)
            for idx, col in enumerate(df_income.columns):
                max_len = max(df_income[col].astype(str).str.len().max(), len(col)) + 2
                worksheet.set_column(idx, idx, min(max_len, 50))
        
        # Sheet 5: Neraca
        balance_data = export_balance_sheet()
        if balance_data:
            df_balance = pd.DataFrame(balance_data)
            df_balance.to_excel(writer, sheet_name='Neraca', index=False)
            worksheet = writer.sheets['Neraca']
            for col_num, value in enumerate(df_balance.columns.values):
                worksheet.write(0, col_num, value, header_format)
            for idx, col in enumerate(df_balance.columns):
                max_len = max(df_balance[col].astype(str).str.len().max(), len(col)) + 2
                worksheet.set_column(idx, idx, min(max_len, 50))
        
        # Sheet 6: Laporan Arus Kas
        cashflow_data = export_cash_flow()
        if cashflow_data:
            df_cashflow = pd.DataFrame(cashflow_data)
            df_cashflow.to_excel(writer, sheet_name='Laporan Arus Kas', index=False)
            worksheet = writer.sheets['Laporan Arus Kas']
            for col_num, value in enumerate(df_cashflow.columns.values):
                worksheet.write(0, col_num, value, header_format)
            for idx, col in enumerate(df_cashflow.columns):
                max_len = max(df_cashflow[col].astype(str).str.len().max(), len(col)) + 2
                worksheet.set_column(idx, idx, min(max_len, 50))
        
        # Sheet 7: Jurnal Penutup
        closing_data = export_closing_entries()
        if closing_data:
            df_closing = pd.DataFrame(closing_data)
            df_closing.to_excel(writer, sheet_name='Jurnal Penutup', index=False)
            worksheet = writer.sheets['Jurnal Penutup']
            for col_num, value in enumerate(df_closing.columns.values):
                worksheet.write(0, col_num, value, header_format)
            for idx, col in enumerate(df_closing.columns):
                max_len = max(df_closing[col].astype(str).str.len().max(), len(col)) + 2
                worksheet.set_column(idx, idx, min(max_len, 50))
        
        # Sheet 8: Neraca Saldo Penutup
        pctb_data, pctb_debit, pctb_credit = get_post_closing_trial_balance()
        if pctb_data:
            # Konversi ke format yang sesuai
            pctb_export_data = []
            for item in pctb_data:
                if item['debit'] != 0 or item['credit'] != 0:
                    pctb_export_data.append({
                        'Kode Akun': item['account']['code'],
                        'Nama Akun': item['account']['name'],
                        'Jenis Akun': item['account']['acct_type'],
                        'Debit': item['debit'],
                        'Kredit': item['credit']
                    })
            
            # Tambahkan total
            pctb_export_data.append({
                'Kode Akun': 'TOTAL',
                'Nama Akun': '',
                'Jenis Akun': '',
                'Debit': pctb_debit,
                'Kredit': pctb_credit
            })
            
            df_pctb = pd.DataFrame(pctb_export_data)
            df_pctb.to_excel(writer, sheet_name='Neraca Saldo Penutup', index=False)
            worksheet = writer.sheets['Neraca Saldo Penutup']
            for col_num, value in enumerate(df_pctb.columns.values):
                worksheet.write(0, col_num, value, header_format)
            for idx, col in enumerate(df_pctb.columns):
                max_len = max(df_pctb[col].astype(str).str.len().max(), len(col)) + 2
                worksheet.set_column(idx, idx, min(max_len, 50))
    
    output.seek(0)
    return output

# ---------- Rute Ekspor yang Lengkap dan Diperbaiki ----------

def export_to_excel(data, sheet_name, filename):
    """Fungsi dasar untuk ekspor data ke Excel - VERSI DIPERBAIKI"""
    output = io.BytesIO()
    
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        # Konversi data ke DataFrame
        if isinstance(data, list) and data:
            df = pd.DataFrame(data)
        else:
            df = pd.DataFrame([data]) if data else pd.DataFrame()
        
        # Tulis ke Excel dengan formatting
        df.to_excel(writer, sheet_name=sheet_name, index=False)
        
        # Dapatkan workbook dan worksheet
        workbook = writer.book
        worksheet = writer.sheets[sheet_name]
        
        # Format header
        header_format = workbook.add_format({
            'bold': True,
            'text_wrap': True,
            'valign': 'top',
            'fg_color': '#1E40AF',
            'font_color': 'white',
            'border': 1
        })
        
        # Format angka
        currency_format = workbook.add_format({'num_format': '#,##0.00'})
        
        # Terapkan formatting ke header
        for col_num, value in enumerate(df.columns.values):
            worksheet.write(0, col_num, value, header_format)
        
        # Auto-adjust column widths
        for idx, col in enumerate(df.columns):
            max_len = max(df[col].astype(str).str.len().max(), len(col)) + 2
            worksheet.set_column(idx, idx, min(max_len, 50))
    
    output.seek(0)
    
    # PERBAIKAN: Response dengan header yang benar untuk force download
    response = Response(
        output.getvalue(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        }
    )
    
    # Tambahkan header untuk mencegah caching
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    
    return response

@app.route('/export/financial-reports')
@login_required
def export_financial_reports_route():
    """Endpoint untuk export ketiga laporan keuangan utama - VERSI DIPERBAIKI"""
    try:
        output = export_financial_reports()
        
        filename = f"laporan_keuangan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        
        # PERBAIKAN: Response dengan header yang benar untuk force download
        response = Response(
            output.getvalue(),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            }
        )
        
        # Tambahkan header untuk mencegah caching
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        
        return response
        
    except Exception as e:
        flash(f'Error generating financial reports: {str(e)}')
        return redirect(url_for('financials'))

@app.route('/export/journal')
@login_required
def export_journal_route():
    """Ekspor jurnal umum"""
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    entry_id = request.args.get('entry_id')
    
    data = export_journal_entries(start_date, end_date, entry_id)
    filename = f"jurnal_umum_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    
    return export_to_excel(data, "Jurnal Umum", filename)

@app.route('/export/adjusting')
@login_required
def export_adjusting_route():
    """Ekspor ayat penyesuaian"""
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    entry_id = request.args.get('entry_id')
    
    data = export_adjusting_entries(start_date, end_date, entry_id)
    filename = f"ayat_penyesuaian_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    
    return export_to_excel(data, "Ayat Penyesuaian", filename)

@app.route('/export/ledger')
@login_required
def export_ledger_route():
    """Ekspor buku besar"""
    account_id = request.args.get('account_id')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    data = export_ledger(account_id, start_date, end_date)
    filename = f"buku_besar_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    
    return export_to_excel(data, "Buku Besar", filename)

@app.route('/export/trial_balance')
@login_required
def export_trial_balance_route():
    """Ekspor neraca saldo"""
    include_adjustments = request.args.get('include_adjustments', 'true').lower() == 'true'
    
    data = export_trial_balance(include_adjustments)
    filename = f"neraca_saldo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    
    return export_to_excel(data, "Neraca Saldo", filename)

@app.route('/export/income_statement')
@login_required
def export_income_statement_route():
    """Ekspor laporan laba rugi"""
    data = export_income_statement()
    filename = f"laporan_laba_rugi_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    
    return export_to_excel(data, "Laporan Laba Rugi", filename)

@app.route('/export/balance_sheet')
@login_required
def export_balance_sheet_route():
    """Ekspor neraca"""
    data = export_balance_sheet()
    filename = f"neraca_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    
    return export_to_excel(data, "Neraca", filename)

@app.route('/export/cash_flow')
@login_required
def export_cash_flow_route():
    """Ekspor laporan arus kas"""
    data = export_cash_flow()
    filename = f"laporan_arus_kas_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    
    return export_to_excel(data, "Laporan Arus Kas", filename)

@app.route('/export/inventory')
@login_required
def export_inventory_route():
    """Ekspor data persediaan"""
    data = export_inventory()
    filename = f"persediaan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    
    return export_to_excel(data, "Persediaan", filename)

@app.route('/export/opening_balances')
@login_required
def export_opening_balances_route():
    """Ekspor saldo awal"""
    data = export_opening_balances()
    filename = f"saldo_awal_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    
    return export_to_excel(data, "Saldo Awal", filename)

@app.route('/export/all')
@login_required
def export_all_reports_route():
    """Ekspor semua laporan ke satu file Excel - VERSI DIPERBAIKI"""
    try:
        output = export_all_reports()
        
        filename = f"laporan_keuangan_lengkap_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        
        # PERBAIKAN: Response dengan header yang benar untuk force download
        response = Response(
            output.getvalue(),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            }
        )
        
        # Tambahkan header untuk mencegah caching
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        
        return response
        
    except Exception as e:
        flash(f'Error generating all reports: {str(e)}')
        return redirect(url_for('dashboard'))

@app.route('/export')
@login_required
def export_management():
    """Halaman manajemen ekspor yang komprehensif"""
    
    body = """
    <div class="page-header">
        <h1 class="page-title">Manajemen Ekspor Excel</h1>
        <p class="page-subtitle">Ekspor data akuntansi ke format Excel untuk analisis dan audit</p>
    </div>
    
    <div class="row">
        <!-- Ekspor Individual -->
        <div class="col-lg-6 mb-4">
            <div class="card h-100">
                <div class="card-header bg-primary text-white">
                    <h5 class="mb-0"><i class="fas fa-file-export me-2"></i>Ekspor Per Laporan</h5>
                </div>
                <div class="card-body">
                    <div class="list-group">
                        <a href="/export/journal" class="list-group-item list-group-item-action d-flex justify-content-between align-items-center">
                            <div>
                                <i class="fas fa-book me-2 text-primary"></i>
                                <strong>Jurnal Umum</strong>
                                <small class="d-block text-muted">Semua entri jurnal transaksi</small>
                            </div>
                            <i class="fas fa-download text-muted"></i>
                        </a>
                        
                        <a href="/export/adjusting" class="list-group-item list-group-item-action d-flex justify-content-between align-items-center">
                            <div>
                                <i class="fas fa-adjust me-2 text-warning"></i>
                                <strong>Ayat Penyesuaian</strong>
                                <small class="d-block text-muted">Entri penyesuaian periode</small>
                            </div>
                            <i class="fas fa-download text-muted"></i>
                        </a>
                        
                        <a href="/export/ledger" class="list-group-item list-group-item-action d-flex justify-content-between align-items-center">
                            <div>
                                <i class="fas fa-file-invoice-dollar me-2 text-success"></i>
                                <strong>Buku Besar</strong>
                                <small class="d-block text-muted">Riwayat semua akun</small>
                            </div>
                            <i class="fas fa-download text-muted"></i>
                        </a>
                        
                        <a href="/export/trial_balance" class="list-group-item list-group-item-action d-flex justify-content-between align-items-center">
                            <div>
                                <i class="fas fa-balance-scale me-2 text-info"></i>
                                <strong>Neraca Saldo</strong>
                                <small class="d-block text-muted">Saldo sebelum & setelah penyesuaian</small>
                            </div>
                            <i class="fas fa-download text-muted"></i>
                        </a>

                        <!-- Tambahkan di bagian Ekspor Individual -->
                        <a href="/export/closing_entries" class="list-group-item list-group-item-action d-flex justify-content-between align-items-center">
                            <div>
                                <i class="fas fa-lock me-2 text-danger"></i>
                                <strong>Jurnal Penutup</strong>
                                <small class="d-block text-muted">Entri penutupan periode</small>
                            </div>
                            <i class="fas fa-download text-muted"></i>
                        </a>

                    </div>
                </div>
            </div>
        </div>
        
        <!-- Ekspor Laporan Keuangan -->
        <div class="col-lg-6 mb-4">
            <div class="card h-100">
                <div class="card-header bg-success text-white">
                    <h5 class="mb-0"><i class="fas fa-chart-line me-2"></i>Laporan Keuangan</h5>
                </div>
                <div class="card-body">
                    <div class="list-group">
                        <a href="/export/income_statement" class="list-group-item list-group-item-action d-flex justify-content-between align-items-center">
                            <div>
                                <i class="fas fa-chart-bar me-2 text-success"></i>
                                <strong>Laporan Laba Rugi</strong>
                                <small class="d-block text-muted">Pendapatan, beban, dan laba bersih</small>
                            </div>
                            <i class="fas fa-download text-muted"></i>
                        </a>
                        
                        <a href="/export/balance_sheet" class="list-group-item list-group-item-action d-flex justify-content-between align-items-center">
                            <div>
                                <i class="fas fa-balance-scale-left me-2 text-primary"></i>
                                <strong>Neraca</strong>
                                <small class="d-block text-muted">Posisi keuangan perusahaan</small>
                            </div>
                            <i class="fas fa-download text-muted"></i>
                        </a>
                        
                        <a href="/export/cash_flow" class="list-group-item list-group-item-action d-flex justify-content-between align-items-center">
                            <div>
                                <i class="fas fa-money-bill-wave me-2 text-info"></i>
                                <strong>Laporan Arus Kas</strong>
                                <small class="d-block text-muted">Arus kas operasi, investasi, pendanaan</small>
                            </div>
                            <i class="fas fa-download text-muted"></i>
                        </a>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- Ekspor Data Master -->
        <div class="col-lg-6 mb-4">
            <div class="card h-100">
                <div class="card-header bg-info text-white">
                    <h5 class="mb-0"><i class="fas fa-database me-2"></i>Data Master</h5>
                </div>
                <div class="card-body">
                    <div class="list-group">
                        <a href="/export/inventory" class="list-group-item list-group-item-action d-flex justify-content-between align-items-center">
                            <div>
                                <i class="fas fa-water me-2 text-info"></i>
                                <strong>Persediaan Tiram</strong>
                                <small class="d-block text-muted">Riwayat stok dan nilai persediaan</small>
                            </div>
                            <i class="fas fa-download text-muted"></i>
                        </a>
                        
                        <a href="/export/opening_balances" class="list-group-item list-group-item-action d-flex justify-content-between align-items-center">
                            <div>
                                <i class="fas fa-play-circle me-2 text-warning"></i>
                                <strong>Saldo Awal</strong>
                                <small class="d-block text-muted">Saldo awal semua akun</small>
                            </div>
                            <i class="fas fa-download text-muted"></i>
                        </a>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- Ekspor Komprehensif -->
        <div class="col-lg-6 mb-4">
            <div class="card h-100">
                <div class="card-header bg-warning text-dark">
                    <h5 class="mb-0"><i class="fas fa-file-archive me-2"></i>Ekspor Lengkap</h5>
                </div>
                <div class="card-body text-center py-5">
                    <i class="fas fa-file-excel fa-4x text-success mb-3"></i>
                    <h4 class="text-dark mb-3">Export Semua Laporan</h4>
                    <p class="text-muted mb-4">
                        Download semua laporan keuangan dalam satu file Excel multi-sheet. 
                        Siap untuk analisis, audit, dan presentasi.
                    </p>
                    <a href="/export/all" class="btn btn-success btn-lg">
                        <i class="fas fa-download me-2"></i>Download Full Report
                    </a>
                    <small class="d-block text-muted mt-2">
                        Includes all 9 reports in separate sheets
                    </small>
                </div>
            </div>
        </div>
    </div>
    
    <!-- Info Section -->
    <div class="row mt-4">
        <div class="col-12">
            <div class="card bg-light">
                <div class="card-body">
                    <h6><i class="fas fa-info-circle me-2 text-primary"></i>Informasi Ekspor</h6>
                    <div class="row">
                        <div class="col-md-4">
                            <strong>Format File:</strong> Excel (.xlsx)
                        </div>
                        <div class="col-md-4">
                            <strong>Encoding:</strong> UTF-8
                        </div>
                        <div class="col-md-4">
                            <strong>Mata Uang:</strong> IDR
                        </div>
                    </div>
                    <div class="row mt-2">
                        <div class="col-12">
                            <strong>Fitur:</strong> Formatting profesional, multi-sheet, siap print, 
                            compatible dengan Excel 2010+, filter data, formulas siap pakai.
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    """
    
    return render_template_string(BASE_TEMPLATE, title='Manajemen Ekspor', body=body, user=current_user())

# Pastikan semua fungsi helper export sudah didefinisikan
def export_to_excel(data, sheet_name, filename):
    """Fungsi dasar untuk ekspor data ke Excel"""
    output = io.BytesIO()
    
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        # Konversi data ke DataFrame
        if isinstance(data, list) and data:
            df = pd.DataFrame(data)
        else:
            df = pd.DataFrame([data]) if data else pd.DataFrame()
        
        # Tulis ke Excel dengan formatting
        df.to_excel(writer, sheet_name=sheet_name, index=False)
        
        # Dapatkan workbook dan worksheet
        workbook = writer.book
        worksheet = writer.sheets[sheet_name]
        
        # Format header
        header_format = workbook.add_format({
            'bold': True,
            'text_wrap': True,
            'valign': 'top',
            'fg_color': '#1E40AF',
            'font_color': 'white',
            'border': 1
        })
        
        # Format angka
        currency_format = workbook.add_format({'num_format': '#,##0.00'})
        
        # Terapkan formatting ke header
        for col_num, value in enumerate(df.columns.values):
            worksheet.write(0, col_num, value, header_format)
        
        # Auto-adjust column widths
        for idx, col in enumerate(df.columns):
            max_len = max(df[col].astype(str).str.len().max(), len(col)) + 2
            worksheet.set_column(idx, idx, min(max_len, 50))
    
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment;filename={filename}"}
    )

@app.route('/debug')
def debug():
    """Route untuk debugging - HAPUS SETELAH FIX"""
    try:
        db = get_db()
        cur = db.cursor()
        
        # Cek users
        cur.execute('SELECT * FROM users')
        users = cur.fetchall()
        
        # Cek session
        session_info = {
            'user_id': session.get('user_id'),
            'session_keys': list(session.keys())
        }
        
        debug_info = f"""
        <div class="container mt-4">
            <h2>Debug Info</h2>
            <div class="card">
                <div class="card-body">
                    <h5>Users in database:</h5>
                    <pre>{users}</pre>
                    <h5>Session info:</h5>
                    <pre>{session_info}</pre>
                    <h5>Current user:</h5>
                    <pre>{current_user()}</pre>
                </div>
            </div>
            <div class="mt-3">
                <a href="/login" class="btn btn-primary">Ke Halaman Login</a>
                <a href="/reset-db" class="btn btn-warning">Reset Database</a>
            </div>
        </div>
        """
        
        return debug_info
    except Exception as e:
        return f"Error: {str(e)}"

@app.route('/reset_opening_balances')
@login_required
def reset_opening_balances():
    """Reset saldo awal ke nilai default sesuai neraca saldo awal"""
    db = get_db()
    
    # Hapus semua saldo awal
    db.execute('DELETE FROM opening_balances')
    
    # Set saldo awal default sesuai neraca saldo
    default_balances = [
        # Assets (Debit)
        (1, 8500000, 0),   # Kas (101)
        (2, 4500000, 0),   # Piutang Usaha (102)
        (3, 1750000, 0),   # Persediaan Tiram Besar (103)
        (4, 1200000, 0),   # Persediaan Tiram Kecil (103.1)
        (5, 500000, 0),    # Peralatan (104)
        (6, 300000, 0),    # Perlengkapan (105)
        (7, 12000000, 0),  # Kendaraan (106)
        
        # Contra Asset (Credit)
        (8, 0, 1500000),   # Akumulasi Penyusutan Kendaraan (107)
        
        # Liabilities (Credit)
        (9, 0, 650000),    # Utang Usaha (201)
        (10, 0, 100000),   # Utang Gaji (202)
        
        # Equity (Credit)
        (11, 0, 22300000), # Modal Pemilik (301)
    ]
    
    for account_id, debit_amount, credit_amount in default_balances:
        db.execute('''
            INSERT INTO opening_balances (account_id, debit_amount, credit_amount) 
            VALUES (?, ?, ?)
        ''', (account_id, debit_amount, credit_amount))
    
    db.commit()
    flash('✅ Saldo awal berhasil direset ke nilai default!')
    return redirect(url_for('opening_balance'))

@app.route('/verify_balances')
@login_required
def verify_balances():
    """Halaman untuk verifikasi saldo awal"""
    db = get_db()
    
    # Hitung total debit dan credit dari opening_balances
    result = db.execute('''
        SELECT SUM(debit_amount) as total_debit, SUM(credit_amount) as total_credit 
        FROM opening_balances
    ''').fetchone()
    
    total_debit = result['total_debit'] or 0
    total_credit = result['total_credit'] or 0
    
    # Dapatkan detail semua saldo
    balances = db.execute('''
        SELECT a.code, a.name, a.acct_type, a.normal_balance, 
               ob.debit_amount, ob.credit_amount
        FROM accounts a
        LEFT JOIN opening_balances ob ON a.id = ob.account_id
        WHERE ob.debit_amount != 0 OR ob.credit_amount != 0
        ORDER BY a.code
    ''').fetchall()
    
    body = f"""
    <div class="page-header">
        <h1 class="page-title">Verifikasi Saldo Awal</h1>
        <p class="page-subtitle">Pastikan saldo awal sesuai dengan neraca saldo</p>
    </div>
    
    <div class="card">
        <div class="card-header">
            <h5 class="mb-0">Summary</h5>
        </div>
        <div class="card-body">
            <div class="row">
                <div class="col-md-6">
                    <div class="alert alert-success">
                        <h6>Total Debit</h6>
                        <h3>Rp {total_debit:,.2f}</h3>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="alert alert-info">
                        <h6>Total Credit</h6>
                        <h3>Rp {total_credit:,.2f}</h3>
                    </div>
                </div>
            </div>
            
            <div class="alert {'alert-success' if total_debit == total_credit else 'alert-danger'}">
                <h6><i class="fas {'fa-check-circle' if total_debit == total_credit else 'fa-exclamation-triangle'} me-2"></i>
                Status: {'SEIMBANG' if total_debit == total_credit else 'TIDAK SEIMBANG'}</h6>
                <p class="mb-0">Selisih: Rp {abs(total_debit - total_credit):,.2f}</p>
            </div>
        </div>
    </div>
    
    <div class="card mt-4">
        <div class="card-header">
            <h5 class="mb-0">Detail Saldo Awal</h5>
        </div>
        <div class="card-body">
            <div class="table-responsive">
                <table class="table table-hover">
                    <thead>
                        <tr>
                            <th>Kode</th>
                            <th>Nama Akun</th>
                            <th>Jenis</th>
                            <th>Saldo Normal</th>
                            <th class="text-end">Debit</th>
                            <th class="text-end">Kredit</th>
                        </tr>
                    </thead>
                    <tbody>
    """
    
    for balance in balances:
        body += f"""
                        <tr>
                            <td><strong>{balance['code']}</strong></td>
                            <td>{balance['name']}</td>
                            <td><span class="badge bg-secondary">{balance['acct_type']}</span></td>
                            <td><span class="badge bg-{'primary' if balance['normal_balance'] == 'Debit' else 'success'}">{balance['normal_balance']}</span></td>
                            <td class="text-end {'text-success fw-bold' if balance['debit_amount'] > 0 else ''}">{balance['debit_amount']:,.2f}</td>
                            <td class="text-end {'text-danger fw-bold' if balance['credit_amount'] > 0 else ''}">{balance['credit_amount']:,.2f}</td>
                        </tr>
        """
    
    body += """
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    
    <div class="mt-4">
        <a href="/trial_balance" class="btn btn-primary">
            <i class="fas fa-balance-scale me-2"></i>Lihat Neraca Saldo
        </a>
        <a href="/fix_database" class="btn btn-warning" onclick="return confirm('Reset database?')">
            <i class="fas fa-sync me-2"></i>Reset Database
        </a>
    </div>
    """
    
    return render_template_string(BASE_TEMPLATE, title='Verifikasi Saldo', body=body, user=current_user())

# ---------- Startup Aplikasi ----------

if __name__ == '__main__':

    with app.app_context():
        if not DB_PATH.exists():
            print("Menginisialisasi Database Akuntansi Tiramine...")
        init_db()
        print("Database berhasil diinisialisasi!")
        print("Transaksi contoh dibuat untuk demonstrasi")
        print("Masuk dengan: admin / password")
        print("🔒 Auto-save enabled: Data aman meskipun CTRL+C")  # Bisa tambah ini juga
    
    app.run(debug=True, use_reloader=True, threaded=False, host='0.0.0.0', port=5000)
